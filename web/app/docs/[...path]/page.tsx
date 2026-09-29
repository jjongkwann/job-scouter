'use client'
import { useParams } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'
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
  const name = (segs[segs.length - 1] ?? '').replace(/\.md$/, '').replaceAll('_', ' ')
  const q = useQuery({
    queryKey: ['doc', path],
    queryFn: () => get<Doc>(`/docs/${segs.map(encodeURIComponent).join('/')}`),
  })
  return (
    <Page title={name || '참고 문서'} back={{ href: '/docs', label: '참고 문서 목록' }} source={<code>{path}</code>}>
      {q.isPending && <Skeleton className="h-96 w-full" />}
      {q.error && (
        <div role="alert" className="notice mb-3">
          문서를 불러오지 못했습니다 — {q.error.message}
        </div>
      )}
      {q.data && <Markdown text={q.data.markdown} />}
    </Page>
  )
}
