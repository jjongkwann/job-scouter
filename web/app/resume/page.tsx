'use client'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useMutation, useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Markdown } from '@/components/markdown'
import { Page } from '@/components/page'
import { get, post, type Resume } from '@/lib/api'

const KEY = '이력서.md'

export default function ResumePage() {
  const router = useRouter()
  const q = useQuery({ queryKey: ['resume'], queryFn: () => get<Resume>('/resume') })
  const newChat = useMutation({
    mutationFn: () => post<{ sid: string }>('/resume/chat', { key: KEY }),
    onSuccess: ({ sid }) => router.push(`/resume/chat/${sid}?key=${encodeURIComponent(KEY)}`),
    onError: (e: Error) => toast.error(e.message),
  })

  return (
    <Page
      title="이력서"
      sub={
        <>
          이력서 정본 <b className="text-[var(--fg)]">이력서.md</b> 한 문서를 그대로 렌더링합니다. 「대화로 고치기」·
          「이력」은 이 문서 하나에 걸립니다. 판정·초안의 근거인 사실베이스는 <Link href="/docs">/docs</Link>에서 볼 수
          있고, 갱신은 ResumeSync 제안을 승인해야만 반영됩니다.
        </>
      }
      source={<code>이력서.md</code>}
    >
      <div className="grid grid-cols-1 items-start gap-4 min-[1060px]:grid-cols-[minmax(0,1fr)_260px]">
        <div>
          <p className="mb-2 flex flex-wrap items-center gap-1.5 font-mono text-[11px] text-[var(--dim)]">
            {KEY} ·{' '}
            <Link href={`/resume/history?key=${encodeURIComponent(KEY)}`} className="font-mono text-[11px]">
              이력
            </Link>{' '}
            ·{' '}
            <Button
              variant="link"
              size="xs"
              className="h-auto p-0 font-mono text-[11px] text-[var(--accent)]"
              disabled={newChat.isPending}
              onClick={() => newChat.mutate()}
            >
              대화로 고치기
            </Button>
          </p>
          {q.isPending && <Skeleton className="h-96 w-full" />}
          {q.error && (
            <Card className="mb-3 rounded-lg border border-[var(--rail-bad)] bg-[var(--badbg)] px-3.5 py-3 text-[12.5px] text-[var(--bad)] ring-0">
              이력서를 불러오지 못했습니다 — {q.error.message}
            </Card>
          )}
          {q.data && <Markdown text={q.data.markdown} />}
        </div>

        <div>
          <Card className="mb-3 gap-2 rounded-lg bg-[var(--row)] px-3.5 py-3 text-[12px] ring-[var(--line)]">
            <h3 className="m-0 text-[11px] font-semibold text-[var(--dim)]">진행 중 대화</h3>
            {q.data?.chats.length ? (
              <div className="flex flex-col gap-0.5">
                {q.data.chats.map((c) => (
                  <Link
                    key={c.sid}
                    href={`/resume/chat/${c.sid}?key=${encodeURIComponent(c.target)}`}
                    className="block rounded-md px-2 py-1.5 text-[12px] text-[var(--fg)] no-underline hover:bg-[var(--hov)]"
                  >
                    {c.target} · {c.n}턴
                  </Link>
                ))}
              </div>
            ) : (
              <p className="m-0 text-[var(--dim)]">없음</p>
            )}
          </Card>

          <Card className="mb-3 gap-2 rounded-lg bg-[var(--row)] px-3.5 py-3 text-[12px] ring-[var(--line)]">
            <h3 className="m-0 text-[11px] font-semibold text-[var(--dim)]">갱신 제안</h3>
            <div className="text-[19px] leading-tight font-bold">
              {q.data?.pending ?? 0}
              <span className="text-[12px] font-normal text-[var(--dim)]"> 건 대기</span>
            </div>
            <p className="m-0 text-[var(--dim)]">ResumeSync 매주 월 08:00 · PKB와 대조해 차이만 제안</p>
            <p className="m-0">
              <Link
                href="/resume/proposals"
                className="inline-block rounded-full border border-[var(--line)] px-3 py-1 text-[12px] text-[var(--fg)] no-underline hover:border-[var(--dim)]"
              >
                갱신 제안 보기
              </Link>
            </p>
          </Card>

          <Card className="mb-3 gap-2 rounded-lg bg-[var(--row)] px-3.5 py-3 text-[12px] ring-[var(--line)]">
            <h3 className="m-0 text-[11px] font-semibold text-[var(--dim)]">규칙</h3>
            <p className="m-0 text-[var(--dim)]">
              사실베이스는 사람이 검증한 문장만 담습니다. 판정·초안·검색(jobscout_facts)이 모두 이 문서를 읽습니다.
            </p>
          </Card>
        </div>
      </div>
    </Page>
  )
}
