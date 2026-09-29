import type { Metadata } from 'next'
import './globals.css'
import { Providers } from './providers'
import { Nav, SectionNav } from '@/components/nav'

export const metadata: Metadata = {
  title: 'Job Scouter',
  description: '근거를 확인하고 지원 준비를 이어가는 개인 채용 작업공간',
}

export default function RootLayout({ children }: LayoutProps<'/'>) {
  return (
    <html lang="ko">
      <body>
        <Providers>
          <a className="skip-link" href="#main">본문으로 건너뛰기</a>
          <Nav />
          <main id="main" className="wrap" tabIndex={-1}>
            <div className="mobile-brand">Job Scouter</div>
            <SectionNav />
            {children}
          </main>
        </Providers>
      </body>
    </html>
  )
}
