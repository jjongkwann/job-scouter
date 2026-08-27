import type { Metadata } from 'next'
import './globals.css'
import { Providers } from './providers'
import { Nav } from '@/components/nav'

export const metadata: Metadata = {
  title: 'job-scouter',
  description: 'job-scouter 대시보드',
}

export default function RootLayout({ children }: LayoutProps<'/'>) {
  return (
    <html lang="ko">
      <body>
        <Providers>
          <div className="wrap">
            <Nav />
            {children}
          </div>
        </Providers>
      </body>
    </html>
  )
}
