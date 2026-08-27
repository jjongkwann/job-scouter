'use client'
import { use } from 'react'
import Link from 'next/link'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { ApiError, get, post, type JobApplication } from '@/lib/api'
import { Due } from '@/components/due'
import { Fit } from '@/components/fit'
import { Page } from '@/components/page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
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

export default function JobApplicationPage({ params }: { params: Promise<{ cid: string }> }) {
  const { cid } = use(params)
  const qc = useQueryClient()

  const { data, isPending, error } = useQuery({
    queryKey: ['application-job', cid],
    queryFn: () => get<JobApplication>(`/applications/job/${encodeURIComponent(cid)}`),
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

  if (error)
    return (
      <Page title="지원서류">
        <Card className="rounded-[9px] border-[var(--rail-bad)] bg-[var(--badbg)] px-[14px] py-[10px] text-[12.5px] text-[var(--bad)]">
          {error instanceof ApiError ? error.detail : String(error)}
        </Card>
      </Page>
    )

  if (isPending || !data)
    return (
      <Page title="지원서류">
        <Skeleton className="mb-4 h-44 w-full" />
        <Skeleton className="h-64 w-full" />
      </Page>
    )

  const { candidate: c, folder, others, docs, drafting } = data
  const src = c.id.startsWith('j') ? '점핏' : '원티드'
  const status = c.closed ? '공고 마감' : folder ? '미지원' : '초안 없음'
  const extra = folder ? folder.files.filter((f) => !APP_FILES.includes(f)) : []

  return (
    <Page
      title={c.company}
      sub={
        folder ? (
          <>
            <code>applications/{folder.slug}</code> · 문서 {folder.docs.length}/5
          </>
        ) : (
          '이 공고에 연결된 지원서류 폴더가 아직 없습니다.'
        )
      }
    >
      <div
        className={`mb-4 rounded-[9px] border border-[var(--line)] bg-[var(--row)] px-[18px] py-[15px] rail ${RAIL[c.rep_key]} ${c.closed ? 'opacity-60' : ''}`}
      >
        <div className="flex items-start justify-between gap-5 border-b border-[var(--line)] pb-[11px]">
          <div>
            <div className="text-[16px] leading-[1.3] font-bold tracking-[-0.2px]">
              {c.title}
              <span
                className={`ml-2 inline-block rounded-[4px] px-[7px] py-[2px] align-middle text-[11px] font-semibold ${
                  c.closed ? 'bg-[var(--badbg)] text-[var(--bad)]' : 'bg-[var(--neubg)] text-[var(--neu)]'
                }`}
              >
                {status}
              </span>
            </div>
            <div className="mt-[3px] text-[12px] text-[var(--dim)]">
              {c.company} ·{' '}
              <a href={c.url} target="_blank" rel="noopener" className="text-[var(--accent)] no-underline hover:underline">
                {src} {c.id} ↗
              </a>
              {folder && (
                <>
                  {' · '}
                  <code>applications/{folder.slug}</code>
                </>
              )}
            </div>
          </div>
          <div className={`text-right text-[17px] leading-[1.1] font-extrabold tabular ${REC_CLS(c.rec)}`}>
            {Math.round(c.rec)}
            <span className="mt-px block text-[10px] font-semibold text-[var(--dim)]">
              추천도{c.rank ? ` · #${c.rank}` : ''}
            </span>
          </div>
        </div>

        <div className="grid grid-cols-[250px_96px_158px_minmax(0,1fr)] gap-5 py-[13px] max-[1060px]:grid-cols-1 max-[1060px]:gap-3">
          <div>
            <div className="mb-[5px] text-[11px] text-[var(--dim)]">적합도</div>
            <Fit total={c.total} tier={c.tier} />
            <div className="mt-1 text-[11px] leading-[1.45] text-[var(--dim)]">
              {AXES.map((a, i) => `${a} ${c.scores[i] ?? 0}`).join(' · ')} · 감점 {c.scores[4] || '—'}
            </div>
          </div>
          <div>
            <div className="mb-[5px] text-[11px] text-[var(--dim)]">마감</div>
            <Due due={c.due} cls={c.due_cls} />
          </div>
          <div>
            <div className="mb-[5px] text-[11px] text-[var(--dim)]">근무지 · 통근</div>
            <div className={`text-[12px] ${ZONE_CLS(c.zone)}`}>{c.zone_label}</div>
            <div className="mt-1 text-[11px] leading-[1.45] text-[var(--dim)]">{c.addr}</div>
          </div>
          <div>
            <div className="mb-[5px] text-[11px] text-[var(--dim)]">평판</div>
            {c.rep ? (
              <div className="text-[12px] leading-[1.45]">
                <span className={`font-bold ${REP_CLS[c.rep_key]}`}>
                  {c.rep_label} {c.rep[1]}
                </span>
                <span className="text-[var(--dim)]">
                  {' '}
                  / {c.rep[2]}건 · ★{c.rep[3]}
                </span>
                <div className="text-[11px] text-[var(--dim)]">{c.rep[4]}</div>
              </div>
            ) : (
              <div className="text-[12px] text-[var(--faint)]">{c.rep_note}</div>
            )}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 pt-[11px]">
          {folder && (
            <span className="mr-auto text-[11px] text-[var(--dim)]">
              최종 수정 {folder.mtime} · 문서 {folder.docs.length}/5
            </span>
          )}
          <Link
            href="/candidates"
            className="rounded-full border border-[var(--line)] px-[11px] py-[3px] text-[12px] no-underline hover:border-[var(--dim)]"
          >
            후보목록에서 보기
          </Link>
          {drafting && (
            <Badge variant="outline" className="rounded-full border-[var(--warn)] px-[11px] py-[3px] text-[11px] text-[var(--warn)]">
              초안 생성 중
            </Badge>
          )}
          <Button
            size="sm"
            variant={folder ? 'outline' : 'default'}
            disabled={drafting || draft.isPending}
            onClick={() => draft.mutate()}
          >
            {folder ? '초안 다시 만들기' : '5종 초안 만들기'}
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)_260px] items-start gap-4 max-[1060px]:grid-cols-1">
        <div>
          <DocTabs
            docs={docs}
            empty={
              <>
                아직 문서가 없습니다.
                <br />
                <span className="text-[12px]">
                  초안 생성은 몇 분 걸립니다 — 끝나면 <code>0_JD</code>부터 <code>4_포트폴리오_구성</code>까지 5종이 이
                  자리에 채워집니다.
                </span>
              </>
            }
          />
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
