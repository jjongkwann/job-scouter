'use client'
import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { Skeleton } from '@/components/ui/skeleton'
import { Page } from '@/components/page'
import { get, type DocItem } from '@/lib/api'

const href = (path: string) => `/docs/${path.split('/').map(encodeURIComponent).join('/')}`
const label = (name: string) => name.replace(/\.md$/, '').replaceAll('_', ' ')

/** group별로 묶어 큰 그룹이 오른쪽 열에 오도록 두 열로 나눈다 — web.py docs_index와 같은 규칙. */
function columns(items: DocItem[]): [string, DocItem[]][][] {
  const groups = new Map<string, DocItem[]>()
  for (const it of items) groups.set(it.group, [...(groups.get(it.group) ?? []), it])
  const ordered = [...groups.entries()].sort((a, b) => b[1].length - a[1].length)
  return ordered.length > 1 ? [ordered.slice(1), ordered.slice(0, 1)] : [ordered]
}

export default function DocsPage() {
  const q = useQuery({ queryKey: ['docs'], queryFn: () => get<DocItem[]>('/docs') })
  const items = q.data ?? []
  const cols = columns(items)
  return (
    <Page
      title="참고 문서"
      sub={`${items.length}건의 참고 자료`}
      source={<code>references/**/*.md</code>}
    >
      {q.isPending && <Skeleton className="h-40 w-full" />}
      {q.error && (
        <div role="alert" className="notice mb-3">
          문서 목록을 불러오지 못했습니다 — {q.error.message}
        </div>
      )}
      {q.data &&
        (items.length ? (
          <div className="grid grid-cols-1 items-start gap-4 min-[1060px]:grid-cols-2">
            {cols.map((col, i) => (
              <div key={i} className="min-w-0">
                {col.map(([title, docs]) => (
                  <div key={title}>
                    <h2 className="section-title">
                      {title === 'references' ? '기본 문서' : title.replaceAll('_', ' ')}
                      <span className="ml-1.5 text-[12px] font-normal text-[var(--dim)]">{docs.length}</span>
                    </h2>
                    <div className="surface mb-3 divide-y divide-[var(--line)]">
                      {docs.map((d) => (
                        <div
                          key={d.path}
                          className="min-w-0 px-4 py-3 font-medium [overflow-wrap:anywhere] hover:bg-[var(--hov)]"
                        >
                          <Link href={href(d.path)} className="inline-flex min-h-11 items-center text-[var(--link)] hover:underline">
                            {label(d.name)}
                          </Link>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            ))}
          </div>
        ) : (
          <div className="empty-state mb-3">
            저장된 참고 문서가 없습니다.
          </div>
        ))}
    </Page>
  )
}
