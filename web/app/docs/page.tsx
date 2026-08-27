'use client'
import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Page } from '@/components/page'
import { get, type DocItem } from '@/lib/api'

const href = (path: string) => `/docs/${path.split('/').map(encodeURIComponent).join('/')}`

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
      title="문서"
      sub={
        <>
          {items.length}건. <code>references/</code>의 마크다운 — 작성 규칙·면접 대비 노트·사실베이스·로드맵.
        </>
      }
      source={<code>references/**/*.md</code>}
    >
      {q.isPending && <Skeleton className="h-40 w-full" />}
      {q.error && (
        <Card className="mb-3 rounded-lg border border-[var(--rail-bad)] bg-[var(--badbg)] px-3.5 py-3 text-[12.5px] text-[var(--bad)] ring-0">
          문서 목록을 불러오지 못했습니다 — {q.error.message}
        </Card>
      )}
      {q.data &&
        (items.length ? (
          <div className="grid grid-cols-1 items-start gap-4 min-[1060px]:grid-cols-2">
            {cols.map((col, i) => (
              <div key={i}>
                {col.map(([title, docs]) => (
                  <div key={title}>
                    <h2 className="mt-0 mb-2 text-[14px] font-semibold tracking-[-0.1px]">
                      {title}
                      <span className="ml-1.5 text-[12px] font-normal text-[var(--dim)]">{docs.length}</span>
                    </h2>
                    <Card className="mb-3 gap-0 rounded-lg bg-[var(--row)] py-0 ring-[var(--line)]">
                      {docs.map((d) => (
                        <div
                          key={d.path}
                          className="border-b border-[var(--line)] px-3.5 py-2.5 font-medium last:border-b-0 hover:bg-[var(--hov)]"
                        >
                          <Link href={href(d.path)} className="text-inherit no-underline hover:underline">
                            {d.name}
                          </Link>
                        </div>
                      ))}
                    </Card>
                  </div>
                ))}
              </div>
            ))}
          </div>
        ) : (
          <div className="mb-3 rounded-[9px] border border-dashed border-[var(--line)] bg-[var(--row)] p-8 text-center text-[13px] text-[var(--dim)]">
            없음
          </div>
        ))}
    </Page>
  )
}
