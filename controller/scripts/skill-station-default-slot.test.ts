// The same-engine cloud hop, and the two meanings of `personaTts: null`.
//
// `plainSlot('cloud')` is how `resolveEngine()` survives a persona whose cloud
// PROVIDER is unconfigured while the engine itself is fine: the engine id stays
// the same and only the provider changes, so the render can only survive on
// different credentials. That hop resolves to a slot with `personaTts: null`.
//
// `null` is also what the operator's CONFIGURED slot carries when they left the
// voice blank, and there it means "nothing configured, use the persona's". One
// field, two meanings, and `speak()` resolves it with `?? personaTts` — which
// cannot tell them apart. So the hop reattached the persona's own dead provider
// and sent the supposedly-rescued render straight back to the provider the
// availability probe had just rejected (#1719).
//
// Asserted on the SOURCE because the behaviour is a `??` against a value that
// only differs by an optional boolean: there is no seam to drive `speak()`
// through without standing up engines and credentials, and the claim being
// guarded is precisely that the substitution does not happen.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const tts = readFileSync(new URL('../src/audio/tts.ts', import.meta.url), 'utf8');
const fb = readFileSync(new URL('../src/audio/tts-fallback.ts', import.meta.url), 'utf8');

test('plainSlot marks its null as the station default, not "nothing configured"', () => {
  assert.match(tts, /function plainSlot\(engine: string\): RescueSlot \{\s*return \{ engine, personaTts: null, stationDefault: true \};\s*\}/,
    'plainSlot must set stationDefault — it is the slot the same-engine cloud hop returns, '
      + 'and an unmarked null is indistinguishable from a blank configured slot');
});

test('speak() does not reattach the persona override to a station-default slot', () => {
  // The defect, verbatim. Read as a whole expression so a reintroduced bare
  // `?? personaTts` is caught even if it is later wrapped in something.
  assert.doesNotMatch(
    tts,
    /const primaryPersonaTts = primarySlot\.personaTts \?\? personaTts;/,
    'the bare backfill is the bug: it cannot distinguish plainSlot()\'s station default '
      + 'from a configured slot that left the voice blank',
  );
  assert.match(
    tts,
    /const primaryPersonaTts = primarySlot\.personaTts\s*\n?\s*\?\? \(primarySlot\.stationDefault \? null : personaTts\);/,
    'the substitution must be guarded by the stationDefault marker',
  );
});

test('the mid-render rescue path applies the same distinction', () => {
  // Same shape, same reason: the hardcoded rungs in fallbackChain() are built
  // with `personaTts: null`, and backfilling them re-creates the bug one stage
  // later — after a render has already failed once.
  assert.doesNotMatch(
    tts,
    /slot\.personaTts \?\? personaTts/,
    'the rescue path had the identical unguarded backfill',
  );
  assert.match(tts, /slot\.personaTts \?\? \(slot\.stationDefault \? null : personaTts\)/,
    'the rescue path must guard on stationDefault too');
});

test('every hardcoded rung is marked, not just plainSlot', () => {
  // partial coverage is the failure mode here: marking plainSlot() alone leaves
  // the rescue chain's own rungs unmarked, and those are built in a different
  // module by a different expression.
  assert.match(fb, /personaTts: null,\s*\n\s*stationDefault: true,/,
    'orderedFallbacks\' hardcoded rungs must carry stationDefault — they are the slots a '
      + 'mid-render rescue lands on');
});

test('the interface records why the marker exists', () => {
  assert.match(fb, /stationDefault\?: boolean;/, 'RescueSlot must declare the marker');
  assert.match(fb, /probe had just rejected|rejected/,
    'the interface comment must keep the reason, since a bare optional boolean '
      + 'invites the next reader to delete the guard it justifies');
});
