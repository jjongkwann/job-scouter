import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { Nav, SectionNav } from './nav'
import { Page } from './page'

let pathname = '/applications/files'
vi.mock('next/navigation', () => ({ usePathname: () => pathname }))

it('기존 상세 경로를 업무 영역에 연결하고 보조 메뉴를 구별한다', async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  const host = document.createElement('div')
  const root = createRoot(host)
  try {
    for (const [path, area, section] of [
      ['/applications/files', '지원서류', '제출용 파일'],
      ['/applications/job/123', '지원서류', '공고별 초안'],
      ['/offers', '검토함', '받은 제안'],
      ['/docs/reference', '자료', '참고 문서'],
      ['/', '검토함', '승인 대기'],
    ]) {
      pathname = path
      await act(async () => root.render(<><Nav /><SectionNav /></>))
      expect(host.querySelectorAll('[aria-label="주 메뉴"] a')).toHaveLength(5)
      expect(host.querySelector('[aria-label="주 메뉴"] [aria-current]')?.textContent).toBe(area)
      expect(host.querySelector('[aria-label="영역 메뉴"] [aria-current]')?.textContent).toBe(section)
    }
  } finally {
    await act(async () => root.unmount())
  }
})

it('보조 통계를 보존하면서 상위 이동과 페이지 제목을 제공한다', async () => {
  const host = document.createElement('div')
  const root = createRoot(host)
  try {
    await act(async () => root.render(<Page title="상세" back={{ href: '/applications', label: '공고별 초안' }} stats={[[1, '하나'], [2, '둘'], [3, '셋'], [4, '넷'], [5, '다섯']]}><p>내용</p></Page>))
    expect(host.querySelectorAll('h1')).toHaveLength(1)
    expect(host.querySelector('a')?.getAttribute('href')).toBe('/applications')
    expect(host.querySelector('details')?.textContent).toContain('다섯')
    expect(host.querySelector('details')?.open).toBe(false)
  } finally {
    await act(async () => root.unmount())
  }
})
