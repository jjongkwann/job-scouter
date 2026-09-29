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

test('폴더에 선택한 문서가 없으면 대체 문서를 알리고, 이전 폴더로 돌아오면 같은 문서를 연다', async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  const host = document.createElement('div')
  const root = createRoot(host)
  const original = { '0_JD.md': '공고 내용', '1_맞춤_이력서.md': '선택한 이력서' }
  try {
    await act(async () => root.render(<DocTabs docs={original} value="1_맞춤_이력서.md" empty="문서 없음" />))
    expect(host.querySelector('[role="tab"][aria-selected="true"]')?.textContent).toBe('맞춤 이력서')
    await act(async () => root.render(<DocTabs docs={{ '0_JD.md': '다른 공고' }} value="1_맞춤_이력서.md" empty="문서 없음" />))
    expect(host.querySelector('[role="status"]')?.textContent).toContain('맞춤 이력서 문서가 없습니다')
    expect(host.querySelector('[role="tab"][aria-selected="true"]')?.textContent).toBe('공고')
    expect(host.textContent).toContain('다른 공고')
    await act(async () => root.render(<DocTabs docs={{}} value="1_맞춤_이력서.md" empty="아직 문서가 없습니다" />))
    expect(host.querySelector('[role="status"]')?.textContent).toContain('맞춤 이력서 문서가 없습니다')
    expect(host.textContent).toContain('아직 문서가 없습니다')
    await act(async () => root.render(<DocTabs docs={original} value="1_맞춤_이력서.md" empty="문서 없음" />))
    expect(host.querySelector('[role="status"]')).toBeNull()
    expect(host.textContent).toContain('선택한 이력서')
  } finally {
    await act(async () => root.unmount())
  }
})
