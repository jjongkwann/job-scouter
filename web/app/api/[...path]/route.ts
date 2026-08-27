import type { NextRequest } from 'next/server'

export const dynamic = 'force-dynamic'

const API = process.env.API_URL ?? 'http://localhost:8091'
const FWD = ['content-type', 'accept', 'sec-fetch-site']

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params
  const url = new URL(req.url)
  const headers = new Headers()
  for (const h of FWD) {
    const v = req.headers.get(h)
    if (v) headers.set(h, v)
  }
  const init: RequestInit & { duplex?: 'half' } = { method: req.method, headers, cache: 'no-store', signal: req.signal }
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    init.body = req.body
    init.duplex = 'half'
  }
  const res = await fetch(`${API}/api/${path.map(encodeURIComponent).join('/')}${url.search}`, init)
  const out = new Headers({ 'cache-control': 'no-store' })
  const ct = res.headers.get('content-type')
  if (ct) out.set('content-type', ct)
  return new Response(res.body, { status: res.status, headers: out })
}

export { proxy as GET, proxy as POST }
