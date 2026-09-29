import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { expect, test } from 'vitest'
import ApplicationFilesPage from './page'
import { JobApplicationFiles, type ApplicationFileCatalogue } from '@/components/application-files'

const pack = {
  id: '123', ids: ['123', 'remember_456'], company: '테스트회사', title: 'AI 개발자',
  source_urls: ['https://example.com/job'], review_notes: '공고별 검토', limitations: '개인 프로젝트', pages: 9,
  files: [{ name: '이력서.pdf', url: '/api/application-files/files/jobs/test/이력서.pdf', size: 1024, format: 'pdf' as const, kind: 'resume' as const },
    { name: '포트폴리오.pptx', url: '/api/application-files/files/jobs/test/포트폴리오.pptx', size: 2048, format: 'pptx' as const, kind: 'portfolio' as const }],
  bundle: { name: '지원서류.zip', url: '/api/application-files/files/jobs/test/지원서류.zip', size: 3000 },
  slide: { url: '/slides/s/portfolio-123', pages: 7 },
}
const catalogue: ApplicationFileCatalogue = {
  items: [{ ...pack, id: 'base', ids: [], company: '기본본', title: '공통 이력서', review_notes: '', limitations: '' }, pack],
  bundle: { name: '전체.zip', url: '/api/application-files/files/전체.zip', size: 5000 },
  stats: { jobs: 1, postings: 2, documents: 4 },
}

test('제출용 파일 목록은 기본본과 다운로드를 표시하고 중복 사이트 ID로 검색한다', async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  client.setQueryData(['application-files'], catalogue)
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  try {
    await act(async () => root.render(<QueryClientProvider client={client}><ApplicationFilesPage /></QueryClientProvider>))
    expect(host.textContent).toContain('기본 이력서·포트폴리오')
    expect(host.textContent).toContain('같은 채용의 공고 2건 연결')
    expect(host.textContent).toContain('실제 지원 여부는 기록되어 있지 않습니다')
    expect(host.querySelectorAll('a[href="https://example.com/job"]')).toHaveLength(2)
    expect(host.querySelector('a[href$="이력서.pdf"]')?.getAttribute('target')).toBe('_blank')
    expect(host.querySelector('a[href$="전체.zip"]')).not.toBeNull()
    expect(host.querySelector('a[href="/slides/s/portfolio-123"]')?.getAttribute('target')).toBe('_blank')
    const input = host.querySelector('input')!
    for (const [value, expected] of [['remember_456', '1 / 1세트'], ['없는 회사', '0 / 1세트']]) {
      await act(async () => {
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value)
        input.dispatchEvent(new Event('input', { bubbles: true }))
      })
      expect(host.textContent).toContain(expected)
    }
    expect(host.textContent).toContain('검색 결과가 없습니다.')
  } finally {
    await act(async () => root.unmount())
    client.clear()
    host.remove()
  }
})

test('중복 사이트의 공고 상세에서도 같은 제출용 파일을 연다', async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  client.setQueryData(['application-files'], catalogue)
  const host = document.createElement('div')
  const root = createRoot(host)
  try {
    await act(async () => root.render(<QueryClientProvider client={client}><JobApplicationFiles cid="remember_456" /></QueryClientProvider>))
    expect(host.querySelectorAll('h2')).toHaveLength(1)
    expect(host.querySelector('a[href$="이력서.pdf"]')).not.toBeNull()
    expect(host.querySelector('a[href="/slides/s/portfolio-123"]')).not.toBeNull()
    expect(host.textContent).toContain('테스트회사')
  } finally {
    await act(async () => root.unmount())
    client.clear()
  }
})
