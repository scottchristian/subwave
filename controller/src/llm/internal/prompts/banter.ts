// Generate the exchange in one call, then queue.announceExchange renders each
// persona's voice through the serialized chain. Speaker enums stay strict;
// repairing ids could air the wrong voice. castSpeakerIdRule mitigates rejection (#1512).

import { z } from 'zod';
import * as settings from '../../../settings.js';
import { soulBrief, cloudExpressionCueFamily } from '../core/pure.js';
import { djObject } from '../strategy/object.js';
import { buildContextLines } from './context.js';
import { resolvePersonaVoiceSlot } from '../../../audio/persona-engine.js';
import { resolveCloudProviderForPersona, resolveCloudModelForPersona } from '../speech/cloud-speech.js';
import { CHATTERBOX_TAG_HINT, ELEVENLABS_V3_TAG_HINT, FISH_S21_TAG_HINT, GEMINI_TTS_TAG_HINT } from './system.js';

// Same field set as the free-text script generators (scripts.ts): ambient
// weather stays out (issue #471 — it dominated every segment); the dedicated
// weather skill owns that beat.
const BANTER_CONTEXT_FIELDS = ['date', 'clock', 'time', 'festival', 'show', 'listeners'];

// The exchange stays short by construction: radio banter that runs past ~6
// lines stops being a break and starts being a podcast.
const MIN_LINES = 3;
const MAX_LINES = 6;

// Souls ride as briefs, not in full: this block repeats once per cast member
// (host + up to GUESTS_PER_SHOW guests), and it exists to tell the model who
// is in the room, not to hand each one their whole character document.
function castBlock(host: any, guests: any[]): string {
  const entry = (p: any, role: string) =>
    `- ${p.id} — ${p.name} (${role}): ${soulBrief(p.soul) || 'no notes'}`;
  return [entry(host, 'HOST'), ...guests.map((g: any) => entry(g, 'GUEST'))].join('\n');
}

// The exchange's system prompt. Exported pure for the same reason as
// programme.ts's exchangeSystem: the station house rules have to be PROVABLY
// on this path (issue #1420 — they weren't), and a test that only asserts the
// block builder exists is exactly the regression it fails to catch.
export function banterSystem({ host, guests, show = null }: any): string {
  const showClause = show?.name ? ` of "${show.name}"` : '';
  const lang = String(host?.language || '').trim() || 'English';
  const langClause = ` Everyone speaks ${lang} on air. ${settings.spokenProperNounDirective(host)}`;
  
  // Resolve the primary engine (host) to see if we can use bracketed cues
  const s = settings.get();
  const engine = resolvePersonaVoiceSlot(host?.tts, s.tts)?.engine;
  let cueHint = '';
  let stageDirectionRule = '- Plain spoken words only: no stage directions, no asterisks, no emoji.';
  
  if (engine === 'chatterbox') {
    cueHint = CHATTERBOX_TAG_HINT;
    stageDirectionRule = '- Plain spoken words only: no asterisks, no emoji. You may use specific bracketed cues as noted below.';
  } else if (engine === 'remote') {
    cueHint = GEMINI_TTS_TAG_HINT;
    stageDirectionRule = '- Plain spoken words only: no asterisks, no emoji. You may use specific bracketed cues as noted below.';
  } else {
    const cueFamily = cloudExpressionCueFamily(
      resolveCloudProviderForPersona(host),
      resolveCloudModelForPersona(host)
    );
    if (cueFamily === 'fish-s21') {
      cueHint = FISH_S21_TAG_HINT;
      stageDirectionRule = '- Plain spoken words only: no asterisks, no emoji. You may use specific bracketed cues as noted below.';
    } else if (cueFamily === 'elevenlabs-v3') {
      cueHint = ELEVENLABS_V3_TAG_HINT;
      stageDirectionRule = '- Plain spoken words only: no asterisks, no emoji. You may use specific bracketed cues as noted below.';
    }
  }

  let banterRules = s.llm?.banterPrompt ? `${s.llm.banterPrompt}\n` : '';
  if (banterRules) {
    const guestNames = guests.map((g: any) => g.name).join(' and ');
    const firstGuest = guests[0]?.name || 'the guest';
    banterRules = banterRules
      .replace(/\{host\}/gi, host?.name || 'the host')
      .replace(/\{guest\}/gi, firstGuest)
      .replace(/\{guests\}/gi, guestNames)
      .replace(/\{show\}/gi, show?.name || 'the show');
  }

  return `You write short on-air exchanges between the hosts${showClause} on a personal internet radio station, mid-show. This is people who know each other talking in one studio: quick, warm, a little loose — real speech, not sketch comedy or a scripted bit.

The cast (persona id — name (role): voice notes):
${castBlock(host, guests)}

Rules:
- ${MIN_LINES} to ${MAX_LINES} lines total, at least two different speakers. Let the turn-taking breathe — it doesn't have to alternate mechanically, but nobody monologues.
- ${settings.castSpeakerIdRule()}
- Each speaker stays in THEIR OWN character per the voice notes. The host carries the room; guests chip in as themselves.
- Ground it in the moment you're given (the track playing, the hour, the show) — react, riff, disagree gently, tease. One thread, not a topic list.
- This is a conversation, NOT a link: do not introduce, back-announce, or name-drop the next track, do not read a station ident, do not announce the time.
- No greetings or sign-offs — the show is already rolling. No invented listener messages, callers, or events.
${banterRules}- IMPORTANT: Do not mention, assume, or invent the current weather (e.g. do not say "enjoy the sunshine"). Weather is handled elsewhere.
${stageDirectionRule}${langClause}${settings.castHouseRulesBlock()}${cueHint}`;
}

// Returns air-ready lines [{ persona, text }] in order, or null when the model
// couldn't produce a usable exchange (fewer than two lines or a single voice
// throughout — a monologue should go through the normal segment paths, not
// masquerade as banter).
export async function generateBanter({
  host, guests, show = null, current = null,
  context = null, recap = null, recentOpeners = null,
}: any) {
  const cast = [host, ...guests];
  const ids = cast.map((p: any) => p.id);
  const schema = z.object({
    lines: z.array(z.object({
      speaker: z.enum(ids as [string, ...string[]]).describe('the persona id of who says this line, from the cast list'),
      text: z.string().min(1).max(400).describe('the spoken line only — one or two short conversational sentences, with no speaker name or label prefix; the separate speaker field selects the voice'),
    })).min(MIN_LINES).max(MAX_LINES).describe('the exchange, in air order'),
  });

  // The host's on-air language governs the room — co-hosts on one show share
  // a broadcast language, same rule as the rest of the station. banterSystem
  // owns the language and spoken-name policy so pure prompt tests cover it.
  const system = banterSystem({ host, guests, show });

  const ctxLines = buildContextLines(context, { contextFields: BANTER_CONTEXT_FIELDS });
  if (current?.title) ctxLines.push(`On air right now: "${current.title}" by ${current.artist || 'unknown'}`);
  if (recap) ctxLines.push(`Already said on air recently (do not repeat these topics or phrasing):\n${recap}`);
  if (recentOpeners?.length) ctxLines.push(`Recent opening words (start the first line differently): ${recentOpeners.join(' | ')}`);
  const prompt = `${ctxLines.join('\n')}\n\nWrite the exchange.`;

  const out = await djObject({
    system,
    prompt,
    schema,
    temperature: 0.95,
    kind: 'generateBanter',
  });

  const byId = new Map(cast.map((p: any) => [p.id, p]));
  const lines = (out?.lines || [])
    .map((l: any) => ({ persona: byId.get(l.speaker), text: String(l.text || '').trim() }))
    .filter((l: any) => l.persona && l.text);
  const speakers = new Set(lines.map((l: any) => l.persona.id));
  if (lines.length < 2 || speakers.size < 2) return null;
  return lines;
}
