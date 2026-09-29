'use client'
import { useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { ApiError, get, post, type Candidate, type Candidates, type Dashboard } from '@/lib/api'
import { ALL, AXES, applyFilters, isDead, sortRows, type Filters, type SortKey } from '@/lib/candidates'
import { jobplanetUrl } from '@/lib/utils'
import { Page } from '@/components/page'
import { Due } from '@/components/due'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'

const RAIL: Record<string, string> = { good: 'rail-good', warn: 'rail-warn', bad: 'rail-bad', none: '' }
const STORE = 'candidates-view'
const SCROLL_STORE = 'candidates-scroll'

const SORTS: [SortKey, string][] = [
  ['rec', '추천순'],
  ['total', '적합도순'],
  ['due', '마감 임박순'],
  ['loc', '가까운 순'],
  ['rep', '평판순'],
  ['domain', '도메인순'],
  ['pos', '회사명순'],
  ['stack', '스택순'], ['level', '레벨순'], ['role', '역할순'], ['penalty', '감점순'],
]

const TAGS: Record<string, [string, string]> = {
  bookmark: ['북마크', 'bg-[var(--neubg)] text-[var(--neu)]'],
  prep: ['지원자료', 'bg-[var(--neubg)] text-[var(--neu)]'],
  rejected: ['탈락 이력', 'bg-[var(--badbg)] text-[var(--bad)]'],
  domain: ['하드웨어·제조', 'bg-[var(--goodbg)] text-[var(--good)]'],
}

export default function CandidatesPage() {
  const qc = useQueryClient()
  const [f, setF] = useState<Filters>(ALL)
  const [sort, setSort] = useState<SortKey>('rec')
  const [q, setQ] = useState('')
  const [picked, setPicked] = useState<string[]>([])
  const [restored, setRestored] = useState(false)
  const [target, setTarget] = useState<string | null>(null)
  const didScroll = useRef(false)

  // 저장된 보기 상태는 마운트 뒤에 읽는다. useState 초기값으로 읽으면 프리렌더된 HTML(기본값)과
  // 어긋나 하이드레이션 오류가 난다 — 브라우저에만 있는 값을 되살리는 건 이 규칙의 정당한 예외다.
  useEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect -- 브라우저에만 있는 저장값 복원 */
    try {
      const s = JSON.parse(localStorage.getItem(STORE) ?? '{}')
      if (s.f) setF({ ...ALL, ...s.f })
      if (s.sort) setSort(s.sort)
      if (typeof s.q === 'string') setQ(s.q)
    } catch {
      /* 저장값이 깨졌으면 기본값 */
    }
    setTarget(new URLSearchParams(window.location.search).get('candidate'))
    setRestored(true)
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [])
  useEffect(() => {
    if (!restored) return
    try {
      localStorage.setItem(STORE, JSON.stringify({ f, sort, q }))
    } catch {
      /* 프라이빗 모드 등 — 저장 못 해도 화면은 동작한다 */
    }
  }, [f, sort, q, restored])

  const { data, isPending, error } = useQuery({
    queryKey: ['candidates'],
    queryFn: () => get<Candidates>('/candidates'),
    refetchInterval: 30_000,
  })

  const { data: dashboard } = useQuery({
    queryKey: ['dashboard'],
    queryFn: () => get<Dashboard>('/dashboard'),
    refetchInterval: 10_000,
  })
  const remove = useMutation({
    mutationFn: (ids: string[]) =>
      post<{ workflow_id: string }>('/publish', { ids: [], rejects: ids.map((id) => ({ id, why: '후보목록에서 삭제' })) }),
    onSuccess: () => {
      toast('후보 제외 처리 시작')
      setPicked([])
      return qc.invalidateQueries()
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.detail : String(e)),
  })
  const busy = remove.isPending || dashboard?.publish?.status === 'RUNNING'
  const rows = useMemo(() => data?.rows ?? [], [data])
  const search = q.trim().toLowerCase()
  const searched = useMemo(() => rows.filter((c) => !search || [c.company, c.title, c.id].some((v) => v.toLowerCase().includes(search))), [rows, search])
  const review = useMemo(() => applyFilters(sortRows(searched.filter((c) => !isDead(c) && (c.experience_review_required || c.experience_excluded)), sort), f, false), [searched, sort, f])
  const live = useMemo(() => applyFilters(sortRows(searched.filter((c) => !isDead(c) && !c.experience_review_required && !c.experience_excluded), sort), f, true), [searched, sort, f])
  const dead = useMemo(() => applyFilters(sortRows(searched.filter(isDead), sort), f, false), [searched, sort, f])
  const visibleCount = live.length + review.length + dead.length
  const targetExists = rows.some((c) => c.id === target)
  const visible = [...live, ...review, ...dead].some((c) => c.id === target)
  useEffect(() => {
    if (!restored || !data || didScroll.current || (target && !visible)) return
    const position = target ? document.getElementById(`candidate-${target}`) : null
    if (position) position.scrollIntoView({ block: 'center' })
    else if (!target) {
      try {
        const saved = Number(sessionStorage.getItem(SCROLL_STORE))
        if (saved > 0) window.scrollTo(0, saved)
      } catch {
        /* 저장소 접근이 막혀도 목록은 열린다 */
      }
    }
    try { sessionStorage.removeItem(SCROLL_STORE) } catch { /* 저장소 접근이 막혀도 목록은 열린다 */ }
    didScroll.current = true
  }, [restored, data, target, visible])
  const selected = rows.filter((c) => picked.includes(c.id))
  const selectCandidate = (id: string, checked: boolean) =>
    setPicked((p) => checked ? [...p, id] : p.filter((x) => x !== id))
  const removeSelected = () => {
    const names = selected.map((c) => `${c.company} · ${c.title}`).join('\n')
    if (window.confirm(`선택한 공고 ${selected.length}건을 후보에서 제외할까요?\n\n${names}\n\n같은 공고는 다시 후보로 올리지 않으며, 기존 지원서류는 보존됩니다.`)) {
      remove.mutate(selected.map((c) => c.id))
    }
  }

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
      title={`채용 후보 ${rows.length}건`}
      sub="추천도는 검토 순서의 보조값입니다. 지원 자격과 근무 조건은 각 공고의 원문을 확인하세요."
      source={<code>jobfeed/candidates.json</code>}
      stats={[
        [rows.length, '전체 공고'],
        [new Set(rows.map((c) => c.company)).size, '회사'],
        [n((c) => c.days_left !== null && c.days_left >= 0 && c.days_left <= 7), '마감 D-7 이내'],
        [n((c) => c.total >= 80 && !c.experience_review_required && !c.experience_excluded), '적합도 80+'],
        [n((c) => !isDead(c) && c.experience_review_required), 'AI 경력 재검토'],
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

      <div className="toolbar mb-3 flex flex-wrap gap-3 p-3">
        <label className="w-full text-[12px] text-[var(--dim)]">
          회사·직무·공고 ID 검색
          <Input className="mt-1 min-h-11 text-[16px]" type="search" value={q} onChange={(e) => { setQ(e.target.value); setTarget(null) }} placeholder="회사, 직무 또는 공고 ID" />
        </label>
        <p className="m-0 w-full text-[12px] text-[var(--dim)]" role="status">표시 {visibleCount} / 전체 {rows.length}건</p>
        <Group label="정렬" value={sort} options={SORTS} onChange={(v) => setSort(v as SortKey)} />
        <Group label="평판" value={f.rep} options={[['all', '전체'], ['good', '괜찮음'], ['warn', '주의'], ['bad', '회피'], ['none', '정보 없음']]} onChange={(v) => setF({ ...f, rep: v as Filters['rep'] })} />
        <Group label="마감" value={f.due} options={[['all', '전체'], ['soon', 'D-7 이내'], ['dated', '마감일 있음'], ['always', '상시']]} onChange={(v) => setF({ ...f, due: v as Filters['due'] })} />
        <details className="w-full text-[13px]">
          <summary className="cursor-pointer text-[var(--link)] underline underline-offset-2">추가 필터</summary>
          <div className="mt-3 flex flex-wrap gap-3">
            <Group label="상태" value={f.st} options={[['all', '전체'], ['bookmark', '북마크'], ['prep', '지원자료 있음'], ['rejected', '탈락 이력'], ['domain', '하드웨어·제조']]} onChange={(v) => setF({ ...f, st: v as Filters['st'] })} />
            <Group label="적합도" value={String(f.min)} options={[['0', '전체'], ['70', '70점 이상'], ['80', '80점 이상']]} onChange={(v) => setF({ ...f, min: Number(v) as Filters['min'] })} />
            <Group label="통근" value={String(f.loc)} options={locOptions} onChange={(v) => setF({ ...f, loc: (v === 'all' ? 'all' : Number(v)) as Filters['loc'] })} />
          </div>
        </details>
      </div>
      {target && !visible && data && <div className="notice mb-3 p-3 text-[13px]" role="status">{targetExists ? <>돌아온 공고가 현재 검색·필터에 보이지 않습니다. <button className="page-link" onClick={() => { setF(ALL); setQ('') }}>검색·필터 초기화</button></> : '돌아온 공고가 현재 후보 목록에 없습니다.'}</div>}

      {remove.isError && (
        <Card className="mb-3 rounded-[9px] border-[var(--rail-bad)] bg-[var(--badbg)] px-[14px] py-[10px] text-[12.5px] leading-[1.5] text-[var(--bad)]" role="alert">
          선택한 {remove.variables?.length ?? selected.length}건의 후보 제외 요청에 문제가 생겼습니다: {remove.error instanceof ApiError ? remove.error.detail : String(remove.error)}. 선택은 남아 있습니다. 요청 접수 여부가 불분명할 수 있으므로 <button className="page-link" onClick={() => qc.invalidateQueries({ queryKey: ['candidates'] })}>후보 목록 새로고침</button>과 처리 상태를 확인한 뒤 필요한 항목만 다시 선택해 처리하세요.
        </Card>
      )}

      {(selected.length > 0 || busy) && <div className="action-bar surface mb-3 flex flex-wrap items-center gap-3 p-3 text-[13px]">
        <span aria-live="polite">{selected.length}건 선택</span>
        <Button variant="outline" size="sm" disabled={!selected.length || busy} onClick={() => setPicked([])}>
          선택 해제
        </Button>
        <Button className="ml-auto" variant="destructive" size="sm" disabled={!selected.length || busy} onClick={removeSelected}>
          {busy ? '처리 중…' : `${selected.length}건 후보에서 제외`}
        </Button>
      </div>}

      <div className="surface mb-3 divide-y divide-[var(--line)]">

        {isPending ? (
          [0, 1, 2, 3].map((i) => (
            <div key={i} className="border-b border-[var(--line)] px-[14px] py-[11px] last:border-b-0">
              <Skeleton className="h-9 w-full" />
            </div>
          ))
        ) : rows.length === 0 ? (
          <div className="empty-state">등록된 후보가 없습니다. 검토함에서 공고를 등록하면 여기에 표시됩니다.</div>
        ) : visibleCount === 0 ? (
          <div className="empty-state">조건에 맞는 공고가 없습니다.</div>
        ) : (
          live.map((c) => <Row key={c.id} c={c} app={data?.apps[c.id]} busy={busy} picked={picked.includes(c.id)} onSelect={selectCandidate} />)
        )}
      </div>

      {review.length > 0 && (
        <details open={!!target && review.some((c) => c.id === target)} className="mt-3.5 border-t border-[var(--line)]">
          <summary className="cursor-pointer py-[11px] text-[12px] text-[var(--dim)]">경력 재검토·제외 공고 <b>{review.length}</b>건</summary>
          <p className="mb-2 text-[12px] text-[var(--dim)]">7년 이상 조건의 기존 공고는 다음 스캔에서 AI가 다시 판정합니다. 기존 지원서류는 그대로 열 수 있습니다.</p>
          {review.map((c) => <Row key={c.id} c={c} app={data?.apps[c.id]} busy={busy} picked={picked.includes(c.id)} onSelect={selectCandidate} />)}
        </details>
      )}

      {dead.length > 0 && (
        <details open={!!target && dead.some((c) => c.id === target)} className="mt-3.5 border-t border-[var(--line)]">
          <summary className="cursor-pointer list-none py-[11px] text-[12px] text-[var(--dim)] hover:text-[var(--fg)]">
            마감 지났거나 내려간 공고 <b>{dead.length}</b>건
          </summary>
          <div className="surface divide-y divide-[var(--line)]">
            {dead.map((c) => (
              <Row key={c.id} c={c} app={data?.apps[c.id]} busy={busy} picked={picked.includes(c.id)} onSelect={selectCandidate} />
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
    <label className="flex min-w-0 flex-1 flex-col gap-1 text-[12px] text-[var(--dim)] sm:flex-none">
      {label}
      <select className="min-h-11 min-w-0 max-w-full rounded-xl border border-[var(--line)] bg-[var(--row)] px-3 text-[16px] text-[var(--fg)]" value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  )
}

// 주소 원문은 "○○시 ○○구 ○○로 17, D1동 16층"처럼 길다 — 앞 두 토막(시·구)만 보인다
const shortAddr = (a: string) => (a ? a.split(/[,(]/)[0].split(/\s+/).slice(0, 2).join(' ') : '')

const ZONE_CLS = (z: number) =>
  z <= 1 ? 'font-bold text-[var(--good)]' : z === 2 ? 'font-bold text-[var(--warn)]' : z <= 4 ? 'font-bold text-[var(--bad)]' : 'text-[var(--dim)]'

const REP_CLS: Record<string, string> = {
  good: 'text-[var(--good)]',
  warn: 'text-[var(--warn)]',
  bad: 'text-[var(--bad)]',
  none: '',
}

function Row({ c, app, busy, picked, onSelect }: {
  c: Candidate
  app?: { slug: string; n: number }
  busy: boolean
  picked: boolean
  onSelect: (id: string, checked: boolean) => void
}) {
  const dead = isDead(c)
  return (
    <article id={'candidate-' + c.id} className={'rail ' + RAIL[c.rep_key] + ' min-w-0 bg-[var(--row)] px-4 py-4 hover:bg-[var(--hov)] ' + (dead ? 'opacity-70' : '')}>
      <div className="flex min-w-0 items-start gap-3">
        <Checkbox checked={picked} disabled={busy} aria-label={c.company + ' ' + c.title + ' 선택'} onCheckedChange={(checked) => onSelect(c.id, checked)} />
        <div className="min-w-0 flex-1">
          <a href={c.url} target="_blank" rel="noopener" className="block text-[14px] font-semibold leading-snug break-words text-[var(--link)] hover:underline">{c.company} · {c.title}</a>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-[var(--dim)]">
            <span>{c.career || '경력 조건 미확인'}</span>
            <Due due={c.due} cls={c.due_cls} />
            <span>근무지 <strong className={ZONE_CLS(c.zone)}>{c.zone_label}</strong>{c.addr && ' · ' + shortAddr(c.addr)}</span>
          </div>
          <p className="mt-2 mb-0 text-[13px] leading-relaxed break-words">
            {c.experience_excluded ? '경력 검토 제외 · ' + (c.experience_reason || '사유 미기록') : c.experience_review_required ? '경력 조건 재검토 필요' : '필수 요건 원문 확인 필요'}
          </p>
          <p className="mt-1 mb-0 text-[13px] leading-relaxed break-words text-[var(--dim)]">등록 메모 · {c.rep_note || '기록 없음'}</p>
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-[var(--dim)]">
            <span>추천도 <strong className="tabular text-[var(--fg)]">{c.experience_review_required || c.experience_excluded ? '—' : Math.round(c.rec)}</strong> · #{c.rank ?? '-'}</span>
            <span>적합도 <strong className="tabular text-[var(--fg)]">{c.total}</strong></span>
            <span>평판 <strong className={REP_CLS[c.rep_key]}>{c.rep_label || '정보 없음'}</strong>{c.rep && ' · ' + c.rep[1] + ' / ' + (c.rep[2] ?? '표본 미확인') + '건'}</span>
            <span>초안 {app ? app.n + '종' : '없음'}</span>
          </div>
          {c.rep?.[4] && <p className="mt-1 mb-0 text-[12px] text-[var(--dim)]">평판 최근 흐름 · {c.rep[4]}</p>}
          {c.tags.filter((t) => TAGS[t]).map((t) => <Badge key={t} variant="secondary" className={'mr-1 mt-2 rounded px-2 text-[11px] ' + TAGS[t][1]}>{TAGS[t][0]}</Badge>)}
          <div className="mt-3 flex flex-wrap gap-3 text-[13px]">
            <Link href={'/applications/job/' + encodeURIComponent(c.id)} onClick={() => { try { sessionStorage.setItem(SCROLL_STORE, String(window.scrollY)) } catch { /* 저장소 없이 이동 */ } }} className="page-link">공고 상세·지원서류 보기 →</Link>
            <a href={jobplanetUrl(c.company)} target="_blank" rel="noopener" className="page-link">잡플래닛</a>
          </div>
          <details className="mt-3 border-t border-[var(--line)] pt-2 text-[12px] text-[var(--dim)]">
            <summary className="cursor-pointer text-[var(--link)] underline underline-offset-2">점수·평판 상세</summary>
            <div className="mt-3 flex flex-wrap gap-4">{c.scores.map((v, i) => <span key={i}>{AXES[i]} {v}</span>)}</div>
            {c.rep ? <p className="mt-2">평판 {c.rep[1]} · 표본 {c.rep[2] ?? '미확인'}건 · 별점 {c.rep[3]} · {c.rep[4]}</p> : <p className="mt-2">평판 정보 없음</p>}
          </details>
        </div>
      </div>
    </article>
  )
}
