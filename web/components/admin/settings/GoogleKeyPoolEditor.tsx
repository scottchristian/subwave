'use client';

// Google key POOL editor — the companion to the single "Google (Gemini) API
// key" field, which stays exactly as it is for the one-key case.
//
// Why this exists: a free-tier station exhausts a key's daily quota long before
// it notices, so the operator keeps a handful of keys and wants the station to
// fail forward through them. The rotation itself is server-side (see
// `util/google-key-pool.ts`); this only adds, removes and displays.
//
// What crosses the wire is deliberately thin: a fingerprint, a hold timer and a
// reason. No key value is ever rendered here, and none comes back from the
// server — `poolStatus()` masks before it serialises, so there is nothing to
// leak even by accident.

import { useCallback, useState } from 'react';
import type { AdminAuth } from '@/lib/adminAuth';
import { adminResponse } from '@/lib/admin-query';
import { Btn } from '../ui';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { notify } from '@/lib/notify';

const POOL_ENV = 'GOOGLE_GENERATIVE_AI_API_KEYS';

export interface GooglePoolKey {
  index: number;
  fingerprint: string;
  held: boolean;
  holdRemainingMs: number;
  reason: 'daily' | 'hint' | 'unknown' | null;
  current: boolean;
}

export interface GooglePoolState {
  count: number;
  keys: GooglePoolKey[];
}

function holdLabel(k: GooglePoolKey): string {
  if (!k.held) return '';
  const mins = Math.max(1, Math.round(k.holdRemainingMs / 60000));
  const why = k.reason === 'daily' ? 'daily quota' : k.reason === 'hint' ? 'rate limit' : 'no hint from Google';
  return `held ~${mins}m · ${why}`;
}

export function GoogleKeyPoolEditor({
  pool,
  adminFetch,
  onChanged,
}: {
  pool?: GooglePoolState;
  adminFetch: AdminAuth['adminFetch'];
  onChanged?: () => void;
}) {
  const [adding, setAdding] = useState('');
  const [busy, setBusy] = useState(false);
  // The full pool is only ever known to the server, so a removal has to be sent
  // as a replacement of the whole list — which needs the values we deliberately
  // never receive. Removal therefore goes through a server-side endpoint that
  // edits the stored list in place, addressed by fingerprint.
  const [testingIndex, setTestingIndex] = useState<number | null>(null);

  const keys = pool?.keys ?? [];

  const post = useCallback(async (path: string, body: unknown) => {
    setBusy(true);
    try {
      const r = await adminResponse(adminFetch, path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const j = await r.json().catch(() => ({})) as { error?: string };
        notify.err(j.error || `Request failed (${r.status})`);
        return false;
      }
      return true;
    } catch (e) {
      notify.err(e instanceof Error ? e.message : 'Request failed');
      return false;
    } finally {
      setBusy(false);
    }
  }, [adminFetch]);

  const addKey = useCallback(async () => {
    const key = adding.trim();
    if (!key) return;
    const ok = await post('/settings/secrets', { [POOL_ENV]: key });
    if (ok) {
      setAdding('');
      notify.ok('Key added to the pool');
      onChanged?.();
    }
  }, [adding, post, onChanged]);

  const removeKey = useCallback(async (index: number) => {
    const ok = await post('/settings/google-key-pool/remove', { index });
    if (ok) {
      notify.ok('Key removed from the pool');
      onChanged?.();
    }
  }, [post, onChanged]);

  const testKey = useCallback(async (index: number) => {
    setTestingIndex(index);
    try {
      const ok = await post('/settings/google-key-pool/test', { index });
      if (ok) notify.ok(`Key ${index + 1} responded`);
    } finally {
      setTestingIndex(null);
    }
  }, [post]);

  return (
    <div className="mt-3 border-t border-[var(--hairline)] pt-3">
      <Label>Gemini key pool</Label>
      <p className="mt-1 text-[12px] text-muted">
        Runs several Gemini keys as one, so a daily free-tier quota running out
        doesn&rsquo;t take the DJ offline.
      </p>

      {keys.length === 0 ? (
        <p className="mt-1 text-[12px] text-muted">
          No pool configured. The single key above is used on its own.
        </p>
      ) : (
        <>
          <ul className="mt-2 flex flex-col gap-1">
            {keys.map(k => (
              <li key={`${k.index}-${k.fingerprint}`} className="flex items-center gap-2 text-[12px]">
                <code className="min-w-[92px]">{k.fingerprint}</code>
                <span className="text-muted">
                  {k.current ? 'in use' : 'standby'}
                  {k.held ? ` · ${holdLabel(k)}` : ''}
                </span>
                <span className="ml-auto flex gap-1">
                  <Btn
                    onClick={() => testKey(k.index)}
                    disabled={busy || testingIndex === k.index}
                    className="px-2 py-1 text-[10px]"
                  >
                    {testingIndex === k.index ? 'Testing…' : 'Test'}
                  </Btn>
                  <Btn
                    onClick={() => removeKey(k.index)}
                    disabled={busy || keys.length === 1}
                    className="px-2 py-1 text-[10px]"
                  >
                    Remove
                  </Btn>
                </span>
              </li>
            ))}
          </ul>
          {keys.length === 1 && (
            <p className="mt-1 text-[12px] text-muted">
              One key — add another to survive a daily quota.
            </p>
          )}
        </>
      )}

      <div className="mt-3 flex flex-wrap items-stretch gap-2 sm:flex-nowrap">
        <Input
          type="password"
          autoComplete="off"
          value={adding}
          placeholder="Paste another Gemini key…"
          onChange={e => setAdding(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); void addKey(); } }}
          className="max-w-[360px]"
        />
        <Btn onClick={addKey} disabled={busy || !adding.trim()}>Add key</Btn>
      </div>
      <p className="mt-1 text-[12px] text-muted">
        Keys are tried in the order you add them. When one hits a quota limit it
        is set aside for as long as Google asks and the next one is used; if
        every key is spent, the station falls back to its configured backup
        model. Shared by the Gemini DJ and Gemini TTS.
      </p>
      <p className="mt-2 text-[12px] text-muted">
        <strong className="text-ink">Put your free-tier keys first and your paid
        key last.</strong> That is the point of the pool: the free keys carry
        the station&rsquo;s normal traffic, and the paid key only covers what
        they can&rsquo;t once their daily quotas run out.
      </p>
      <p className="mt-2 border-l-2 border-[var(--accent)] pl-2 text-[12px] text-muted">
        <strong className="text-ink">Check Google&rsquo;s terms before you
        set this up.</strong> Rotating several free-tier keys to work around a
        single key&rsquo;s quota may conflict with the{' '}
        <a
          href="https://developers.google.com/terms"
          target="_blank"
          rel="noreferrer noopener"
          className="underline"
        >
          Google APIs Terms of Service
        </a>{' '}
        or the Gemini free-tier terms, which can change without notice. Read them
        and decide for yourself whether your use is permitted &mdash; Subwave
        can&rsquo;t make that call for you. Set this up only if you&rsquo;re
        satisfied it is.
      </p>
    </div>
  );
}
