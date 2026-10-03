import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { expect, test, vi } from 'vitest'

import * as api from '@/lib/api'
import Home from './page'

test.each(['jumpit', 'linkedin'])('grouped postings retain %s links and independent publish decisions', async (secondSource) => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  const secondId = secondSource === 'jumpit' ? 'j2' : 'linkedin_2'
  const postings = ['wanted', secondSource].map((src, i): api.Proposal => ({
    id: i ? secondId : '1', company: '테스트회사', title: 'AI 개발자', src,
    url: `https://example.com/${src}`, scores: [30, 20, 20, 15, 0], total: 85,
    reason: `${src} 판정`, quotes: [], confidence: 0.9, rubric_version: 'v2', judged_at: '',
    cells: [[30, 'hi'], [20, ''], [20, 'hi'], [15, ''], ['·', '']], tier: 't1', rail: 'none',
    due: '상시', due_cls: '', busy: false,
    career: '5~6년', experience_review_required: false,
  }))
  const dashboard: api.Dashboard = {
    groups: [{ id: '1', company: '테스트회사', title: 'AI 개발자', postings }],
    stats: { pending: 1, postings: 2, fit75: 1, gone: 0, unresearched: 1 },
    review_pending: [], unresearched: [], runs: [], runs_error: null, publish: null,
  }
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  qc.setQueryData(['dashboard'], dashboard)
  vi.spyOn(api, 'get').mockResolvedValue(dashboard)
  const publish = vi.spyOn(api, 'post').mockRejectedValueOnce(new api.ApiError(503, '접수 응답 실패')).mockResolvedValue({ workflow_id: 'publish-1' })
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  try {
    await act(async () => root.render(<QueryClientProvider client={qc}><Home /></QueryClientProvider>))
    expect(host.querySelectorAll('section')).toHaveLength(1)
    expect(host.textContent).toContain('같은 공고 2개 사이트')
    expect(host.querySelector('a[href="https://example.com/wanted"]')).not.toBeNull()
    expect(host.querySelector(`a[href="https://example.com/${secondSource}"]`)).not.toBeNull()
    expect(host.textContent).toContain('wanted 판정')
    expect(host.textContent).toContain(`${secondSource} 판정`)
    expect(host.textContent).toContain(secondSource === 'linkedin' ? '링크드인' : '점핏')
    const approve = host.querySelectorAll<HTMLButtonElement>('button[aria-label$=" 후보 등록"]')
    const reject = host.querySelectorAll<HTMLButtonElement>('button[aria-label$=" 후보에서 제외"]')
    await act(async () => approve[1].click())
    expect(approve[0].getAttribute('aria-pressed')).toBe('false')
    expect(approve[1].getAttribute('aria-pressed')).toBe('true')
    await act(async () => reject[0].click())
    const submit = [...host.querySelectorAll('button')].find((b) => b.textContent === '2건 선택 처리')!
    await act(async () => { submit.click(); await new Promise((resolve) => setTimeout(resolve, 0)) })
    expect(publish).toHaveBeenCalledWith('/publish', { ids: [secondId], rejects: [{ id: '1', why: '적합도 낮음' }] })
    expect(publish).toHaveBeenCalledTimes(1)
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('접수 응답 실패')
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('요청 접수 여부가 불분명')
    expect(host.textContent).toContain('2건 선택')
    expect(reject[0].getAttribute('aria-pressed')).toBe('true')
    await act(async () => {
      qc.setQueryData(['dashboard'], { ...dashboard, publish: {
        id: 'publish-1', status: 'FAILED', start: '2026-09-29 12:00', ids: [secondId], reject_ids: ['1'], error: '초안 생성 실패',
      } })
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
    expect(host.textContent).toContain('마지막 후보 처리 실패')
    expect(host.textContent).toContain('선택 처리 요청에 문제가 생겼습니다')
  } finally {
    await act(async () => root.unmount())
    host.remove()
    qc.clear()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  }
})
