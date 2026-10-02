// Pins for the native `gemini` TTS engine (direct Google, no sidecar) and the
// voiceStyle delivery directive.
//
// Contracts:
//   • `gemini` is a first-class engine id in the persona + skill vocabularies
//     (restated lists stay equal — same posture as the tag regexes).
//   • splitCues mirrors gemini_tts.py split_cues: vocal bursts become <...>,
//     delivery modifiers join style, unknown brackets (track titles) survive.
//   • fallbackTextFor strips brackets for gemini rescues (it speaks literally).
//   • OpenAI instructions carry voiceStyle on gpt-4o-tts only.
//   • Gemini is presented as a CLOUD PROVIDER, not a peer engine card, while
//     keeping its own engine id end to end (see the fold block at the bottom).
//
// Run: `npm test -- gemini-tts`.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { TTS_ENGINES } from '../src/schemas/persona.js';
import { splitCues } from '../src/audio/gemini.js';
import { fallbackTextFor } from '../src/audio/tts-fallback.js';
import { deliveryHint } from '../src/llm/internal/speech/cloud-speech.js';

test('gemini is a first-class engine id', () => {
  assert.ok((TTS_ENGINES as readonly string[]).includes('gemini'));
});

test('persona schema accepts a gemini slot', async () => {
  const persona = await import('../src/schemas/persona.js');
  const slot = { engine: 'gemini', voice: 'Despina', cloudProvider: 'openai', gainDb: 0, speed: 1 };
  const parsed = persona.personaSchema.parse({
    name: 'G', soul: 's', tagline: '', frequency: 'moderate', scriptLength: 'concise',
    djMode: false, linkStyle: 'natural', humour: 5, localColour: 5, warmth: 5,
    language: '', avatar: '', tts: slot, skills: null, tags: [],
  });
  const out = Array.isArray(parsed) ? parsed[0] : parsed;
  assert.equal(out.tts.engine, 'gemini');
  assert.equal(out.tts.voice, 'Despina');
});

test('splitCues: bursts become angle tags, delivery joins style, titles survive', () => {
  assert.deepEqual(
    splitCues('Hello [sigh] mate, that was [sarcasm] brilliant [short pause] news'),
    { text: 'Hello <sigh> mate, that was brilliant <short pause> news', styles: ['sarcastic'] },
  );
  assert.deepEqual(
    splitCues('Live from [Track 2] tonight'),
    { text: 'Live from [Track 2] tonight', styles: [] },
  );
  assert.deepEqual(splitCues('No cues'), { text: 'No cues', styles: [] });
});

test('fallbackTextFor strips brackets for gemini rescues', () => {
  assert.equal(fallbackTextFor('gemini', null, 'Well [sigh] hello'), 'Well hello');
  assert.equal(fallbackTextFor('piper', null, 'Well [sigh] hello'), 'Well [sigh] hello');
});

test('OpenAI instructions carry voiceStyle on gpt-4o-tts only', () => {
  const hinted = deliveryHint(
    { language: '', soul: '', voiceStyle: 'broad Australian accent' },
    'openai', 'gpt-4o-mini-tts',
  );
  assert.match(hinted.instructions || '', /broad Australian accent/);
  const legacy = deliveryHint(
    { language: '', soul: '', voiceStyle: 'broad Australian accent' },
    'openai', 'tts-1-hd',
  );
  assert.deepEqual(legacy, {});
  const eleven = deliveryHint(
    { language: 'Turkish', soul: '', voiceStyle: 'broad Australian accent' },
    'elevenlabs', 'eleven_v3',
  );
  assert.ok(!('instructions' in eleven));
});

// --- the fold: Gemini as a Cloud provider, still its own engine id ----------
//
// The product call: Gemini reaches Google with the same API key as the LLM
// section, so an operator picking a voice should find it beside OpenAI /
// ElevenLabs / Fish rather than as a card of its own. Two Google-backed choices
// in two different menus is a question nobody can answer from the screen.
//
// The fold is PRESENTATION ONLY. The dispatcher still resolves `gemini` as its
// own engine, `TTS_ENGINES` still lists it, and every stored persona keeps its
// value — so this asserts the pairing holds in both directions, which is the
// invariant that would break if one selector were changed without the other.

test('gemini is offered as a Cloud provider, not as a peer engine card', async () => {
  const { ENGINES } = await import('../../web/components/admin/tts/engineMeta.js');
  const { CLOUD_PROVIDERS } = await import('../../web/components/admin/tts/cloudProviderMeta.js');

  assert.ok(!ENGINES.some(e => e.id === 'gemini'),
    'gemini must not be its own top-level engine card');
  assert.ok(CLOUD_PROVIDERS.some(p => p.id === 'gemini'),
    'gemini must appear in the Cloud provider grid');
  // Cloud's blurb is what the operator reads on the card they now pick instead.
  const cloud = ENGINES.find(e => e.id === 'cloud');
  assert.match(cloud!.blurb, /Gemini/,
    'the Cloud card must name Gemini now that Gemini is one of its providers');
});

test('the engine <-> provider mapping is exact in both directions', async () => {
  const { engineCategory, engineForCloudProvider, GEMINI_CLOUD_PROVIDER }
    = await import('../../web/components/admin/tts/engineMeta.js');

  assert.equal(GEMINI_CLOUD_PROVIDER, 'gemini');
  // Which card lights up at the top.
  assert.equal(engineCategory('gemini'), 'cloud');
  assert.equal(engineCategory('cloud'), 'cloud');
  assert.equal(engineCategory('piper'), 'piper');
  // What choosing a provider writes. Gemini keeps its own id; the rest share cloud.
  assert.equal(engineForCloudProvider('gemini'), 'gemini');
  for (const p of ['openai', 'elevenlabs', 'fish-audio', 'openai-compatible']) {
    assert.equal(engineForCloudProvider(p), 'cloud', `${p} must resolve to the cloud engine`);
  }
});

test("gemini's badge reads the engine flag, not cloudByProvider", async () => {
  const { cloudProviderStatus } = await import('../../web/components/admin/tts/cloudProviderMeta.js');

  // Gemini is an engine, so it never appears in cloudByProvider. Reading that
  // map would report "no key" on a station whose engine can speak perfectly.
  assert.deepEqual(
    cloudProviderStatus('gemini', { gemini: true, cloudByProvider: {} }),
    { label: 'key set', tone: 'ok', state: 'ready' });
  assert.equal(cloudProviderStatus('gemini', { gemini: false }).state, 'off');
  assert.equal(cloudProviderStatus('gemini', { gemini: false }).label, 'no key');
  // Unasked is not the same as absent — the badge must not cry wolf.
  assert.equal(cloudProviderStatus('gemini', {}).state, 'unknown');
  assert.equal(cloudProviderStatus('gemini', { cloudByProvider: { gemini: false } }).state, 'unknown',
    'cloudByProvider must not decide the gemini badge');
});

test('the Gemini card is gone from the ENGINE grid, not just from ENGINES', async () => {
  const fs = await import('node:fs');
  const panel = fs.readFileSync(
    new URL('../../web/components/admin/settings/TtsSection.tsx', import.meta.url), 'utf8');

  // The engine grid is fed by the CONTROLLER's tts.engines, not by engineMeta's
  // ENGINES — which is why removing Gemini from ENGINES alone left the card on
  // screen. The dispatcher must keep reporting it (a stored persona may name it),
  // so the filter belongs here, at the point of use.
  assert.match(panel, /const engines = \(data\.tts\?\.engines \|\| \['piper'\]\)\.filter\(/,
    'the engine card list must filter gemini out at the point of use');
  assert.match(panel, /e !== GEMINI_CLOUD_PROVIDER/,
    'the filter must be on the gemini id specifically');

  // And the Cloud card's own badge must not ask about cloud.provider while
  // Gemini speaks: that value is stale, and it rendered "no key" directly above
  // a Gemini card reading "key set".
  assert.match(panel, /const providerCloudReady = geminiSelected\s*\n\s*\? available\.gemini/,
    'the Cloud badge must read the engine flag while gemini is selected');
});

test('the cloud-only panel content is gated on the selection, not removed', async () => {
  const fs = await import('node:fs');
  const panel = fs.readFileSync(
    new URL('../../web/components/admin/settings/TtsSection.tsx', import.meta.url), 'utf8');

  // Every provider after Gemini — the connection block, the model, the provider
  // voice, the provider knobs — must still be there. Gemini is ONE provider, not
  // a replacement for the others, so this asserts OpenAI and the rest are
  // untouched rather than merely absent from the file.
  for (const marker of [
    'cloudProviderLabel(form.tts.cloud.provider)',
    '<Label>Default voice</Label>',
    'engineId="cloud"',
  ]) {
    assert.ok(panel.includes(marker), `${marker} must survive — Gemini is one provider, not a replacement`);
  }
  const providers = fs.readFileSync(
    new URL('../../web/components/admin/tts/cloudProviderMeta.ts', import.meta.url), 'utf8');
  for (const id of ['openai', 'elevenlabs', 'fish-audio', 'openai-compatible', 'gemini']) {
    assert.ok(providers.includes(`id: '${id}'`), `${id} must remain a Cloud provider`);
  }

  // They are gated on the SELECTION rather than deleted, because under a Gemini
  // selection the panel was showing an OpenAI connection form the operator never
  // chose — directly beneath a Gemini card reading "key set".
  assert.match(panel, /\{!geminiSelected && \([\s\S]{0,1500}cloudProviderLabel\(/,
    'the cloud-only block must be gated on !geminiSelected');
});

test('both panels derive the Gemini selection from the one stored engine id', async () => {
  const fs = await import('node:fs');
  const read = (rel: string) => fs.readFileSync(new URL(rel, import.meta.url), 'utf8');

  // The settings panel and the persona slot each render a provider grid; both
  // must read defaultEngine/engine and highlight from it, never from a second
  // field that could disagree.
  const panel = read('../../web/components/admin/settings/TtsSection.tsx');
  const persona = read('../../web/components/admin/tts/EngineVoiceFields.tsx');

  for (const [name, src] of [['TtsSection', panel], ['EngineVoiceFields', persona]] as const) {
    assert.match(src, /value=\{engineCategory\(/,
      `${name}: the engine grid must highlight through engineCategory`);
    assert.match(src, /geminiSelected \? GEMINI_CLOUD_PROVIDER : /,
      `${name}: the provider grid must highlight gemini from the stored engine`);
    assert.match(src, /\.\.\.new Set\(\[/,
      `${name}: the provider list must be de-duplicated before gemini is appended`);
    assert.match(src, /new Set\(\[[\s\S]{0,400}?GEMINI_CLOUD_PROVIDER/,
      `${name}: gemini must be appended to the provider list`);
    // Gemini must not run through selectCloudProvider, which rewrites
    // cloud.voice / cloud.model and would hand it a Fish Audio voice id.
    assert.doesNotMatch(src, /selectCloudProvider\(f, v\)/,
      `${name}: the provider grid must not route gemini through selectCloudProvider`);
  }

  // The Gemini fields (key, voice, speed, level) live inside the Cloud panel,
  // so picking Gemini shows them in the same place as the other providers'.
  assert.match(panel, /form\.tts\.defaultEngine === 'cloud' \|\| geminiSelected/,
    'the Cloud panel must open for gemini');
  assert.match(panel, /\{geminiSelected && \(/,
    'the Gemini options must render inside that panel');
});

test('gemini still reads the standard key, never the pool', async () => {
  const fs = await import('node:fs');
  const gemini = fs.readFileSync(new URL('../src/audio/gemini.ts', import.meta.url), 'utf8');
  // The pool is a separate feature with its own PR. Reading it here would make
  // the voice engine depend on an LLM setting and silently change which key
  // speaks once a pool exists.
  assert.doesNotMatch(gemini, /google-key-pool|currentKey/,
    'the Gemini voice engine must read GOOGLE_GENERATIVE_AI_API_KEY only');
  assert.match(gemini, /process\.env\.GOOGLE_GENERATIVE_AI_API_KEY/);
});
