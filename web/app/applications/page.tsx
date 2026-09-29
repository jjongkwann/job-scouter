'use client'
import { useState } from 'react'
import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'

import { ApiError, get, type Applications } from '@/lib/api'
import { Due } from '@/components/due'
import { Page } from '@/components/page'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
const GRID = 'grid-cols-[minmax(150px,.8fr)_minmax(230px,1.5fr)_66px_76px_152px_96px] max-[1280px]:grid-cols-2'
const ORPHAN_GRID = 'grid-cols-[minmax(150px,.9fr)_minmax(0,1.6fr)_96px] max-[1280px]:grid-cols-1'
const RAIL: Record<string, string> = { good: 'rail-good', warn: 'rail-warn', bad: 'rail-bad', none: '' }

const REC_CLS = (r: number) => (r >= 85 ? 'text-[var(--good)]' : r >= 70 ? 'text-[var(--fg)]' : 'text-[var(--dim)]')

export default function ApplicationsPage() {
  const [search, setSearch] = useState('')
  const { data, isPending, error } = useQuery({
    queryKey: ['applications'],
    queryFn: () => get<Applications>('/applications'),
    refetchInterval: 30_000,
  })

  const s = data?.stats
  const linked = data?.linked ?? []
  const orphans = data?.orphans ?? []
  const query = search.trim().toLocaleLowerCase()
  const shownLinked = linked.filter((it) => [it.c.company, it.c.title, it.c.id, it.slug].join(' ').toLocaleLowerCase().includes(query))
  const shownOrphans = orphans.filter((it) => [it.slug, ...it.ids].join(' ').toLocaleLowerCase().includes(query))

  return (
    <Page
      title="공고별 초안"
      sub={
        <>
          후보로 등록한 공고의 초안 5종을 확인합니다. 생성된 초안은 내용 검토를 마친 서류나 실제 지원 기록을 뜻하지 않습니다.
        </>
      }
      source={
        <>
          후보 공고와 공고별 초안 기록
        </>
      }
      stats={
        s && [
          [s.candidates, '등재 공고'],
          [s.linked, '연결된 초안 폴더'],
          [orphans.length, '공고 연결 미확인'],
        ]
      }
    >
      {error && (
        <Card className="mb-3 rounded-[9px] border-[var(--rail-bad)] bg-[var(--badbg)] px-[14px] py-[10px] text-[12.5px] text-[var(--bad)]">
          지원서류 목록을 불러오지 못했습니다 — {error instanceof ApiError ? error.detail : String(error)}
        </Card>
      )}

      <label htmlFor="applications-search" className="mb-1.5 block text-[13px] font-medium">회사·직무·공고 ID 검색</label>
      <Input id="applications-search" type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="회사, 직무 또는 공고 ID" className="mb-2 max-w-2xl" />
      {data && <p className="mb-4 text-[12px] text-[var(--dim)]" aria-live="polite">연결 {shownLinked.length} / {linked.length}폴더 · 미연결 {shownOrphans.length} / {orphans.length}폴더</p>}

      <h2 className="mt-0 mb-2 text-[15px] font-semibold">
        공고에 연결된 초안<span className="ml-1.5 text-[12px] font-normal text-[var(--dim)]">{shownLinked.length}</span>
      </h2>
      <div className="mb-6 min-w-0 rounded-[9px] border border-[var(--line)] bg-[var(--row)]">
        <div
          className={`grid items-center gap-[10px] border-b border-[var(--line)] bg-[var(--bg)] px-[14px] py-[9px] text-[12px] text-[var(--dim)] max-[1280px]:hidden ${GRID}`}
        >
          <div>회사</div>
          <div>연결된 공고</div>
          <div>추천도</div>
          <div>마감</div>
          <div>초안 문서</div>
          <div>최종 수정</div>
        </div>

        {isPending ? (
          [0, 1, 2].map((i) => (
            <div key={i} className="border-b border-[var(--line)] px-[14px] py-[11px] last:border-b-0">
              <Skeleton className="h-9 w-full" />
            </div>
          ))
        ) : shownLinked.length === 0 ? (
          <div className="p-8 text-center text-[13px] text-[var(--dim)]">{query ? '검색 결과가 없습니다.' : '공고에 연결된 폴더가 아직 없습니다.'}</div>
        ) : (
          shownLinked.map((it) => (
            <div
              key={it.slug + it.c.id}
              className={`grid min-w-0 items-center gap-[10px] border-b border-[var(--line)] px-[14px] py-[9px] last:border-b-0 hover:bg-[var(--hov)] rail ${RAIL[it.c.rep_key]} ${GRID} max-[1280px]:py-[13px]`}
            >
              <div className="min-w-0">
                <div className="break-words text-[14px] leading-[1.35] font-semibold tracking-[-0.1px]">
                  <Link
                    href={`/applications/job/${encodeURIComponent(it.c.id)}?folder=${encodeURIComponent(it.slug)}`}
                    className="text-inherit no-underline hover:underline hover:underline-offset-2"
                  >
                    {it.c.company}
                  </Link>
                  {it.c.closed && <span className="ml-2 text-[12px] font-normal text-[var(--dim)]">공고 마감</span>}
                </div>
                <div className="mt-px break-all text-[12px] text-[var(--dim)]">폴더 {it.slug}</div>
              </div>

              <div className="min-w-0 break-words text-[13px] leading-[1.4]">
                <div>{it.c.title}</div>
                <div className="break-all text-[12px] text-[var(--dim)]">
                  {it.c.id}
                  {it.others > 0 && ` · 이 회사 공고 ${it.others + 1}건`}
                </div>
              </div>

              <div className={`text-[15px] leading-[1.1] font-extrabold tabular ${REC_CLS(it.c.rec)}`}>
                <span className="mr-1 hidden text-[12px] font-normal text-[var(--dim)] max-[1280px]:inline">추천도</span>
                {Math.round(it.c.rec)}
                <span className="mt-px block text-[10px] font-semibold text-[var(--dim)]">
                  {it.c.rank ? `#${it.c.rank}` : '마감'}
                </span>
              </div>

              <Due due={it.c.due} cls={it.c.due_cls} />

              <div className="text-[12px] tabular text-[var(--dim)]">초안 {it.docs.length}/5종 생성</div>

              <div className="text-[12px] tabular text-[var(--dim)]"><span className="hidden max-[1280px]:inline">최종 수정 </span>{it.mtime}</div>
            </div>
          ))
        )}
      </div>

      {orphans.length > 0 && (
        <>
          <h2 className="mt-0 mb-2 text-[15px] font-semibold">
            공고 연결 미확인 초안<span className="ml-1.5 text-[12px] font-normal text-[var(--dim)]">{shownOrphans.length}</span>
          </h2>
          <Card className="mb-2 rounded-[9px] px-[14px] py-[10px] text-[12.5px] leading-[1.55] text-[var(--dim)]">
            현재 후보 공고와 연결되지 않은 보관 문서입니다. 문서에서 확인된 공고 ID의 후보 등록 여부와 연결 정보를 함께 표시합니다.
          </Card>
          <div className="min-w-0 rounded-[9px] border border-[var(--line)] bg-[var(--row)]">
            {shownOrphans.map((o) => (
              <div
                key={o.slug}
                className={`grid min-w-0 items-center gap-[10px] border-b border-[var(--line)] px-[14px] py-[9px] last:border-b-0 hover:bg-[var(--hov)] ${ORPHAN_GRID} max-[1280px]:py-[13px]`}
              >
                <div className="min-w-0">
                  <div className="break-all text-[14px] leading-[1.35] font-semibold tracking-[-0.1px]">
                    <Link
                      href={`/applications/${encodeURIComponent(o.slug)}`}
                      className="text-inherit no-underline hover:underline hover:underline-offset-2"
                    >
                      {o.slug}
                    </Link>
                  </div>
                  <div className="mt-px break-all text-[12px] text-[var(--dim)]">
                    초안 {o.docs.length}/5종 · 파일 {o.files.length}개
                    {o.ids.length > 0 && ` · ${o.ids.join(', ')}`}
                  </div>
                </div>
                <div className="min-w-0 break-words text-[13px] text-[var(--dim)]">{o.ids.length > 0 ? '확인된 공고 ID가 현재 후보목록에 없습니다.' : '문서에서 연결할 공고 ID를 확인하지 못했습니다.'}</div>
                <div>
                  <span
                    className={`inline-block rounded-[4px] px-[7px] py-[2px] text-[11px] font-semibold ${
                      o.cls === 'warn' ? 'bg-[var(--warnbg)] text-[var(--warn)]' : 'bg-[var(--badbg)] text-[var(--bad)]'
                    }`}
                  >
                    {o.ids.length > 0 ? '후보 연결 없음' : 'ID 미확인'}
                  </span>
                </div>
              </div>
            ))}
            {shownOrphans.length === 0 && <p className="p-6 text-[13px] text-[var(--dim)]">검색 결과가 없습니다.</p>}
          </div>
        </>
      )}
    </Page>
  )
}
