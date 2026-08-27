import type { ReactNode } from 'react'
import { Card, CardContent } from '@/components/ui/card'

export function Page({
  title,
  sub,
  source,
  stats,
  children,
}: {
  title: string
  sub?: ReactNode
  source?: ReactNode
  stats?: [ReactNode, string][]
  children: ReactNode
}) {
  return (
    <div>
      <h1 className="text-[21px] font-semibold m-0 mb-1">{title}</h1>
      {sub && <p className="sub m-0 mb-4 max-w-[78ch] text-[13px] text-[var(--dim)]">{sub}</p>}
      {stats && stats.length > 0 && (
        <Card className="mb-4 py-3">
          <CardContent className="flex flex-wrap gap-5 px-4">
            {stats.map(([value, label], i) => (
              <div key={i} className="flex flex-col gap-0.5">
                <span className="text-[19px] font-bold tabular leading-none">{value}</span>
                <span className="text-[11px] text-[var(--dim)]">{label}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
      {children}
      {source && <footer className="mt-6 text-[11px] text-[var(--faint)]">원본: {source}</footer>}
    </div>
  )
}
