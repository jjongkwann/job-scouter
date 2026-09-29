import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it } from 'vitest'
import { ApplicationFileCard, type ApplicationFilePack } from './application-files'

it('제출용 파일의 경험 제한과 확인 사항을 파일 행동 전에 항상 보여준다', async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  const pack: ApplicationFilePack = {
    id: '123', ids: ['123'], company: '테스트회사', title: '백엔드', source_urls: ['https://example.com/job'],
    limitations: 'Kubernetes 운영 경험 없음', review_notes: '지원 전 담당 범위 확인', pages: 2,
    files: [{ name: '이력서.pdf', url: '/resume.pdf', size: 1024, format: 'pdf', kind: 'resume' }],
    bundle: null,
  }
  const host = document.createElement('div')
  const root = createRoot(host)
  try {
    await act(async () => root.render(<ApplicationFileCard pack={pack} />))
    const card = host.querySelector('[data-slot="card"]')!
    const note = [...card.querySelectorAll('p')].find((p) => p.textContent === pack.limitations)!
    const action = card.querySelector('a[href="/resume.pdf"]')!
    expect(note.closest('details')).toBeNull()
    expect(note.compareDocumentPosition(action)).toBe(Node.DOCUMENT_POSITION_FOLLOWING)
    expect(card.textContent).toContain(pack.review_notes)
    expect(card.querySelector('details')?.textContent).toContain('공고 원문')
  } finally {
    await act(async () => root.unmount())
  }
})
