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

export function DocTabs({ docs, empty, value, onValueChange }: {
  docs: Record<string, string>; empty: ReactNode; value?: string; onValueChange?: (file: string) => void
}) {
  const files = Object.keys(docs)
  const [tab, setTab] = useState('')
  const selected = value ?? tab
  // 폴더를 바꾸어 선택한 문서가 없을 때는 이유를 알리고 첫 문서를 대신 연다.
  const cur = files.includes(selected) ? selected : (files[0] ?? '')
  const missing = APP_FILES.filter((f) => !files.includes(f))

  if (!cur)
    return <Card className="rounded-[9px] p-8 text-center text-[13px] leading-[1.7] text-[var(--dim)]">
      {selected && <p role="status">이 폴더에는 {DOC_LABELS[selected] ?? selected} 문서가 없습니다.</p>}
      {empty}
    </Card>

  return (
    <Tabs value={cur} onValueChange={(v) => (onValueChange ?? setTab)(String(v))}>
      {selected && !files.includes(selected) && (
        <p role="status" className="notice text-[var(--warn)]">
          이 폴더에는 {DOC_LABELS[selected] ?? selected} 문서가 없습니다. 대신 {DOC_LABELS[cur] ?? cur} 문서를 표시합니다.
        </p>
      )}
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
