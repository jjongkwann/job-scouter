'use client'
import { Suspense } from 'react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Diff } from '@/components/diff'
import { Page } from '@/components/page'
import { get, post, type Diff as DiffData, type History } from '@/lib/api'

function HistoryView() {
  const sp = useSearchParams()
  const key = sp.get('key') || '이력서.md'
  const sha = sp.get('sha') || ''
  const qc = useQueryClient()

  const log = useQuery({
    queryKey: ['resume-history', key],
    queryFn: () => get<History>(`/resume/history?key=${encodeURIComponent(key)}`),
  })
  const diff = useQuery({
    queryKey: ['resume-diff', key, sha],
    queryFn: () => get<DiffData>(`/resume/history/${sha}?key=${encodeURIComponent(key)}`),
    enabled: !!sha,
  })
  const revert = useMutation({
    mutationFn: (s: string) => post<{ workflow_id: string }>('/resume/revert', { key, sha: s }),
    onSuccess: () => {
      toast('되돌리기 시작')
      qc.invalidateQueries()
    },
    onError: (e: Error) => toast.error(e.message),
  })

  const commits = log.data?.commits ?? []
  return (
    <Page
      title="이력서 수정 이력"
      back={{ href: "/resume", label: "공통 이력서" }}
      sub="변경 내용을 확인하고 이전 버전으로 되돌릴 수 있습니다. 되돌린 기록도 보존됩니다."
    >
      <div className="grid grid-cols-1 items-start gap-4 min-[1280px]:grid-cols-2">
        <div>
          <h2 className="mt-0 mb-2 text-[14px] font-semibold tracking-[-0.1px]">
            수정 기록
            <span className="ml-1.5 text-[12px] font-normal text-[var(--dim)]">{commits.length}</span>
          </h2>
          {log.isPending && <Skeleton className="h-40 w-full" />}
          {log.error && (
            <Card className="mb-3 rounded-lg border border-[var(--rail-bad)] bg-[var(--badbg)] px-3.5 py-3 text-[12.5px] text-[var(--bad)] ring-0">
              이력을 불러오지 못했습니다 — {log.error.message}
            </Card>
          )}
          {log.data &&
            (commits.length ? (
              <Card className="mb-3 gap-0 rounded-lg bg-[var(--row)] py-0 ring-[var(--line)]">
                {commits.map((c) => (
                  <div
                    key={c.sha}
                    className="flex flex-wrap items-center gap-2.5 border-b border-[var(--line)] px-3.5 py-2.5 last:border-b-0 hover:bg-[var(--hov)]"
                  >
                    <div className="tabular text-[12px] text-[var(--dim)]">{c.date}</div>
                    <code className="font-mono text-[11.5px]">{c.sha}</code>
                    <div className="flex-[1_1_200px] text-[12.5px]">{c.subject}</div>
                    <Link
                      href={`/resume/history?key=${encodeURIComponent(key)}&sha=${c.sha}`}
                      className="page-link"
                    >
                      변경 내용 보기
                    </Link>
                    <Button
                      variant="outline"
                      size="sm"
                      className="rounded-full text-[12px]"
                      disabled={revert.isPending}
                      onClick={() => revert.mutate(c.sha)}
                    >
                      이 버전으로 되돌리기
                    </Button>
                  </div>
                ))}
              </Card>
            ) : (
              <div className="mb-3 rounded-[9px] border border-dashed border-[var(--line)] bg-[var(--row)] p-8 text-center text-[13px] text-[var(--dim)]">
                수정 기록 없음
              </div>
            ))}
        </div>

        <Card className="mb-3 gap-2 rounded-lg bg-[var(--row)] px-3.5 py-3 text-[12px] ring-[var(--line)]">
          <h2 className="m-0 text-[13px] font-semibold text-[var(--dim)]">변경 내용{sha ? ` · ${sha}` : ''}</h2>
          {!sha && <p className="m-0 text-[var(--dim)]">수정 기록에서 「변경 내용 보기」를 눌러 확인하세요.</p>}
          {sha && diff.isPending && <Skeleton className="h-40 w-full" />}
          {sha && diff.error && <p className="m-0 text-[var(--bad)]">변경 내용을 불러오지 못했습니다 — {diff.error.message}</p>}
          {sha && diff.data && <Diff diff={diff.data.diff} />}
        </Card>
      </div>
    </Page>
  )
}

export default function ResumeHistoryPage() {
  return (
    <Suspense fallback={<Skeleton className="h-96 w-full" />}>
      <HistoryView />
    </Suspense>
  )
}
