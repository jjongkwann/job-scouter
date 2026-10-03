'use client'
import { use, useEffect } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { ApiError, get, post, type JobApplication } from '@/lib/api'
import { Due } from '@/components/due'
import { Fit } from '@/components/fit'
import { Page } from '@/components/page'
import { JobApplicationFiles } from '@/components/application-files'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { APP_FILES, DocTabs } from '../../doc-tabs'

const RAIL: Record<string, string> = { good: 'rail-good', warn: 'rail-warn', bad: 'rail-bad', none: '' }
const REC_CLS = (r: number) => (r >= 85 ? 'text-[var(--good)]' : r >= 70 ? 'text-[var(--fg)]' : 'text-[var(--dim)]')
const ZONE_CLS = (z: number) =>
  z <= 1 ? 'font-bold text-[var(--good)]' : z === 2 ? 'font-bold text-[var(--warn)]' : z <= 4 ? 'font-bold text-[var(--bad)]' : 'text-[var(--dim)]'
const REP_CLS: Record<string, string> = {
  good: 'text-[var(--good)]',
  warn: 'text-[var(--warn)]',
  bad: 'text-[var(--bad)]',
  none: '',
}
const AXES = ['스택', '도메인', '레벨', '역할']

export default function JobApplicationPage({ params, searchParams }: { params: Promise<{ cid: string }>; searchParams: Promise<{ folder?: string; doc?: string }> }) {
  const { cid } = use(params)
  const { folder: requestedFolder, doc: requestedDoc = '' } = use(searchParams)
  const router = useRouter()
  const qc = useQueryClient()
  // 같은 공고를 가리키는 폴더가 여럿일 때 URL로 선택을 보존한다. 비면 서버 기본 폴더.
  const folderSlug = requestedFolder ?? ''

  const { data, isPending, isPlaceholderData, error } = useQuery({
    queryKey: ['application-job', cid, folderSlug],
    queryFn: () =>
      get<JobApplication>(`/applications/job/${encodeURIComponent(cid)}${folderSlug ? `?folder=${encodeURIComponent(folderSlug)}` : ''}`),
    placeholderData: (previous, previousQuery) => previousQuery?.queryKey[1] === cid ? previous : undefined,
    // 초안이 도는 동안만 짧게 폴링한다 — 끝나면 SSE 토스트와 함께 무효화되고 멈춘다
    refetchInterval: (q) => (q.state.data?.drafting ? 3000 : false),
  })

  const draft = useMutation({
    mutationFn: () => post<{ workflow_id: string }>('/applications/draft', { id: cid }),
    onSuccess: () => {
      toast('초안 생성 시작 — 몇 분 걸립니다')
      qc.invalidateQueries()
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.detail : String(e)),
  })

  const docUrl = (folder: string, doc: string) =>
    `/applications/job/${encodeURIComponent(cid)}?folder=${encodeURIComponent(folder)}${doc ? `&doc=${encodeURIComponent(doc)}` : ''}`

  useEffect(() => {
    if (requestedFolder && requestedDoc && data?.folder?.slug === requestedFolder && !isPlaceholderData) {
      document.getElementById('application-docs')?.scrollIntoView({ block: 'start' })
    }
  }, [data?.folder?.slug, isPlaceholderData, requestedDoc, requestedFolder])

  if (error)
    return (
      <Page title="지원서류" back={{ href: '/applications', label: '공고별 초안' }}>
        <Card className="rounded-[9px] border-[var(--rail-bad)] bg-[var(--badbg)] px-[14px] py-[10px] text-[12.5px] text-[var(--bad)]">
          {error instanceof ApiError ? error.detail : String(error)}
        </Card>
      </Page>
    )

  if (isPending || !data)
    return (
      <Page title="지원서류" back={{ href: '/applications', label: '공고별 초안' }}>
        <Skeleton className="mb-4 h-44 w-full" />
        <Skeleton className="h-64 w-full" />
      </Page>
    )

  const { candidate: c, folder, folders, others, docs, drafting } = data
  const experienceBlocked = c.experience_review_required || c.experience_excluded
  const src = c.src === 'wanted' ? '원티드' : c.src === 'jumpit' ? '점핏' : c.src === 'remember' ? '리멤버' : c.src === 'linkedin' ? '링크드인' : '공식 채용'
  const status = isPlaceholderData ? '폴더 확인 중' : drafting ? '초안 생성 중' : folder?.docs.length ? `초안 ${folder.docs.length}/5종 생성` : '초안 없음'
  const extra = folder && !isPlaceholderData ? folder.files.filter((f) => !APP_FILES.includes(f)) : []

  return (
    <Page
      title={c.company}
      back={{ href: '/applications', label: '공고별 초안' }}
      sub={isPlaceholderData ? '선택한 폴더를 불러오는 중입니다.' : folder ? `초안 ${folder.docs.length}/5종 생성 · 최종 수정 ${folder.mtime}` : '이 공고에 연결된 초안이 아직 없습니다.'}
    >
      <div
        className={`surface rail mb-4 min-w-0 p-4 ${RAIL[c.rep_key]}`}
      >
        <div className="flex flex-wrap items-start justify-between gap-5 border-b border-[var(--line)] pb-[11px]">
          <div className="min-w-0">
            <div className="break-words text-[16px] leading-[1.3] font-bold tracking-[-0.2px]">
              {c.title}
              <span
                className="ml-2 inline-block rounded-md bg-[var(--neubg)] px-2 py-1 align-middle text-[12px] font-semibold text-[var(--neu)]"
              >
                {status}
              </span>
              {c.closed && <span className="ml-2 inline-block rounded-md bg-[var(--badbg)] px-2 py-1 align-middle text-[12px] font-semibold text-[var(--bad)]">공고 마감</span>}
            </div>
            <div className="mt-1 break-all text-[12px] text-[var(--dim)]">
              {c.company} ·{' '}
              <a href={c.url} target="_blank" rel="noopener" className="text-[var(--link)] no-underline hover:underline">
                {src} {c.id} ↗
              </a>
            </div>
          </div>
          <div className={`text-right text-[17px] leading-[1.1] font-extrabold tabular ${REC_CLS(c.rec)}`}>
            {experienceBlocked ? '—' : Math.round(c.rec)}
            <span className="mt-1 block text-[12px] font-semibold text-[var(--dim)]">
              추천도{c.rank ? ` · #${c.rank}` : ''}
            </span>
          </div>
        </div>

        <div className="grid grid-cols-[250px_96px_158px_minmax(0,1fr)] gap-5 py-3 max-[1280px]:grid-cols-2 max-[640px]:grid-cols-1 max-[1280px]:gap-3">
          <div>
            <div className="mb-1 text-[12px] text-[var(--dim)]">적합도</div>
            <Fit total={c.total} tier={c.tier} />
            <div className="mt-1 text-[12px] leading-[1.45] text-[var(--dim)]">
              {AXES.map((a, i) => `${a} ${c.scores[i] ?? 0}`).join(' · ')} · 감점 {c.scores[4] || '—'}
            </div>
          </div>
          <div>
            <div className="mb-1 text-[12px] text-[var(--dim)]">마감</div>
            <Due due={c.due} cls={c.due_cls} />
          </div>
          <div>
            <div className="mb-1 text-[12px] text-[var(--dim)]">근무지 · 통근</div>
            <div className={`text-[13px] ${ZONE_CLS(c.zone)}`}>{c.zone_label}</div>
            <div className="mt-1 break-words text-[12px] leading-[1.45] text-[var(--dim)]">{c.addr}</div>
          </div>
          <div>
            <div className="mb-1 text-[12px] text-[var(--dim)]">평판</div>
            {c.rep ? (
              <div className="text-[13px] leading-[1.45]">
                <span className={`font-bold ${REP_CLS[c.rep_key]}`}>
                  {c.rep_label} {c.rep[1]}
                </span>
                <span className="text-[var(--dim)]">
                  {' '}
                  / {c.rep[2] ?? '표본 미확인'}{c.rep[2] === null ? '' : '건'} · ★{c.rep[3]}
                </span>
                <div className="text-[12px] text-[var(--dim)]">{c.rep[4]}</div>
              </div>
            ) : (
              <div className="text-[13px] text-[var(--dim)]">평판 정보 없음</div>
            )}
          </div>
        </div>

        {c.rep_note && <p className="mb-1 break-words text-[13px] text-[var(--dim)]">등록 메모 · {c.rep_note}</p>}
        {experienceBlocked && <p className="text-[13px] text-[var(--warn)]">{c.experience_review_required ? `경력 ${c.career} · AI 재검토 대기` : `경력 검토 제외 · ${c.experience_reason}`} — 기존 문서는 열람할 수 있으며 새 초안 생성은 보류됩니다.</p>}
        {draft.error && <p role="alert" className="notice text-[var(--bad)]">초안 생성을 시작하지 못했습니다: {draft.error instanceof ApiError ? draft.error.detail : String(draft.error)}</p>}
        <div className="flex flex-wrap items-center gap-2 pt-[11px]">
          {folder && !isPlaceholderData && (
            <span className="mr-auto text-[12px] text-[var(--dim)]">
              초안 {folder.docs.length}/5종 · 최종 수정 {folder.mtime}
            </span>
          )}
          <Link
            href={`/candidates?candidate=${encodeURIComponent(cid)}`}
            className="inline-flex min-h-11 items-center rounded-xl border border-[var(--line)] px-3 py-2 text-[13px] no-underline hover:border-[var(--link)]"
          >
            후보목록의 이 공고 보기
          </Link>
          <Button
            size="sm"
            variant={folder ? 'outline' : 'default'}
            disabled={drafting || draft.isPending || experienceBlocked}
            onClick={() => draft.mutate()}
          >
            {folder ? '초안 다시 만들기' : '5종 초안 만들기'}
          </Button>
        </div>
      </div>

      <JobApplicationFiles cid={cid} />
      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_260px] items-start gap-4 max-[1280px]:grid-cols-1">
        <div id="application-docs" className="scroll-mt-4">
          {folders.length > 1 && folder && (
            <div className="mb-2 flex flex-wrap items-center gap-2 text-[12px] text-[var(--dim)]">
              <span>폴더</span>
              <ToggleGroup value={[isPlaceholderData ? requestedFolder || folder.slug : folder.slug]} onValueChange={(v) => v[0] && router.replace(docUrl(String(v[0]), requestedDoc || Object.keys(docs)[0] || ''), { scroll: false })}>
                {folders.map((f) => (
                  <ToggleGroupItem
                    key={f.slug}
                    value={f.slug}
                    size="sm"
                    aria-label={`폴더 ${f.slug}`}
                    className="rounded-full border border-[var(--line)] bg-[var(--row)] px-2.5 text-[12px] hover:border-[var(--dim)] aria-pressed:border-[var(--fg)] aria-pressed:bg-[var(--fg)] aria-pressed:text-white"
                  >
                    {f.slug} · {f.mtime}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            </div>
          )}
          <div className="relative" aria-busy={isPlaceholderData}>
            {isPlaceholderData && <p role="status" className="absolute top-0 left-0 text-[13px] text-[var(--dim)]">선택한 폴더의 문서를 불러오는 중입니다.</p>}
            <div className={isPlaceholderData ? 'invisible' : ''}>
              <DocTabs
                docs={docs}
                value={requestedDoc}
                onValueChange={(doc) => router.replace(docUrl(requestedFolder || folder?.slug || '', doc), { scroll: false })}
                empty={
                  <>
                    아직 문서가 없습니다.
                    <br />
                    <span className="text-[12px]">
                      초안 생성은 몇 분 걸립니다. 공고·맞춤 이력서·자기소개서·면접 준비·포트폴리오 구성 문서가 이 자리에 채워집니다.
                    </span>
                  </>
                }
              />
            </div>
          </div>
        </div>
        <div>
          {others.length > 0 && (
            <Card className="mb-3 rounded-[9px] px-[14px] py-3 text-[12px]">
              <h3 className="m-0 mb-2 text-[11px] font-semibold text-[var(--dim)]">
                이 회사의 다른 공고 {others.length}건
              </h3>
              {others.map((o) => (
                <div key={o.id} className="border-b border-[var(--line)] py-[7px] last:border-b-0">
                  <Link href={`/applications/job/${encodeURIComponent(o.id)}`} className="no-underline hover:underline">
                    {o.title}
                  </Link>
                  <div className="mt-0.5 text-[11px] tabular text-[var(--dim)]">
                    추천도 {Math.round(o.rec)}
                    {o.rank ? ` · #${o.rank}` : ''} · {o.due} · 적합도 {o.total}
                  </div>
                </div>
              ))}
            </Card>
          )}
          {extra.length > 0 && (
            <Card className="rounded-[9px] px-[14px] py-3 text-[12px]">
              <h3 className="m-0 mb-2 text-[11px] font-semibold text-[var(--dim)]">표준 5종이 아닌 파일</h3>
              {extra.map((f) => (
                <div key={f} className="py-[3px] text-[var(--dim)]">
                  {f}
                </div>
              ))}
            </Card>
          )}
        </div>
      </div>
    </Page>
  )
}
