// A pool of Google API keys with per-key holds, shared by the Gemini LLM leg
// and (once #1718's engine is wired up) Gemini TTS.
//
// Why a pool and not a rotation: free-tier keys are cheap and plentiful, and a
// station running one exhausts its daily quota long before it notices. The
// behaviour wanted is fail-forward — use key 1 until it stops working, park it
// for as long as Google says, move to key 2, and only fall through to the
// station's configured backup leg when the whole pool is spent.
//
// Selection is deliberately PRIMARY-FIRST rather than round-robin. Key 1 keeps
// its quota for as long as possible, and the operator's first key stays the one
// that gets tested and reported on.
//
// Holds are IN MEMORY. A controller restart re-probes keys that are still
// exhausted; they are re-parked from the same 429 within one call, which is
// cheaper than a second writer on the state dir and than persisting a wall-clock
// that is meaningless to a key whose quota resets on Google's schedule, not
// ours.
//
// Absent configuration, EVERY function here is a no-op and the module is
// invisible: an upgraded station with one key behaves exactly as before.

import {
  hasDailyQuotaViolation,
  noHintCooldownMs,
  parseGeminiRetryDelayMs,
} from '../llm/internal/provider/gemini-cooldown.js';

export const GOOGLE_KEYS_ENV = 'GOOGLE_GENERATIVE_AI_API_KEYS';
export const GOOGLE_KEY_ENV = 'GOOGLE_GENERATIVE_AI_API_KEY';

/** A Google API key is `AIza` + 35 chars today. The bound is generous on
 *  purpose: this is a length guard against a pasted paragraph, not a format
 *  check, because a future key shape must not silently drop keys. */
export const GOOGLE_KEY_MAX = 200;
export const GOOGLE_POOL_MAX = 50;

interface Hold {
  until: number;
  reason: 'daily' | 'hint' | 'unknown';
}

let holds = new Map<string, Hold>();
let poolCache: { keys: string[]; at: number } | null = null;

// Parsed on every access in principle; cached briefly so a hot loop (the DJ
// fires many calls a minute) does not re-parse the environment each time. The
// TTL is short enough that a key added at runtime is picked up almost at once.
const POOL_CACHE_MS = 2_000;

/**
 * Split a configured pool into keys. Comma-separated on purpose: Google keys
 * never contain a comma, and `secrets.env` is read by dotenv as single-line
 * values — a multi-line quoted list is dropped by that reader with a warning.
 */
export function parsePool(raw: string | undefined | null): string[] {
  if (!raw) return [];
  const out: string[] = [];
  const seen = new Set<string>();
  for (const part of String(raw).split(',')) {
    const key = part.trim();
    if (!key || key.length > GOOGLE_KEY_MAX) continue;
    if (seen.has(key)) continue; // a pasted duplicate is one key, not two slots
    seen.add(key);
    out.push(key);
    if (out.length >= GOOGLE_POOL_MAX) break;
  }
  return out;
}

/** The configured pool, or the single legacy key as a one-entry pool. */
function configuredKeys(): string[] {
  const pooled = parsePool(process.env[GOOGLE_KEYS_ENV]);
  if (pooled.length) return pooled;
  const single = (process.env[GOOGLE_KEY_ENV] || '').trim();
  return single && single.length <= GOOGLE_KEY_MAX ? [single] : [];
}

/** Every key, held or not, in configured order. */
export function poolKeys(): string[] {
  const now = Date.now();
  if (poolCache && now - poolCache.at < POOL_CACHE_MS) return poolCache.keys;
  const keys = configuredKeys();
  poolCache = { keys, at: now };
  return keys;
}

/** Drop the memo. The settings save path calls this after writing a new pool so
 *  the change is visible without waiting out the TTL. */
export function invalidatePool(): void {
  poolCache = null;
}

export function poolSize(): number {
  return poolKeys().length;
}

/**
 * The key to send right now: the first in configured order that is not held.
 * Returns '' only when nothing is configured — a real station with an exhausted
 * pool returns the LAST key anyway, so the caller still makes one attempt per
 * call rather than failing before it starts. The caller is what decides an
 * exhausted pool is fatal.
 */
export function currentKey(): string {
  const now = Date.now();
  const keys = poolKeys();
  for (const key of keys) {
    const hold = holds.get(key);
    if (!hold || hold.until <= now) {
      if (hold) holds.delete(key);
      return key;
    }
  }
  // Every key is held. Return the first anyway: the caller gets a real 429
  // with a real RetryInfo, which is strictly more information than guessing a
  // wait here, and it keeps one-shot callers (a preview, a Test key button)
  // working instead of failing on a transient state.
  return keys[0] || '';
}

/** True when every configured key is currently parked. The failover layer asks
 *  this to decide whether an exhausted pool should escalate to the backup leg
 *  immediately rather than after burning another call. */
export function allKeysHeld(): boolean {
  const keys = poolKeys();
  if (!keys.length) return false;
  const now = Date.now();
  return keys.every((k) => {
    const h = holds.get(k);
    if (!h) return false;
    if (h.until <= now) { holds.delete(k); return false; }
    return true;
  });
}

export function holdRemainingMs(key: string): number {
  const h = holds.get(key);
  if (!h) return 0;
  const left = h.until - Date.now();
  if (left <= 0) { holds.delete(key); return 0; }
  return left;
}

export function isHeld(key: string): boolean {
  return holdRemainingMs(key) > 0;
}

/** Park a key. `bodyText` is the raw 429 body, which carries both the retry
 *  hint and the daily-vs-per-minute distinction. Returns the hold length so a
 *  caller can log it. */
export function reportKeyFailure(key: string, bodyText?: unknown): number {
  if (!key) return 0;
  const daily = hasDailyQuotaViolation(bodyText);
  const hint = parseGeminiRetryDelayMs(bodyText);
  const ms = daily ? noHintCooldownMs() : (hint ?? noHintCooldownMs());
  holds.set(key, { until: Date.now() + ms, reason: daily ? 'daily' : hint != null ? 'hint' : 'unknown' });
  return ms;
}

/** Clear a hold — a key that just succeeded was demonstrably not exhausted. */
export function reportKeySuccess(key: string): void {
  if (key) holds.delete(key);
}

/** Everything the admin UI needs, with no secret material in it. The
 *  fingerprint is a short suffix so an operator can tell key 3 from key 7
 *  without the value ever crossing the wire. */
export interface PoolStatus {
  index: number;
  fingerprint: string;
  held: boolean;
  holdRemainingMs: number;
  reason: Hold['reason'] | null;
  current: boolean;
}

export function poolStatus(): PoolStatus[] {
  const now = Date.now();
  const current = currentKey();
  return poolKeys().map((key, index) => {
    const hold = holds.get(key);
    const remaining = hold ? hold.until - now : 0;
    const live = remaining > 0;
    if (hold && !live) holds.delete(key);
    return {
      index,
      fingerprint: fingerprint(key),
      held: live,
      holdRemainingMs: live ? remaining : 0,
      reason: live ? hold!.reason : null,
      current: key === current,
    };
  });
}

/** Last 4 characters, prefixed to look deliberate in the UI. A short suffix of
 *  a 39-char key is enough to disambiguate and far too short to be useful to
 *  anyone who intercepted it. */
export function fingerprint(key: string): string {
  if (!key) return '';
  return `••••${key.slice(-4)}`;
}

/** Test seam: forget every hold and the memo without touching configuration. */
export function __resetHoldsForTest(): void {
  holds = new Map();
  poolCache = null;
}
