import type { Tier } from '@/lib/api'

// 적합도 — 숫자 + 5px 막대. t1 ≥80 · t2 ≥70 · t3 그 외 (web.py .fit 규격)
const NUM: Record<Tier, string> = { t1: 'text-[var(--good)]', t2: 'text-[var(--fg)]', t3: 'text-[var(--faint)]' }
const BAR: Record<Tier, string> = { t1: 'bg-[var(--good)]', t2: 'bg-[var(--neu)]', t3: 'bg-[var(--faint)]' }

export function Fit({ total, tier }: { total: number; tier: Tier }) {
  return (
    <div className="flex items-center gap-[7px]">
      <span className={`min-w-6 text-right text-[15px] font-bold tabular ${NUM[tier]}`}>{total}</span>
      <span className="h-[5px] flex-1 overflow-hidden rounded-[3px] bg-[var(--neubg)]">
        <span className={`block h-full rounded-[3px] ${BAR[tier]}`} style={{ width: `${Math.max(0, Math.min(100, total))}%` }} />
      </span>
    </div>
  )
}
