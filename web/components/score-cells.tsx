import { AXES, type Cell } from '@/lib/candidates'

// 5칸(스택·도메인·레벨·역할·감점). 그리드의 직계 자식이어야 해서 fragment로 낸다.
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
        <div key={i} className={`text-center text-[12px] tabular max-[1060px]:text-left ${CLS[cls]}`}>
          {/* 좁은 화면에선 한 열로 접히므로 항목명을 붙여 준다 */}
          <span className="hidden text-[11px] text-[var(--faint)] max-[1060px]:inline">{AXES[i]} </span>
          {v}
        </div>
      ))}
    </>
  )
}
