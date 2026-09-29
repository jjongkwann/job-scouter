'use client'
import { useState } from 'react'
import Link from 'next/link'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { ApiError, get, post, type Dashboard, type Proposal } from '@/lib/api'
import { jobplanetUrl } from '@/lib/utils'
import { Page } from '@/components/page'
import { Fit } from '@/components/fit'
import { Due } from '@/components/due'
import { AXES } from '@/lib/candidates'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'

const RAIL: Record<string, string> = { good: 'rail-good', warn: 'rail-warn', bad: 'rail-bad', none: '' }

// 거부 사유 프리셋 — X를 고르면 첫 항목으로 미리 채워지고, datalist로도 제안된다
const X_REASONS = ['적합도 낮음', '스택 불일치', '도메인 불일치', '레벨 불일치', '역할 불일치', '마감·내려감', '평판', '조건(연봉·근무지)']
const SOURCES: Record<string, string> = { wanted: '원티드', jumpit: '점핏', remember: '리멤버' }

type Decision = { d: 'o' } | { d: 'x'; why: string }

export default function Home() {
  const qc = useQueryClient()
  const [decisions, setDecisions] = useState<Record<string, Decision>>({})

  const { data, isPending, error } = useQuery({
    queryKey: ['dashboard'],
    queryFn: () => get<Dashboard>('/dashboard'),
    refetchInterval: 10_000,
  })

  const submit = useMutation({
    mutationFn: () =>
      post<{ workflow_id: string }>('/publish', {
        ids: Object.entries(decisions).filter(([, v]) => v.d === 'o').map(([id]) => id),
        rejects: Object.entries(decisions)
          .filter((e): e is [string, { d: 'x'; why: string }] => e[1].d === 'x')
          .map(([id, v]) => ({ id, why: v.why.trim() || X_REASONS[0] })),
      }),
    onSuccess: () => {
      toast('승인 처리 시작')
      setDecisions({})
      qc.invalidateQueries()
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.detail : String(e)),
  })

  const pub = data?.publish
  const busy = pub?.status === 'RUNNING'
  const groups = data?.groups ?? []
  const picked = Object.keys(decisions).length

  const decide = (id: string, v: string[]) =>
    setDecisions((s) => {
      const rest = Object.fromEntries(Object.entries(s).filter(([k]) => k !== id))
      if (v[0] === 'o') return { ...rest, [id]: { d: 'o' } }
      if (v[0] === 'x') return { ...rest, [id]: { d: 'x', why: X_REASONS[0] } }
      return rest
    })
  const setWhy = (id: string, why: string) =>
    setDecisions((s) => (s[id]?.d === 'x' ? { ...s, [id]: { d: 'x', why } } : s))

  return (
    <Page
      title="승인 대기"
      sub="수집된 공고의 근거를 확인하고 후보로 등록할 항목을 고릅니다. 등록 처리 뒤 지원서류 초안 생성이 자동으로 이어집니다."
      source={<code>jobfeed/proposals.json</code>}
      stats={[
        [data?.stats.pending ?? '–', '승인 대기'],
        [data?.stats.fit75 ?? '–', '적합도 75+'],
        [data?.review_pending.length ?? '–', 'AI 경력 재검토'],
        [data?.stats.gone ?? '–', '마감 지남'],
        [data?.stats.unresearched ?? '–', '평판 미조사 회사'],
        ['09:07', '정기 수집 시각'],
      ]}
    >
      <Link href="/applications/files" className="page-link mb-4 inline-block text-[13px]">
        제출용 파일 보기 →
      </Link>
      {error && (
        <Card className="mb-3 rounded-[9px] border-[var(--rail-bad)] bg-[var(--badbg)] px-[14px] py-[10px] text-[12.5px] leading-[1.5] text-[var(--bad)]">
          대시보드를 불러오지 못했습니다 — {error instanceof ApiError ? error.detail : String(error)}
        </Card>
      )}

      {busy && (
        <Card className="mb-3 rounded-[9px] px-[14px] py-[10px] text-[12.5px] leading-[1.5]">
          후보 등록 {pub.ids.length}건 · 제외 {pub.reject_ids.length}건 처리 중 ({pub.start}). 완료되면 등록한 공고의 지원서류 초안 생성이 이어집니다.
        </Card>
      )}
      {pub?.status === 'FAILED' && (
        <Card className="mb-3 rounded-[9px] border-[var(--rail-bad)] bg-[var(--badbg)] px-[14px] py-[10px] text-[12.5px] leading-[1.5] text-[var(--bad)]">
          마지막 후보 처리 실패 ({pub.start}): {pub.error} 등재·제외는 이미 반영됐을 수 있습니다. 후보 목록에서 상태를 확인하고 필요한 초안을 다시 만드세요.
        </Card>
      )}
      {submit.isError && (
        <Card className="mb-3 rounded-[9px] border-[var(--rail-bad)] bg-[var(--badbg)] px-[14px] py-[10px] text-[12.5px] leading-[1.5] text-[var(--bad)]" role="alert">
          선택 처리 요청에 문제가 생겼습니다: {submit.error instanceof ApiError ? submit.error.detail : String(submit.error)}. 선택과 제외 사유는 남아 있습니다. 요청 접수 여부가 불분명할 수 있으므로 <button className="page-link" onClick={() => qc.invalidateQueries({ queryKey: ['dashboard'] })}>처리 상태 새로고침</button>과 <Link href="/candidates" className="page-link">후보 목록</Link>을 확인한 뒤 필요한 항목만 다시 처리하세요.
        </Card>
      )}

      <div className="surface mb-3 divide-y divide-[var(--line)]">

        {isPending ? (
          [0, 1, 2].map((i) => (
            <div key={i} className="border-b border-[var(--line)] px-[14px] py-[11px] last:border-b-0">
              <Skeleton className="h-9 w-full" />
            </div>
          ))
        ) : groups.length === 0 ? (
          <div className="empty-state">승인 대기 중인 공고가 없습니다.</div>
        ) : (
          groups.map((group) => (
            <section key={group.id} aria-label={`${group.company} ${group.title}`}>
              {group.postings.length > 1 && (
                <div className="flex flex-wrap items-center gap-2 bg-[var(--neubg)] px-[14px] py-2 text-[12px]">
                  <span className="font-semibold">{group.company} · 같은 공고 {group.postings.length}개 사이트</span>
                  {group.postings.map((p) => (
                    <a key={p.id} href={p.url} target="_blank" rel="noopener" className="page-link">
                      {SOURCES[p.src] ?? '공식 채용'}
                    </a>
                  ))}
                  <span className="text-[var(--dim)]">사이트별 조건을 확인하고 각각 선택하세요</span>
                </div>
              )}
              {group.postings.map((p) => (
                <Row key={p.id} p={p} locked={busy || submit.isPending}
                  decision={decisions[p.id]} onDecide={(v) => decide(p.id, v)} onWhy={(why) => setWhy(p.id, why)} />
              ))}
            </section>
          ))
        )}
      </div>
      <datalist id="x-reasons">
        {X_REASONS.map((r) => (
          <option key={r} value={r} />
        ))}
      </datalist>

      {!!data?.review_pending.length && (
        <details className="my-3 rounded-[9px] border border-[var(--line)] px-[14px] py-3 text-[12px]">
          <summary className="cursor-pointer font-semibold">AI 경력 재검토 대기 {data.review_pending.length}건</summary>
          <p className="my-2 text-[var(--dim)]">7년 이상 조건을 포함해 다음 스캔에서 다시 판정합니다. 판정이 끝나면 승인할 수 있습니다.</p>
          {data.review_pending.map((p) => (
            <div key={p.id} className="py-1">
              <a href={p.url} target="_blank" rel="noopener" className="text-[var(--link)] hover:underline">{p.company} · {p.title}</a>
              {' · '}{p.career}
            </div>
          ))}
        </details>
      )}

      {(picked > 0 || busy || submit.isPending) && <div className="action-bar surface mt-3 flex flex-wrap items-center gap-3 p-3 text-[13px] shadow-sm">
        {busy ? (
          <span>후보 처리 중에는 새 선택을 제출할 수 없습니다.</span>
        ) : (
          <>
            <span aria-live="polite">{picked}건 선택 · 후보 등록 뒤 지원서류 초안이 자동 생성됩니다. 제외한 공고는 사유와 함께 기록됩니다.</span>
            <Button
              className="ml-auto"
              size="sm"
              disabled={picked === 0 || submit.isPending}
              onClick={() => submit.mutate()}
            >
              {submit.isPending ? '처리 요청 중…' : `${picked}건 선택 처리`}
            </Button>
          </>
        )}
      </div>}

      <details className="mt-6 surface p-4 text-[13px]">
      <summary className="cursor-pointer font-semibold">추가 정보 · 평판 미조사 {data?.unresearched.length ?? 0}곳 · 최근 실행</summary>
      <h2 className="mt-5 mb-2 text-[15px] font-semibold">평판 미조사 회사 {data?.unresearched.length ?? 0}</h2>
      {data && data.unresearched.length > 0 ? (
        <>
          <div className="flex flex-wrap gap-1">
            {data.unresearched.map((c) => (
              <Badge key={c} variant="secondary" className="rounded-[4px] bg-[var(--neubg)] text-[11px] text-[var(--neu)]">
                {c}
              </Badge>
            ))}
          </div>
          <p className="mt-1.5 text-[13px] text-[var(--dim)]">
            잡플래닛은 자동 조회하지 않습니다. <code>/job-scout</code>로 조사해 <code>jobfeed/기업평판.md</code>를 push하면 다음
            Publish부터 색띠와 추천도에 반영됩니다.
          </p>
        </>
      ) : (
        <p className="text-[13px] text-[var(--dim)]">없음</p>
      )}

      <h2 className="mt-7 mb-2 text-[15px] font-semibold">최근 실행</h2>
      <Card className="rounded-[9px] px-4 py-0 text-[12.5px]">
        {data?.runs_error ? (
          <p className="py-3 text-[var(--bad)]">Temporal 연결 실패: {data.runs_error}</p>
        ) : data && data.runs.length > 0 ? (
          <table className="my-2.5 w-full border-collapse">
            <thead>
              <tr className="text-[11px] font-semibold text-[var(--dim)]">
                <th className="w-40 border-b border-[var(--line)] py-[5px] pr-2.5 text-left">종류</th>
                <th className="w-30 border-b border-[var(--line)] py-[5px] pr-2.5 text-left">상태</th>
                <th className="border-b border-[var(--line)] py-[5px] text-left">시작 (KST)</th>
              </tr>
            </thead>
            <tbody>
              {data.runs.map((r, i) => (
                <tr key={i}>
                  <td className="border-b border-[var(--line)] py-[5px] pr-2.5 align-top last:border-b-0">{r.type}</td>
                  <td className="border-b border-[var(--line)] py-[5px] pr-2.5 align-top">
                    <span className={`rounded-[4px] px-[7px] py-px text-[11px] ${statusCls(r.status)}`}>{r.status}</span>
                  </td>
                  <td className="border-b border-[var(--line)] py-[5px] align-top tabular">{r.start}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="py-3">없음</p>
        )}
      </Card>
      </details>
    </Page>
  )
}

const statusCls = (s: string) =>
  s === 'COMPLETED'
    ? 'bg-[var(--goodbg)] text-[var(--good)]'
    : ['FAILED', 'TERMINATED', 'TIMED_OUT'].includes(s)
      ? 'bg-[var(--badbg)] text-[var(--bad)]'
      : 'bg-[var(--neubg)] text-[var(--neu)]'

function Row({
  p,
  locked,
  decision,
  onDecide,
  onWhy,
}: {
  p: Proposal
  locked: boolean
  decision?: Decision
  onDecide: (v: string[]) => void
  onWhy: (why: string) => void
}) {
  return (
    <article className={`rail ${RAIL[p.rail]} min-w-0 bg-[var(--row)] px-4 py-4 hover:bg-[var(--hov)]`}>
      <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(0,1fr)_auto]">
        <div className="min-w-0">
          <div className="text-[14px] font-semibold leading-snug break-words">
            <a href={p.url} target="_blank" rel="noopener" className="text-[var(--link)] hover:underline">{p.company} · {p.title}</a>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-[var(--dim)]">
            <span>{SOURCES[p.src] ?? '공식 채용'}</span><span>{p.career || '경력 조건 미확인'}</span>
            {p.due && <Due due={p.due} cls={p.due_cls} />}
            <span className="font-medium text-[var(--warn)]">{p.experience_review_required ? '경력 조건 재검토 필요' : '필수 요건 원문 확인 필요'}</span>
          </div>
          <p className="mt-2 mb-0 text-[13px] leading-relaxed break-words">{p.reason || '판정 사유가 기록되지 않았습니다.'}</p>
          <div className="mt-2 flex flex-wrap items-center gap-3 text-[12px] text-[var(--dim)]">
            <span>적합도 <strong className="text-[var(--fg)] tabular">{p.total}</strong></span>
            <span>평판 {p.rail === 'none' ? '정보 없음' : p.rail === 'good' ? '괜찮음' : p.rail === 'warn' ? '주의' : '회피'}</span>
            <a href={jobplanetUrl(p.company)} target="_blank" rel="noopener" className="page-link">잡플래닛</a>
          </div>
        </div>
        <div className="flex min-w-0 flex-col items-start gap-2 lg:items-end">
          {p.busy || locked ? <Badge variant="secondary">처리 중</Badge> : <>
            <ToggleGroup value={decision ? [decision.d] : []} onValueChange={onDecide}>
              <ToggleGroupItem value="o" size="sm" aria-label={`${p.title} 후보 등록`} className="border border-[var(--line)] px-3 aria-pressed:border-[var(--good)] aria-pressed:bg-[var(--goodbg)]">후보 등록</ToggleGroupItem>
              <ToggleGroupItem value="x" size="sm" aria-label={`${p.title} 후보에서 제외`} className="border border-[var(--line)] px-3 aria-pressed:border-[var(--bad)] aria-pressed:bg-[var(--badbg)]">후보에서 제외</ToggleGroupItem>
            </ToggleGroup>
            {decision?.d === 'x' && <Input className="w-full min-w-0 max-w-64 text-[16px]" placeholder="제외 사유" list="x-reasons" value={decision.why} onChange={(e) => onWhy(e.target.value)} aria-label={`${p.title} 제외 사유`} />}
          </>}
        </div>
      </div>
      <details className="mt-3 border-t border-[var(--line)] pt-2 text-[12px] text-[var(--dim)]">
        <summary className="cursor-pointer text-[var(--link)] underline underline-offset-2">평가 상세 · 점수와 인용 {p.quotes.length}건</summary>
        <div className="mt-3 flex max-w-full flex-wrap gap-4"><Fit total={p.total} tier={p.tier} />{p.cells.map(([value], i) => <span key={i}>{AXES[i]} {value}</span>)}</div>
        <p className="mt-2">평가 확신도 {(p.confidence ?? 0).toFixed(2)} · 평가 시점 {p.judged_at || '미확인'} · 평가 기준 {p.rubric_version || '미확인'}</p>
        {p.quotes.length > 0 && <ul className="mt-2 list-disc pl-5 break-words">{p.quotes.map((q, i) => <li key={i}>{q}</li>)}</ul>}
      </details>
    </article>
  )
}
