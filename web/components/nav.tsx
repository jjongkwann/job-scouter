'use client'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { Inbox, ListChecks, Files, FileUser, Library } from 'lucide-react'

export const NAV = [
  { href: '/', label: '검토함', icon: Inbox, paths: ['/', '/offers'] },
  { href: '/candidates', label: '후보', icon: ListChecks, paths: ['/candidates'] },
  { href: '/applications', label: '지원서류', icon: Files, paths: ['/applications'] },
  { href: '/resume', label: '이력서', icon: FileUser, paths: ['/resume'] },
  { href: '/reports', label: '자료', icon: Library, paths: ['/reports', '/docs'] },
]

const matches = (pathname: string, path: string) => path === '/' ? pathname === '/' : pathname === path || pathname.startsWith(`${path}/`)

export function Nav() {
  const pathname = usePathname()
  return (
    <aside className="site-nav">
      <Link href="/" className="brand">Job Scouter<span>개인 채용 작업공간</span></Link>
      <nav aria-label="주 메뉴" className="primary-nav">
        {NAV.map(({ href, label, icon: Icon, paths }) => (
          <Link key={href} href={href} aria-current={paths.some((p) => matches(pathname, p)) ? 'page' : undefined}>
            <Icon size={19} aria-hidden="true" /><span>{label}</span>
          </Link>
        ))}
      </nav>
      <p className="nav-note">개인 네트워크 전용</p>
    </aside>
  )
}

export function SectionNav() {
  const pathname = usePathname()
  const links = pathname === '/' || matches(pathname, '/offers')
    ? [['/', '승인 대기'], ['/offers', '받은 제안']]
    : matches(pathname, '/applications')
      ? [['/applications', '공고별 초안'], ['/applications/files', '제출용 파일']]
      : matches(pathname, '/reports') || matches(pathname, '/docs')
        ? [['/reports', '조사 보고서'], ['/docs', '참고 문서']]
        : []
  if (!links.length) return null
  const current = [...links].reverse().find(([path]) => matches(pathname, path))?.[0]
  return (
    <nav aria-label="영역 메뉴" className="section-nav">
      {links.map(([href, label]) => <Link key={href} href={href} aria-current={current === href ? 'page' : undefined}>{label}</Link>)}
    </nav>
  )
}
