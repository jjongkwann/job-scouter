import { NextResponse, type NextRequest } from 'next/server'

const HOST_OK = /^(\d{1,3}(\.\d{1,3}){3}|localhost|[\w-]+|[\w-]+\.local)$/

export function proxy(req: NextRequest) {
  const host = (req.headers.get('host') ?? '').replace(/:\d+$/, '')
  if (!HOST_OK.test(host)) return new NextResponse('허용되지 않은 Host', { status: 403 })
  return NextResponse.next()
}

export const config = { matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'] }
