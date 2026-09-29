import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, test } from 'vitest'
import { DocTabs } from './doc-tabs'

test('초안 탭은 읽을 수 있는 이름으로 선택되고 빠진 문서를 표시한다', async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  try {
    await act(async () => root.render(<DocTabs docs={{ '0_JD.md': '공고 내용', '1_맞춤_이력서.md': '이력서 내용' }} empty="문서 없음" />))
    const tabs = host.querySelectorAll('[role="tab"]')
    expect(tabs).toHaveLength(2)
    expect(tabs[0].textContent).toBe('공고')
    expect(tabs[0].getAttribute('title')).toBe('0_JD.md')
    expect(tabs[0].getAttribute('aria-selected')).toBe('true')
    expect(host.textContent).toContain('자기소개서 없음')
    await act(async () => (tabs[1] as HTMLElement).click())
    expect(tabs[1].getAttribute('aria-selected')).toBe('true')
    expect(host.textContent).toContain('이력서 내용')
  } finally {
    await act(async () => root.unmount())
    host.remove()
  }
})
