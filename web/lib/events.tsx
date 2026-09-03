'use client'
import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import type { WorkflowInfo } from './api'

export const WF_LABEL: Record<string, string> = {
  Publish: '승인 처리',
  DailyScan: '일일 스캔',
  ResumeSync: '이력서 갱신 제안',
  ApplyResume: '제안 반영',
  Draft: '지원서류 초안',
  Drafts: '지원서류 초안(일괄)',
  RevertFile: '되돌리기',
  ResumeChat: '대화 턴',
  EndChat: '대화 종료',
}

export function WorkflowEvents() {
  const qc = useQueryClient()
  useEffect(() => {
    const es = new EventSource('/api/events')
    let first = true // 접속 직후 스냅샷은 토스트 없이 상태만 맞춘다
    const t = setTimeout(() => {
      first = false
    }, 3000)
    es.addEventListener('workflow', (e) => {
      const w = JSON.parse((e as MessageEvent).data) as WorkflowInfo
      qc.invalidateQueries()
      if (first) return
      const name = WF_LABEL[w.type] ?? w.type
      if (w.status === 'RUNNING') toast(`${name} 진행 중${w.stage ? ` — ${w.stage}` : ''}`, { id: w.id })
      else if (w.status === 'COMPLETED') toast.success(`${name} 완료`, { id: w.id })
      else toast.error(`${name} ${w.status}${w.error ? ` — ${w.error}` : ''}`, { id: w.id, duration: 10000 })
    })
    return () => {
      clearTimeout(t)
      es.close()
    }
  }, [qc])
  return null
}
