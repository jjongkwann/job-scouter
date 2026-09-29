import { AXES, type Cell } from '@/lib/candidates'

// 상세 점수는 화면 너비와 무관하게 각 항목명을 함께 표시한다.
const CLS = {
  '': 'text-[var(--dim)]',
  hi: 'font-bold text-[var(--good)]',
  lo: 'text-[var(--faint)]',
  pen: 'text-[var(--bad)]',
}

export function ScoreCells({ cells }: { cells: Cell[] }) {
  return (
    <>
      {cells.map(([v, cls], i) => (
        <div key={i} className={`text-[13px] tabular ${CLS[cls]}`}>
          <span className="text-[12px] text-[var(--dim)]">{AXES[i]} </span>
          {v}
        </div>
      ))}
    </>
  )
}
