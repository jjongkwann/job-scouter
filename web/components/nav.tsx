'use client'
import Link from 'next/link'
import { usePathname } from 'next/navigation'

export const NAV: [string, string][] = [
  ['/', '대시보드'],
  ['/candidates', '후보목록'],
  ['/reports', '보고서'],
  ['/resume', '이력서'],
  ['/applications', '지원서류'],
  ['/docs', '문서'],
]

export function Nav() {
  const pathname = usePathname()
  return (
    <nav className="flex items-center gap-1.5 border-b border-[var(--line)] pb-3 mb-5">
      {NAV.map(([href, label]) => {
        const active = href === '/' ? pathname === '/' : pathname.startsWith(href)
        return (
          <Link
            key={href}
            href={href}
            aria-pressed={active}
            className="rounded-full border border-[var(--line)] bg-[var(--row)] px-3 py-1 text-[13px] text-[var(--fg)] no-underline hover:border-[var(--dim)] aria-pressed:bg-[var(--fg)] aria-pressed:text-white aria-pressed:border-[var(--fg)]"
          >
            {label}
          </Link>
        )
      })}
      <span className="ml-auto text-[11px] text-[var(--dim)]">LAN 전용 · 인증 없음</span>
    </nav>
  )
}
