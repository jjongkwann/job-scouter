'use client'
import { useState } from 'react'
import Link from 'next/link'
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
const ROW =
  'grid grid-cols-1 items-center gap-2.5 px-3.5 py-2.5 min-[1060px]:grid-cols-[150px_170px_64px_minmax(300px,1.5fr)_minmax(220px,1fr)_56px]'

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
      sub={
        <>
          매주 월요일 <b className="text-[var(--fg)]">ResumeSync</b>가 PKB(경력·소개 문서)와 사실베이스를 대조해 차이만
          제안합니다. PKB가 지난주와 같으면 제안을 만들지 않습니다(해시 게이트).{' '}
          <Link href="/resume">이력서 보기로 돌아가기</Link>
        </>
      }
      stats={[
        [items.length, '대기 제안'],
        ['월 08:00', 'ResumeSync'],
      ]}
      source={<code>jobfeed/resume_proposals.json</code>}
    >
      {q.isPending && <Skeleton className="h-40 w-full" />}
      {q.error && (
        <Card className="mb-3 rounded-lg border border-[var(--rail-bad)] bg-[var(--badbg)] px-3.5 py-3 text-[12.5px] text-[var(--bad)] ring-0">
          제안을 불러오지 못했습니다 — {q.error.message}
        </Card>
      )}
      {q.data &&
        (items.length ? (
          <Card className="mb-3 gap-0 rounded-lg bg-[var(--row)] py-0 ring-[var(--line)]">
            <div className={`${ROW} hidden border-b border-[var(--line)] bg-[var(--bg)] text-[11px] text-[var(--dim)] min-[1060px]:grid`}>
              <div>대상</div>
              <div>섹션</div>
              <div>종류</div>
              <div>현재 → 제안</div>
              <div>근거 (PKB)</div>
              <div className="text-center">반영</div>
            </div>
            {items.map((it) => (
              <div key={it.id} className={`${ROW} border-b border-[var(--line)] last:border-b-0 hover:bg-[var(--hov)]`}>
                <div>
                  <Badge variant="outline" className="border-0 bg-[var(--neubg)] text-[var(--neu)]">
                    {it.target}
                  </Badge>
                </div>
                <div className="text-[12px]">{it.section}</div>
                <div>
                  <Badge
                    variant="outline"
                    className={`border-0 ${KIND[it.kind] ?? 'bg-[var(--warnbg)] text-[var(--warn)]'}`}
                  >
                    {it.kind}
                  </Badge>
                </div>
                <div className="text-[12.5px] leading-[1.5]">
                  {it.current && (
                    <>
                      <del className="text-[var(--faint)]">{it.current}</del>
                      <br />
                    </>
                  )}
                  → {it.proposed}
                </div>
                <div className="text-[11.5px] leading-[1.45] text-[var(--dim)]">{it.evidence}</div>
                <div className="min-[1060px]:text-center">
                  <Checkbox
                    checked={picked.includes(it.id)}
                    onCheckedChange={(on) =>
                      setPicked((p) => (on ? [...p, it.id] : p.filter((x) => x !== it.id)))
                    }
                    aria-label={`${it.section} 제안 반영`}
                    className="inline-flex"
                  />
                </div>
              </div>
            ))}
          </Card>
        ) : (
          <div className="mb-3 rounded-[9px] border border-dashed border-[var(--line)] bg-[var(--row)] p-8 text-center text-[13px] text-[var(--dim)]">
            대기 중인 제안 없음 — ResumeSync는 매주 월 08:00, PKB가 그대로면 제안을 만들지 않습니다
          </div>
        ))}
      <div className="mt-2.5 flex items-center gap-3 rounded-[9px] border border-[var(--line)] bg-[var(--row)] px-3.5 py-2.5 text-[12px] text-[var(--dim)]">
        <span>체크한 제안만 ApplyResume이 사실베이스에 반영하고 검색 색인을 다시 만든 뒤 커밋합니다</span>
        <Button
          className="ml-auto rounded-full text-[12px]"
          disabled={!picked.length || apply.isPending}
          onClick={() => apply.mutate()}
        >
          반영
        </Button>
      </div>
    </Page>
  )
}
