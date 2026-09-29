'use client'
import { useState } from 'react'
import { ApiError } from '@/lib/api'
import { Page } from '@/components/page'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { ApplicationFileCard, useApplicationFiles } from '@/components/application-files'

export default function ApplicationFilesPage() {
  const { data, isPending, error } = useApplicationFiles()
  const [search, setSearch] = useState('')
  const base = data?.items.find((p) => p.id === 'base')
  const query = search.trim().toLocaleLowerCase()
  const jobs = (data?.items ?? []).filter((p) => p.id !== 'base')
  const matches = jobs.filter((p) => [p.company, p.title, ...p.ids].join(' ').toLocaleLowerCase().includes(query))
  return (
    <Page title="제출용 파일"
      sub="생성된 이력서·포트폴리오를 확인하고 PDF·PPTX·ZIP을 받을 수 있습니다. 파일이 있어도 내용 검토나 실제 지원 완료를 뜻하지 않습니다."
      stats={data && [[data.stats.jobs, '공고별 파일 세트'], [data.stats.postings, '연결 공고'], [data.stats.documents, 'PDF·PPTX 파일']]}>
      {error && <p role="alert" className="text-[var(--bad)]">서류 목록을 불러오지 못했습니다: {error instanceof ApiError ? error.detail : String(error)}</p>}
      {isPending && <Skeleton className="h-48 w-full" />}
      {base && <div className="mb-5"><ApplicationFileCard pack={base} /></div>}
      {data?.bundle && (
        <a href={data.bundle.url} className="mb-5 inline-flex min-h-11 max-w-full items-center rounded-xl border border-[var(--line)] px-4 py-2 text-[13px] font-semibold no-underline hover:border-[var(--link)]">
          기본본·전체 공고 ZIP 받기 ({Math.ceil(data.bundle.size / 1024 / 1024)} MB)
        </a>
      )}
      {jobs.length > 0 && (
        <>
          <label htmlFor="application-files-search" className="mb-1.5 block text-[13px] font-medium">회사·직무·공고 ID 검색</label>
          <Input id="application-files-search" type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="회사, 직무 또는 공고 ID" className="mb-2 max-w-2xl" />
          <p className="mb-3 text-[12px] text-[var(--dim)]" aria-live="polite">{matches.length} / {jobs.length}세트</p>
          <div className="grid grid-cols-2 items-start gap-3 max-[1060px]:grid-cols-1">
            {matches.map((pack) => <ApplicationFileCard key={pack.id} pack={pack} />)}
          </div>
          {matches.length === 0 && <p className="py-6 text-[13px] text-[var(--dim)]">검색 결과가 없습니다.</p>}
        </>
      )}
      {data && jobs.length === 0 && <p className="text-[13px] text-[var(--dim)]">공고별 제출용 파일이 아직 없습니다.</p>}
    </Page>
  )
}
