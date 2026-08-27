// 후보목록의 필터·정렬 — 데이터 repo template.html의 apply()·render() 규칙 그대로 옮긴 순수 함수.
// 서버(candidates.py)가 rec·rank·zone·days_left를 이미 계산해 주므로 여기서는 거르고 줄만 세운다.
import type { Candidate, Rail } from './api'

export const MAX = [35, 25, 20, 20] // 스택/도메인/레벨/역할 배점 상한 — candidates.py MAX와 같은 값
export const AXES = ['스택', '도메인', '레벨', '역할', '감점']

export type Filters = {
  rep: 'all' | Rail
  st: 'all' | 'bookmark' | 'prep' | 'rejected' | 'domain'
  min: 0 | 70 | 80
  due: 'all' | 'soon' | 'dated' | 'always'
  loc: 'all' | 0 | 1 | 2 | 3
}
export type SortKey = 'rec' | 'total' | 'stack' | 'domain' | 'level' | 'role' | 'penalty' | 'rep' | 'due' | 'loc' | 'pos'

export const ALL: Filters = { rep: 'all', st: 'all', min: 0, due: 'all', loc: 'all' }

// 마감이 지났거나 내려간 공고 — 목록에서 빼고 접힌 섹션으로 보낸다
export const isDead = (c: Candidate) => c.closed || (c.days_left !== null && c.days_left < 0)

// 정렬용 남은 일수. 상시·마감됨은 뒤로 보내려고 큰 수를 준다 (template.html dleft 그대로)
const dleft = (c: Candidate) => (c.closed ? 1e6 : (c.days_left ?? 9e5))

export function applyFilters(rows: Candidate[], f: Filters, dueFilter: boolean): Candidate[] {
  return rows.filter((c) => {
    if (f.rep !== 'all' && c.rep_key !== f.rep) return false
    if (f.st !== 'all' && !c.tags.includes(f.st)) return false
    if (f.loc !== 'all' && c.zone > f.loc) return false // "40분대"면 더 가까운 밴드도 포함해야 한다
    if (c.total < f.min) return false
    // 접힌 목록에는 마감 필터를 걸지 않는다 — 거기선 전부 지난 공고라 뜻이 없다
    if (!dueFilter || f.due === 'all') return true
    const d = c.days_left
    if (f.due === 'soon') return d !== null && d >= 0 && d <= 7
    if (f.due === 'dated') return d !== null && d >= 0
    return d === null && !c.closed // always
  })
}

// 평판 정렬은 총점이 아니라 **판정**으로 한다. 총점은 과거가 만든 값이라 총점순으로 세우면
// ✅3.3/285건이 ⚠️3.8/41건보다 아래로 간다. 같은 판정이면 표본이 두꺼운 쪽을 위로.
const REP_ORDER: Record<Rail, number> = { good: 0, warn: 1, none: 2, bad: 3 }
const REP_CONF = 40
const repConf = (c: Candidate) => (c.rep ? Math.min((c.rep[2] ?? 0) / REP_CONF, 1) : 0)
const repVal = (c: Candidate) => (c.rep ? c.rep[1] : -1)

const KEYS: SortKey[] = ['stack', 'domain', 'level', 'role', 'penalty']

export function sortRows(rows: Candidate[], key: SortKey): Candidate[] {
  const i = KEYS.indexOf(key)
  return [...rows].sort((a, b) =>
    key === 'pos'
      ? a.company.localeCompare(b.company, 'ko')
      : key === 'rep'
        ? REP_ORDER[a.rep_key] - REP_ORDER[b.rep_key] || repConf(b) - repConf(a) || repVal(b) - repVal(a)
        : key === 'rec'
          ? b.rec - a.rec
          : key === 'due'
            ? dleft(a) - dleft(b) || b.total - a.total // 임박한 것부터, 상시는 뒤로
            : key === 'loc'
              ? a.zone - b.zone || b.total - a.total // 가까운 곳부터
              : i >= 0
                ? (b.scores[i] ?? 0) - (a.scores[i] ?? 0) || b.total - a.total
                : b.total - a.total,
  )
}

export type Cell = [number | string, '' | 'hi' | 'lo' | 'pen']

// 대시보드는 서버가 cells를 주지만 후보목록은 점수만 온다 — api.py와 같은 규칙으로 만든다.
// 감점은 0이 좋은 값이라 hi/lo 규칙이 반대다: 0은 표시하지 않고, 깎인 만큼 붉게.
export function scoreCells(scores: number[]): Cell[] {
  const cells: Cell[] = MAX.map((m, i) => {
    const v = scores[i] ?? 0
    return [v, v / m >= 0.85 ? 'hi' : v / m <= 0.4 ? 'lo' : '']
  })
  const p = scores[4] ?? 0
  cells.push([p || '·', p ? 'pen' : ''])
  return cells
}
