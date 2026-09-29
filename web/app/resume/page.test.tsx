import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { expect, test, vi } from 'vitest'
import type { Resume } from '@/lib/api'
import ResumePage from './page'

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }))

test('진행 중 대화와 갱신 제안이 긴 이력서 본문보다 먼저 나온다', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  const qc = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } })
  const resume: Resume = { markdown: '# 긴 원본\n\n' + '경력 내용.\n\n'.repeat(100), pending: 2,
    chats: [{ sid: 'chat-1', target: '이력서.md', n: 3 }] }
  qc.setQueryData(['resume'], resume)
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  try {
    await act(async () => root.render(<QueryClientProvider client={qc}><ResumePage /></QueryClientProvider>))
    const chatHeading = [...host.querySelectorAll('h3')].find((h) => h.textContent === '진행 중 대화')!
    const bodyHeading = [...host.querySelectorAll('h2')].find((h) => h.textContent === '긴 원본')!
    expect(chatHeading.compareDocumentPosition(bodyHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(host.querySelector('a[href="/resume/chat/chat-1?key=%EC%9D%B4%EB%A0%A5%EC%84%9C.md"]')).not.toBeNull()
    expect(host.querySelector('a[href="/resume/proposals"]')?.textContent).toContain('갱신 제안 보기')
    expect(host.textContent).toContain('2 건 대기')
  } finally {
    await act(async () => root.unmount())
    host.remove()
    qc.clear()
    vi.unstubAllGlobals()
  }
})
