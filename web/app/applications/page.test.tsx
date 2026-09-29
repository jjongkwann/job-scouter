import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { expect, test } from 'vitest'

import type { Applications, Candidate } from '@/lib/api'
import ApplicationsPage from './page'

const candidate = {
  id: 'wanted_123', company: '가온테크', title: '백엔드 개발자', rec: 82,
  rank: 2, due: '상시', due_cls: 'always', rep_key: 'none', closed: false,
} as Candidate

test('공고별 초안은 회사·직무·ID·폴더명으로 검색하고 연결 여부별 결과 수를 보인다', async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  const catalogue: Applications = {
    stats: { candidates: 2, folders: 3, linked: 2, gone: 1, unlinked: 0 },
    linked: [
      { slug: 'ga_123', ids: ['wanted_123'], files: [], docs: ['0_JD.md'], mtime: '2026-09-29', c: candidate, others: 0 },
      { slug: 'na_456', ids: ['j456'], files: [], docs: ['0_JD.md'], mtime: '2026-09-28', c: { ...candidate, id: 'j456', company: '나래랩', title: '데이터 엔지니어' }, others: 0 },
    ],
    orphans: [{ slug: 'saved_789', ids: ['wanted_789'], files: ['0_JD.md'], docs: ['0_JD.md'], mtime: '2026-09-27', why: '현재 후보 없음', badge: '공고 내려감', cls: 'warn' }],
  }
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  client.setQueryData(['applications'], catalogue)
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  try {
    await act(async () => root.render(<QueryClientProvider client={client}><ApplicationsPage /></QueryClientProvider>))
    const input = host.querySelector<HTMLInputElement>('#applications-search')!
    const search = async (value: string) => act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value)
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await search('나래')
    expect(host.textContent).toContain('연결 1 / 2폴더 · 미연결 0 / 1폴더')
    expect(host.querySelector('a[href*="ga_123"]')).toBeNull()
    expect(host.querySelector('a[href*="na_456"]')).not.toBeNull()
    await search('wanted_789')
    expect(host.querySelector('a[href*="saved_789"]')).not.toBeNull()
    expect(host.textContent).toContain('확인된 공고 ID가 현재 후보목록에 없습니다.')
    expect(host.textContent).not.toContain('공고 내려감')
    await search('없는 공고')
    expect(host.textContent).toContain('연결 0 / 2폴더 · 미연결 0 / 1폴더')
    await search('')
    expect(host.querySelector('a[href*="ga_123"]')).not.toBeNull()
  } finally {
    await act(async () => root.unmount())
    host.remove()
    client.clear()
  }
})
