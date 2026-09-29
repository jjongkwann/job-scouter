import { act, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { expect, test, vi } from 'vitest'

import type { SlugApplication } from '@/lib/api'
import SlugApplicationPage from './page'

vi.mock('next/navigation', () => ({ useRouter: () => ({ replace: vi.fn() }) }))

test('미연결 문서는 공고 링크가 이미 있어도 링크 추가를 해결책으로 안내하지 않는다', async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  const slug = 'saved_342471'
  const data: SlugApplication = {
    folder: { slug, ids: ['342471'], files: ['0_JD.md'], docs: ['0_JD.md'], mtime: '2026-09-14' },
    docs: { '0_JD.md': '공고 원문 https://example.com/job/342471' }, linked_cid: null,
  }
  client.setQueryData(['application-slug', slug], data)
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  try {
    await act(async () => root.render(
      <QueryClientProvider client={client}><Suspense fallback="로딩"><SlugApplicationPage params={Promise.resolve({ slug })} /></Suspense></QueryClientProvider>,
    ))
    expect(host.textContent).toContain('공고 ID 342471가 현재 후보목록에 없어 연결되지 않았습니다')
    expect(host.textContent).not.toContain('공고 원문 링크를 적으면')
    expect(host.textContent).toContain('공고 원문')
  } finally {
    await act(async () => root.unmount())
    host.remove()
    client.clear()
  }
})
