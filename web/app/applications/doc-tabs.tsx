'use client'
import { useState, type ReactNode } from 'react'

import { Markdown } from '@/components/markdown'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

// jobscouter/config.py APP_FILES — Draft가 만드는 표준 5종. 없는 건 탭 대신 점선 배지로 자리만 보여 준다.
export const APP_FILES = ['0_JD.md', '1_맞춤_이력서.md', '2_자기소개서.md', '3_면접지식맵.md', '4_포트폴리오_구성.md']

export function DocTabs({ docs, empty }: { docs: Record<string, string>; empty: ReactNode }) {
  const files = Object.keys(docs)
  const [tab, setTab] = useState('')
  // 초안이 도는 동안 files가 비었다가 채워진다 — 고른 문서가 아직/이미 없으면 첫 문서로
  const cur = files.includes(tab) ? tab : (files[0] ?? '')
  const missing = APP_FILES.filter((f) => !files.includes(f))

  if (!cur)
    return <Card className="rounded-[9px] p-8 text-center text-[13px] leading-[1.7] text-[var(--dim)]">{empty}</Card>

  return (
    <Tabs value={cur} onValueChange={(v) => setTab(String(v))}>
      <div className="mb-2.5 flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-[11px] text-[var(--dim)]">문서</span>
        <TabsList variant="line" className="h-auto flex-wrap gap-1.5 p-0">
          {files.map((f) => (
            <TabsTrigger
              key={f}
              value={f}
              className="h-auto rounded-full border border-[var(--line)] bg-[var(--row)] px-[11px] py-[3px] text-[12px] font-normal hover:border-[var(--dim)] data-active:border-[var(--fg)] data-active:bg-[var(--fg)] data-active:text-white"
            >
              {f}
            </TabsTrigger>
          ))}
        </TabsList>
        {missing.map((f) => (
          <Badge
            key={f}
            variant="outline"
            className="rounded-full border-dashed px-[11px] py-[3px] text-[11px] font-normal text-[var(--faint)]"
          >
            {f} 없음
          </Badge>
        ))}
      </div>
      {files.map((f) => (
        <TabsContent key={f} value={f}>
          <Markdown text={docs[f]} />
        </TabsContent>
      ))}
    </Tabs>
  )
}
