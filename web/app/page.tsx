'use client'
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { ApiError, get, post, type Dashboard, type Proposal } from '@/lib/api'
import { Page } from '@/components/page'
import { Fit } from '@/components/fit'
import { Due } from '@/components/due'
import { ScoreCells } from '@/components/score-cells'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'

// web.py `.dash` 규격 그대로 — 1060px 이하에서는 한 열로 접힌다. 판정 열은 O/X 토글 두 칸이 들어가게 96px
const GRID = 'grid-cols-[minmax(220px,1.1fr)_78px_repeat(5,44px)_48px_minmax(290px,1.6fr)_96px_150px] max-[1060px]:grid-cols-1'
const RAIL: Record<string, string> = { good: 'rail-good', warn: 'rail-warn', bad: 'rail-bad', none: '' }

const LEGEND: [string, string][] = [
  ['var(--rail-good)', '괜찮음'],
  ['var(--rail-warn)', '주의'],
  ['var(--rail-bad)', '회피'],
  ['var(--rail-none)', '정보 없음'],
]

// 거부 사유 프리셋 — X를 고르면 첫 항목으로 미리 채워지고, datalist로도 제안된다
const X_REASONS = ['적합도 낮음', '스택 불일치', '도메인 불일치', '레벨 불일치', '역할 불일치', '마감·내려감', '평판', '조건(연봉·근무지)']

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
  const proposals = data?.proposals ?? []
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
      sub="DailyScan이 찾아 판정한 공고입니다. 승인하면 후보목록에 등재되고, 지원서류 초안은 이어서 별도 워크플로(Drafts)가 만듭니다 — 그동안 대시보드는 잠기지 않습니다."
      source={<code>jobfeed/proposals.json</code>}
      stats={[
        [data?.stats.pending ?? '–', '승인 대기'],
        [data?.stats.fit75 ?? '–', '적합도 75+'],
        [data?.stats.gone ?? '–', '마감 지남'],
        [data?.stats.unresearched ?? '–', '평판 미조사 회사'],
        ['09:07', '다음 DailyScan'],
      ]}
    >
      {error && (
        <Card className="mb-3 rounded-[9px] border-[var(--rail-bad)] bg-[var(--badbg)] px-[14px] py-[10px] text-[12.5px] leading-[1.5] text-[var(--bad)]">
          대시보드를 불러오지 못했습니다 — {error instanceof ApiError ? error.detail : String(error)}
        </Card>
      )}

      {busy && (
        <Card className="mb-3 rounded-[9px] px-[14px] py-[10px] text-[12.5px] leading-[1.5]">
          Publish 실행 중 ({pub.start}) — 승인 {pub.ids.length}건 · 거부 {pub.reject_ids.length}건 처리 중. 등재·거부 반영 →
          보고서 순으로 진행되고, 완료 후 승인건의 지원서류 초안(Drafts)이 따로 시작됩니다. 끝나기 전에는 제출할 수 없습니다 —
          끝나면 자동으로 갱신됩니다.
        </Card>
      )}
      {pub?.status === 'FAILED' && (
        <Card className="mb-3 rounded-[9px] border-[var(--rail-bad)] bg-[var(--badbg)] px-[14px] py-[10px] text-[12.5px] leading-[1.5] text-[var(--bad)]">
          마지막 Publish 실패 ({pub.start}): {pub.error} — 등재·거부는 앞 단계라 반영됐을 수 있고, 보고서·초안은 만들어지지
          않았습니다. 초안은 후보목록/공고 화면의 「초안 만들기」 버튼 또는 <code>worker draft &lt;공고id&gt;</code>로 만듭니다.
        </Card>
      )}

      <div className="mb-0.5 flex flex-wrap items-center gap-4 px-[14px] py-[9px] text-[11.5px] text-[var(--dim)]">
        <span>행 왼쪽 색띠 = 평판 판정 (후보목록과 동일)</span>
        {LEGEND.map(([bg, label]) => (
          <span key={label} className="flex items-center gap-1.5">
            <i className="inline-block h-[14px] w-[4px] rounded-[2px]" style={{ background: bg }} />
            {label}
          </span>
        ))}
      </div>

      <div className="mb-3 overflow-hidden rounded-[9px] border border-[var(--line)] bg-[var(--row)]">
        <div
          className={`grid items-center gap-[10px] border-b border-[var(--line)] bg-[var(--bg)] px-[14px] py-[9px] text-[11px] text-[var(--dim)] max-[1060px]:hidden ${GRID}`}
        >
          <div>포지션 / 회사</div>
          <div>적합도</div>
          <div className="text-center">스택</div>
          <div className="text-center">도메인</div>
          <div className="text-center">레벨</div>
          <div className="text-center">역할</div>
          <div className="text-center">감점</div>
          <div className="text-center">conf</div>
          <div>판정 사유 · 인용</div>
          <div className="text-center">판정</div>
          <div>거부 사유</div>
        </div>

        {isPending ? (
          [0, 1, 2].map((i) => (
            <div key={i} className="border-b border-[var(--line)] px-[14px] py-[11px] last:border-b-0">
              <Skeleton className="h-9 w-full" />
            </div>
          ))
        ) : proposals.length === 0 ? (
          <div className="p-8 text-center text-[13px] text-[var(--dim)]">대기 중인 후보 없음 — 다음 DailyScan은 매일 09:07</div>
        ) : (
          proposals.map((p) => (
            <Row
              key={p.id}
              p={p}
              locked={busy}
              decision={decisions[p.id]}
              onDecide={(v) => decide(p.id, v)}
              onWhy={(why) => setWhy(p.id, why)}
            />
          ))
        )}
      </div>
      <datalist id="x-reasons">
        {X_REASONS.map((r) => (
          <option key={r} value={r} />
        ))}
      </datalist>

      <div className="mt-2.5 flex items-center gap-3 rounded-[9px] border border-[var(--line)] bg-[var(--row)] px-[14px] py-[11px] text-[12px] text-[var(--dim)]">
        {busy ? (
          <span>실행 중인 Publish가 끝나면 제출할 수 있습니다</span>
        ) : (
          <>
            <span>O(승인) 또는 X(거부, 사유) 선택 후 제출하면 Publish 워크플로가 등재·판례·보고서를 처리하고, 완료 후 Drafts가 승인건 초안을 순차로 만듭니다</span>
            <Button
              className="ml-auto rounded-full"
              size="sm"
              disabled={picked === 0 || submit.isPending}
              onClick={() => submit.mutate()}
            >
              {submit.isPending ? '제출 중…' : '제출'}
            </Button>
          </>
        )}
      </div>

      <h2 className="mt-7 mb-2 text-[15px] font-semibold">평판 미조사 회사 {data?.unresearched.length ?? 0}</h2>
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
    <div
      className={`grid items-center gap-[10px] border-b border-[var(--line)] bg-[var(--row)] px-[14px] py-[9px] last:border-b-0 hover:bg-[var(--hov)] rail ${RAIL[p.rail]} ${GRID} max-[1060px]:py-[13px]`}
    >
      <div>
        <div className="text-[14px] leading-[1.35] font-semibold tracking-[-0.1px]">
          <a href={p.url} target="_blank" rel="noopener" className="text-inherit no-underline hover:underline hover:underline-offset-2">
            {p.title}
          </a>
        </div>
        <div className="mt-px text-[12px] text-[var(--dim)]">
          {p.company}
          {p.due && (
            <>
              {' · '}
              <Due due={p.due} cls={p.due_cls} />
            </>
          )}
        </div>
      </div>
      <Fit total={p.total} tier={p.tier} />
      <ScoreCells cells={p.cells} />
      <div className="text-center text-[12px] text-[var(--dim)] tabular">{(p.confidence ?? 0).toFixed(2)}</div>
      <div className="text-[12px] leading-[1.45]">
        {p.reason}
        {p.quotes.length > 0 && (
          <details className="mt-1 text-[11px] text-[var(--dim)]">
            <summary className="cursor-pointer list-none text-[var(--accent)]">인용 {p.quotes.length}건</summary>
            <ul className="mt-1 list-disc pl-4">
              {p.quotes.map((q, i) => (
                <li key={i}>{q}</li>
              ))}
            </ul>
          </details>
        )}
      </div>
      {p.busy || locked ? (
        <div className="col-span-2 text-center max-[1060px]:col-span-1 max-[1060px]:text-left">
          <Badge variant="secondary" className="text-[11px]">
            처리 중
          </Badge>
        </div>
      ) : (
        <>
          <div className="flex justify-center max-[1060px]:justify-start">
            <ToggleGroup value={decision ? [decision.d] : []} onValueChange={onDecide}>
              <ToggleGroupItem
                value="o"
                size="sm"
                aria-label={`${p.title} 승인`}
                className="rounded-full border border-[var(--line)] bg-[var(--row)] px-2.5 text-[12px] hover:border-[var(--dim)] aria-pressed:border-[var(--good)] aria-pressed:bg-[var(--good)] aria-pressed:text-white"
              >
                O
              </ToggleGroupItem>
              <ToggleGroupItem
                value="x"
                size="sm"
                aria-label={`${p.title} 거부`}
                className="rounded-full border border-[var(--line)] bg-[var(--row)] px-2.5 text-[12px] hover:border-[var(--dim)] aria-pressed:border-[var(--bad)] aria-pressed:bg-[var(--bad)] aria-pressed:text-white"
              >
                X
              </ToggleGroupItem>
            </ToggleGroup>
          </div>
          <div>
            {decision?.d === 'x' && (
              <Input
                className="h-7 rounded-md text-[12px]"
                placeholder="거부 사유"
                list="x-reasons"
                value={decision.why}
                onChange={(e) => onWhy(e.target.value)}
                aria-label={`${p.title} 거부 사유`}
              />
            )}
          </div>
        </>
      )}
    </div>
  )
}
