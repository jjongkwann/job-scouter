'use client'
import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Page } from '@/components/page'
import { get, type ReportItem } from '@/lib/api'

export default function ReportsPage() {
  const q = useQuery({ queryKey: ['reports'], queryFn: () => get<ReportItem[]>('/reports') })
  const items = q.data ?? []
  return (
    <Page
      title="보고서"
      sub={
        <>
          {items.length}건. <b className="text-[var(--fg)]">매칭조사</b>는 <code>/job-scout</code>로 직접 조사한 날의
          기록, <b className="text-[var(--fg)]">자동사이클</b>은 Publish가 쓰는 사이클 요약입니다.
        </>
      }
      source={<code>jobfeed/reports/*.md</code>}
    >
      {q.isPending && <Skeleton className="h-40 w-full" />}
      {q.error && (
        <Card className="mb-3 rounded-lg border border-[var(--rail-bad)] bg-[var(--badbg)] px-3.5 py-3 text-[12.5px] text-[var(--bad)] ring-0">
          보고서 목록을 불러오지 못했습니다 — {q.error.message}
        </Card>
      )}
      {q.data &&
        (items.length ? (
          <Card className="mb-3 gap-0 rounded-lg bg-[var(--row)] py-0 ring-[var(--line)]">
            {items.map((it) => (
              <div
                key={it.name}
                className="grid grid-cols-1 items-center gap-2.5 border-b border-[var(--line)] px-3.5 py-2.5 last:border-b-0 hover:bg-[var(--hov)] min-[1060px]:grid-cols-[110px_90px_minmax(0,1fr)]"
              >
                <div className="tabular text-[12.5px]">{it.date}</div>
                <div>
                  <Badge
                    variant="outline"
                    className={
                      it.kind === '자동사이클'
                        ? 'border-0 bg-[var(--goodbg)] text-[var(--good)]'
                        : 'border-0 bg-[var(--neubg)] text-[var(--neu)]'
                    }
                  >
                    {it.kind}
                  </Badge>
                </div>
                <div className="font-semibold tracking-[-0.1px]">
                  <Link href={`/reports/${encodeURIComponent(it.name)}`} className="text-inherit no-underline hover:underline">
                    {it.name}
                  </Link>
                </div>
              </div>
            ))}
          </Card>
        ) : (
          <div className="mb-3 rounded-[9px] border border-dashed border-[var(--line)] bg-[var(--row)] p-8 text-center text-[13px] text-[var(--dim)]">
            없음
          </div>
        ))}
    </Page>
  )
}
