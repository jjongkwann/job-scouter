import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { expect, it } from 'vitest'
import OffersPage from './page'

it('답변 대기와 이력을 구분하고 조사 요청을 복사할 수 없으면 선택할 텍스트를 보여준다', async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } })
  const item = { id: '1', company: '대기회사', title: '백엔드', job_id: '123', received_at: '2026-09-21T12:00:00',
    status: '지원 제안 받음', status_code: 'OFFER', expires_at: '2999-01-01', offer_type: 'APPLY', offer_mode: 'AUTO',
    active: true, state: 'unassessed', rail: 'none', reason: '', url: 'https://www.wanted.co.kr/status/proposal?kind=OFFER',
    job_url: 'https://www.wanted.co.kr/wd/123', assessment: null, listed_scores: null, review: '', report_name: '', message: '제안 원문' }
  client.setQueryData(['offers'], { collected_at: '2026-09-22', items: [item, { ...item, id: '2', company: '이력회사', active: false, status: '기간 만료' }] })
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  try {
    await act(async () => root.render(<QueryClientProvider client={client}><OffersPage /></QueryClientProvider>))
    expect(host.querySelectorAll('h2')).toHaveLength(1)
    expect(host.querySelector('h2')?.textContent).toContain('대기회사')
    const button = [...host.querySelectorAll('button')].find((b) => b.textContent === '평가·조사 요청 복사')!
    await act(async () => button.click())
    expect(host.querySelector('textarea')?.value).toContain('https://www.wanted.co.kr/wd/123')
    const select = host.querySelector('select')!
    await act(async () => { select.value = 'history'; select.dispatchEvent(new Event('change', { bubbles: true })) })
    expect(host.querySelectorAll('h2')).toHaveLength(1)
    expect(host.querySelector('h2')?.textContent).toContain('이력회사')
    await act(async () => { select.value = 'all'; select.dispatchEvent(new Event('change', { bubbles: true })) })
    expect(host.querySelectorAll('h2')).toHaveLength(2)
  } finally {
    await act(async () => root.unmount())
    client.clear()
    host.remove()
  }
})
