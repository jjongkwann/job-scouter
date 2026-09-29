import { act, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { expect, test, vi } from 'vitest'

import type { Candidate, JobApplication } from '@/lib/api'
import JobApplicationPage from './page'

const replace = vi.hoisted(() => vi.fn())
vi.mock('next/navigation', () => ({ useRouter: () => ({ replace }) }))
vi.mock('@/components/application-files', () => ({ JobApplicationFiles: () => null }))

const candidate = {
  id: '383001', company: '테스트회사', title: '백엔드 개발자', url: 'https://example.com/job', src: 'wanted',
  scores: [30, 20, 20, 15, 0], total: 85, tier: 't1', rep: null, rep_key: 'none', rep_label: '정보 없음', rep_note: '',
  tags: [], addr: '', zone: 1, zone_label: '가까움', due: '상시', due_cls: 'always', days_left: null,
  closed: false, rec: 88, rank: 1, career: '5년', experience_review_required: false, experience_excluded: false, experience_reason: '',
} as Candidate
const folders = [
  { slug: 'first_383001', ids: ['383001'], files: [], docs: ['0_JD.md', '1_맞춤_이력서.md'], mtime: '2026-09-14' },
  { slug: 'second_383001', ids: ['383001'], files: [], docs: ['0_JD.md', '1_맞춤_이력서.md'], mtime: '2026-09-14' },
]

test('같은 날 두 폴더를 구별하고 선택한 맞춤 이력서와 문서 위치를 전환 후에도 유지한다', async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  const scroll = vi.fn()
  Element.prototype.scrollIntoView = scroll
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  for (const [index, folder] of folders.entries()) {
    const data: JobApplication = {
      candidate, folder, folders, others: [], drafting: false,
      docs: { '0_JD.md': `공고 ${index}`, '1_맞춤_이력서.md': `맞춤 이력서 ${index}` },
    }
    client.setQueryData(['application-job', '383001', folder.slug], data)
  }
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  const params = Promise.resolve({ cid: '383001' })
  const render = async (folder: string, doc = '1_맞춤_이력서.md') => {
    const searchParams = Promise.resolve({ folder, doc })
    await act(async () => root.render(
      <QueryClientProvider client={client}><Suspense fallback="로딩"><JobApplicationPage params={params} searchParams={searchParams} /></Suspense></QueryClientProvider>,
    ))
  }
  try {
    await render(folders[0].slug)
    expect(host.textContent).toContain('first_383001 · 2026-09-14')
    expect(host.textContent).toContain('second_383001 · 2026-09-14')
    expect(host.querySelector('[role="tab"][aria-selected="true"]')?.textContent).toBe('맞춤 이력서')
    expect(host.textContent).toContain('맞춤 이력서 0')
    await render(folders[1].slug)
    expect(host.querySelector('[role="tab"][aria-selected="true"]')?.textContent).toBe('맞춤 이력서')
    expect(host.textContent).toContain('맞춤 이력서 1')
    expect(host.textContent).not.toContain('맞춤 이력서 0')
    expect(scroll).toHaveBeenCalled()
    await act(async () => [...host.querySelectorAll<HTMLElement>('[aria-label^="폴더 "]')].find((el) => el.getAttribute('aria-label') === '폴더 first_383001')!.click())
    expect(replace).toHaveBeenCalledWith('/applications/job/383001?folder=first_383001&doc=1_%EB%A7%9E%EC%B6%A4_%EC%9D%B4%EB%A0%A5%EC%84%9C.md', { scroll: false })
    client.setQueryData(['application-job', '383001', 'missing'], client.getQueryData(['application-job', '383001', folders[0].slug]))
    await render('missing')
    expect(host.querySelector('[aria-label="폴더 first_383001"]')?.getAttribute('aria-pressed')).toBe('true')
  } finally {
    await act(async () => root.unmount())
    host.remove()
    client.clear()
    replace.mockClear()
  }
})
