import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { expect, test, vi } from 'vitest'
import * as api from '@/lib/api'
import ResumeHistoryPage from './page'

vi.mock('next/navigation', () => ({ useSearchParams: () => new URLSearchParams(window.location.search) }))

test('선택한 변경분 아래에서만 복원할 수 있고 요청 오류가 남는다', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  const sha = 'a123456'
  const key = '이력서.md'
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  qc.setQueryData(['resume-history', key], { key, commits: [
    { sha, date: '2026-09-29', subject: '첫 변경' },
    { sha: 'b123456', date: '2026-09-28', subject: '이전 변경' },
  ] } satisfies api.History)
  qc.setQueryData(['resume-diff', key, sha], { sha, diff: '-이전 문장\n+새 문장' } satisfies api.Diff)
  const post = vi.spyOn(api, 'post').mockRejectedValue(new Error('연결 실패'))
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  try {
    window.history.replaceState({}, '', '/resume/history')
    await act(async () => root.render(<QueryClientProvider client={qc}><ResumeHistoryPage /></QueryClientProvider>))
    expect(host.querySelectorAll('button')).toHaveLength(0)

    window.history.replaceState({}, '', `/resume/history?sha=${sha}`)
    await act(async () => root.render(<QueryClientProvider client={qc}><ResumeHistoryPage /></QueryClientProvider>))
    expect(host.querySelectorAll('a[aria-current="true"]')).toHaveLength(1)
    expect(host.querySelectorAll('button')).toHaveLength(1)
    expect(host.querySelector('#selected-change')?.textContent).toContain('현재 이력서와의 전체 차이는 아닙니다')
    expect(document.activeElement?.textContent).toContain('첫 변경')
    const restore = host.querySelector('button')!
    await act(async () => {
      restore.click()
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
    expect(post).toHaveBeenCalledWith('/resume/revert', { key, sha })
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('연결 실패')
    expect(host.querySelector('a[aria-current="true"]')).not.toBeNull()
    expect(host.querySelector('#selected-change')).not.toBeNull()
  } finally {
    await act(async () => root.unmount())
    host.remove()
    qc.clear()
    window.history.replaceState({}, '', '/')
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  }
})


test('최근 목록 밖 버전의 직접 링크도 열고 실제 복원 대상을 표시한다', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  const key = 'factbase'
  const sha = 'c123456'
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  qc.setQueryData(['resume-history', key], { key, commits: [] } satisfies api.History)
  qc.setQueryData(['resume-diff', key, sha], { sha, diff: '-옛 사실\n+확인된 사실' } satisfies api.Diff)
  const host = document.createElement('div')
  const root = createRoot(host)
  try {
    window.history.replaceState({}, '', `/resume/history?key=${key}&sha=${sha}`)
    await act(async () => root.render(<QueryClientProvider client={qc}><ResumeHistoryPage /></QueryClientProvider>))
    const selected = host.querySelector('#selected-change')!
    expect(selected.textContent).toContain('직접 선택한 버전')
    expect(selected.textContent).toContain('factbase 문서 원본')
    expect(selected.textContent).not.toContain('공통 이력서 원본')
    expect(selected.querySelectorAll('button')).toHaveLength(1)
  } finally {
    await act(async () => root.unmount())
    qc.clear()
    window.history.replaceState({}, '', '/')
    vi.unstubAllGlobals()
  }
})
