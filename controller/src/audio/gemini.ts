// Native Gemini TTS engine: Google's TTS API directly, no sidecar.
//
// Model order mirrors the sidecar (cheapest first): gemini-3.8-flash-lite-tts,
// then gemini-3.8-flash-tts, via the Interactions API with delivery in
// speech_metadata.style. The transcript is NEVER prefixed with [...] blocks —
// 3.8 treats input as verbatim and lite vocalizes them (rambling/static tail).
//
// Key: GOOGLE_GENERATIVE_AI_API_KEY (state/secrets.env → process.env).
// Never the 9router key — Google rejects it with API_KEY_INVALID.
//
// Cue translation (splitCues) ports the sidecar's split_cues; the two must
// stay in sync — scripts/gemini-tts.test.ts pins this copy's vectors, and any
// change here must be mirrored in gemini_tts.py.
import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import crypto from 'node:crypto';
import { config } from '../config.js';

const API_BASE = 'https://generativelanguage.googleapis.com/v1beta';
const MODELS = ['gemini-3.8-flash-lite-tts', 'gemini-3.8-flash-tts'];
const VOICE_STYLE_MAX = 300;

// Multi-speaker single-request cap for prebuilt voices (Google docs).
const MULTI_VOICE_CAP = 2;

export function apiKey(): string {
  return process.env.GOOGLE_GENERATIVE_AI_API_KEY || '';
}

export function isAvailable(): boolean {
  return !!apiKey();
}

const VOCAL_BURSTS: Record<string, string> = {
  laugh: 'laugh', laughing: 'laugh', laughter: 'laugh',
  chuckle: 'chuckle', chuckles: 'chuckle', giggle: 'giggle',
  sigh: 'sigh', sighs: 'sigh', cough: 'cough', breath: 'breath',
  gasp: 'gasp', groan: 'groan', yawn: 'yawn', sneeze: 'sneeze',
  snort: 'snort', sob: 'sob', cry: 'cry', shout: 'shout',
  scream: 'scream', whisper: 'whispering', whispering: 'whispering',
  'short pause': 'short pause', 'long pause': 'long pause',
  uhm: 'breath',
};

const DELIVERY_STYLES: Record<string, string> = {
  sarcasm: 'sarcastic', shouting: 'loud', whispering: 'whispered',
  robotic: 'flat and mechanical', 'extremely fast': 'speaking rapidly',
};

const CUE_RE = /\[([^\]\r\n]{1,40})\]/g;

/** Pull [...] cues out: vocal bursts become <...> tags, delivery modifiers
 *  join the style string, unknown brackets (track titles) survive. */
export function splitCues(text: string): { text: string; styles: string[] } {
  const styles: string[] = [];
  const clean = String(text ?? '').replace(CUE_RE, (m, body: string) => {
    const key = String(body).trim().toLowerCase();
    if (VOCAL_BURSTS[key]) return `<${VOCAL_BURSTS[key]}>`;
    if (DELIVERY_STYLES[key]) {
      styles.push(DELIVERY_STYLES[key]);
      return '';
    }
    return m;
  });
  return { text: clean.replace(/\s+/g, ' ').trim(), styles };
}

// NOTE: the Interactions API accepts no safety params (both snake_case and
// camelCase 400), so generation_config carries speech only. Default filters
// govern; a blocked render fails over through the normal fallback chain.

function styleFor(voiceStyle: unknown, cueStyles: string[]): string {
  const base = typeof voiceStyle === 'string' ? voiceStyle.trim().slice(0, VOICE_STYLE_MAX) : '';
  const extra = cueStyles.join(', ');
  const style = [base, extra].filter(Boolean).join(', ');
  return style;
}

import { fetchWithTimeout } from '../util/fetch-timeout.js';

// 3 minutes: TTS renders are slow and retried per model; the caller's abort
// (preview cancel, shutdown) still wins via signal composition.
const REQUEST_TIMEOUT_MS = 180_000;

async function postInteraction(body: unknown, signal?: AbortSignal): Promise<Buffer> {
  const key = apiKey();
  if (!key) throw new Error('GOOGLE_GENERATIVE_AI_API_KEY not set');
  let lastErr: unknown = null;
  for (const model of MODELS) {
    let res: Response;
    try {
      res = await fetchWithTimeout(`${API_BASE}/interactions`, {
        method: 'POST',
        headers: { 'x-goog-api-key': key, 'Content-Type': 'application/json' },
        body: JSON.stringify({ model, ...(body as Record<string, unknown>) }),
        signal,
        timeoutMs: REQUEST_TIMEOUT_MS,
      });
    } catch (err) {
      // Timeout or caller abort: a stall here must not wedge the render —
      // try the next model, then let the controller fallback chain cover.
      lastErr = err;
      continue;
    }
    if (res.status === 429) {
      lastErr = new Error(`Gemini TTS ${model} rate-limited (429)`);
      continue; // fail over immediately; the controller fallback chain covers
    }
    if (res.status >= 500) {
      const text = await res.text().catch(() => '');
      lastErr = new Error(`Gemini TTS ${model} HTTP ${res.status}: ${text.slice(0, 200)}`);
      continue; // transient server error — try the next model before giving up
    }
    if (!res.ok) {
      const text = await res.text().catch(() => '');
      throw new Error(`Gemini TTS ${model} HTTP ${res.status}: ${text.slice(0, 200)}`);
    }
    const json = (await res.json()) as any;
    const data: string | undefined = json?.output_audio?.data
      ?? json?.steps?.filter((s: any) => s?.type === 'model_output')
        .flatMap((s: any) => s?.content ?? [])
        .filter((c: any) => c?.type === 'audio')
        .at(-1)?.data;
    if (!data) {
      lastErr = new Error(`Gemini TTS ${model} returned no audio`);
      continue;
    }
    // Unary audio is WAV (RIFF) already — write bytes directly, never re-wrap.
    return Buffer.from(data, 'base64');
  }
  throw lastErr instanceof Error ? lastErr : new Error('Gemini TTS failed on all models');
}

async function outFile(customPath?: string): Promise<string> {
  const outPath = customPath || join(config.piper.outDir, `${crypto.randomBytes(6).toString('hex')}.wav`);
  await mkdir(dirname(outPath), { recursive: true });
  return outPath;
}

export async function speak(
  text: string,
  { voice, style, outPath: customPath, signal }: { voice?: string; style?: string; outPath?: string; signal?: AbortSignal } = {},
): Promise<string> {
  if (!text || !text.trim()) throw new Error('Empty TTS text');
  const { text: clean, styles } = splitCues(text);
  const body = {
    input: [{
      type: 'user_input',
      content: [{
        type: 'text',
        text: clean,
        annotations: [{ type: 'speech_metadata', style: styleFor(style, styles) }],
      }],
    }],
    response_format: { type: 'audio' },
    generation_config: {
      // No safety key: the Interactions API 400s unknown generation_config
      // params, and defaults govern. A blocked render fails over normally.
      speech_config: [{ voice: (voice || '').trim() || 'Puck' }],
    },
  };
  const audio = await postInteraction(body, signal);
  const outPath = await outFile(customPath);
  await writeFile(outPath, audio);
  return outPath;
}

export interface MultiLine {
  text: string;
  voice?: string;
  style?: string;
}

/** One conversational call for the whole exchange. Throws when more than
 *  MULTI_VOICE_CAP distinct voices are present — the caller falls back to
 *  per-line renders, same as the remote fast-path rule. */
export async function speakMulti(
  lines: MultiLine[],
  { outPath: customPath, signal }: { outPath?: string; signal?: AbortSignal } = {},
): Promise<string> {
  if (!lines || lines.length === 0) throw new Error('Empty TTS lines');
  const seen = new Map<string, string>();
  const turns: unknown[] = [];
  for (const line of lines) {
    const { text: clean, styles } = splitCues(line.text);
    const voice = (line.voice || '').trim() || 'Puck';
    const alias = voice.toLowerCase();
    if (!seen.has(alias)) {
      if (seen.size >= MULTI_VOICE_CAP) {
        throw new Error(`speakMulti supports ${MULTI_VOICE_CAP} voices per call`);
      }
      seen.set(alias, voice);
    }
    turns.push({
      type: 'text',
      text: clean,
      annotations: [{
        type: 'speech_metadata',
        speaker: seen.get(alias),
        style: styleFor(line.style, styles),
      }],
    });
  }
  const speakers = [...seen.entries()].map(([_alias, voice]) => ({ speaker: voice, voice }));
  const body = {
    input: [{ type: 'user_input', content: turns }],
    response_format: { type: 'audio' },
    generation_config: {
      speech_config: { mode: 'conversational', speakers },
    },
  };
  const audio = await postInteraction(body, signal);
  const outPath = await outFile(customPath);
  await writeFile(outPath, audio);
  return outPath;
}

/** Prebuilt voice ids for the picker. Empty on any failure — the UI falls
 *  back to free text like cloud-compat. */
export async function listVoices(): Promise<string[]> {
  try {
    const key = apiKey();
    if (!key) return [];
    const res = await fetch(`${API_BASE}/voices?pageSize=100&type=prebuilt`, {
      headers: { 'x-goog-api-key': key },
    });
    if (!res.ok) return [];
    const json = (await res.json()) as any;
    const voices = Array.isArray(json?.voices) ? json.voices : [];
    return voices
      .map((v: any) => String(v?.name || v?.id || '').replace(/^voices\//, '').trim())
      .filter((v: string) => v && v.length <= 100)
      .slice(0, 200);
  } catch {
    return [];
  }
}
