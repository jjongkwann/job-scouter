'use client'
import { useParams } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Markdown } from '@/components/markdown'
import { Page } from '@/components/page'
import { get, type Doc } from '@/lib/api'

// 라우터가 이미 디코드해 주는 경우가 있어 한 번 풀고 세그먼트별로 다시 인코딩한다.
const dec = (s: string) => {
  try {
    return decodeURIComponent(s)
  } catch {
    return s
  }
}

export default function DocPage() {
  const raw = useParams().path
  const segs = (Array.isArray(raw) ? raw : raw ? [raw] : []).map(dec)
  const path = segs.join('/')
  const q = useQuery({
    queryKey: ['doc', path],
    queryFn: () => get<Doc>(`/docs/${segs.map(encodeURIComponent).join('/')}`),
  })
  return (
    <Page title={path}>
      <p className="mb-2 font-mono text-[11px] text-[var(--dim)]">{segs[segs.length - 1]}</p>
      {q.isPending && <Skeleton className="h-96 w-full" />}
      {q.error && (
        <Card className="mb-3 rounded-lg border border-[var(--rail-bad)] bg-[var(--badbg)] px-3.5 py-3 text-[12.5px] text-[var(--bad)] ring-0">
          문서를 불러오지 못했습니다 — {q.error.message}
        </Card>
      )}
      {q.data && <Markdown text={q.data.markdown} />}
    </Page>
  )
}
