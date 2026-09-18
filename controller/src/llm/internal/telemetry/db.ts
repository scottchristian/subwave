import Database from 'better-sqlite3';
import { STATE_DIR } from '../../../config.js';

let db: Database.Database | null = null;

export function getTelemetryDb(): Database.Database {
  if (db) return db;
  
  db = new Database(`${STATE_DIR}/telemetry.db`);
  db.pragma('journal_mode = WAL');
  db.pragma('synchronous = NORMAL');
  
  // Initialize table if it doesn't exist
  db.exec(`
    CREATE TABLE IF NOT EXISTS daily_stats (
      date TEXT PRIMARY KEY,
      peak_listeners INTEGER DEFAULT 0,
      llm_tokens INTEGER DEFAULT 0,
      tts_chars INTEGER DEFAULT 0
    )
  `);
  
  return db;
}

export function utcDay(): string {
  return new Date().toISOString().slice(0, 10); // YYYY-MM-DD
}
