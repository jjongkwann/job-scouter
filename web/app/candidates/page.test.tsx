import { act, StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { expect, test, vi } from 'vitest'

import * as api from '@/lib/api'
import CandidatesPage from './page'

test('StrictMode에서도 상세 복귀 후 검색·정렬·필터를 유지하고 요청 실패 시 선택을 보존한다', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  const values = new Map<string, string>()
  const storage = { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => values.set(key, value), removeItem: (key: string) => values.delete(key) }
  vi.stubGlobal('localStorage', storage)
  vi.stubGlobal('sessionStorage', storage)
  vi.stubGlobal('confirm', vi.fn(() => true))
  const scroll = vi.fn()
  Element.prototype.scrollIntoView = scroll
  window.history.replaceState({}, '', '/candidates?candidate=c1')
  localStorage.setItem('candidates-view', JSON.stringify({ f: { rep: 'bad' }, sort: 'due', q: '데이터' }))
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
  const publish = vi.spyOn(api, 'post').mockRejectedValueOnce(new api.ApiError(503, '일시적 오류')).mockResolvedValue({ workflow_id: 'publish-1' })
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  try {
    await act(async () => root.render(<StrictMode><QueryClientProvider client={qc}><CandidatesPage /></QueryClientProvider></StrictMode>))
    expect(host.textContent).toContain('돌아온 공고가 현재 검색·필터에 보이지 않습니다')
    expect([...host.querySelectorAll('select')].find((s) => s.value === 'bad')).toBeDefined()
    expect(host.querySelector<HTMLInputElement>('input[type="search"]')?.value).toBe('데이터')
    await act(async () => (host.querySelector('button.page-link') as HTMLButtonElement).click())
    let search = host.querySelector<HTMLInputElement>('input[type="search"]')!
    expect(search.value).toBe('')
    expect(host.querySelector('#candidate-c1')).not.toBeNull()
    expect(host.textContent).toContain('등록 메모 · 업무 경험 적합')
    const row = host.querySelector('#candidate-c1')!
    const toggle = row.querySelector<HTMLButtonElement>('button[aria-controls="candidate-info-c1"]')!
    const info = row.querySelector<HTMLElement>('#candidate-info-c1')!
    expect(info.hidden).toBe(true)
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    expect(row.querySelector('a')?.getAttribute('href')).toBe('/applications/job/c1')
    expect(info.textContent).toContain('등록 메모 · 업무 경험 적합')
    expect(info.querySelector('a[target="_blank"]')?.getAttribute('href')).toBe(candidate.url)
    expect(host.textContent).not.toContain('필수 요건 원문 확인 필요')
    await act(async () => toggle.click())
    expect(info.hidden).toBe(false)
    expect(toggle.getAttribute('aria-expanded')).toBe('true')
    expect(row.querySelector('[role="checkbox"]')?.getAttribute('aria-checked')).toBe('false')
    expect(host.querySelector<HTMLElement>('#candidate-info-c2')?.hidden).toBe(true)
    await act(async () => toggle.click())
    expect(info.hidden).toBe(true)
    expect(scroll).toHaveBeenCalled()
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(search, '테스트회사')
      search.dispatchEvent(new Event('input', { bubbles: true }))
    })
    expect(host.textContent).toContain('표시 2 / 전체 2건')
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(search, 'c2')
      search.dispatchEvent(new Event('input', { bubbles: true }))
    })
    expect(host.textContent).toContain('표시 1 / 전체 2건')
    expect(host.querySelector('#candidate-c1')).toBeNull()
    expect(host.querySelector('#candidate-c2')).not.toBeNull()
    expect(JSON.parse(localStorage.getItem('candidates-view')!).q).toBe('c2')
    // 상세 화면으로 떠났다가 돌아오는 마운트 과정을 재현한다.
    await act(async () => root.render(null))
    await act(async () => root.render(<StrictMode><QueryClientProvider client={qc}><CandidatesPage /></QueryClientProvider></StrictMode>))
    search = host.querySelector<HTMLInputElement>('input[type="search"]')!
    expect(search.value).toBe('c2')
    expect([...host.querySelectorAll('select')].find((s) => s.value === 'due')).toBeDefined()
    expect(host.textContent).toContain('표시 1 / 전체 2건')
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(search, '')
      search.dispatchEvent(new Event('input', { bubbles: true }))
    })
    const checkboxes = host.querySelectorAll<HTMLElement>('[role="checkbox"][aria-label$=" 선택"]')
    await act(async () => { checkboxes[0].click(); checkboxes[1].click() })
    const exclude = [...host.querySelectorAll('button')].find((b) => b.textContent === '2건 후보에서 제외')!
    await act(async () => { exclude.click(); await new Promise((resolve) => setTimeout(resolve, 0)) })
    expect(publish).toHaveBeenCalledWith('/publish', { ids: [], rejects: [
      { id: 'c1', why: '후보목록에서 삭제' }, { id: 'c2', why: '후보목록에서 삭제' },
    ] })
    expect(publish).toHaveBeenCalledTimes(1)
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('일시적 오류')
    expect(host.textContent).toContain('2건 선택')
    expect(host.textContent).toContain('후보 목록 새로고침')
    // 접힌 보관 목록에서도 상태 경고는 행 요약에, 긴 사유는 검토 정보에 남는다.
    await act(async () => {
      qc.setQueryData(['candidates'], {
        ...candidates,
        rows: [
          { ...candidate, experience_excluded: true, experience_reason: '필수 경력 부족', rep_key: 'bad', rep_label: '회피' },
          { ...candidate, id: 'c2', title: '데이터 엔지니어', closed: true },
          { ...candidate, id: 'c3', experience_review_required: true },
        ],
      })
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
    const excluded = host.querySelector('#candidate-c1')!
    const summary = excluded.firstElementChild!
    expect(summary.textContent).toContain('경력 검토 제외')
    expect(summary.textContent).toContain('회피')
    expect(summary.textContent).not.toContain('필수 경력 부족')
    expect(excluded.querySelector<HTMLElement>('#candidate-info-c1')?.hidden).toBe(true)
    expect(excluded.textContent).toContain('필수 경력 부족')
    expect(host.querySelector('#candidate-c2')?.firstElementChild?.textContent).toContain('공고 마감')
    expect(host.querySelector('#candidate-c3')?.firstElementChild?.textContent).toContain('경력 재검토')
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
