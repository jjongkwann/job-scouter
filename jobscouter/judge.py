"""llm 큐 activity — ANTHROPIC_API_KEY는 이 모듈을 로드하는 워커 프로세스에만 있다."""
import hashlib
import json
import time

from temporalio import activity

from jobscouter.config import (DATA, FACTBASE, JOBFEED, JUDGE_MODEL, PROMPTS,
                               JudgeInput, Judgment)

RUBRIC_VERSION = "v1"
_CAPS = [35, 25, 20, 20]
_CACHE = DATA / "judgments.jsonl"

SCORE_TOOL = {
    "name": "score_job",
    "description": "공고 1건의 루브릭 채점 결과",
    "input_schema": {
        "type": "object",
        "properties": {
            "scores": {"type": "array", "items": {"type": "integer"},
                       "minItems": 5, "maxItems": 5,
                       "description": "[스택0-35, 도메인0-25, 레벨0-20, 역할0-20, 감점-25~0]"},
            "exclude": {"type": "boolean",
                        "description": "핵심 업무 통째 미보유·직무 불일치 등 등재 불가"},
            "reason": {"type": "string", "description": "판정 사유 3문장 이내"},
            "quotes": {"type": "array", "items": {"type": "string"},
                       "description": "근거가 된 자격요건 원문 인용"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["scores", "exclude", "reason", "quotes", "confidence"],
    },
}


def factbase_hash() -> str:
    return hashlib.sha256(FACTBASE.read_bytes()).hexdigest()[:12]


def _cache_key(inp: JudgeInput, fb_hash: str) -> str:
    return f"{inp.target.id}|{RUBRIC_VERSION}|{fb_hash}"


def _load_cache() -> dict[str, dict]:
    if not _CACHE.exists():
        return {}
    return {r["key"]: r for r in map(json.loads, _CACHE.read_text().splitlines())}


def _validate(s: list[int]) -> list[int]:
    if len(s) != 5:
        raise ValueError(f"점수 {len(s)}원소 (5원소여야 함)")
    for i, (v, m) in enumerate(zip(s, _CAPS)):
        if not 0 <= v <= m:
            raise ValueError(f"{['스택','도메인','레벨','역할'][i]} {v} (상한 {m})")
    if not -25 <= s[4] <= 0:
        raise ValueError(f"감점 {s[4]} (범위 -25~0)")
    return s


@activity.defn
def judge(inp: JudgeInput) -> Judgment:
    fb = factbase_hash()
    key = _cache_key(inp, fb)
    hit = _load_cache().get(key)
    if hit:
        return Judgment(**hit["judgment"], cached=True)

    import anthropic  # llm 워커에서만 로드
    client = anthropic.Anthropic()
    rubric = (PROMPTS / f"rubric_{RUBRIC_VERSION}.md").read_text()
    system = [{"type": "text",
               "text": rubric.replace("{factbase}", FACTBASE.read_text()),
               "cache_control": {"type": "ephemeral"}}]  # 사이클 내 불변 → 캐시 적중
    user = (f"회사: {inp.target.company}\n포지션: {inp.target.title}\n"
            f"출처: {inp.target.src} {inp.target.url}\n\n"
            f"자격요건 원문:\n{inp.requirements}")
    if inp.search_context:
        user += f"\n\n<검색 컨텍스트>\n{inp.search_context}\n</검색 컨텍스트>"

    t0 = time.monotonic()
    r = client.messages.create(
        model=JUDGE_MODEL, max_tokens=inp.max_tokens, system=system,
        messages=[{"role": "user", "content": user}],
        tools=[SCORE_TOOL], tool_choice={"type": "tool", "name": "score_job"})
    out = next(b.input for b in r.content if b.type == "tool_use")
    scores = _validate([int(x) for x in out["scores"]])

    j = Judgment(
        id=inp.target.id, company=inp.target.company, title=inp.target.title,
        scores=scores, total=sum(scores), exclude=bool(out["exclude"]),
        reason=out["reason"], quotes=list(out["quotes"]),
        confidence=float(out["confidence"]), rubric_version=RUBRIC_VERSION,
        usage={"in": r.usage.input_tokens, "out": r.usage.output_tokens,
               "cache_read": getattr(r.usage, "cache_read_input_tokens", 0) or 0,
               "model": JUDGE_MODEL,
               "ms": int((time.monotonic() - t0) * 1000)})
    DATA.mkdir(exist_ok=True)
    rec = {"key": key, "judgment": {k: v for k, v in j.__dict__.items()
                                    if k != "cached"}}
    with _CACHE.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return j


@activity.defn
def report(stats: dict) -> str:
    """사이클 요약 md — 서술은 LLM, 수치는 stats 그대로."""
    import anthropic
    from datetime import date

    client = anthropic.Anthropic()
    r = client.messages.create(
        model=JUDGE_MODEL, max_tokens=1500,
        messages=[{"role": "user", "content":
                   "다음 job-scouter 사이클 통계로 간결한 운영 보고서 md를 써라. "
                   "섹션: 요약(2문장) / 등재·제외 / 강등·실패 / 비용·latency. "
                   "수치를 지어내지 말 것:\n" + json.dumps(stats, ensure_ascii=False)}])
    body = r.content[0].text
    path = JOBFEED / "reports" / f"{date.today()}_자동사이클.md"
    path.write_text(f"# {date.today()} 자동 사이클\n\n{body}\n")
    return str(path)
