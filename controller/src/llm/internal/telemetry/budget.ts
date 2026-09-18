// Daily LLM token counter, TTS character counter, and peak listeners
// stored durably in SQLite.
import { getTelemetryDb, utcDay } from './db.js';

function ensureTodayRow(): void {
  const db = getTelemetryDb();
  const day = utcDay();
  db.prepare(`
    INSERT INTO daily_stats (date, peak_listeners, llm_tokens, tts_chars)
    VALUES (?, 0, 0, 0)
    ON CONFLICT(date) DO NOTHING
  `).run(day);
}

// Add a call's token total to today's tally.
export function addDailyUsage(tokens: number): void {
  if (!Number.isFinite(tokens) || tokens <= 0) return;
  const db = getTelemetryDb();
  const day = utcDay();
  
  db.prepare(`
    INSERT INTO daily_stats (date, peak_listeners, llm_tokens, tts_chars)
    VALUES (?, 0, ?, 0)
    ON CONFLICT(date) DO UPDATE SET llm_tokens = llm_tokens + excluded.llm_tokens
  `).run(day, tokens);
}

// Tokens spent so far today (UTC).
export function dailyTokensUsed(): number {
  ensureTodayRow();
  const db = getTelemetryDb();
  const row = db.prepare('SELECT llm_tokens FROM daily_stats WHERE date = ?').get(utcDay()) as any;
  return row ? row.llm_tokens : 0;
}

// Add a call's character count to today's TTS tally.
export function addDailyTtsUsage(chars: number): void {
  if (!Number.isFinite(chars) || chars <= 0) return;
  const db = getTelemetryDb();
  const day = utcDay();
  
  db.prepare(`
    INSERT INTO daily_stats (date, peak_listeners, llm_tokens, tts_chars)
    VALUES (?, 0, 0, ?)
    ON CONFLICT(date) DO UPDATE SET tts_chars = tts_chars + excluded.tts_chars
  `).run(day, chars);
}

// TTS characters spent so far today (UTC).
export function dailyTtsCharsUsed(): number {
  ensureTodayRow();
  const db = getTelemetryDb();
  const row = db.prepare('SELECT tts_chars FROM daily_stats WHERE date = ?').get(utcDay()) as any;
  return row ? row.tts_chars : 0;
}

// Record a new peak listener count for today if it exceeds the current peak.
export function addPeakListeners(count: number): void {
  if (!Number.isFinite(count) || count <= 0) return;
  const db = getTelemetryDb();
  const day = utcDay();
  
  db.prepare(`
    INSERT INTO daily_stats (date, peak_listeners, llm_tokens, tts_chars)
    VALUES (?, ?, 0, 0)
    ON CONFLICT(date) DO UPDATE SET peak_listeners = MAX(peak_listeners, excluded.peak_listeners)
  `).run(day, count);
}

// Peak listeners so far today (UTC).
export function peakListenersToday(): number {
  ensureTodayRow();
  const db = getTelemetryDb();
  const row = db.prepare('SELECT peak_listeners FROM daily_stats WHERE date = ?').get(utcDay()) as any;
  return row ? row.peak_listeners : 0;
}

// Stub function to maintain compatibility with log.ts calling it on boot
export async function seedDailyUsageFromLog(): Promise<{ tokens: number; chars: number }> {
  // DB is already durable, so we just return the current values
  return { tokens: dailyTokensUsed(), chars: dailyTtsCharsUsed() };
}
