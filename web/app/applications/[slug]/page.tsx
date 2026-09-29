'use client'
import { use, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'

import { ApiError, get, type SlugApplication } from '@/lib/api'
import { Page } from '@/components/page'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { DocTabs } from '../doc-tabs'

export default function SlugApplicationPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params)
  const router = useRouter()

  const { data, isPending, error } = useQuery({
    queryKey: ['application-slug', slug],
    queryFn: () => get<SlugApplication>(`/applications/${encodeURIComponent(slug)}`),
  })

  // 폴더가 공고에 이어져 있으면 공고 화면이 정본이다 — 히스토리에 이 주소를 남기지 않는다
  const cid = data?.linked_cid
  useEffect(() => {
    if (cid) router.replace(`/applications/job/${encodeURIComponent(cid)}?folder=${encodeURIComponent(slug)}`)
  }, [cid, router, slug])

  if (error)
    return (
      <Page title="연결되지 않은 초안" back={{ href: '/applications', label: '공고별 초안' }}>
        <Card className="rounded-[9px] border-[var(--rail-bad)] bg-[var(--badbg)] px-[14px] py-[10px] text-[12.5px] text-[var(--bad)]">
          {error instanceof ApiError ? error.detail : String(error)}
        </Card>
      </Page>
    )

  if (isPending || !data || cid)
    return (
      <Page title="연결되지 않은 초안" back={{ href: '/applications', label: '공고별 초안' }}>
        <Skeleton className="h-64 w-full" />
      </Page>
    )

  return (
    <Page
      title="연결되지 않은 초안"
      back={{ href: '/applications', label: '공고별 초안' }}
      sub={
        <>
          {slug} · 초안 {data.folder.docs.length}/5종 ·{' '}
          {data.folder.ids.length > 0
            ? `문서에서 확인된 공고 ID ${data.folder.ids.join(', ')}가 현재 후보목록에 없어 연결되지 않았습니다.`
            : '문서에서 연결할 공고 ID를 확인하지 못해 현재 후보와 연결되지 않았습니다.'}
        </>
      }
      source={`초안 폴더 ${slug}`}
    >
      <DocTabs docs={data.docs} empty="이 폴더에는 마크다운 문서가 없습니다." />
    </Page>
  )
}
