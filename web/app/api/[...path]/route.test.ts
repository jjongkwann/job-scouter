import { afterEach, describe, expect, it, vi } from 'vitest'
import { NextRequest } from 'next/server'
import { GET, HEAD, POST } from './route'

const file = { params: Promise.resolve({ path: ['application-files', 'files', 'sample.pdf'] }) }

afterEach(() => vi.unstubAllGlobals())

describe('API proxy', () => {
  it('streams a ranged attachment and preserves download headers', async () => {
    const disposition = "attachment; filename*=UTF-8''%EC%9D%B4%EB%A0%A5%EC%84%9C.pdf"
    const upstreamResponse = new Response('PDF', {
      status: 206,
      headers: {
        'content-type': 'application/pdf',
        'content-disposition': disposition,
        'content-length': '3',
        'accept-ranges': 'bytes',
        'content-range': 'bytes 0-2/10',
        etag: '"v1"',
        'last-modified': 'Tue, 29 Sep 2026 00:00:00 GMT',
      },
    })
    const upstream = vi.fn<(url: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(async () => upstreamResponse)
    vi.stubGlobal('fetch', upstream)

    const res = await GET(new NextRequest('http://localhost/api/application-files/files/sample.pdf', {
      headers: { range: 'bytes=0-2', 'if-range': '"v1"' },
    }), file)

    expect(upstream.mock.calls[0][0]).toBe('http://localhost:8091/api/application-files/files/sample.pdf')
    const sent = upstream.mock.calls[0][1]!
    expect((sent.headers as Headers).get('range')).toBe('bytes=0-2')
    expect((sent.headers as Headers).get('if-range')).toBe('"v1"')
    expect(res.status).toBe(206)
    for (const name of ['content-type', 'content-disposition', 'content-length', 'accept-ranges', 'content-range', 'etag', 'last-modified']) {
      expect(res.headers.get(name)).toBe(upstreamResponse.headers.get(name))
    }
    expect(res.headers.get('content-disposition')).toBe(disposition)
    expect(res.body).toBe(upstreamResponse.body)
    expect(await res.text()).toBe('PDF')
  })

  it('sends HEAD upstream without returning a body', async () => {
    const upstreamResponse = new Response('ignored', {
      headers: { 'content-length': '10', 'accept-ranges': 'bytes' },
    })
    const upstream = vi.fn<(url: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(async () => upstreamResponse)
    vi.stubGlobal('fetch', upstream)

    const res = await HEAD(new NextRequest('http://localhost/api/application-files/files/sample.pdf', {
      method: 'HEAD',
    }), file)

    expect(upstream.mock.calls[0][1]?.method).toBe('HEAD')
    expect(upstream.mock.calls[0][1]?.body).toBeUndefined()
    expect(res.body).toBeNull()
    expect(res.headers.get('content-length')).toBe('10')
  })

  it('forwards the existing JSON POST payload', async () => {
    let payload = ''
    const upstream = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      payload = await new Response(init?.body).text()
      return Response.json({ ok: true })
    })
    vi.stubGlobal('fetch', upstream)

    const res = await POST(new NextRequest('http://localhost/api/judge', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ id: '123' }),
    }), { params: Promise.resolve({ path: ['judge'] }) })

    expect(upstream.mock.calls[0][1]?.method).toBe('POST')
    expect((upstream.mock.calls[0][1]?.headers as Headers).get('content-type')).toBe('application/json')
    expect(payload).toBe('{"id":"123"}')
    expect(await res.json()).toEqual({ ok: true })
  })
})
