import type { ReactNode } from 'react'
import Link from 'next/link'
import { ArrowLeft } from 'lucide-react'

export function Page({ title, sub, source, stats, back, actions, children }: {
  title: string
  sub?: ReactNode
  source?: ReactNode
  stats?: [ReactNode, string][]
  back?: { href: string; label: string }
  actions?: ReactNode
  children: ReactNode
}) {
  const statItems = (items: [ReactNode, string][]) => items.map(([value, label]) => (
    <div key={label} className="stat"><span className="stat-value tabular">{value}</span><span>{label}</span></div>
  ))
  return (
    <div className="page">
      {back && <Link href={back.href} className="back-link"><ArrowLeft size={15} aria-hidden="true" />{back.label}</Link>}
      <header className="page-header">
        <div><h1>{title}</h1>{sub && <p className="page-description">{sub}</p>}</div>
        {actions && <div className="page-actions">{actions}</div>}
      </header>
      {!!stats?.length && <div className="page-stats">
        <div className="stats-grid">{statItems(stats.slice(0, 4))}</div>
        {stats.length > 4 && <details className="more-stats"><summary>추가 현황 {stats.length - 4}개</summary><div className="stats-grid">{statItems(stats.slice(4))}</div></details>}
      </div>}
      {children}
      {source && <footer className="source-note"><details><summary>출처·기록 정보</summary><div>{source}</div></details></footer>}
    </div>
  )
}
