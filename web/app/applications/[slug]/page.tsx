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
    if (cid) router.replace(`/applications/job/${encodeURIComponent(cid)}`)
  }, [cid, router])

  if (error)
    return (
      <Page title={slug}>
        <Card className="rounded-[9px] border-[var(--rail-bad)] bg-[var(--badbg)] px-[14px] py-[10px] text-[12.5px] text-[var(--bad)]">
          {error instanceof ApiError ? error.detail : String(error)}
        </Card>
      </Page>
    )

  if (isPending || !data || cid)
    return (
      <Page title={slug}>
        <Skeleton className="h-64 w-full" />
      </Page>
    )

  return (
    <Page
      title={slug}
      sub={
        <>
          <code>applications/{slug}</code> · md {data.folder.files.length} · 후보목록의 공고와 연결되지 않았습니다 —
          문서에 공고 링크를 적으면 이어집니다.
        </>
      }
      source={<code>{`applications/${slug}/*.md`}</code>}
    >
      <DocTabs docs={data.docs} empty="이 폴더에는 마크다운 문서가 없습니다." />
    </Page>
  )
}
