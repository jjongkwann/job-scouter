'use client'
import { useParams } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Markdown } from '@/components/markdown'
import { Page } from '@/components/page'
import { get, type Report } from '@/lib/api'

// 라우터가 이미 디코드해 주는 경우가 있어 한 번 풀고 다시 인코딩한다 — 어느 쪽이든 같은 결과.
const dec = (s: string) => {
  try {
    return decodeURIComponent(s)
  } catch {
    return s
  }
}

export default function ReportPage() {
  const name = dec(String(useParams().name ?? ''))
  const q = useQuery({
    queryKey: ['report', name],
    queryFn: () => get<Report>(`/reports/${encodeURIComponent(name)}`),
  })
  return (
    <Page title={name}>
      <p className="mb-2 font-mono text-[11px] text-[var(--dim)]">{name}.md</p>
      {q.isPending && <Skeleton className="h-96 w-full" />}
      {q.error && (
        <Card className="mb-3 rounded-lg border border-[var(--rail-bad)] bg-[var(--badbg)] px-3.5 py-3 text-[12.5px] text-[var(--bad)] ring-0">
          보고서를 불러오지 못했습니다 — {q.error.message}
        </Card>
      )}
      {q.data && <Markdown text={q.data.markdown} />}
    </Page>
  )
}
