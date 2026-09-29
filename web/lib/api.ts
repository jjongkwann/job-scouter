// jobscouter/api.py 응답 JSON 계약과 1:1 — 타입을 바꾸려면 그쪽부터.

export type Rail = 'good' | 'warn' | 'bad' | 'none'
export type Tier = 't1' | 't2' | 't3'
export type DueCls = '' | 'u0' | 'u1' | 'gone' | 'always'

export type Proposal = {
  id: string; company: string; title: string; url: string; src: string; scores: number[]; total: number
  reason: string; quotes: string[]; confidence: number; rubric_version: string; judged_at: string
  cells: [number | string, '' | 'hi' | 'lo' | 'pen'][]; tier: Tier; rail: Rail; due: string; due_cls: DueCls; busy: boolean
  career: string; experience_review_required: boolean
}

export type PublishInfo = { id: string; status: string; start: string; ids: string[]; reject_ids: string[]; error: string }

export type ReceivedOffer = {
  id: string; company: string; title: string; job_id: string; received_at: string; status: string; message: string
  company_id: string; status_code: string; status_at: string; expires_at: string; offer_type: string; offer_mode: string; active: boolean
  url: string; job_url: string; rail: Rail; reason: string
  state: 'unassessed' | 'skipped' | 'excluded' | 'listed' | 'pending' | 'reviewed'
  assessment: Proposal | null; listed_scores: number[] | null; review: string; report_name: string
}
export type ReceivedOffers = { items: ReceivedOffer[]; collected_at: string; source_url: string }

export type Dashboard = {
  groups: { id: string; company: string; title: string; postings: Proposal[] }[]
  review_pending: Proposal[]
  unresearched: string[]; runs: { type: string; status: string; start: string }[]
  runs_error: string | null; publish: PublishInfo | null
  stats: { pending: number; postings: number; fit75: number; gone: number; unresearched: number }
}

export type Candidate = {
  id: string; company: string; title: string; url: string; src: string; scores: number[]; total: number; tier: Tier
  rep: [Rail, number, number | null, number | string, string] | null; rep_key: Rail; rep_label: string; rep_note: string
  tags: string[]; addr: string; zone: number; zone_label: string; due: string; due_cls: DueCls; days_left: number | null
  closed: boolean; rec: number; rank: number | null
  career: string; experience_review_required: boolean; experience_excluded: boolean; experience_reason: string
}

export type Candidates = { rows: Candidate[]; apps: Record<string, { slug: string; n: number }>; errors: string[]; updated: string }

export type ReportItem = { date: string | null; kind: string; name: string; title: string }
export type Report = { name: string; markdown: string }

export type Resume = { markdown: string; pending: number; chats: { sid: string; target: string; n: number }[] }

export type History = { key: string; commits: { sha: string; date: string; subject: string }[] }
export type Diff = { sha: string; diff: string }

export type ResumeProposal = { id: string; target: string; section: string; kind: string; current: string; proposed: string; evidence: string }

export type Turn = { role: 'user' | 'assistant'; text: string; applied?: number; skipped?: string[] }
export type ChatSession = { sid: string; target: string; exists: boolean; turns: Turn[]; diff: string; pending: boolean }

export type Folder = { slug: string; ids: string[]; files: string[]; docs: string[]; mtime: string }

export type Applications = {
  stats: { candidates: number; folders: number; linked: number; gone: number; unlinked: number }
  linked: (Folder & { c: Candidate; others: number })[]
  orphans: (Folder & { why: string; badge: string; cls: 'warn' | 'bad' })[]
}

export type JobApplication = {
  candidate: Candidate
  folder: Folder | null
  folders: Folder[] // 같은 공고를 가리키는 폴더 전부 — 원본 + 재생성 슬롯(_draft)
  others: Candidate[]
  docs: Record<string, string>
  drafting: boolean
}
export type SlugApplication = { folder: Folder; docs: Record<string, string>; linked_cid: string | null }

export type DocItem = { path: string; name: string; group: string }
export type Doc = { path: string; markdown: string }

export type WorkflowInfo = { id: string; type: string; status: string; stage: string | null; error: string; start: string }
// 오류: { detail: string }.  SSE: `event: workflow\ndata: <WorkflowInfo JSON>\n\n`, 15초마다 `: ping\n\n`

export class ApiError extends Error {
  constructor(public status: number, public detail: string, public conflict = false) {
    super(detail)
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`/api${path}`, { ...init, headers: { 'content-type': 'application/json', ...(init?.headers ?? {}) } })
  if (!r.ok) {
    const j = await r.json().catch(() => ({}))
    throw new ApiError(r.status, j.detail ?? j.cause ?? r.statusText, !!j.conflict)
  }
  return r.json()
}

export const get = <T,>(path: string) => call<T>(path)
export const post = <T,>(path: string, body: unknown) => call<T>(path, { method: 'POST', body: JSON.stringify(body) })
