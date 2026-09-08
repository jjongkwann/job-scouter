import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

// 잡플래닛 회사 검색 링크. 기업평판.md는 URL을 안 남기므로 회사명으로 검색한다 —
// 법인 표기·괄호 별칭을 떼야 검색이 맞는다(config._norm과 같은 규칙, 띄어쓰기는 유지).
export function jobplanetUrl(company: string): string {
  const name = company
    .replace(/\(주\)|주식회사|㈜|Inc\.?|Ltd\.?/g, '')
    .replace(/\([^)]*\)/g, '')
    .trim()
  return `https://www.jobplanet.co.kr/search?query=${encodeURIComponent(name || company)}`
}
