// The `tts.gemini` station block: validation, round-trip, and the upgrade path.
//
// Split from gemini-tts.test.ts on purpose. settings.js captures SETTINGS_PATH at
// import time and caches what it loads, so a file that both asserts on settings
// and imports modules that pull settings in transitively ends up testing against
// whatever loaded first. This file owns a temp STATE_DIR and nothing else, the
// same shape archive-retention.test.ts uses.
//
// Run: `npm test -- gemini-tts-settings`.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const root = mkdtempSync(join(tmpdir(), 'subwave-gemini-tts-settings-'));
process.env.STATE_DIR = root;
process.on('exit', () => rmSync(root, { recursive: true, force: true }));

const settings = await import('../src/settings.js');
const store = await import('../src/settings/store.js');

async function fresh() {
  store.setCache(null);
  await settings.load();
}

test('a fresh install gets the engine defaults', async () => {
  await fresh();
  // Empty model = "walk the engine's fallback chain", which is the upgrade-safe
  // default. Pinning a model at install time would freeze the chain at whatever
  // happened to be newest today.
  assert.equal(settings.get().tts?.gemini?.model, '');
  assert.equal(settings.get().tts?.gemini?.voice, 'Puck');
});

test('a model or voice Google does not accept is rejected at save time', async () => {
  await fresh();
  // These must fail HERE, with a form error. Left to speak time they become a 400
  // from inside the request, and the operator reads a stack trace instead.
  await assert.rejects(
    () => settings.update({ tts: { gemini: { model: 'gemini-nope-tts' } } }),
    /tts\.gemini\.model must be one of/,
  );
  // Rejected because the engine sends a speech annotation this model refuses —
  // it synthesises audio through generateContent but would 400 on every render.
  await assert.rejects(
    () => settings.update({ tts: { gemini: { model: 'gemini-2.5-pro-preview-tts' } } }),
    /tts\.gemini\.model must be one of/,
  );
  await assert.rejects(
    () => settings.update({ tts: { gemini: { voice: 'NotAVoice' } } }),
    /tts\.gemini\.voice must be one of/,
  );
  // A blank voice is not a voice — the engine has no voice to fall back to.
  await assert.rejects(
    () => settings.update({ tts: { gemini: { voice: '   ' } } }),
    /tts\.gemini\.voice must not be blank/,
  );
});

test('the real choices round-trip', async () => {
  await fresh();
  await settings.update({ tts: { gemini: { model: '', voice: 'Kore' } } });
  assert.equal(settings.get().tts?.gemini?.voice, 'Kore');
  assert.equal(settings.get().tts?.gemini?.model, '', 'a blank model is a real choice');
  await settings.update({ tts: { gemini: { model: 'gemini-3.8-flash-tts' } } });
  assert.equal(settings.get().tts?.gemini?.model, 'gemini-3.8-flash-tts');
  // And it survives a reload, so it is actually persisted rather than cached.
  await fresh();
  assert.equal(settings.get().tts?.gemini?.model, 'gemini-3.8-flash-tts');
  assert.equal(settings.get().tts?.gemini?.voice, 'Kore');
});

test('a settings.json predating the block loads at the defaults', async () => {
  // The upgrade has to be a no-op: an install that never touched this block must
  // come up with a working voice, not an undefined one the dispatcher trips over.
  writeFileSync(join(root, 'settings.json'), JSON.stringify({ tts: { defaultEngine: 'gemini' } }));
  await fresh();
  assert.equal(settings.get().tts?.gemini?.voice, 'Puck');
  assert.equal(settings.get().tts?.gemini?.model, '');
  assert.equal(settings.get().tts?.defaultEngine, 'gemini', 'the rest of tts survives');
});

test('a junk stored value is repaired, not propagated', async () => {
  writeFileSync(join(root, 'settings.json'), JSON.stringify({
    tts: { gemini: { model: 42, voice: { nested: true } } },
  }));
  await fresh();
  assert.equal(settings.get().tts?.gemini?.model, '');
  assert.equal(settings.get().tts?.gemini?.voice, 'Puck');
});
