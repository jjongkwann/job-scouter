'use client'
import { Suspense, useState } from 'react'
import Link from 'next/link'
import { useParams, useRouter, useSearchParams } from 'next/navigation'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { Diff } from '@/components/diff'
import { Page } from '@/components/page'
import { ApiError, get, post, type ChatSession } from '@/lib/api'

function ChatView() {
  const sid = String(useParams().sid ?? '')
  const sp = useSearchParams()
  const router = useRouter()
  const qc = useQueryClient()
  const [message, setMessage] = useState('')
  const [failed, setFailed] = useState<ApiError | null>(null)

  const q = useQuery({
    queryKey: ['chat', sid],
    queryFn: () => get<ChatSession>(`/resume/chat/${sid}`),
    // 턴은 비동기라 돌아오는 걸 폴링으로 본다 — 끝나면 멈춘다.
    refetchInterval: (query) => (query.state.data?.pending ? 2000 : false),
  })
  const key = q.data?.target || sp.get('key') || '이력서.md'

  const send = useMutation({
    mutationFn: (text: string) => post<{ workflow_id: string }>(`/resume/chat/${sid}/turns`, { key, message: text }),
    onSuccess: () => {
      setMessage('')
      qc.invalidateQueries({ queryKey: ['chat', sid] })
    },
    onError: (e: Error) => toast.error(e.message),
  })
  const end = useMutation({
    mutationFn: (save: boolean) => post<{ result: string }>(`/resume/chat/${sid}/end`, { save }),
    onSuccess: () => {
      qc.invalidateQueries()
      router.push('/resume')
    },
    onError: (e: Error) => {
      if (e instanceof ApiError && e.status === 409) setFailed(e)
      else toast.error(e.message)
    },
  })

  const turns = q.data?.turns ?? []
  return (
    <Page
      title={`대화로 고치기 — ${key}`}
      sub={
        <>
          <code>{key}</code>를 대화로 고칩니다. 저장 전까지는 세션 버퍼일 뿐이라 원본은 바뀌지 않습니다.{' '}
          <Link href="/resume">이력서 보기로 돌아가기</Link>
        </>
      }
    >
      {failed && (
        <Card className="mb-3 gap-2 rounded-lg border border-[var(--rail-bad)] bg-[var(--badbg)] px-3.5 py-2.5 text-[12.5px] leading-[1.5] text-[var(--bad)] ring-0">
          <div>
            <b>저장하지 못했습니다.</b> {failed.detail}
          </div>
          {failed.conflict && (
            <p className="m-0 text-[13px] text-[var(--dim)]">
              대상 문서가 대화를 시작한 뒤에 바뀌었습니다(다른 창에서 수정했거나 ResumeSync 반영이 있었을 수 있습니다).{' '}
              <b className="text-[var(--fg)]">덮어쓰지 않고 멈췄으니 두 수정 모두 그대로 있습니다.</b> 바뀐 내용을 확인한
              뒤, 이 대화는 버리고 새로 시작하는 편이 안전합니다.
            </p>
          )}
          <div className="flex flex-wrap gap-1.5">
            <Link
              href={`/resume/history?key=${encodeURIComponent(key)}`}
              className="inline-block rounded-full border border-[var(--line)] bg-[var(--row)] px-3 py-1 text-[12px] text-[var(--fg)] no-underline hover:border-[var(--dim)]"
            >
              문서 이력 보기
            </Link>
            <Link
              href="/resume"
              className="inline-block rounded-full border border-[var(--line)] bg-[var(--row)] px-3 py-1 text-[12px] text-[var(--fg)] no-underline hover:border-[var(--dim)]"
            >
              이력서
            </Link>
          </div>
        </Card>
      )}

      <div className="grid grid-cols-1 items-start gap-4 min-[1060px]:grid-cols-2">
        <div>
          <Card className="mb-3 gap-0 rounded-lg bg-[var(--row)] py-0 ring-[var(--line)]">
            {q.isPending && <Skeleton className="m-3.5 h-16" />}
            {turns.map((t, i) => (
              <div key={i} className="border-b border-[var(--line)] px-3.5 py-2.5 text-[12.5px] last:border-b-0">
                {t.role === 'user' ? (
                  <div>
                    <b>나</b> {t.text}
                  </div>
                ) : (
                  <div>
                    <b>조수</b> {t.text}{' '}
                    <Badge variant="outline" className="border-0 bg-[var(--goodbg)] text-[var(--good)]">
                      적용 {t.applied ?? 0}건
                    </Badge>
                    {t.skipped?.length ? (
                      <div className="mt-1 text-[11px] text-[var(--dim)]">
                        {t.skipped.map((s, j) => (
                          <div key={j}>{s}</div>
                        ))}
                      </div>
                    ) : null}
                  </div>
                )}
              </div>
            ))}
            {q.data?.pending && (
              <div className="flex items-center gap-2.5 border-b border-[var(--line)] px-3.5 py-2.5 text-[12.5px] last:border-b-0">
                <b>조수</b>
                <span className="text-[var(--dim)]">생성 중…</span>
                <Skeleton className="h-4 flex-1" />
              </div>
            )}
            {q.data && !turns.length && !q.data.pending && (
              <div className="px-3.5 py-8 text-center text-[13px] text-[var(--dim)]">아직 대화 없음</div>
            )}
          </Card>

          <div className="mt-2.5 flex items-center gap-3 rounded-[9px] border border-[var(--line)] bg-[var(--row)] px-3.5 py-2.5">
            <Textarea
              rows={3}
              placeholder="수정 요청을 입력하세요"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              className="flex-1 rounded-md border-[var(--line)] text-[12px]"
            />
            <Button
              className="rounded-full text-[12px]"
              disabled={!message.trim() || send.isPending}
              onClick={() => send.mutate(message.trim())}
            >
              보내기
            </Button>
          </div>
        </div>

        <div>
          <Card className="mb-3 gap-2 rounded-lg bg-[var(--row)] px-3.5 py-3 text-[12px] ring-[var(--line)]">
            <h3 className="m-0 text-[11px] font-semibold text-[var(--dim)]">변경사항</h3>
            {q.data?.diff ? <Diff diff={q.data.diff} /> : <p className="m-0 text-[var(--dim)]">아직 수정 없음</p>}
          </Card>
          <div className="flex items-center gap-2 rounded-[9px] border border-[var(--line)] bg-[var(--row)] px-3.5 py-2.5">
            <Button className="rounded-full text-[12px]" disabled={end.isPending} onClick={() => end.mutate(true)}>
              저장
            </Button>
            <Button
              variant="outline"
              className="rounded-full text-[12px]"
              disabled={end.isPending}
              onClick={() => end.mutate(false)}
            >
              버림
            </Button>
          </div>
        </div>
      </div>
    </Page>
  )
}

export default function ResumeChatPage() {
  return (
    <Suspense fallback={<Skeleton className="h-96 w-full" />}>
      <ChatView />
    </Suspense>
  )
}
