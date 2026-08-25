"""llm 큐 activity — Claude Code headless(`claude -p`)로 판정한다.

구독 인증(로그인된 CLI 또는 CLAUDE_CODE_OAUTH_TOKEN)은 이 모듈을 로드하는 llm 워커
프로세스에만 있다. io·workflow 모듈은 이 모듈을 import하지 않는다(테스트로 강제)."""
import hashlib
import json
import os
import subprocess
import time
from datetime import date

from temporalio import activity

from jobscouter.config import (DATA, FACTBASE, JOBFEED, JUDGE_MODEL, PROMPTS,
                               JudgeInput, Judgment)

RUBRIC_VERSION = "v1"
EFFORT = "medium"
CLAUDE = os.environ.get("JOBSCOUTER_CLAUDE", "claude")
_CAPS = [35, 25, 20, 20]
_CACHE = DATA / "judgments.jsonl"
# 린 모드 — 사용자 설정·MCP·도구를 전부 빼야 호출당 ~1k 토큰. 기본 모드는 MCP 도구
# 스키마만 수십만 토큰을 실어 보낸다(실측 245k). --bare는 구독 로그인을 안 읽어 못 쓴다.
_LEAN = ["--output-format", "json", "--tools", "", "--no-session-persistence",
         "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
         "--setting-sources", ""]

SCORE_SCHEMA = {
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


def _claude(prompt: str, system: str, max_usd: float,
            schema: dict | None = None) -> dict:
    """claude -p 1회. 결과 JSON(structured_output·result·usage·total_cost_usd)을 돌려준다."""
    cmd = [CLAUDE, "-p", prompt, "--system-prompt", system, "--model", JUDGE_MODEL,
           "--effort", EFFORT, "--max-budget-usd", str(max_usd), *_LEAN]
    if schema:
        cmd += ["--json-schema", json.dumps(schema, ensure_ascii=False)]
    DATA.mkdir(exist_ok=True)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=240, cwd=DATA)
    try:
        d = json.loads(r.stdout)
    except ValueError:
        raise RuntimeError(f"claude -p exit {r.returncode}: {(r.stderr or r.stdout)[-300:]}")
    if r.returncode != 0 or d.get("is_error"):
        raise RuntimeError(f"claude -p 실패 {d.get('subtype')}: {str(d.get('result'))[:300]}")
    return d


@activity.defn
def judge(inp: JudgeInput) -> Judgment:
    fb = factbase_hash()
    key = _cache_key(inp, fb)
    hit = _load_cache().get(key)
    if hit:
        return Judgment(**hit["judgment"], cached=True)

    rubric = (PROMPTS / f"rubric_{RUBRIC_VERSION}.md").read_text()
    system = rubric.replace("{factbase}", FACTBASE.read_text())  # 사이클 내 불변 → 캐시 적중
    user = (f"회사: {inp.target.company}\n포지션: {inp.target.title}\n"
            f"출처: {inp.target.src} {inp.target.url}\n\n"
            f"자격요건 원문:\n{inp.requirements}")
    if inp.search_context:
        user += f"\n\n<검색 컨텍스트>\n{inp.search_context}\n</검색 컨텍스트>"

    t0 = time.monotonic()
    d = _claude(user, system, inp.max_usd, SCORE_SCHEMA)
    out = d["structured_output"]
    scores = _validate([int(x) for x in out["scores"]])
    u = d.get("usage") or {}

    j = Judgment(
        id=inp.target.id, company=inp.target.company, title=inp.target.title,
        scores=scores, total=sum(scores), exclude=bool(out["exclude"]),
        reason=out["reason"], quotes=list(out["quotes"]),
        confidence=float(out["confidence"]), rubric_version=RUBRIC_VERSION,
        usage={"in": u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0),
               "out": u.get("output_tokens", 0),
               "cache_read": u.get("cache_read_input_tokens", 0),
               "usd": d.get("total_cost_usd", 0), "model": JUDGE_MODEL,
               "ms": int((time.monotonic() - t0) * 1000)})
    rec = {"key": key, "judgment": {k: v for k, v in j.__dict__.items()
                                    if k != "cached"}}
    with _CACHE.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return j


@activity.defn
def report(stats: dict) -> str:
    """사이클 요약 md — 서술은 LLM, 수치는 stats 그대로."""
    d = _claude(
        "다음 job-scouter 사이클 통계로 간결한 운영 보고서 md를 써라. "
        "섹션: 요약(2문장) / 등재·제외 / 강등·실패 / 비용·latency. "
        "수치를 지어내지 말 것:\n" + json.dumps(stats, ensure_ascii=False),
        "너는 운영 보고서 작성기다. 마크다운 본문만 출력한다.", max_usd=0.2)
    path = JOBFEED / "reports" / f"{date.today()}_자동사이클.md"
    path.write_text(f"# {date.today()} 자동 사이클\n\n{d['result']}\n")
    return str(path)
