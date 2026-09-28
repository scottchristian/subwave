// googleSafetyOptions (llm/internal/provider/capabilities.ts) — the per-call
// safety channel for the native `google` provider.
//
// Proven by wire capture: ai-sdk reads safetySettings ONLY from per-call
// providerOptions, never from the model-construction settings object, which
// never reaches the request body. Checked = block that category;
// unchecked/absent = allow. Every other provider gets {} (no-op spread), so
// call sites never name a provider.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { googleSafetyOptions } from '../src/llm/internal/provider/capabilities.js';

const FULL = {
  provider: 'google',
  geminiSafety: { harassment: true, hateSpeech: false, sexuallyExplicit: true, dangerousContent: false },
};

test('google leg carries all four thresholds with checked=block polarity', () => {
  const out = googleSafetyOptions(FULL) as any;
  const byCat = Object.fromEntries(out.providerOptions.google.safetySettings.map((s: any) => [s.category, s.threshold]));
  assert.deepEqual(byCat, {
    HARM_CATEGORY_HATE_SPEECH: 'BLOCK_NONE',
    HARM_CATEGORY_DANGEROUS_CONTENT: 'BLOCK_NONE',
    HARM_CATEGORY_SEXUALLY_EXPLICIT: 'BLOCK_MEDIUM_AND_ABOVE',
    HARM_CATEGORY_HARASSMENT: 'BLOCK_MEDIUM_AND_ABOVE',
  });
});

test('absent flags read as allow, never as block', () => {
  const out = googleSafetyOptions({ provider: 'google' }) as any;
  for (const s of out.providerOptions.google.safetySettings) {
    assert.equal(s.threshold, 'BLOCK_NONE');
  }
});

test('every other provider gets an empty object', () => {
  for (const provider of ['ollama', 'openai-compatible', 'openai', 'anthropic', 'deepseek', 'openrouter']) {
    assert.deepEqual(googleSafetyOptions({ provider, geminiSafety: FULL.geminiSafety }), {});
  }
  assert.deepEqual(googleSafetyOptions(null), {});
  assert.deepEqual(googleSafetyOptions(undefined), {});
});
