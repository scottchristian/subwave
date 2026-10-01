// TTS dispatcher: picks an engine per voice-kind, with a settings-driven
// override and an automatic fallback if the chosen engine fails. Every caller
// goes through here, never an engine module directly.

import * as piper from './piper.js';
import * as kokoro from './kokoro.js';
import { applyEdgeFades } from './wav-edges.js';
import * as chatterbox from './chatterbox.js';
import * as pocketTts from './pocketTts.js';
import { heavyColdEngines, heavyEnabledEngines } from './ttsHeavyClient.js';
import * as remoteTts from './remoteTts.js';
import * as gemini from './gemini.js';
import { normalizeForSpeech } from './speech-text.js';
import { scrubCjkForSpeech } from './spoken-script-policy.js';
import {
  configuredSlot, fallbackTextFor, orderedFallbacks, sameTtsTarget,
  type RescueSlot, type TtsTarget,
} from './tts-fallback.js';
import { localizedPreviewText } from './preview-text.js';
import * as cloud from '../llm/speech.js';
import { resolvePersonaVoiceSlot } from './persona-engine.js';
import { stripThinking } from '../llm/sdk.js';
import * as settings from '../settings.js';
import { recordTts } from '../stats.js';
import { logEvent } from '../observability/events.js';
import { energyForDaypart } from '../context.js';

export const ENGINES = ['piper', 'kokoro', 'chatterbox', 'pocket-tts', 'cloud', 'remote', 'gemini'];

// Kinds NOT voiced by the on-air persona: they use the global defaultEngine.
// Every other kind takes engine+voice from the effective persona's `tts`.
const GLOBAL_VOICE_KINDS = new Set(['jingle', 'default']);

// Explicit override (the persona-handoff mic-pass voices the OUTGOING persona
// after the clock has moved on), else the clock-driven effective persona.
function personaFor(persona?: any): any {
  return persona ?? settings.getEffectivePersona();
}

// The persona's TTS config for a persona-voiced kind, else null. This is the one
// seam where the 'inherit' engine sentinel is resolved; everything downstream
// compares against a concrete engine id.
function djPersonaTts(kind: string, persona?: any): any {
  if (GLOBAL_VOICE_KINDS.has(kind)) return null;
  const slot = personaFor(persona)?.tts || null;
  return resolvePersonaVoiceSlot(slot, settings.get().tts);
}

// The engine asked for BEFORE resolveEngine()'s availability/key reroute, so a
// resolve-time fallback shows in Stats as `fellBack` (#691).
function requestedEngine(kind: string, personaTts: any): string {
  if (personaTts && ENGINES.includes(personaTts.engine)) return personaTts.engine;
  return settings.get().tts?.defaultEngine || 'piper';
}

// Pre-flight availability/key gate, in one predicate so resolveEngine() (the
// primary) and fallbackChain() (the runtime rescue) agree on what "installed"
// means. `cloudProvider` scopes the key check to the provider that would be
// called. Piper is local, keyless and always present: the universal floor.
function engineUsable(engine: string, cloudProvider?: string | null): boolean {
  if (!ENGINES.includes(engine)) return false;
  if (engine === 'cloud') return cloud.isConfigured(cloudProvider ?? null);
  if (engine === 'chatterbox') return chatterbox.isAvailable();
  if (engine === 'pocket-tts') return pocketTts.isAvailable();
  if (engine === 'kokoro') return kokoro.isAvailable();
  if (engine === 'remote') return remoteTts.isAvailable();
  if (engine === 'gemini') return gemini.isAvailable();
  return true;
}

// The persona's own cloud provider, but only when the persona is actually ON
// the cloud engine — otherwise the global Cloud provider applies.
function personaCloudProvider(personaTts: any): string | null {
  return (personaTts && personaTts.engine === 'cloud') ? (personaTts.cloudProvider ?? null) : null;
}

// The operator's configured rescue slot (settings.tts.fallback), or null when
// absent/off. One reader for both the pre-flight reroute and the mid-render chain.
function fallbackSlot(): RescueSlot | null {
  return configuredSlot(settings.get().tts?.fallback, ENGINES);
}

// A slot for an engine chosen by the system, not the operator: no voice
// override, so the engine speaks with its own default.
function plainSlot(engine: string): RescueSlot {
  return { engine, personaTts: null };
}

// What a render is aimed at: the engine, plus (for `cloud` only) the provider.
// The station default is NOT substituted here; that is sameTtsTarget's job.
function ttsTarget(engine: string, personaTts: any): TtsTarget {
  return {
    engine,
    cloudProvider: engine === 'cloud' ? personaCloudProvider(personaTts) : null,
  };
}

// The station's Cloud provider — what an unspecified cloud target resolves to.
function defaultCloudProvider(): string | null {
  return settings.get().tts?.cloud?.provider ?? null;
}

// True when a segment did not go out on the target the persona asked for:
// a different engine, or a different provider inside `cloud` (#1345).
function rerouted(
  requestedEngineId: string, requestedPersonaTts: any,
  actualEngine: string, actualPersonaTts: any,
): boolean {
  return !sameTtsTarget(
    ttsTarget(requestedEngineId, requestedPersonaTts),
    ttsTarget(actualEngine, actualPersonaTts),
    defaultCloudProvider(),
  );
}

// Which engine — and which voice — speaks a segment of `kind`. Returns a slot
// because a reroute can carry the operator's chosen fallback voice; an ordinary
// resolve returns a null override so the persona's own voice applies.
function resolveEngine(kind: string, personaTts: any): RescueSlot {
  const tts = settings.get().tts || {};
  let chosen;
  if (personaTts && ENGINES.includes(personaTts.engine)) {
    chosen = personaTts.engine;          // persona owns the spoken engine
  } else {
    chosen = tts.defaultEngine || 'piper';   // jingle / fallback
  }
  if (!ENGINES.includes(chosen)) return plainSlot('piper');
  // Known-unavailable engine: route to the operator's configured fallback if it
  // can speak, else their saved default engine, else Piper. The default engine
  // branch is deliberately NOT probed; the runtime chain in speak() catches it.
  if (!engineUsable(chosen, personaCloudProvider(personaTts))) {
    // Probed with the fallback's own cloud provider, matching the credentials
    // the call would use.
    const configured = fallbackSlot();
    if (
      configured
      && rerouted(configured.engine, configured.personaTts, chosen, personaTts)
      && engineUsable(configured.engine, configured.personaTts?.cloudProvider ?? null)
    ) {
      return configured;
    }
    if (tts.defaultEngine && tts.defaultEngine !== chosen) return plainSlot(tts.defaultEngine);
    // Same engine id as the unusable primary, which only a different cloud
    // provider can survive (#1345). Probed, unlike the branch above.
    if (
      tts.defaultEngine
      && rerouted(tts.defaultEngine, null, chosen, personaTts)
      && engineUsable(tts.defaultEngine, null)
    ) {
      return plainSlot(tts.defaultEngine);
    }
    return plainSlot('piper');
  }
  return plainSlot(chosen);
}

// Ordered runtime rescues after `primary` threw mid-render. Order: operator's
// configured fallback (the only rung carrying a voice), their default engine,
// Piper, Kokoro. At most four attempts. The hardcoded rungs are probed with the
// GLOBAL cloud provider (null); the configured rung with its own.
// Ordering is pure and pinned by scripts/tts-fallback.test.ts.
function fallbackChain(primary: TtsTarget): RescueSlot[] {
  return orderedFallbacks(
    primary,
    fallbackSlot(),
    settings.get().tts?.defaultEngine,
    (engine, cloudProvider) => engineUsable(engine, cloudProvider ?? null),
    defaultCloudProvider(),
  );
}

// Voice level trim (dB) for a segment of `kind`: per-engine gain plus the
// persona's own trim, clamped to ±TTS_GAIN_CLAMP_DB. 0 = unity. Applied
// downstream by broadcast/queue.ts as a `liq_amplify` annotation. Uses the
// RESOLVED engine so the gain matches whichever engine actually speaks.
export function voiceGainDb(kind: string, persona?: any): number {
  const personaTts = djPersonaTts(kind, persona);
  const { engine } = resolveEngine(kind, personaTts);
  const tts: any = settings.get().tts || {};
  const engineGain = settings.clampTtsGain(tts.gainDb?.[engine]);
  const personaGain = personaTts ? settings.clampTtsGain(personaTts.gainDb) : 0;
  return settings.clampTtsGain(engineGain + personaGain);
}

// Speech-rate multiplier for `kind` (1.0 = engine default), clamped to
// [0.5, 2.0]: engine base x persona x current programme pace. The engine base
// applies universally, jingles included; persona x programme pace only to
// persona-voiced kinds, so a jingle cut at 2am carries no 2am pacing.
// `liveOverride` replaces the persona/programme term but still composes with
// the engine base. Reads the
// RESOLVED engine, like voiceGainDb(). Also feeds the intro-budget word
// ceiling (#962) in dj-agent.ts.
export function speechPaceScale(kind: string, persona?: any, liveOverride?: number | null): number {
  const personaTts = djPersonaTts(kind, persona);
  const { engine: primary } = resolveEngine(kind, personaTts);
  const ttsCfg: any = settings.get().tts || {};
  const engineSpeed = settings.clampTtsSpeed(ttsCfg.speed?.[primary]);
  const live = liveOverride != null
    ? liveOverride
    : GLOBAL_VOICE_KINDS.has(kind)
      ? 1
      : (personaTts ? settings.clampTtsSpeed(personaTts.speed) : 1) * energyForDaypart().speed;
  // Bounds-clamp but do NOT snap to the 0.05 grid: programme pacing is a
  // non-grid value. Snapping applies only to the stored engine/persona knobs.
  return settings.clampEffectiveTtsSpeed(engineSpeed * live);
}

async function speakWith(engine: string, text: string, opts: any, personaTts: any) {
  if (engine === 'kokoro') {
    const voice = (personaTts && personaTts.engine === 'kokoro' && personaTts.voice)
      ? personaTts.voice
      : settings.get().tts?.kokoro?.voice;
    // Explicit phonemizer lang. Absent → KOKORO_LANG env → auto-detect.
    const lang = opts.lang || settings.get().tts?.kokoro?.lang || undefined;
    return kokoro.speak(text, { ...opts, voice, lang });
  }
  if (engine === 'chatterbox') {
    // chatterbox `voice` is a reference-WAV filename; empty → built-in default.
    const voice = (personaTts && personaTts.engine === 'chatterbox' && personaTts.voice)
      ? personaTts.voice
      : settings.get().tts?.chatterbox?.referenceVoice;
    return chatterbox.speak(text, { ...opts, voice });
  }
  if (engine === 'pocket-tts') {
    // PocketTTS voice is a built-in id (alba, anna, …); persona override wins.
    // The worker falls back to its default on an unknown id, never silence.
    const voice = (personaTts && personaTts.engine === 'pocket-tts' && personaTts.voice)
      ? personaTts.voice
      : settings.get().tts?.pocketTts?.voice;
    return pocketTts.speak(text, { ...opts, voice });
  }
  if (engine === 'cloud') {
    // Persona picks provider + voice; the shared tts.cloud holds key + model.
    // `opts.cloudVoiceSettings` is preview-only (synthesizeSample) and rides the
    // same override so "Play sample" auditions unsaved slider values.
    const personaOverride = (personaTts && personaTts.engine === 'cloud')
      ? { provider: personaTts.cloudProvider, voice: personaTts.voice }
      : null;
    const cloudModelOverride = typeof opts.cloudModel === 'string' ? { model: opts.cloudModel } : null;
    const cloudOverride = (personaOverride || cloudModelOverride || opts.cloudVoiceSettings || opts.fishSettings)
      ? { ...(personaOverride || {}), ...(cloudModelOverride || {}), ...(opts.cloudVoiceSettings || {}), ...(opts.fishSettings || {}) }
      : null;
    return cloud.speak(text, { ...opts, cloudOverride });
  }
  if (engine === 'remote') {
    // `voice` is forwarded as-is; the endpoint interprets it and owns its
    // own defaults, so there is no global fallback voice here. `voiceStyle`
    // rides the same way: the persona's delivery directive, or empty for the
    // endpoint's built-in style.
    const voice = (personaTts && personaTts.engine === 'remote' && personaTts.voice)
      ? personaTts.voice
      : undefined;
    const style = typeof opts.voiceStyle === 'string' ? opts.voiceStyle : undefined;
    return remoteTts.speak(text, { ...opts, voice, style });
  }
  if (engine === 'gemini') {
    // Direct Google TTS, no sidecar. Voice ids are prebuilt/custom/replicated
    // names; empty falls to the engine default. Style threads identically.
    const voice = (personaTts && personaTts.engine === 'gemini' && personaTts.voice)
      ? personaTts.voice
      : undefined;
    const style = typeof opts.voiceStyle === 'string' ? opts.voiceStyle : undefined;
    return gemini.speak(text, { ...opts, voice, style });
  }
  // piper `voice` is an .onnx filename; empty → the baked-in default voice.
  const voice = (personaTts && personaTts.engine === 'piper' && personaTts.voice)
    ? personaTts.voice
    : undefined;
  return piper.speak(text, { ...opts, voice });
}

// Admin voice-preview ("Play sample"). Renders a one-off sample WAV with an
// EXPLICIT engine + voice, bypassing both persona resolution and speak()'s
// silent fallback chain so an unavailable engine raises a real error. Gain (dB)
// is a playout-time trim and is deliberately not baked in. Returns the WAV path;
// the caller serves and unlinks it.
const PREVIEW_TEXT_MAX = 200;
const DEFAULT_PREVIEW_TEXT = "You're listening to SUB/WAVE. This is a voice preview.";

export async function synthesizeSample(
  { engine, voice = '', cloudProvider = 'openai', cloudModel, speed, lang, language, text, corrections, voiceSettings, fishSettings: requestedFishSettings, signal, style }: {
    engine: string;
    voice?: string;
    cloudProvider?: string;
    // Unsaved model id so preview validates the exact provider/model choice.
    cloudModel?: string;
    speed?: number;
    lang?: string;
    // Persona's free-text on-air language ("Turkish", "Türkçe"): picks the
    // sample sentence when no explicit `text` is given. Unknown → English.
    language?: string;
    text?: string;
    // Unsaved corrections override (admin "Test corrections"), used instead of
    // settings.tts.corrections for this call. Sanitized through the same
    // normalizeTtsCorrections the persisted settings use, so preview can't drift.
    corrections?: unknown;
    // Unsaved provider controls to audition; same field names as
    // settings.tts.cloud so they merge straight into cloudOverride.
    voiceSettings?: {
      voiceStability?: number;
      voiceStyle?: number;
      voiceSimilarityBoost?: number;
      voiceUseSpeakerBoost?: boolean;
    };
    fishSettings?: {
      temperature?: number;
      topP?: number;
      latency?: 'low' | 'normal' | 'balanced';
    };
    signal?: AbortSignal;
    // Delivery directive to audition (persona voiceStyle). Only the remote
    // engine reads it; empty means the endpoint's built-in style.
    style?: string;
  },
): Promise<string> {
  if (!ENGINES.includes(engine)) throw new Error(`Unknown engine: ${engine}`);
  const raw = (typeof text === 'string' && text.trim())
    ? text.trim()
    : (localizedPreviewText(language) ?? DEFAULT_PREVIEW_TEXT);
  const activeCorrections = corrections !== undefined
    ? settings.normalizeTtsCorrections(corrections)
    : settings.get().tts?.corrections;
  const sample = normalizeForSpeech(raw.slice(0, PREVIEW_TEXT_MAX), activeCorrections);
  // `speed` is already the final preview multiplier. A persona preview can
  // compose two saved 0.05-grid controls into a non-grid rate (0.90 x 1.15 =
  // 1.035), so only bounds-clamp here; snapping again would diverge from air.
  const scale = settings.clampEffectiveTtsSpeed(speed);
  let previewCloudModel: string | undefined;
  if (engine === 'cloud' && cloudModel !== undefined) {
    const v = String(cloudModel).trim();
    if (v.length < 1 || v.length > 100 || /[\r\n]/.test(v)) {
      throw new Error('Cloud preview model must be 1-100 characters with no line breaks');
    }
    previewCloudModel = v;
  }
  // Clamp to ElevenLabs' [0,1] like settings.update() does for saved values,
  // so a hand-crafted preview request can't 400 the provider call.
  const clamp01 = (n: unknown) =>
    typeof n === 'number' && Number.isFinite(n) ? Math.min(1, Math.max(0, n)) : undefined;
  let cloudVoiceSettings: Record<string, number | boolean> | undefined;
  if (engine === 'cloud' && voiceSettings) {
    cloudVoiceSettings = {};
    for (const key of ['voiceStability', 'voiceStyle', 'voiceSimilarityBoost'] as const) {
      const v = clamp01(voiceSettings[key]);
      if (v !== undefined) cloudVoiceSettings[key] = v;
    }
    if (typeof voiceSettings.voiceUseSpeakerBoost === 'boolean') {
      cloudVoiceSettings.voiceUseSpeakerBoost = voiceSettings.voiceUseSpeakerBoost;
    }
    if (Object.keys(cloudVoiceSettings).length === 0) cloudVoiceSettings = undefined;
  }
  // Synthetic persona so speakWith()'s per-engine branches pick up the
  // requested voice/provider. No outPath → each engine self-generates a WAV
  // path under config.piper.outDir (reaped by cleanupOldVoices).
  const personaTts = { engine, voice, cloudProvider };
  let fishSettings: Record<string, number | string> | undefined;
  if (engine === 'cloud' && requestedFishSettings) {
    fishSettings = {
      temperature: clamp01(requestedFishSettings.temperature) ?? settings.get().tts?.cloud?.temperature ?? 0.7,
      topP: clamp01(requestedFishSettings.topP) ?? settings.get().tts?.cloud?.topP ?? 0.7,
      latency: ['low', 'normal', 'balanced'].includes(requestedFishSettings.latency || '')
        ? requestedFishSettings.latency as string
        : settings.get().tts?.cloud?.latency || 'normal',
    };
  }
  return speakWith(engine, sample, { speedScale: scale, language: '', soul: '', lang, cloudModel: previewCloudModel, cloudVoiceSettings, fishSettings, signal, voiceStyle: style }, personaTts);
}

// Public entry point. Tries the configured engine; on failure falls back so the
// DJ never goes silent. Every call is timed into the TTS ring buffer (stats.js).
// A whole exchange in ONE Gemini request. Two things make this safe to expose
// separately from announceExchange's own loop:
//
//   • Rendering is the only thing batched. The caller still decides how to air
//     it, so per-line session turns, per-speaker attribution, per-line gain and
//     the handoff's "settle on the final line" rule all stay intact — a batch
//     that collapsed N lines into one segment would lose every one of those.
//   • It is strictly optional. Anything mixed, a 3rd distinct voice, a custom
//     `voice_…` id, or any failure at all throws, and the caller renders
//     per-line. Multi-speaker is an improvement in cadence, never a
//     precondition for speaking.
export async function speakExchange(
  lines: { persona?: any; text: string }[],
  { kind = 'banter', outPath, signal, speedScale }: {
    kind?: string; outPath?: string; signal?: AbortSignal; speedScale?: number;
  } = {},
): Promise<string> {
  if (!lines || lines.length === 0) throw new Error('Empty TTS exchange');
  const resolved = lines.map((l) => {
    const personaTts = djPersonaTts(kind, l.persona);
    const slot = resolveEngine(kind, personaTts);
    return { line: l, engine: slot.engine, personaTts: slot.personaTts ?? personaTts };
  });
  // All-gemini only: a mixed engine is two renderers, not one conversation.
  if (!resolved.every((r) => r.engine === 'gemini')) {
    throw new Error('speakExchange batches an all-gemini exchange only');
  }
  const out = resolved.map(({ line: l, personaTts }) => ({
    text: scrubCjkForSpeech(
      normalizeForSpeech(stripThinking(l.text || ''), settings.get().tts?.corrections),
      String(personaFor(l.persona)?.language || '').trim(),
    ),
    // Only a persona that actually PINS gemini owns its voice; otherwise the
    // line takes gemini's default, same rule as the single-line path.
    voice: personaTts?.engine === 'gemini' && personaTts.voice ? personaTts.voice : undefined,
    style: typeof l.persona?.voiceStyle === 'string' ? l.persona.voiceStyle : undefined,
    speaker: String(l.persona?.name || '').trim() || undefined,
  }));

  const started = Date.now();
  try {
    const result = await gemini.speakMulti(out, { outPath, signal, speedScale });
    if (typeof result === 'string') await applyEdgeFades(result);
    const combined = out.map((l) => l.text).join(' ').slice(0, 240);
    recordTts({
      kind, requested: 'gemini', chars: combined.length,
      text: combined, persona: 'Multi-Speaker',
      engine: 'gemini', fellBack: false,
      ok: true, ms: Date.now() - started, t: new Date().toISOString(),
    });
    return result;
  } catch (err) {
    recordTts({
      kind, requested: 'gemini', chars: 0,
      text: 'Multi-speaker exchange failed', persona: 'Multi-Speaker',
      engine: 'gemini', fellBack: false,
      ok: false, ms: Date.now() - started, error: (err as any).message,
      t: new Date().toISOString(),
    });
    throw err;
  }
}

export async function speak(
  text: string,
  { kind = 'default', outPath, speedScale, persona }: { kind?: string; outPath?: string; speedScale?: number; persona?: any } = {},
) {
  // Resolve before normalising the text: the same value owns both the cloud
  // pronunciation hint and the unsupported-script safety boundary.
  const language = GLOBAL_VOICE_KINDS.has(kind)
    ? ''
    : String(personaFor(persona)?.language || '').trim();
  // Scrub leaked reasoning at the single point every booth-bound string
  // converges (#949): a structured say/intro field can carry a <think> token
  // that the free-text generators' own stripThinking never sees. No-op on clean
  // text. Operator speech corrections are read live, so a saved rule applies to
  // the next spoken line with no restart.
  const normalizedText = normalizeForSpeech(stripThinking(text), settings.get().tts?.corrections);
  const speakText = GLOBAL_VOICE_KINDS.has(kind)
    ? normalizedText
    : scrubCjkForSpeech(normalizedText, language);
  // `persona` overrides the effective persona so the handoff mic-pass can voice
  // the outgoing DJ after the hour has flipped.
  const personaTts = djPersonaTts(kind, persona);
  const requested = requestedEngine(kind, personaTts);
  const primarySlot = resolveEngine(kind, personaTts);
  const primary = primarySlot.engine;
  // A pre-flight reroute onto the operator's configured fallback carries THAT
  // slot's voice; an ordinary resolve leaves the persona's own override.
  const primaryPersonaTts = primarySlot.personaTts ?? personaTts;
  const primaryFellBack = rerouted(requested, personaTts, primary, primaryPersonaTts);
  // Engine-native bracket cues reach the expressive primary untouched; a
  // local/remote rescue would speak them literally, so sanitize only that.
  const speakingPersona = GLOBAL_VOICE_KINDS.has(kind) ? null : personaFor(persona);
  const cloudCueFamily = requested === 'cloud' && speakingPersona
    ? cloud.requestedCloudExpressionCueFamilyForPersona(speakingPersona)
    : '';
  const rescueText = fallbackTextFor(requested, cloudCueFamily, speakText);
  const primaryText = primaryFellBack ? rescueText : speakText;
  // Persona soul rides to the cloud engine so delivery matches the writing
  // (#579), like `language` does for pronunciation (#558). DJ-voiced kinds only.
  // Only cloud-speech.ts reads either; every other engine ignores them.
  const soul = GLOBAL_VOICE_KINDS.has(kind)
    ? ''
    : String(personaFor(persona)?.soul || '').trim();
  // Delivery directive for the remote engine (accent, pace, energy). DJ-voiced
  // kinds only; empty means the endpoint's built-in style for that voice.
  const voiceStyle = GLOBAL_VOICE_KINDS.has(kind)
    ? ''
    : String((speakingPersona as any)?.voiceStyle || '').trim();
  const scale = speechPaceScale(kind, persona, speedScale);
  const started = Date.now();
  const chars = (speakText || '').length;
  // Shared fields for every recordTts() outcome below. `text` is capped so the
  // ring buffer stays small (the admin debug panel polls the whole ring ~2s).
  const callBase = {
    kind, requested, chars,
    text: (speakText || '').slice(0, 240),
    persona: GLOBAL_VOICE_KINDS.has(kind) ? null : (personaFor(persona)?.name || null),
  };
  try {
    const result = await speakWith(primary, primaryText, { outPath, speedScale: scale, language, soul, voiceStyle }, primaryPersonaTts);
    // Bake 40ms edge fades in so hard file boundaries never reach the broadcast
    // compressor as a click. Render time is the only place the tail can be
    // faded. Best-effort: non-WAV output (cloud mp3) is left as-is.
    if (typeof result === 'string') await applyEdgeFades(result);
    recordTts({
      ...callBase, engine: primary, fellBack: primaryFellBack,
      ok: true, ms: Date.now() - started, t: new Date().toISOString(),
    });
    logEvent('tts', { chars, engine: primary });

    return result;
  } catch (err) {
    // Primary passed the pre-flight gate but threw mid-render: walk the chain.
    const chain = fallbackChain(ttsTarget(primary, primaryPersonaTts));
    if (!chain.length) {
      recordTts({
        ...callBase, engine: primary, fellBack: primaryFellBack,
        ok: false, ms: Date.now() - started, error: err.message,
        t: new Date().toISOString(),
      });
      throw err;
    }
    let lastErr = err;
    let lastEngine = primary;
    for (const slot of chain) {
      const fallback = slot.engine;
      console.error(`[tts] ${lastEngine} failed for kind=${kind}: ${lastErr.message} — falling back to ${fallback}`);
      try {
        // The persona's own tts is never forwarded to a rescue: a cloud persona
        // rerouted off a dead provider and rescued onto `cloud` would re-apply
        // the credentials the chain probe just rejected. What rides is the
        // slot's own override (null for hardcoded rungs, the operator's
        // engine+voice for their configured one), so probe and call agree.
        const result = await speakWith(fallback, rescueText, { outPath, speedScale: scale, language, soul, voiceStyle }, slot.personaTts);
        if (typeof result === 'string') await applyEdgeFades(result);
        recordTts({
          ...callBase, engine: fallback, fellBack: true,
          ok: true, ms: Date.now() - started, t: new Date().toISOString(),
        });
        logEvent('tts', { chars: rescueText.length, engine: fallback });
        return result;
      } catch (err2) {
        lastErr = err2;
        lastEngine = fallback;
      }
    }
    // Every rescue failed too — record against the last engine attempted.
    recordTts({
      ...callBase, engine: lastEngine, fellBack: true,
      ok: false, ms: Date.now() - started, error: lastErr.message,
      t: new Date().toISOString(),
    });
    throw lastErr;
  }
}

// Attempt to speak an entire multi-voice exchange at once if all speakers
// are configured to use the `remote` engine. Named `speakRemoteExchange`, not
// `speakExchange`: the native-Gemini batching above owns the upstream name, and
// two exports of one name is a redeclare error rather than an overload.
// NOTE: the air path currently renders exchanges PER LINE (queue.ts), so
// neither batcher is called; both are kept because batching is opt-in by
// engine and either side may be switched back on. This is significantly faster
// and allows the LLM to hear the full conversation flow (Gemini Multi-Speaker).
// Throws if any line isn't using the remote engine (caller should fallback to per-line).
export async function speakRemoteExchange(
  lines: { persona: any; text: string }[],
  { kind = 'banter', outPath }: { kind?: string; outPath?: string } = {},
): Promise<string> {
  const remoteLines: { text: string; voice?: string }[] = [];
  
  for (const l of lines) {
    const personaTts = djPersonaTts(kind, l.persona);
    const slot = resolveEngine(kind, personaTts);
    if (slot.engine !== 'remote') {
      throw new Error('speakRemoteExchange only supports the remote engine for all speakers');
    }
    
    // We must pass the raw text and the persona voice
    const speakText = scrubCjkForSpeech(
      normalizeForSpeech(stripThinking(l.text), settings.get().tts?.corrections),
      String(personaFor(l.persona)?.language || '').trim()
    );
    
    const primaryPersonaTts = slot.personaTts ?? personaTts;
    const voice = (primaryPersonaTts && primaryPersonaTts.engine === 'remote' && primaryPersonaTts.voice)
      ? primaryPersonaTts.voice
      : undefined;
      
    remoteLines.push({ text: speakText, voice });
  }

  const started = Date.now();
  try {
    const result = await remoteTts.speakMulti(remoteLines, { outPath });
    if (typeof result === 'string') await applyEdgeFades(result);
    
    // Log a single aggregate entry in the TTS ring buffer
    const combinedText = lines.map(l => `${l.persona?.name || 'DJ'}: ${l.text}`).join('\n').slice(0, 240);
    recordTts({
      kind, requested: 'remote', chars: combinedText.length,
      text: combinedText, persona: 'Multi-Speaker',
      engine: 'remote', fellBack: false,
      ok: true, ms: Date.now() - started, t: new Date().toISOString(),
    });
    const totalChars = lines.reduce((acc, l) => acc + (l.text || '').length, 0);
    logEvent('tts', { chars: totalChars, engine: 'remote' });
    
    return result;
  } catch (err) {
    recordTts({
      kind, requested: 'remote', chars: 0,
      text: 'Multi-speaker exchange failed', persona: 'Multi-Speaker',
      engine: 'remote', fellBack: false,
      ok: false, ms: Date.now() - started, error: (err as any).message,
      t: new Date().toISOString(),
    });
    throw err;
  }
}

// Re-exported: every engine writes WAVs into piper's output dir, so cleanup is
// engine-agnostic and callers need not know which engine wrote the file.
export { cleanupOldVoices } from './piper.js';

export function availableEngines() {
  return {
    piper: true,
    kokoro: kokoro.isAvailable(),
    chatterbox: chatterbox.isAvailable(),
    'pocket-tts': pocketTts.isAvailable(),
    // tts-heavy sidecar's configured engines (TTS_HEAVY_ENGINES): string[] when
    // reachable, null when unknown. Separates "engine off" from "sidecar off".
    heavyEnabled: heavyEnabledEngines(),
    // Which of those the sidecar has idle-unloaded (#1579). Still available (the
    // next line pays a model load), so routing is unaffected; badge only.
    heavyCold: heavyColdEngines(),
    // Whether PocketTTS can clone voices (gated weights present); null = unknown.
    // The admin UI warns that a cloned .wav silently reverts otherwise (#238).
    pocketTtsCloning: pocketTts.cloningAvailable(),
    cloud: cloud.isConfigured(),
    remote: remoteTts.isAvailable(),
    gemini: gemini.isAvailable(),
    // Per-provider: a persona's cloud voice needs ITS provider configured,
    // which can differ from the global Cloud-engine provider.
    cloudByProvider: {
      openai: cloud.isConfigured('openai'),
      elevenlabs: cloud.isConfigured('elevenlabs'),
      'fish-audio': cloud.isConfigured('fish-audio'),
    },
  };
}

// A PocketTTS `voice` that is a cloned reference (.wav filename or absolute
// path) rather than a built-in id. Mirrors resolveVoice() in pocketTts.ts.
function isPocketClone(voice?: string | null): boolean {
  const v = (voice || '').trim();
  return !!v && (/\.wav$/i.test(v) || v.startsWith('/'));
}

// Snapshot of how a spoken segment would route right now, for /debug: which
// engine the effective persona resolves to and whether that is a fallback.
export function describeRouting() {
  const persona = settings.getEffectivePersona();
  const tts = settings.get().tts || {};
  // Resolved, like djPersonaTts(): this function reproduces the dispatcher's
  // per-engine comparisons, and against a raw 'inherit' slot every one of them
  // is wrong — `fellBack` would report a fallback on a station where nothing
  // fell back at all.
  const personaTts = resolvePersonaVoiceSlot(persona?.tts || null, tts);
  const requested = personaTts?.engine || tts.defaultEngine || 'piper';
  const slot = resolveEngine('dj-speak', personaTts);   // any persona-voiced kind
  const engine = slot.engine;
  let voice: string | null = null;
  let provider: string | null = null;
  if (slot.personaTts) {
    // Pre-flight reroute: the slot carries the exact voice/provider that will
    // speak, so report it directly rather than re-deriving from the persona.
    voice = slot.personaTts.voice || null;
    provider = engine === 'cloud' ? (slot.personaTts.cloudProvider || null) : null;
  } else if (engine === 'cloud') {
    voice = personaTts?.engine === 'cloud' ? personaTts.voice : tts.cloud?.voice;
    provider = (personaTts?.engine === 'cloud' ? personaTts.cloudProvider : tts.cloud?.provider) as any;
  } else if (engine === 'kokoro') {
    voice = (personaTts?.engine === 'kokoro' && personaTts.voice)
      ? personaTts.voice
      : tts.kokoro?.voice;
  } else if (engine === 'chatterbox') {
    // For chatterbox, `voice` is the reference-WAV filename; empty → built-in.
    voice = (personaTts?.engine === 'chatterbox' && personaTts.voice)
      ? personaTts.voice
      : (tts.chatterbox?.referenceVoice || null);
  } else if (engine === 'pocket-tts') {
    voice = (personaTts?.engine === 'pocket-tts' && personaTts.voice)
      ? personaTts.voice
      : (tts.pocketTts?.voice || null);
  } else if (engine === 'piper') {
    // For piper, `voice` is the .onnx filename; empty → baked-in default.
    voice = (personaTts?.engine === 'piper' && personaTts.voice)
      ? personaTts.voice
      : null;
  } else if (engine === 'remote' || engine === 'gemini') {
    voice = (personaTts?.engine === engine && personaTts.voice)
      ? personaTts.voice
      : null;
  }
  // A cloned PocketTTS voice silently reverts to a built-in when the gated
  // weights are absent (#238); surface why, not a healthy-looking no-op.
  let warning: string | null = null;
  if (engine === 'pocket-tts' && isPocketClone(voice) && pocketTts.cloningAvailable() === false) {
    warning = 'PocketTTS voice cloning is unavailable in this build (gated weights '
      + 'not loaded) — this cloned voice reverts to a built-in. Set HF_TOKEN to enable cloning.';
  }
  // The configured rescue, so /debug answers "what speaks if this engine dies".
  // `usable` probes the fallback's own cloud provider: the chain silently skips
  // a configured-but-unusable fallback, which is worth seeing here.
  const configured = fallbackSlot();
  const fallbackCfg = tts.fallback || {};
  return {
    effectivePersona: persona ? { id: persona.id, name: persona.name } : null,
    available: availableEngines(),
    spoken: {
      requested,
      engine,
      voice: voice || null,
      provider: provider || null,
      // Provider-aware like speak()'s: a cloud→cloud reroute is still a fallback.
      fellBack: rerouted(requested, personaTts, engine, slot.personaTts ?? personaTts),
      warning,
    },
    fallback: {
      enabled: !!fallbackCfg.enabled,
      engine: configured?.engine || fallbackCfg.engine || null,
      voice: configured?.personaTts?.voice || null,
      provider: configured?.engine === 'cloud'
        ? (configured.personaTts?.cloudProvider || null)
        : null,
      usable: configured
        ? engineUsable(configured.engine, configured.personaTts?.cloudProvider ?? null)
        : false,
    },
    jingle: { engine: resolveEngine('jingle', null).engine },
  };
}
