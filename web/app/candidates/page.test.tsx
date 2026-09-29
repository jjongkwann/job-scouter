import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { expect, test, vi } from 'vitest'

import * as api from '@/lib/api'
import CandidatesPage from './page'

test('saved filters remain after detail return and the requested candidate can be found', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  const values = new Map<string, string>()
  const storage = { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => values.set(key, value), removeItem: (key: string) => values.delete(key) }
  vi.stubGlobal('localStorage', storage)
  vi.stubGlobal('sessionStorage', storage)
  vi.stubGlobal('confirm', vi.fn(() => true))
  const scroll = vi.fn()
  Element.prototype.scrollIntoView = scroll
  window.history.replaceState({}, '', '/candidates?candidate=c1')
  localStorage.setItem('candidates-view', JSON.stringify({ f: { rep: 'bad' }, sort: 'due' }))
  const candidate: api.Candidate = {
    id: 'c1', company: '테스트회사', title: 'AI 개발자', url: 'https://example.com/job', src: 'wanted',
    scores: [30, 20, 20, 15, 0], total: 85, tier: 't1', rep: null, rep_key: 'none', rep_label: '정보 없음', rep_note: '업무 경험 적합',
    tags: [], addr: '', zone: 1, zone_label: '가까움', due: '상시', due_cls: 'always', days_left: null,
    closed: false, rec: 88, rank: 1, career: '5년', experience_review_required: false, experience_excluded: false, experience_reason: '',
  }
  const candidates: api.Candidates = { rows: [candidate, { ...candidate, id: 'c2', title: '데이터 엔지니어' }], apps: {}, errors: [], updated: '' }
  const dashboard: api.Dashboard = { groups: [], review_pending: [], unresearched: [], runs: [], runs_error: null, publish: null,
    stats: { pending: 0, postings: 0, fit75: 0, gone: 0, unresearched: 0 } }
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  qc.setQueryData(['candidates'], candidates)
  qc.setQueryData(['dashboard'], dashboard)
  vi.spyOn(api, 'get').mockImplementation(async (path) => path === '/candidates' ? candidates : dashboard)
  const publish = vi.spyOn(api, 'post').mockResolvedValue({ workflow_id: 'publish-1' })
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  try {
    await act(async () => root.render(<QueryClientProvider client={qc}><CandidatesPage /></QueryClientProvider>))
    expect(host.textContent).toContain('돌아온 공고가 현재 필터에 보이지 않습니다')
    expect([...host.querySelectorAll('select')].find((s) => s.value === 'bad')).toBeDefined()
    await act(async () => (host.querySelector('button.page-link') as HTMLButtonElement).click())
    expect(host.querySelector('#candidate-c1')).not.toBeNull()
    expect(host.textContent).toContain('등록 메모 · 업무 경험 적합')
    expect(scroll).toHaveBeenCalled()
    const checkboxes = host.querySelectorAll<HTMLElement>('[role="checkbox"][aria-label$=" 선택"]')
    await act(async () => { checkboxes[0].click(); checkboxes[1].click() })
    const exclude = [...host.querySelectorAll('button')].find((b) => b.textContent === '2건 후보에서 제외')!
    await act(async () => exclude.click())
    expect(publish).toHaveBeenCalledWith('/publish', { ids: [], rejects: [
      { id: 'c1', why: '후보목록에서 삭제' }, { id: 'c2', why: '후보목록에서 삭제' },
    ] })
  } finally {
    await act(async () => root.unmount())
    host.remove()
    qc.clear()
    window.history.replaceState({}, '', '/')
    localStorage.removeItem('candidates-view')
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  }
})
