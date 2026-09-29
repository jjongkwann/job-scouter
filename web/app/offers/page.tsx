'use client'
import { useState } from 'react'
import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { get, type ReceivedOffer, type ReceivedOffers } from '@/lib/api'
import { jobplanetUrl } from '@/lib/utils'
import { Page } from '@/components/page'
import { Markdown } from '@/components/markdown'
import { Fit } from '@/components/fit'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'

const STATES = { unassessed: '평가 전', pending: '후보 승인 대기', listed: '후보 등록', excluded: '평가 제외', skipped: '후보에서 제외함', reviewed: '평가·조사 기록 있음' }
const RAILS = { good: '괜찮음', warn: '주의', bad: '회피·사용자 제외', none: '정보 부족' }

export default function OffersPage() {
  const [filter, setFilter] = useState('active')
  const q = useQuery({ queryKey: ['offers'], queryFn: () => get<ReceivedOffers>('/offers'), refetchInterval: 10000 })
  const items = q.data?.items ?? []
  const visible = items.filter((item) => filter === 'all' || (filter === 'active' ? item.active : filter === 'history' ? !item.active : filter === 'research' ? item.active && !item.review : item.active && item.state === 'unassessed'))
  return (
    <Page title="받은 제안" sub="원티드에서 회사가 보낸 제안입니다. 제안 내용과 내 경력 적합도, 기업 조사 결과를 확인한 뒤 원티드에서 답변하세요."
      stats={[[q.data ? items.filter((i) => i.active).length : '–', '답변 대기'], [q.data ? items.length : '–', '전체 수신 이력'],
        [q.data ? items.filter((i) => i.active && !i.review).length : '–', '대기 제안 중 미조사']]}
      source={q.data?.collected_at ? `원티드 · 마지막 수집 ${q.data.collected_at}` : '아직 수집하지 않았습니다'}>
      <div className="toolbar">
        <a href="https://www.wanted.co.kr/status/proposal?kind=OFFER" target="_blank" rel="noopener noreferrer" className="page-link">원티드 제안 목록 열기 ↗</a>
        <label className="flex min-w-0 flex-wrap items-center gap-2 text-[13px]">보기
          <select aria-label="제안 필터" className="max-w-full" value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="active">답변 대기</option><option value="history">수락·거절·만료 이력</option><option value="all">전체</option><option value="unassessed">답변 대기 중 평가 전</option><option value="research">답변 대기 중 미조사</option>
          </select>
        </label>
      </div>
      {q.error && <Card role="alert" className="mb-3 p-4 text-[var(--bad)]">제안을 불러오지 못했습니다: {q.error.message}</Card>}
      {q.isPending && <Skeleton className="h-48 w-full" />}
      {q.data && !items.length && <Card className="empty-state">수집된 제안이 없습니다. 로그인한 Chrome의 원티드 제안 목록을 확인해 수집을 요청하세요.</Card>}
      {q.data && items.length > 0 && !visible.length && <p className="empty-state">이 조건에 맞는 제안이 없습니다.</p>}
      <p className="mb-4 text-[12px] text-[var(--dim)]">{q.data?.collected_at ? `마지막 수집 ${q.data.collected_at} · 응답 상태는 원티드에서 다시 확인하세요.` : q.isPending ? '제안 정보를 불러오는 중입니다.' : q.data ? '수집 시점이 기록되지 않았습니다.' : ''}</p>
      <div className="space-y-4">{visible.map((item) => <OfferCard key={item.id} item={item} />)}</div>
    </Page>
  )
}

function OfferCard({ item }: { item: ReceivedOffer }) {
  const [request, setRequest] = useState('')
  const copyRequest = async () => {
    const text = `Job Scouter의 원티드 받은 제안 ${item.id} (${item.company} / ${item.title})을 평가하고 조사해 주세요.\n제안 목록: ${item.url}\n${item.job_url ? `공고: ${item.job_url}\n` : '연결된 공고가 없어 원티드 제안 상세에서 직무 요건부터 확인해 주세요.\n'}제안 원문과 이력서 사실베이스·현재 루브릭을 대조하고, 적합/제외 사유·기업 공식 정보·평판 근거·확인할 질문을 출처 및 조사일과 함께 정리해 주세요. 결과는 jobfeed/reports/wanted_offer_${item.id}.md에 저장해 받은 제안 화면에서 확인하게 해 주세요. 원티드 답변은 제가 합니다.`
    try {
      await navigator.clipboard.writeText(text)
      toast('평가·조사 요청을 복사했습니다. 대화에 붙여넣으세요.')
    } catch {
      setRequest(text)
    }
  }
  const assessment = item.assessment
  return (
    <Card className={`gap-4 p-5 rail rail-${item.rail}`} >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-[16px] font-semibold break-words">{item.company} · {item.title}</h2>
          <p className="mt-1 text-xs text-[var(--dim)]">수신 {item.received_at.replace('T', ' ') || '날짜 미확인'} · 제안 #{item.id}</p>
          {item.expires_at && <p className="mt-1 text-xs text-[var(--dim)]">응답 기한 {item.expires_at.replace('T', ' ')} · 원티드 표시 기준</p>}
        </div>
        <div className="flex flex-wrap gap-1.5">
          <Badge variant="secondary">원티드: {item.status || '상태 미확인'}</Badge>
          {item.offer_mode === 'AUTO' && <Badge variant="outline">자동 발송</Badge>}
          <Badge variant="outline">검토: {STATES[item.state]}</Badge>
          <Badge variant="outline">평판: {RAILS[item.rail]}</Badge>
        </div>
      </div>
      {assessment ? <div className="flex flex-wrap items-center gap-2 text-[13px] [&_a]:inline-flex [&_a]:min-h-11 [&_a]:items-center [&_a]:text-[var(--link)] [&_a]:underline"><span className="text-[var(--dim)]">적합도</span><div className="w-28"><Fit total={assessment.total} tier={assessment.tier} /></div><span>기존 공고 평가 · {assessment.judged_at || '날짜 미확인'}</span></div>
        : item.listed_scores ? <p className="text-sm">등록된 공고 적합도 {item.listed_scores.reduce((sum, score) => sum + score, 0)}점</p>
          : <p className="text-sm text-[var(--dim)]">{item.review ? '아래 보고서에서 적합도와 확인할 조건을 살펴보세요.' : item.job_id ? '공고 적합도 평가가 없습니다.' : '연결된 공고 없음 · 제안 상세의 직무 요건을 확인해야 합니다.'}</p>}
      {item.reason && <p className="text-sm leading-relaxed">{item.state === 'listed' && '기존 후보 메모: '}{item.reason}</p>}
      {assessment && assessment.quotes.length > 0 && <details className="text-sm"><summary className="cursor-pointer">평가 근거 인용</summary><ul className="mt-2 list-disc pl-5">{assessment.quotes.map((quote, i) => <li key={i}>{quote}</li>)}</ul></details>}
      <details className="text-sm"><summary className="cursor-pointer">받은 제안 원문</summary><p className="mt-2 whitespace-pre-wrap leading-relaxed">{item.message || '아직 상세 내용을 수집하지 않았습니다.'}</p></details>
      {item.review ? <><details className="text-sm"><summary className="cursor-pointer font-medium">평가·기업 조사 보고서 보기</summary><div className="mt-3"><Markdown text={item.review} /></div></details></>
        : <p className="text-sm text-[var(--dim)]">조사 보고서가 없습니다. 평가·조사 요청을 복사해 대화에 붙여넣으세요.</p>}
      <div className="flex flex-wrap items-center gap-2 text-[13px] [&_a]:inline-flex [&_a]:min-h-11 [&_a]:items-center [&_a]:text-[var(--link)] [&_a]:underline">
        <a href={item.url} target="_blank" rel="noopener noreferrer">원티드에서 확인·답변 ↗</a>
        {item.job_url && <a href={item.job_url} target="_blank" rel="noopener noreferrer">공고 원문 ↗</a>}
        <a href={jobplanetUrl(item.company)} target="_blank" rel="noopener noreferrer">잡플래닛 ↗</a>
        {item.state === 'pending' && <Link href="/">후보 승인 검토</Link>}
        {item.state === 'listed' && item.job_id && <Link href={`/applications/job/${encodeURIComponent(item.job_id)}`}>지원서류</Link>}
        {item.report_name && <Link href={`/reports/${encodeURIComponent(item.report_name)}`}>보고서 전체</Link>}
        <Button size="sm" variant="outline" onClick={copyRequest}>{item.review ? '재평가·조사 요청 복사' : '평가·조사 요청 복사'}</Button>
      </div>
      {item.active && <p className="text-xs text-[var(--dim)]">{item.offer_type === 'INTERVIEW' ? '면접 제안입니다. 수락 후 연락 방식과 직무 범위를 원티드에서 확인하세요.' : '지원 제안입니다. 수락하면 이력서가 전달되고 지원 완료로 처리될 수 있으므로 원티드 안내를 확인하세요.'}</p>}
      {request && <label className="text-sm">아래 요청을 복사해 대화에 붙여넣으세요<textarea aria-label="평가·조사 요청" readOnly value={request} onFocus={(e) => e.target.select()} className="mt-2 min-h-32 w-full rounded-xl border border-[var(--line)] p-3 text-base" /></label>}
    </Card>
  )
}
