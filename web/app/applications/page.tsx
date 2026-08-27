'use client'
import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'

import { ApiError, get, type Applications } from '@/lib/api'
import { Due } from '@/components/due'
import { Page } from '@/components/page'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { APP_FILES } from './doc-tabs'

// web.py `.app` / `.orphan` 규격 그대로 — 1060px 이하에서는 한 열로 접힌다
const GRID = 'grid-cols-[minmax(150px,.8fr)_minmax(230px,1.5fr)_66px_76px_152px_96px] max-[1060px]:grid-cols-1'
const ORPHAN_GRID = 'grid-cols-[minmax(150px,.9fr)_minmax(0,1.6fr)_96px] max-[1060px]:grid-cols-1'
const RAIL: Record<string, string> = { good: 'rail-good', warn: 'rail-warn', bad: 'rail-bad', none: '' }

const REC_CLS = (r: number) => (r >= 85 ? 'text-[var(--good)]' : r >= 70 ? 'text-[var(--fg)]' : 'text-[var(--dim)]')

export default function ApplicationsPage() {
  const { data, isPending, error } = useQuery({
    queryKey: ['applications'],
    queryFn: () => get<Applications>('/applications'),
    refetchInterval: 30_000,
  })

  const s = data?.stats
  const linked = data?.linked ?? []
  const orphans = data?.orphans ?? []

  return (
    <Page
      title="지원서류"
      sub={
        <>
          폴더와 등재 공고를 <b>공고 id</b>로 이어 한 줄로 보여줍니다 — 회사명이 아니라 문서에 적힌{' '}
          <code>wanted.co.kr/wd/{'{id}'}</code>가 연결 키입니다. 승인한 공고는 Publish가{' '}
          <b>JD·맞춤 이력서·자기소개서·면접지식맵·포트폴리오 구성</b> 5종 초안을 만들어 두고, 검토는 사람이 합니다.
        </>
      }
      source={
        <>
          <code>applications/&lt;폴더&gt;/*.md</code> · <code>jobfeed/candidates.json</code>
        </>
      }
      stats={
        s && [
          [s.candidates, '등재 공고'],
          [s.folders, '지원서류 폴더'],
          [s.linked, '공고에 연결됨'],
          [s.gone, '공고 내려감'],
          [s.unlinked, 'id 없음 — 수동 연결'],
        ]
      }
    >
      {error && (
        <Card className="mb-3 rounded-[9px] border-[var(--rail-bad)] bg-[var(--badbg)] px-[14px] py-[10px] text-[12.5px] text-[var(--bad)]">
          지원서류 목록을 불러오지 못했습니다 — {error instanceof ApiError ? error.detail : String(error)}
        </Card>
      )}

      <h2 className="mt-0 mb-2 text-[15px] font-semibold">
        공고에 연결된 폴더<span className="ml-1.5 text-[12px] font-normal text-[var(--dim)]">{linked.length}</span>
      </h2>
      <div className="mb-6 overflow-hidden rounded-[9px] border border-[var(--line)] bg-[var(--row)]">
        <div
          className={`grid items-center gap-[10px] border-b border-[var(--line)] bg-[var(--bg)] px-[14px] py-[9px] text-[11px] text-[var(--dim)] max-[1060px]:hidden ${GRID}`}
        >
          <div>회사 · 폴더</div>
          <div>연결된 공고</div>
          <div>추천도</div>
          <div>마감</div>
          <div>문서 (0_JD … 4_포트폴리오)</div>
          <div>최종 수정</div>
        </div>

        {isPending ? (
          [0, 1, 2].map((i) => (
            <div key={i} className="border-b border-[var(--line)] px-[14px] py-[11px] last:border-b-0">
              <Skeleton className="h-9 w-full" />
            </div>
          ))
        ) : linked.length === 0 ? (
          <div className="p-8 text-center text-[13px] text-[var(--dim)]">공고에 연결된 폴더가 아직 없습니다</div>
        ) : (
          linked.map((it) => (
            <div
              key={it.slug + it.c.id}
              className={`grid items-center gap-[10px] border-b border-[var(--line)] px-[14px] py-[9px] last:border-b-0 hover:bg-[var(--hov)] rail ${RAIL[it.c.rep_key]} ${GRID} max-[1060px]:py-[13px] ${it.c.closed ? 'opacity-55' : ''}`}
            >
              <div>
                <div className="text-[14px] leading-[1.35] font-semibold tracking-[-0.1px]">
                  <Link
                    href={`/applications/job/${encodeURIComponent(it.c.id)}`}
                    className="text-inherit no-underline hover:underline hover:underline-offset-2"
                  >
                    {it.c.company}
                  </Link>
                </div>
                <div className="mt-px font-mono text-[11.5px] text-[var(--dim)]">{it.slug}</div>
              </div>

              <div className="text-[12.5px] leading-[1.4]">
                <div>{it.c.title}</div>
                <div className="text-[11px] text-[var(--dim)]">
                  {it.c.id}
                  {it.others > 0 && ` · 이 회사 공고 ${it.others + 1}건`}
                </div>
              </div>

              <div className={`text-[15px] leading-[1.1] font-extrabold tabular ${REC_CLS(it.c.rec)}`}>
                {Math.round(it.c.rec)}
                <span className="mt-px block text-[10px] font-semibold text-[var(--dim)]">
                  {it.c.rank ? `#${it.c.rank}` : '마감'}
                </span>
              </div>

              <Due due={it.c.due} cls={it.c.due_cls} />

              <div className="flex items-center gap-2">
                <div className="flex gap-[3px]">
                  {APP_FILES.map((f) => (
                    <span
                      key={f}
                      className={`inline-flex h-[17px] w-[17px] items-center justify-center rounded-[4px] text-[9.5px] font-semibold ${
                        it.docs.includes(f)
                          ? 'bg-[var(--goodbg)] text-[var(--good)]'
                          : 'bg-[var(--neubg)] text-[var(--faint)]'
                      }`}
                    >
                      {f[0]}
                    </span>
                  ))}
                </div>
                <span
                  className={`text-[11px] tabular ${it.docs.length === 5 ? 'text-[var(--dim)]' : 'font-semibold text-[var(--warn)]'}`}
                >
                  {it.docs.length === 5 ? '5종' : `${it.docs.length} / 5`}
                </span>
              </div>

              <div className="text-[11.5px] tabular text-[var(--dim)]">{it.mtime}</div>
            </div>
          ))
        )}
      </div>

      {orphans.length > 0 && (
        <>
          <h2 className="mt-0 mb-2 text-[15px] font-semibold">
            공고를 못 찾은 폴더<span className="ml-1.5 text-[12px] font-normal text-[var(--dim)]">{orphans.length}</span>
          </h2>
          <Card className="mb-2 rounded-[9px] px-[14px] py-[10px] text-[12.5px] leading-[1.55] text-[var(--dim)]">
            문서에 적힌 공고가 후보목록에서 <b>내려간</b> 경우와, 공고 링크가 <b>아예 없는</b> 경우입니다. 후자는 문서
            어딘가에 원티드·점핏 링크를 한 줄 적어 주면 다음 열람부터 이어집니다.
          </Card>
          <div className="overflow-hidden rounded-[9px] border border-[var(--line)] bg-[var(--row)]">
            {orphans.map((o) => (
              <div
                key={o.slug}
                className={`grid items-center gap-[10px] border-b border-[var(--line)] px-[14px] py-[9px] last:border-b-0 hover:bg-[var(--hov)] ${ORPHAN_GRID} max-[1060px]:py-[13px]`}
              >
                <div>
                  <div className="text-[14px] leading-[1.35] font-semibold tracking-[-0.1px]">
                    <Link
                      href={`/applications/${encodeURIComponent(o.slug)}`}
                      className="text-inherit no-underline hover:underline hover:underline-offset-2"
                    >
                      {o.slug}
                    </Link>
                  </div>
                  <div className="mt-px text-[12px] text-[var(--dim)]">
                    md {o.files.length}
                    {o.ids.length > 0 && ` · ${o.ids.join(', ')}`}
                  </div>
                </div>
                <div className="text-[12.5px] text-[var(--dim)]">{o.why}</div>
                <div>
                  <span
                    className={`inline-block rounded-[4px] px-[7px] py-[2px] text-[11px] font-semibold ${
                      o.cls === 'warn' ? 'bg-[var(--warnbg)] text-[var(--warn)]' : 'bg-[var(--badbg)] text-[var(--bad)]'
                    }`}
                  >
                    {o.badge}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </Page>
  )
}
