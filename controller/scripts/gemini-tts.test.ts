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

test('the persona schema accepts a gemini slot', async () => {
  const persona = await import('../src/schemas/persona.js');
  const slot = { engine: 'gemini', voice: 'Despina', cloudProvider: 'openai', gainDb: 0, speed: 1 };
  const out = persona.personaSchema.parse({
    name: 'G', soul: 's', tagline: '', frequency: 'moderate', scriptLength: 'concise',
    djMode: false, linkStyle: 'natural', humour: 5, localColour: 5, warmth: 5,
    language: '', avatar: '', tts: slot, skills: null, tags: [],
  });
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
