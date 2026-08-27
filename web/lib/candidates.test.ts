import { expect, test } from 'vitest'

import type { Candidate } from './api'
import { ALL, applyFilters, isDead, scoreCells, sortRows } from './candidates'

const mk = (o: Partial<Candidate>): Candidate => ({
  id: '1', company: 'a', title: '', url: '', scores: [30, 18, 20, 16, 0], total: 84, tier: 't1',
  rep: null, rep_key: 'none', rep_label: '', rep_note: '', tags: [], addr: '', zone: 9, zone_label: '',
  due: '', due_cls: '', days_left: null, closed: false, rec: 80, rank: 1, ...o,
})

test('loc filter includes nearer zones', () => {
  expect(applyFilters([mk({ zone: 0 }), mk({ zone: 2 })], { ...ALL, loc: 1 }, true).length).toBe(1)
})

test('due soon', () => {
  const rows = [mk({ days_left: 3 }), mk({ days_left: 20 }), mk({ days_left: null })]
  expect(applyFilters(rows, { ...ALL, due: 'soon' }, true).length).toBe(1)
})

test('due dated keeps only rows with a date, always keeps only 상시', () => {
  const rows = [mk({ id: 'd', days_left: 20 }), mk({ id: 'a' }), mk({ id: 'c', closed: true })]
  expect(applyFilters(rows, { ...ALL, due: 'dated' }, true).map((r) => r.id)).toEqual(['d'])
  expect(applyFilters(rows, { ...ALL, due: 'always' }, true).map((r) => r.id)).toEqual(['a'])
})

test('due filter is skipped for the folded list', () => {
  expect(applyFilters([mk({ days_left: 20 })], { ...ALL, due: 'soon' }, false).length).toBe(1)
})

test('rep, tag and min filters', () => {
  const rows = [mk({ id: 'g', rep_key: 'good', tags: ['bookmark'], total: 84 }), mk({ id: 'b', rep_key: 'bad', total: 60 })]
  expect(applyFilters(rows, { ...ALL, rep: 'good' }, true).map((r) => r.id)).toEqual(['g'])
  expect(applyFilters(rows, { ...ALL, st: 'bookmark' }, true).map((r) => r.id)).toEqual(['g'])
  expect(applyFilters(rows, { ...ALL, min: 70 }, true).map((r) => r.id)).toEqual(['g'])
})

test('sort rep by verdict then sample', () => {
  const r = sortRows(
    [mk({ id: 'w', rep_key: 'warn', rep: ['warn', 3.8, 41, 4, ''] }), mk({ id: 'g', rep_key: 'good', rep: ['good', 3.3, 285, 3, ''] })],
    'rep',
  )
  expect(r.map((x) => x.id)).toEqual(['g', 'w'])
})

test('sort due puts null last', () => {
  expect(sortRows([mk({ id: 'n' }), mk({ id: 'd', days_left: 2 })], 'due').map((x) => x.id)).toEqual(['d', 'n'])
})

test('sort pos by company in Korean collation', () => {
  const r = sortRows([mk({ id: '2', company: '하늘' }), mk({ id: '1', company: '가람' })], 'pos')
  expect(r.map((x) => x.id)).toEqual(['1', '2'])
})

test('sort by axis descending, ties broken by total', () => {
  const rows = [
    mk({ id: 'lo', scores: [10, 0, 0, 0, 0] }),
    mk({ id: 'hi-b', scores: [30, 0, 0, 0, 0], total: 70 }),
    mk({ id: 'hi-a', scores: [30, 0, 0, 0, 0], total: 90 }),
  ]
  expect(sortRows(rows, 'stack').map((x) => x.id)).toEqual(['hi-a', 'hi-b', 'lo'])
})

test('sort does not mutate the input', () => {
  const rows = [mk({ id: 'a', rec: 1 }), mk({ id: 'b', rec: 9 })]
  sortRows(rows, 'rec')
  expect(rows.map((r) => r.id)).toEqual(['a', 'b'])
})

test('isDead covers closed and past due', () => {
  expect(isDead(mk({ closed: true }))).toBe(true)
  expect(isDead(mk({ days_left: -1 }))).toBe(true)
  expect(isDead(mk({ days_left: 0 }))).toBe(false)
  expect(isDead(mk({}))).toBe(false)
})

test('scoreCells marks hi/lo and renders a zero penalty as a dot', () => {
  expect(scoreCells([35, 15, 2, 20, 0])).toEqual([
    [35, 'hi'],
    [15, ''],
    [2, 'lo'],
    [20, 'hi'],
    ['·', ''],
  ])
  expect(scoreCells([0, 0, 0, 0, -5])[4]).toEqual([-5, 'pen'])
  // 경계: 85% 이상이 hi, 40% 이하가 lo
  expect(scoreCells([29.75, 10, 0, 0, 0]).slice(0, 2)).toEqual([[29.75, 'hi'], [10, 'lo']])
})
