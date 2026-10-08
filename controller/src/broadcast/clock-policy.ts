// Gate all automatic clock references here, including prompt context and the hourly tick.
// Daypart descriptions and manual segments remain eligible; read the switch live.

import * as settings from '../settings.js';

export function clockEnabled(): boolean {
  const s = settings.get();
  if (s?.djSpeakClock === false) return false;

  const show = settings.resolveActiveShow();
  if (show && show.speakClock !== true) return false;

  return true;
}

// May a spoken line state the wall-clock time?
export function speakClockAllowed(): boolean {
  return clockEnabled();
}

// A boundary-deferred ident's daypart can go stale while its WAV waits for a
// seam. Stamp only a daypart the model was allowed to use: an ident written
// with the clock off made no clock claim and must not be dropped later.
export function stationIdDaypartStamp(daypart: unknown, clockAllowed: boolean): string | null {
  if (!clockAllowed || typeof daypart !== 'string') return null;
  return daypart.trim() || null;
}

// Air-time backstop for the stamp above. Missing/malformed stamps fail OPEN:
// they mean no validated daypart claim reached this channel.
export function stationIdDaypartDrifted(stamped: unknown, live: unknown): boolean {
  if (typeof stamped !== 'string' || !stamped.trim()) return false;
  if (typeof live !== 'string' || !live.trim()) return false;
  return stamped.trim() !== live.trim();
}

// May the AUTOMATIC top-of-the-hour time check fire? Manual runners must NOT
// call this — bypassing the gate is what preserves the operator's pad.
export function autoTimeCheckAllowed(): boolean {
  return clockEnabled();
}

export function clockStatus() {
  return { enabled: clockEnabled() };
}
