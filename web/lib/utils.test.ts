import { describe, expect, it } from 'vitest'
import { jobplanetUrl } from './utils'

describe('jobplanetUrl', () => {
  it('법인 표기와 괄호 별칭을 떼고 회사명으로 검색한다', () => {
    expect(jobplanetUrl('(주)연호엔지니어링')).toBe(
      `https://www.jobplanet.co.kr/search?query=${encodeURIComponent('연호엔지니어링')}`,
    )
    expect(jobplanetUrl('코드잇(codeit)')).toContain(encodeURIComponent('코드잇'))
    expect(jobplanetUrl('브레이브모바일(숨고,Soomgo)')).toContain(encodeURIComponent('브레이브모바일'))
  })
  it('다 떼서 비면 원래 이름을 쓴다', () => {
    expect(jobplanetUrl('(주)')).toContain(encodeURIComponent('(주)'))
  })
})
