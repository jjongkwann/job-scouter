'use client'
import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'

import { ApiError, get, type Candidate, type Candidates } from '@/lib/api'
import { ALL, applyFilters, isDead, scoreCells, sortRows, type Filters, type SortKey } from '@/lib/candidates'
import { Page } from '@/components/page'
import { Fit } from '@/components/fit'
import { Due } from '@/components/due'
import { ScoreCells } from '@/components/score-cells'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'

// template.html의 후보 행 규격 — 1060px 이하에서는 한 열로 접힌다
const GRID =
  'grid-cols-[minmax(190px,1fr)_62px_78px_68px_90px_repeat(5,44px)_116px_150px] max-[1060px]:grid-cols-1'
const RAIL: Record<string, string> = { good: 'rail-good', warn: 'rail-warn', bad: 'rail-bad', none: '' }
const STORE = 'candidates-view'

const SORTS: [SortKey, string][] = [
  ['rec', '추천순'],
  ['total', '적합도순'],
  ['due', '마감 임박순'],
  ['loc', '가까운 순'],
  ['rep', '평판순'],
  ['domain', '도메인순'],
  ['pos', '회사명순'],
]

// 헤더를 눌러도 정렬된다 — 축별 정렬(스택·레벨·역할·감점)은 여기서만 닿는다
const HEAD: [SortKey | '', string, boolean][] = [
  ['pos', '포지션 / 회사', false],
  ['rec', '추천도', false],
  ['total', '적합도', false],
  ['due', '마감', false],
  ['loc', '근무지 · 통근', false],
  ['stack', '스택', true],
  ['domain', '도메인', true],
  ['level', '레벨', true],
  ['role', '역할', true],
  ['penalty', '감점', true],
  ['rep', '평판 · 최근 흐름', false],
  ['', '상태 · 지원서류', false],
]

const TAGS: Record<string, [string, string]> = {
  bookmark: ['북마크', 'bg-[var(--neubg)] text-[var(--neu)]'],
  prep: ['지원자료', 'bg-[var(--neubg)] text-[var(--neu)]'],
  rejected: ['탈락 이력', 'bg-[var(--badbg)] text-[var(--bad)]'],
  domain: ['하드웨어·제조', 'bg-[var(--goodbg)] text-[var(--good)]'],
}

const LEGEND: [string, string][] = [
  ['var(--rail-good)', '괜찮음'],
  ['var(--rail-warn)', '주의'],
  ['var(--rail-bad)', '회피'],
  ['var(--rail-none)', '정보 없음'],
]

export default function CandidatesPage() {
  const [f, setF] = useState<Filters>(ALL)
  const [sort, setSort] = useState<SortKey>('rec')

  // 저장된 보기 상태는 마운트 뒤에 읽는다. useState 초기값으로 읽으면 프리렌더된 HTML(기본값)과
  // 어긋나 하이드레이션 오류가 난다 — 브라우저에만 있는 값을 되살리는 건 이 규칙의 정당한 예외다.
  useEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect -- 브라우저에만 있는 저장값 복원 */
    try {
      const s = JSON.parse(localStorage.getItem(STORE) ?? '{}')
      if (s.f) setF({ ...ALL, ...s.f })
      if (s.sort) setSort(s.sort)
    } catch {
      /* 저장값이 깨졌으면 기본값 */
    }
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [])
  useEffect(() => {
    try {
      localStorage.setItem(STORE, JSON.stringify({ f, sort }))
    } catch {
      /* 프라이빗 모드 등 — 저장 못 해도 화면은 동작한다 */
    }
  }, [f, sort])

  const { data, isPending, error } = useQuery({
    queryKey: ['candidates'],
    queryFn: () => get<Candidates>('/candidates'),
    refetchInterval: 30_000,
  })

  const rows = useMemo(() => data?.rows ?? [], [data])
  const live = useMemo(() => applyFilters(sortRows(rows.filter((c) => !isDead(c)), sort), f, true), [rows, sort, f])
  const dead = useMemo(() => applyFilters(sortRows(rows.filter(isDead), sort), f, false), [rows, sort, f])

  // 통근 밴드 이름은 데이터 repo settings.json에서 온다 — 화면에 기준지를 박아 두지 않는다
  const zoneLabels = useMemo(() => {
    const m = new Map<number, string>()
    for (const c of rows) if (!m.has(c.zone) && c.zone_label) m.set(c.zone, c.zone_label)
    return m
  }, [rows])
  const locOptions: [string, string][] = [
    ['all', '전체'],
    ...([0, 1, 2, 3] as const).map(
      (z) => [String(z), z === 0 ? (zoneLabels.get(0) ?? '가장 가까움') : `${zoneLabels.get(z) ?? `밴드 ${z}`}까지`] as [string, string],
    ),
  ]

  const n = (p: (c: Candidate) => boolean) => rows.filter(p).length

  return (
    <Page
      title={`채용 후보 ${rows.length}건 — 추천도 순위`}
      sub="추천도 = 적합도 × 평판계수 + 통근보정. 적합도 상위가 곧 지원 순서는 아닙니다 — 적합도(내가 맞는가) · 평판(가도 되는가) · 통근(다닐 만한가)은 서로 섞이지 않는 축입니다."
      source={<code>jobfeed/candidates.json</code>}
      stats={[
        [rows.length, '전체 공고'],
        [new Set(rows.map((c) => c.company)).size, '회사'],
        [n((c) => c.days_left !== null && c.days_left >= 0 && c.days_left <= 7), '마감 D-7 이내'],
        [n((c) => c.total >= 80), '적합도 80+'],
        [n((c) => c.rep_key === 'good'), '평판 괜찮음'],
        [n((c) => c.rep_key === 'bad'), '평판 회피'],
        [n((c) => c.rep_key === 'none'), '평판 정보 없음'],
        [n((c) => c.tags.includes('domain')), '하드웨어·제조'],
      ]}
    >
      {error && (
        <Card className="mb-3 rounded-[9px] border-[var(--rail-bad)] bg-[var(--badbg)] px-[14px] py-[10px] text-[12.5px] text-[var(--bad)]">
          후보목록을 불러오지 못했습니다 — {error instanceof ApiError ? error.detail : String(error)}
        </Card>
      )}
      {data && data.errors.length > 0 && (
        <Card className="mb-3 rounded-[9px] border-[var(--rail-warn)] bg-[var(--warnbg)] px-[14px] py-[10px] text-[12.5px] leading-[1.5] text-[var(--warn)]">
          <div className="font-semibold">candidates.json에서 걸러낸 줄 {data.errors.length}건</div>
          {data.errors.map((e, i) => (
            <div key={i}>{e}</div>
          ))}
        </Card>
      )}

      <div className="mb-3.5 flex flex-col gap-1.5">
        <Group label="정렬" value={sort} options={SORTS.map(([v, l]) => [v, l])} onChange={(v) => setSort(v as SortKey)} />
        <Group
          label="평판"
          value={f.rep}
          options={[['all', '전체'], ['good', '괜찮음'], ['warn', '주의'], ['bad', '회피'], ['none', '정보 없음']]}
          onChange={(v) => setF({ ...f, rep: v as Filters['rep'] })}
        />
        <Group
          label="상태"
          value={f.st}
          options={[['all', '전체'], ['bookmark', '북마크'], ['prep', '지원자료 있음'], ['rejected', '탈락 이력'], ['domain', '하드웨어·제조']]}
          onChange={(v) => setF({ ...f, st: v as Filters['st'] })}
        />
        <Group
          label="적합도"
          value={String(f.min)}
          options={[['0', '전체'], ['70', '70점 이상'], ['80', '80점 이상']]}
          onChange={(v) => setF({ ...f, min: Number(v) as Filters['min'] })}
        />
        <Group
          label="마감"
          value={f.due}
          options={[['all', '전체'], ['soon', 'D-7 이내'], ['dated', '마감일 있음'], ['always', '상시']]}
          onChange={(v) => setF({ ...f, due: v as Filters['due'] })}
        />
        <Group
          label="통근"
          value={String(f.loc)}
          options={locOptions}
          onChange={(v) => setF({ ...f, loc: (v === 'all' ? 'all' : Number(v)) as Filters['loc'] })}
        />
      </div>

      <div className="mb-0.5 flex flex-wrap items-center gap-4 px-[14px] py-[9px] text-[11.5px] text-[var(--dim)]">
        <span>행 왼쪽 색띠 = 평판 판정</span>
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
          {HEAD.map(([key, label, mid], i) =>
            key ? (
              <button
                key={i}
                type="button"
                onClick={() => setSort(key)}
                data-active={sort === key}
                className={`cursor-pointer bg-transparent p-0 text-[11px] text-inherit data-[active=true]:font-bold data-[active=true]:text-[var(--fg)] ${mid ? 'text-center' : 'text-left'}`}
              >
                {label}
              </button>
            ) : (
              <div key={i}>{label}</div>
            ),
          )}
        </div>

        {isPending ? (
          [0, 1, 2, 3].map((i) => (
            <div key={i} className="border-b border-[var(--line)] px-[14px] py-[11px] last:border-b-0">
              <Skeleton className="h-9 w-full" />
            </div>
          ))
        ) : rows.length === 0 ? (
          <div className="p-8 text-center text-[13px] text-[var(--dim)]">
            등재된 후보가 없습니다 — 대시보드에서 승인하면 여기에 쌓입니다.
          </div>
        ) : live.length === 0 ? (
          <div className="p-8 text-center text-[13px] text-[var(--dim)]">조건에 맞는 공고가 없습니다.</div>
        ) : (
          live.map((c) => <Row key={c.id} c={c} app={data?.apps[c.id]} />)
        )}
      </div>

      {dead.length > 0 && (
        <details className="mt-3.5 border-t border-[var(--line)]">
          <summary className="cursor-pointer list-none py-[11px] text-[12px] text-[var(--dim)] hover:text-[var(--fg)]">
            마감 지났거나 내려간 공고 <b>{dead.length}</b>건
          </summary>
          <div className="overflow-hidden rounded-[9px] border border-[var(--line)] bg-[var(--row)]">
            {dead.map((c) => (
              <Row key={c.id} c={c} app={data?.apps[c.id]} />
            ))}
          </div>
        </details>
      )}

      {data?.updated && <p className="mt-4 text-[11px] text-[var(--faint)]">갱신 {data.updated}</p>}
    </Page>
  )
}

function Group({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: string
  options: [string, string][]
  onChange: (v: string) => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="min-w-11 text-[11px] text-[var(--dim)]">{label}</span>
      <ToggleGroup
        value={[value]}
        onValueChange={(v) => {
          if (v[0]) onChange(v[0])
        }}
      >
        {options.map(([v, l]) => (
          <ToggleGroupItem
            key={v}
            value={v}
            size="sm"
            className="rounded-full border border-[var(--line)] bg-[var(--row)] px-[11px] text-[12px] hover:border-[var(--dim)] aria-pressed:border-[var(--fg)] aria-pressed:bg-[var(--fg)] aria-pressed:text-white"
          >
            {l}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
    </div>
  )
}

// 주소 원문은 "○○시 ○○구 ○○로 17, D1동 16층"처럼 길다 — 앞 두 토막(시·구)만 보인다
const shortAddr = (a: string) => (a ? a.split(/[,(]/)[0].split(/\s+/).slice(0, 2).join(' ') : '')

const ZONE_CLS = (z: number) =>
  z <= 1 ? 'font-bold text-[var(--good)]' : z === 2 ? 'font-bold text-[var(--warn)]' : z <= 4 ? 'font-bold text-[var(--bad)]' : 'text-[var(--dim)]'

const REC_CLS = (r: number) => (r >= 85 ? 'text-[var(--good)]' : r >= 70 ? 'text-[var(--fg)]' : 'text-[var(--dim)]')

const REP_CLS: Record<string, string> = {
  good: 'text-[var(--good)]',
  warn: 'text-[var(--warn)]',
  bad: 'text-[var(--bad)]',
  none: '',
}

function Row({ c, app }: { c: Candidate; app?: { slug: string; n: number } }) {
  const dead = isDead(c)
  return (
    <div
      className={`grid items-center gap-[10px] border-b border-[var(--line)] bg-[var(--row)] px-[14px] py-[9px] last:border-b-0 hover:bg-[var(--hov)] rail ${RAIL[c.rep_key]} ${GRID} max-[1060px]:py-[13px] ${dead ? 'opacity-55' : ''}`}
    >
      <div>
        <div className="text-[14px] leading-[1.35] font-semibold tracking-[-0.1px]">
          <a href={c.url} target="_blank" rel="noopener" className="text-inherit no-underline hover:underline hover:underline-offset-2">
            {c.title}
          </a>
        </div>
        <div className="mt-px text-[12px] text-[var(--dim)]">{c.company}</div>
      </div>

      <div className={`text-[15px] leading-[1.1] font-extrabold tabular ${REC_CLS(c.rec)}`}>
        <span className="hidden text-[11px] font-normal text-[var(--faint)] max-[1060px]:inline">추천도 </span>
        {Math.round(c.rec)}
        <span className="mt-px block text-[10px] font-semibold text-[var(--dim)]">#{c.rank ?? '-'}</span>
      </div>

      <Fit total={c.total} tier={c.tier} />
      <Due due={c.due} cls={c.due_cls} />

      <div className="text-[12px] leading-[1.3]">
        <span className="hidden text-[11px] text-[var(--faint)] max-[1060px]:inline">근무지 </span>
        <span className={ZONE_CLS(c.zone)}>{c.zone_label}</span>
        {c.addr && <div className="text-[var(--dim)]">{shortAddr(c.addr)}</div>}
      </div>

      <ScoreCells cells={scoreCells(c.scores)} />

      <div className="text-[12px] leading-[1.4]">
        {c.rep ? (
          <>
            <span className={`font-bold tabular ${REP_CLS[c.rep_key]}`}>{c.rep[1]}</span>
            {c.rep[2] ? <span className="font-mono text-[10.5px] text-[var(--dim)]"> / {c.rep[2]}건</span> : null}
            <div className="font-mono text-[10.5px] text-[var(--dim)]">★{c.rep[3]}</div>
            {c.rep[4] && <div className="mt-[3px] text-[11px] leading-[1.4] text-[var(--dim)]">{c.rep[4]}</div>}
          </>
        ) : (
          <span className="text-[var(--faint)]">{c.rep_note}</span>
        )}
      </div>

      <div className="flex flex-col items-start gap-1">
        <Link
          href={`/applications/job/${encodeURIComponent(c.id)}`}
          className={`rounded-full border px-[9px] py-[3px] text-[11px] leading-[1.45] no-underline hover:border-[var(--dim)] ${
            app
              ? app.n >= 5
                ? 'border-[#c9d9f2] bg-[#f2f6fd] font-semibold text-[var(--accent)]'
                : 'border-[#eddcb6] bg-[var(--warnbg)] font-semibold text-[var(--warn)]'
              : 'border-dashed border-[var(--line)] text-[var(--faint)]'
          }`}
        >
          {app ? `지원서류 ${app.n}종 →` : '초안 만들기 →'}
        </Link>
        <div className="text-[11px] leading-[1.5]">
          {c.tags.filter((t) => TAGS[t]).length === 0 ? (
            <span className="opacity-40">—</span>
          ) : (
            c.tags
              .filter((t) => TAGS[t])
              .map((t) => (
                <Badge key={t} variant="secondary" className={`mr-0.5 rounded-[4px] px-[7px] text-[11px] ${TAGS[t][1]}`}>
                  {TAGS[t][0]}
                </Badge>
              ))
          )}
        </div>
      </div>
    </div>
  )
}
