'use client'
import { Suspense, useEffect, useRef } from 'react'
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
  const selectedHeading = useRef<HTMLHeadingElement>(null)

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

  useEffect(() => {
    if (sha && log.isSuccess && !diff.isPending) selectedHeading.current?.focus()
  }, [sha, log.isSuccess, diff.isPending])

  const commits = log.data?.commits ?? []
  const shownCommits = sha && log.data && !commits.some((c) => c.sha === sha)
    ? [...commits, { sha, date: '날짜 미확인', subject: '직접 선택한 버전' }]
    : commits
  return (
    <Page
      title="이력서 수정 이력"
      back={{ href: "/resume", label: "공통 이력서" }}
      sub={<>대상: <code>{key}</code> · 변경 내용을 확인하고 이전 버전으로 되돌릴 수 있습니다. 되돌린 기록도 보존됩니다.</>}
    >
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
            (shownCommits.length ? (
              <Card className="mb-3 gap-0 rounded-lg bg-[var(--row)] py-0 ring-[var(--line)]">
                {shownCommits.map((c) => (
                  <div
                    key={c.sha}
                    className={`border-b border-[var(--line)] last:border-b-0 ${sha === c.sha ? 'bg-[var(--secondary)]' : 'hover:bg-[var(--hov)]'}`}
                  >
                    <div className="flex flex-wrap items-center gap-2.5 px-3.5 py-2.5">
                      <div className="tabular text-[12px] text-[var(--dim)]">{c.date}</div>
                      <code className="font-mono text-[11.5px]">{c.sha}</code>
                      <div className="flex-[1_1_200px] text-[12.5px]">{c.subject}</div>
                      <Link
                        href={`/resume/history?key=${encodeURIComponent(key)}&sha=${c.sha}`}
                        scroll={false}
                        aria-current={sha === c.sha ? 'true' : undefined}
                        aria-expanded={sha === c.sha}
                        aria-controls={sha === c.sha ? 'selected-change' : undefined}
                        className="page-link"
                      >
                        {sha === c.sha ? '선택한 변경 내용' : '변경 내용 보기'}
                      </Link>
                    </div>
                    {sha === c.sha && (
                      <section id="selected-change" className="border-t border-[var(--line)] bg-[var(--row)] px-3.5 py-3">
                        <h3 ref={selectedHeading} tabIndex={-1} className="m-0 text-[14px] font-semibold">{c.date} · {c.subject} · {c.sha}</h3>
                        <p className="my-2 text-[12px] text-[var(--dim)]">아래는 이 버전이 만들어질 때의 변경 내용입니다. 현재 이력서와의 전체 차이는 아닙니다.</p>
                        {diff.isPending && <Skeleton className="h-40 w-full" />}
                        {diff.error && <p className="m-0 text-[var(--bad)]">변경 내용을 불러오지 못했습니다 — {diff.error.message}</p>}
                        {diff.data && <Diff diff={diff.data.diff} />}
                        {diff.data && (
                          <div className="mt-4 border-t border-[var(--line)] pt-3">
                            <p className="mb-2 text-[13px]"><code>{key}</code> 문서 원본을 이 버전의 내용으로 되돌리고 새 수정 기록을 남깁니다.</p>
                            <Button
                              variant="outline"
                              disabled={revert.isPending || (revert.isSuccess && revert.variables === c.sha)}
                              onClick={() => revert.mutate(c.sha)}
                            >
                              {c.sha} 버전으로 되돌리기
                            </Button>
                            {revert.isSuccess && revert.variables === c.sha && <p role="status" className="mt-2 text-[var(--dim)]">복원 작업을 요청했습니다. 완료 여부는 대상 문서와 수정 이력에서 확인하세요.</p>}
                            {revert.error && revert.variables === c.sha && <p role="alert" className="mt-2 text-[var(--bad)]">{c.sha} 버전 복원 요청에 실패했습니다: {revert.error.message} 요청 처리 여부가 불분명할 수 있습니다. 대상 문서와 수정 이력을 확인한 뒤 다시 시도하세요.</p>}
                          </div>
                        )}
                      </section>
                    )}
                  </div>
                ))}
              </Card>
            ) : (
              <div className="mb-3 rounded-[9px] border border-dashed border-[var(--line)] bg-[var(--row)] p-8 text-center text-[13px] text-[var(--dim)]">
                수정 기록 없음
              </div>
            ))}
        {!sha && log.data && commits.length > 0 && <p className="text-[13px] text-[var(--dim)]">수정 기록에서 「변경 내용 보기」를 눌러 확인하세요.</p>}
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
