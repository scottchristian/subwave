'use client';

import { Fragment, isValidElement, memo, type ReactNode } from 'react';
import { m } from 'motion/react';
import { cn } from '@/lib/cn';
import OdometerNumber from '@/components/OdometerNumber';
import { HandCoins } from 'lucide-react';
import type { PlayerDrawer } from './CommandPalette';

interface RailItem {
  k: PlayerDrawer;
  l: string;
}

const ITEMS: readonly RailItem[] = [
  { k: 'schedule', l: 'Schedule' },
  { k: 'timeline', l: 'Timeline' },
  { k: 'booth',    l: 'Booth' },
  { k: 'request',  l: 'Request' },
];

export interface DotRailProps {
  /** Counts (or icon nodes) keyed by drawer id. `request` is rendered as "+" regardless. */
  counts?: Partial<Record<PlayerDrawer, ReactNode>>;
  donateUrl?: string | null;
  active: PlayerDrawer | null;
  onSelect: (id: PlayerDrawer | null) => void;
}

export default memo(function DotRail({ counts, donateUrl, active, onSelect }: DotRailProps) {
  return (
    <div
      // Slimmed on phones; CenterStage's right reserve tracks these widths.
      className="absolute top-20 right-0 bottom-20 z-20 flex w-[76px] flex-col items-center justify-center gap-1 sm:w-24"
    >
      {ITEMS.map(item => {
        const isActive = active === item.k;
        const isRequest = item.k === 'request';
        const n: ReactNode = isRequest ? '+' : (counts?.[item.k] ?? 0);
        const isIcon = isValidElement(n);
        const btn = (
          <button
            key={item.k}
            onClick={() => onSelect(isActive ? null : item.k)}
            className={cn(
              'v3-focus relative flex w-full cursor-pointer flex-col items-center gap-[6px] border-0 px-1 py-[14px] font-[inherit] sm:px-2',
              isActive ? 'text-bg' : 'bg-transparent text-ink',
              isRequest && !isActive && 'bg-[rgba(197,48,42,0.08)] shadow-[inset_2px_0_0_var(--accent)]',
            )}
            aria-pressed={isActive}
          >
            {/* The spans below need `relative` to sit above this
                absolutely-positioned element. */}
            {isActive && (
              <m.span
                layoutId="dot-rail-active"
                className="absolute inset-0 bg-ink"
                initial={false}
                transition={{ type: 'spring', stiffness: 380, damping: 32 }}
                aria-hidden="true"
              />
            )}
            <span
              className={cn(
                'v3-tab-num relative leading-none',
                isRequest ? 'text-[26px] font-semibold' : 'text-[22px] font-extralight',
                isIcon && 'inline-flex h-[22px] items-center justify-center',
                isActive ? 'text-vermilion' : isRequest ? 'text-vermilion' : 'text-ink',
              )}
            >
              {typeof n === 'number' ? <OdometerNumber value={n} /> : n}
            </span>
            <span
              className={cn(
                // Tighter tracking so "SCHEDULE" still fits the slim phone rail.
                'relative text-[8px] tracking-[0.2em] uppercase sm:text-[9px] sm:tracking-[0.3em]',
                isActive ? 'text-bg' : isRequest ? 'font-bold text-vermilion' : 'text-ink',
              )}
            >
              {item.l}
            </span>
          </button>
        );

        if (item.k === 'booth' && donateUrl) {
          return (
            <Fragment key="booth-group">
              {btn}
              <div className="py-2 w-full">
                <button
                  onClick={() => window.open(donateUrl, '_blank', 'noopener,noreferrer')}
                  className="v3-focus flex w-full cursor-pointer flex-col items-center gap-[6px] border-0 px-1 py-[14px] font-[inherit] sm:px-2 bg-amber-500/8 text-amber-500 shadow-[inset_2px_0_0_rgba(245,158,11,0.5)]"
                  aria-label="Donate — opens in a new tab"
                >
                  <span className="v3-tab-num relative inline-flex h-[22px] items-center justify-center leading-none text-amber-500">
                    <HandCoins size={18} strokeWidth={1.5} />
                  </span>
                  <span className="relative text-[8px] font-bold tracking-[0.2em] uppercase text-amber-500 sm:text-[9px] sm:tracking-[0.3em]">
                    Donate
                  </span>
                </button>
              </div>
            </Fragment>
          );
        }
        
        return btn;
      })}
    </div>
  );
});
