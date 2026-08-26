"""llm 큐 activity — Claude Code headless(`claude -p`)로 판정한다.

구독 인증(로그인된 CLI 또는 CLAUDE_CODE_OAUTH_TOKEN)은 이 모듈을 로드하는 llm 워커
프로세스에만 있다. io·workflow 모듈은 이 모듈을 import하지 않는다(테스트로 강제)."""
import hashlib
import json
import os
import subprocess
import tempfile
import time
from datetime import date

from temporalio import activity

from jobscouter.config import (APP_FILES, APP_EXAMPLE, APPLICATIONS, DATA, FACTBASE, JK_MD,
                               JOBFEED, JUDGE_MODEL, PROMPTS, JudgeInput, Judgment)


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

# 긴 자유 텍스트(reason)는 맨 끝 — 모델이 긴 문자열 뒤에 XML 파라미터 문법을 섞어 넣으면
# 뒤따르는 필드가 reason 안으로 삼켜져 스키마 검증이 계속 실패한다(2026-08-25 실측, 5/15건).
SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "scores": {"type": "array", "items": {"type": "integer"},
                   "minItems": 5, "maxItems": 5,
                   "description": "[스택0-35, 도메인0-25, 레벨0-20, 역할0-20, 감점-25~0]"},
        "exclude": {"type": "boolean",
                    "description": "핵심 업무 통째 미보유·직무 불일치 등 등재 불가"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "quotes": {"type": "array", "items": {"type": "string"},
                   "description": "근거가 된 자격요건 원문 인용 (짧게, 3개 이내)"},
        "reason": {"type": "string", "description": "판정 사유 3문장 이내"},
    },
    "required": ["scores", "exclude", "confidence", "quotes", "reason"],
}

# evidence(근거 발췌)가 가장 긴 자유 텍스트라 SCORE_SCHEMA와 같은 이유로 맨 끝에 둔다.
RESUME_SCHEMA = {
    "type": "object",
    "properties": {
        "proposals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "enum": ["factbase", "JK.md"]},
                    "section": {"type": "string", "description": "대상 문서 내 절 제목"},
                    "kind": {"type": "string", "enum": ["add", "change", "remove"]},
                    "current": {"type": "string",
                                "description": "change/remove 대상 원문 그대로. add면 빈 문자열"},
                    "proposed": {"type": "string",
                                 "description": "제안 내용(add/change). remove면 빈 문자열"},
                    "evidence": {"type": "string", "description": "근거 PKB 문서 제목·발췌"},
                },
                "required": ["target", "section", "kind", "current", "proposed", "evidence"],
            },
        },
    },
    "required": ["proposals"],
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
            schema: dict | None = None, timeout: int = 240) -> dict:
    """claude -p 1회. 결과 JSON(structured_output·result·usage·total_cost_usd)을 돌려준다.

    프롬프트는 argv로 넘기지 않는다 — 리눅스는 인수 하나가 128KB를 넘으면 실행 자체가
    실패한다(E2BIG, 실측: 초안 시스템 프롬프트 = 사실베이스+JK.md ≈ 110KB). 시스템 프롬프트는
    파일, 사용자 프롬프트는 stdin."""
    cmd = [CLAUDE, "-p", "--model", JUDGE_MODEL,
           "--effort", EFFORT, "--max-budget-usd", str(max_usd), *_LEAN]
    if schema:
        cmd += ["--json-schema", json.dumps(schema, ensure_ascii=False)]
    DATA.mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".md", dir=DATA, delete=False) as f:
        f.write(system)
    try:
        r = subprocess.run(cmd + ["--system-prompt-file", f.name], input=prompt,
                           capture_output=True, text=True, timeout=timeout, cwd=DATA)
    finally:
        os.unlink(f.name)
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
        reason=out["reason"].split("</")[0].strip(), quotes=list(out["quotes"]),
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


def _example_docs() -> str:
    folder = APPLICATIONS / APP_EXAMPLE
    parts = [f"=== FILE: {name} ===\n{(folder / name).read_text()}"
             for name in APP_FILES if (folder / name).exists()]
    return "\n\n".join(parts)


@activity.defn
def draft_application(company: str, title: str, posting: str) -> dict[str, str]:
    """승인 공고 1건의 지원서류 5종 초안. 사실베이스에 없는 주장 금지, 앵커 회사
    (APP_EXAMPLE)의 형식(섹션·표)을 따른다. 스키마 없음 — 자유 텍스트를
    `=== FILE: 이름 ===` 구분자로 split. 5개 미만이면 재시도용 예외."""
    readme_path = APPLICATIONS / "README.md"
    rules = readme_path.read_text() if readme_path.exists() else ""
    system = (
        f"<사실베이스>\n{FACTBASE.read_text()}\n</사실베이스>\n\n"
        f"<JK.md>\n{JK_MD.read_text()}\n</JK.md>\n\n"
        f"<지원서류 규칙>\n{rules}\n</지원서류 규칙>\n\n"
        f"<형식 예시 — {APP_EXAMPLE}사>\n{_example_docs()}\n</형식 예시>"
    )
    prompt = (
        f"회사: {company}\n포지션: {title}\n\n공고 전문:\n{posting}\n\n"
        "위 정보로 지원서류 5개 문서를 작성하라. `=== FILE: 파일명 ===` 구분자로 나눠 "
        "하나의 출력으로 이어 써라. 파일명은 정확히 이 순서·이름으로: "
        + ", ".join(APP_FILES) + ". "
        "사실베이스에 없는 주장은 절대 하지 말 것. 형식 예시의 섹션·표 구성을 유지할 것."
    )
    d = _claude(prompt, system, max_usd=1.0, timeout=600)
    files: dict[str, str] = {}
    for chunk in d["result"].split("=== FILE: ")[1:]:
        name, _, body = chunk.partition(" ===")
        files[name.strip()] = body.strip("\n")
    if len(files) < 5:
        raise RuntimeError(f"지원서류 초안 {len(files)}개뿐 — 5개 필요 (재시도)")
    return files


@activity.defn
def propose_resume_update(snapshot_text: str) -> list[dict]:
    """PKB curated 발췌(snapshot_text)를 사실베이스·JK.md와 대조해 갱신 제안만 낸다.
    이미 있는 내용은 제외, 날짜·숫자는 PKB 원문 그대로, 추정 금지. id는 여기서
    안 만든다(io_acts.save_resume_proposals가 내용 해시로 부여)."""
    system = (
        "너는 이력서 갱신 제안기다. PKB(개인 지식베이스) 최신 발췌를 사실베이스·JK.md와 "
        "대조해 반영할 변경만 제안한다. 규칙: 사실베이스·JK.md에 이미 있는 내용은 "
        "제안하지 않는다. 날짜·숫자는 PKB 원문 그대로 옮기고 추정하지 않는다. "
        "PKB 발췌에 근거 없는 내용은 절대 제안하지 않는다.\n\n"
        f"<사실베이스>\n{FACTBASE.read_text()}\n</사실베이스>\n\n"
        f"<JK.md>\n{JK_MD.read_text()}\n</JK.md>"
    )
    prompt = (f"<PKB 발췌>\n{snapshot_text}\n</PKB 발췌>\n\n"
              "위 PKB 발췌를 기준으로 사실베이스·JK.md 갱신 제안 목록을 만들어라. "
              "반영할 변경이 없으면 빈 목록을 반환하라.")
    d = _claude(prompt, system, max_usd=1.0, schema=RESUME_SCHEMA)
    return list(d["structured_output"]["proposals"])


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
