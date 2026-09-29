'use client'
import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Page } from '@/components/page'
import { get, type ReportItem } from '@/lib/api'

export default function ReportsPage() {
  const q = useQuery({ queryKey: ['reports'], queryFn: () => get<ReportItem[]>('/reports') })
  const items = q.data ?? []
  return (
    <Page
      title="조사 보고서"
      sub={`${items.length}건의 조사·면접 자료`}
      source={<code>jobfeed/reports/*.md</code>}
    >
      {q.isPending && <Skeleton className="h-40 w-full" />}
      {q.error && (
        <div role="alert" className="notice mb-3">
          보고서 목록을 불러오지 못했습니다 — {q.error.message}
        </div>
      )}
      {q.data &&
        (items.length ? (
          <div className="surface mb-3 divide-y divide-[var(--line)]">
            {items.map((it) => (
              <div
                key={it.name}
                className="min-w-0 px-4 py-3 hover:bg-[var(--hov)]"
              >
                <div className="min-w-0 font-semibold [overflow-wrap:anywhere]">
                  <Link href={`/reports/${encodeURIComponent(it.name)}`} className="inline-flex min-h-11 items-center text-[var(--link)] hover:underline">
                    {it.title}
                  </Link>
                </div>
                <div className="mt-1.5 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-[var(--dim)]">
                  <Badge variant="outline">{it.kind}</Badge>
                  <span className="tabular">{it.date ?? '날짜 미확인'}</span>
                  <span className="min-w-0 [overflow-wrap:anywhere]">{it.name}.md</span>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="empty-state mb-3">
            저장된 보고서가 없습니다.
          </div>
        ))}
    </Page>
  )
}
