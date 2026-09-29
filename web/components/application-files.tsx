'use client'
import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { ApiError, get } from '@/lib/api'
import { Card } from '@/components/ui/card'

type Download = { name: string; url: string; size: number }
export type ApplicationFilePack = {
  id: string; ids: string[]; company: string; title: string
  source_urls: string[]; review_notes: string; limitations: string; pages: number
  files: (Download & { format: 'pdf' | 'pptx'; kind: 'resume' | 'portfolio' })[]
  bundle: Download | null
  slide?: { url: string; pages: number } | null
}
export type ApplicationFileCatalogue = {
  items: ApplicationFilePack[]; bundle: Download | null
  stats: { jobs: number; postings: number; documents: number }
}

export function useApplicationFiles() {
  return useQuery({
    queryKey: ['application-files'],
    queryFn: () => get<ApplicationFileCatalogue>('/application-files'),
    staleTime: 30_000,
  })
}

const LINK = 'inline-flex min-h-11 max-w-full items-center justify-center rounded-xl border border-[var(--line)] px-3 py-2 text-center text-[13px] font-medium no-underline hover:border-[var(--link)] focus-visible:outline-2 focus-visible:outline-offset-2'

export function ApplicationFileCard({ pack }: { pack: ApplicationFilePack }) {
  const sourceUrls = pack.source_urls.filter((u) => /^https?:\/\//.test(u))
  return (
    <Card className="min-w-0 gap-0 p-4">
      <h2 className="m-0 break-words text-[16px] font-semibold">
        {pack.id === 'base' ? '기본 이력서·포트폴리오' : pack.company}
      </h2>
      <p className="mt-1 mb-2 break-words text-[14px]">{pack.title}</p>
      <div className="mb-3 flex flex-wrap gap-x-3 gap-y-1 text-[12px] text-[var(--dim)]">
        <span>{pack.pages}쪽{pack.files.length > 0 && ` · ${[...new Set(pack.files.map((f) => f.format.toUpperCase()))].join(' / ')}`}</span>
        {pack.ids.length > 1 && <span>같은 채용의 공고 {pack.ids.length}건 연결</span>}
        {pack.ids.map((id) => (
          <Link key={id} href={`/applications/job/${encodeURIComponent(id)}`} className="break-all text-[var(--link)] hover:underline">
            공고 {id}
          </Link>
        ))}
      </div>
      <p className="mb-3 text-[12px] text-[var(--dim)]">생성된 파일입니다. 내용 검토나 실제 지원 여부는 기록되어 있지 않습니다.</p>
      <div className="flex flex-wrap gap-2">
        {pack.slide && (
          <a href={pack.slide.url} target="_blank" rel="noopener"
            className={`${LINK} bg-[var(--fg)] text-[var(--bg)]`}>
            포트폴리오 슬라이드 보기 ↗
          </a>
        )}
        {pack.files.map((file) => (
          <a key={file.url} href={file.url} target={file.format === 'pdf' ? '_blank' : undefined}
            rel={file.format === 'pdf' ? 'noopener' : undefined}
            className={`${LINK} ${!pack.slide && file === pack.files.find((f) => f.format === 'pdf') ? 'bg-[var(--fg)] text-[var(--bg)]' : ''}`}>
            {file.kind === 'resume' ? '이력서' : '포트폴리오'} {file.format.toUpperCase()}{file.format === 'pdf' ? ' 보기 ↗' : ' 받기'}
          </a>
        ))}
        {pack.bundle && <a href={pack.bundle.url} className={LINK}>이 세트 ZIP 받기</a>}
      </div>
      {(pack.review_notes || pack.limitations || sourceUrls.length > 0) && (
        <details className="mt-3 text-[13px] text-[var(--dim)]">
          <summary className="min-h-11 cursor-pointer py-3">{pack.review_notes || pack.limitations ? '경험 범위·지원 전 확인' : '공고 원문'}</summary>
          {pack.limitations && <p className="whitespace-pre-line">{pack.limitations}</p>}
          {pack.review_notes && <p>{pack.review_notes}</p>}
          <div className="flex flex-wrap gap-3">
            {sourceUrls.map((url, i) => (
              <a key={url} href={url} target="_blank" rel="noopener" className="text-[var(--link)] underline underline-offset-2">원문 {i + 1} ↗</a>
            ))}
          </div>
        </details>
      )}
    </Card>
  )
}

export function JobApplicationFiles({ cid }: { cid: string }) {
  const { data, isPending, error } = useApplicationFiles()
  if (error) return <p role="alert" className="text-[13px] text-[var(--bad)]">제출용 파일을 불러오지 못했습니다: {error instanceof ApiError ? error.detail : String(error)}</p>
  if (isPending) return <p className="mb-5 text-[13px] text-[var(--dim)]">제출용 파일을 확인하는 중입니다.</p>
  const pack = data?.items.find((p) => p.ids.includes(cid))
  if (!pack) return <p className="mb-5 text-[13px] text-[var(--dim)]">이 공고에 연결된 제출용 파일이 아직 없습니다.</p>
  return (
    <div className="mb-5">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-[14px]">
        <span className="font-semibold">제출용 파일</span>
        <Link href="/applications/files" className="text-[var(--link)] hover:underline">전체 제출용 파일</Link>
      </div>
      <ApplicationFileCard pack={pack} />
    </div>
  )
}
