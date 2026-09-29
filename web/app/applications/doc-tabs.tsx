'use client'
import { useState, type ReactNode } from 'react'

import { Markdown } from '@/components/markdown'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

// jobscouter/config.py APP_FILES — Draft가 만드는 표준 5종. 없는 건 탭 대신 점선 배지로 자리만 보여 준다.
export const APP_FILES = ['0_JD.md', '1_맞춤_이력서.md', '2_자기소개서.md', '3_면접지식맵.md', '4_포트폴리오_구성.md']
const DOC_LABELS: Record<string, string> = {
  '0_JD.md': '공고',
  '1_맞춤_이력서.md': '맞춤 이력서',
  '2_자기소개서.md': '자기소개서',
  '3_면접지식맵.md': '면접 준비',
  '4_포트폴리오_구성.md': '포트폴리오 구성',
}

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
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="text-[12px] text-[var(--dim)]">초안 문서</span>
        <TabsList variant="line" className="h-auto max-w-full flex-wrap justify-start gap-x-3 gap-y-2 p-0">
          {files.map((f) => (
            <TabsTrigger
              key={f}
              value={f}
              title={f}
              className="min-h-11 flex-none rounded-none px-1 py-2 text-[13px] font-medium"
            >
              {DOC_LABELS[f] ?? f}
            </TabsTrigger>
          ))}
        </TabsList>
        {missing.map((f) => (
          <Badge
            key={f}
            variant="outline"
            title={f}
            className="rounded-md border-dashed px-2 py-1 text-[12px] font-normal text-[var(--dim)]"
          >
            {DOC_LABELS[f]} 없음
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
