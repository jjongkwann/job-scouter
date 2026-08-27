import type { DueCls } from '@/lib/api'

// 마감 — 라벨과 긴급도는 서버(candidates.due_label)가 정한다. u0 ≤3일 · u1 ≤7일 · gone 지남 · always 상시
const CLS: Record<DueCls, string> = {
  '': 'font-bold',
  u0: 'font-bold text-[var(--bad)]',
  u1: 'font-bold text-[var(--warn)]',
  gone: 'font-bold text-[var(--bad)] line-through',
  always: 'text-[11.5px] text-[var(--faint)]',
}

export function Due({ due, cls }: { due: string; cls: DueCls }) {
  if (!due) return null
  return <span className={`text-[12px] leading-[1.3] tabular ${CLS[cls]}`}>{due}</span>
}
