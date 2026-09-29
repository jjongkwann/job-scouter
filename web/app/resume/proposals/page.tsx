'use client'
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Skeleton } from '@/components/ui/skeleton'
import { Page } from '@/components/page'
import { get, post, type ResumeProposal } from '@/lib/api'

const KIND: Record<string, string> = {
  add: 'bg-[var(--goodbg)] text-[var(--good)]',
  추가: 'bg-[var(--goodbg)] text-[var(--good)]',
  remove: 'bg-[var(--badbg)] text-[var(--bad)]',
  삭제: 'bg-[var(--badbg)] text-[var(--bad)]',
}

export default function ResumeProposalsPage() {
  const qc = useQueryClient()
  const [picked, setPicked] = useState<string[]>([])
  const q = useQuery({
    queryKey: ['resume-proposals'],
    queryFn: () => get<{ items: ResumeProposal[] }>('/resume/proposals'),
  })
  const apply = useMutation({
    mutationFn: () => post<{ workflow_id: string }>('/resume/apply', { ids: picked }),
    onSuccess: () => {
      toast('제안 반영 시작')
      setPicked([])
      qc.invalidateQueries()
    },
    onError: (e: Error) => toast.error(e.message),
  })

  const items = q.data?.items ?? []
  return (
    <Page
      title="이력서 갱신 제안"
      back={{ href: "/resume", label: "공통 이력서" }}
      sub="경력 자료와 사실베이스의 차이를 확인하세요. 선택한 제안만 사실베이스에 반영합니다."
      stats={[
        [q.data ? items.length : '–', '대기 제안'],
        ['월 08:00', '자동 확인'],
      ]}
      source={<code>jobfeed/resume_proposals.json</code>}
    >
      {apply.error && <div className="notice text-[var(--bad)]" role="alert">제안을 반영하지 못했습니다: {apply.error.message}</div>}
      {q.isPending && <Skeleton className="h-40 w-full" />}
      {q.error && (
        <Card className="mb-3 rounded-lg border border-[var(--rail-bad)] bg-[var(--badbg)] px-3.5 py-3 text-[12.5px] text-[var(--bad)] ring-0">
          제안을 불러오지 못했습니다 — {q.error.message}
        </Card>
      )}
      {q.data &&
        (items.length ? (
          <Card className="mb-3 gap-0 rounded-lg bg-[var(--row)] py-0 ring-[var(--line)]">
            {items.map((it) => (
              <article key={it.id} className="min-w-0 border-b border-[var(--line)] p-5 last:border-b-0">
                <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                  <div className="flex flex-wrap items-center gap-2"><h2 className="text-[15px] font-semibold">{it.section}</h2><Badge variant="outline">{it.target}</Badge><Badge variant="secondary" className={KIND[it.kind] ?? 'bg-[var(--warnbg)] text-[var(--warn)]'}>{it.kind}</Badge></div>
                  <label className="inline-flex min-h-11 items-center gap-2 text-[13px]"><Checkbox checked={picked.includes(it.id)} disabled={apply.isPending} onCheckedChange={(on) => setPicked((p) => on ? [...p, it.id] : p.filter((x) => x !== it.id))} aria-label={`${it.section} 제안 반영`} />반영할 내용 선택</label>
                </div>
                <div className="grid min-w-0 gap-5 md:grid-cols-2">
                  <div className="min-w-0 break-words text-[14px]">{it.current && <p className="mb-2 text-[var(--dim)]"><span className="block text-xs">현재 내용</span>{it.current}</p>}<p><span className="mb-1 block text-xs text-[var(--dim)]">제안 내용</span>{it.proposed}</p></div>
                  <p className="min-w-0 break-words text-[14px]"><span className="mb-1 block text-xs text-[var(--dim)]">경력 자료 근거</span>{it.evidence}</p>
                </div>
              </article>
            ))}
          </Card>
        ) : (
          <div className="mb-3 rounded-[9px] border border-dashed border-[var(--line)] bg-[var(--row)] p-8 text-center text-[13px] text-[var(--dim)]">
            대기 중인 갱신 제안이 없습니다. 경력 자료에 변화가 있으면 제안이 표시됩니다.
          </div>
        ))}
      <div className="mt-2.5 flex flex-wrap items-center gap-3 rounded-[9px] border border-[var(--line)] bg-[var(--row)] px-3.5 py-2.5 text-[12px] text-[var(--dim)]">
        <span>선택한 제안만 사실베이스에 반영하고 변경 이력을 남깁니다.</span>
        <Button
          className="ml-auto rounded-full text-[12px]"
          disabled={!picked.length || apply.isPending}
          onClick={() => apply.mutate()}
        >
          {picked.length}건 사실베이스에 반영
        </Button>
      </div>
    </Page>
  )
}
