"""llm 큐 activity — Codex CLI(`codex exec`)로 판정한다.

구독 인증(로그인된 Codex CLI)은 이 모듈을 로드하는 llm 워커
프로세스에만 있다. io·workflow 모듈은 이 모듈을 import하지 않는다(테스트로 강제)."""
import hashlib
import json
import os
import signal
import subprocess
import tempfile
import time
from datetime import date
from pathlib import Path

from temporalio import activity

from jobscouter.config import (APP_FILES, APP_EXAMPLE, APPLICATIONS, DATA, FACTBASE, RESUME,
                               JOBFEED, JUDGE_MODEL, REASONING_EFFORT, PROMPTS, RUBRIC_VERSION, JudgeInput,
                               Judgment)


CODEX = os.environ.get("JOBSCOUTER_CODEX", "codex")
_CAPS = [35, 25, 20, 20]
_CACHE = DATA / "judgments.jsonl"
# 생성 전용 실행: 호스트 설정·프로젝트 지침·외부 도구를 읽지 않는다.
_LEAN = ["--ignore-user-config", "--ignore-rules", "--ephemeral",
         "--skip-git-repo-check", "--sandbox", "read-only", "--json"]
_CONFIG = {
    "project_doc_max_bytes": 0,
    "web_search": "disabled",
    **{f"features.{name}": False for name in (
        "shell_tool", "apps", "plugins", "multi_agent", "code_mode",
        "code_mode_host", "browser_use", "computer_use", "image_generation", "view_image")},
}

SCORE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "scores": {"type": "array", "items": {"type": "integer"},
                   "minItems": 5, "maxItems": 5,
                   "description": "[스택0-35, 도메인0-25, 레벨0-20, 역할0-20, 감점-25~0]"},
        "exclude": {"type": "boolean",
                    "description": "등재 불가 — 필수 주력 스택이 사실베이스 보유 스킬에 없음·직무 불일치·핵심 업무 통째 미보유·스킬 대조 불가"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "quotes": {"type": "array", "items": {"type": "string"},
                   "description": "근거가 된 자격요건 원문 인용 (짧게, 3개 이내)"},
        "reason": {"type": "string", "description": "판정 사유 3문장 이내"},
    },
    "required": ["scores", "exclude", "confidence", "quotes", "reason"],
}

RESUME_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "proposals": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "target": {"type": "string", "enum": ["factbase", "이력서.md"]},
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

CHAT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "edits": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "current": {"type": "string",
                                "description": "고칠 원문을 문서에서 그대로 인용. 문서에 정확히 한 번만 나오는 만큼 길게"},
                    "proposed": {"type": "string", "description": "대체할 내용. 삭제면 빈 문자열"},
                    "why": {"type": "string", "description": "이 수정을 하는 이유 한 문장"},
                },
                "required": ["current", "proposed", "why"],
            },
        },
        "reply": {"type": "string", "description": "사용자에게 보일 답변"},
    },
    "required": ["edits", "reply"],
}


def factbase_hash() -> str:
    return hashlib.sha256(FACTBASE.read_bytes()).hexdigest()[:12]


def _cache_key(inp: JudgeInput, fb_hash: str) -> str:
    return f"{inp.target.id}|{RUBRIC_VERSION}|{fb_hash}|{JUDGE_MODEL}|{REASONING_EFFORT}"


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


def _codex(prompt: str, system: str, schema: dict | None = None,
           timeout: int = 240) -> dict:
    """Codex 1회. 큰 시스템 프롬프트는 파일, 사용자 프롬프트는 stdin으로 전달한다."""
    DATA.mkdir(exist_ok=True)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="codex-", dir=DATA) as tmp:
        folder = Path(tmp).resolve()
        instructions, output = folder / "instructions.md", folder / "output.txt"
        instructions.write_text(system)
        config = {**_CONFIG, "model_reasoning_effort": REASONING_EFFORT,
                  "model_instructions_file": str(instructions)}
        cmd = [CODEX, "exec", "--model", JUDGE_MODEL, *_LEAN]
        for key, value in config.items():
            cmd += ["--config", f"{key}={json.dumps(value)}"]
        if schema is not None:
            schema_path = folder / "schema.json"
            schema_path.write_text(json.dumps(schema, ensure_ascii=False))
            cmd += ["--output-schema", str(schema_path)]
        cmd += ["--output-last-message", str(output), "-"]
        with subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, cwd=folder,
                              start_new_session=True) as proc:
            try:
                stdout, stderr = proc.communicate(prompt, timeout=timeout)
            except subprocess.TimeoutExpired:
                # npm 런처뿐 아니라 자식 Codex 프로세스도 종료해 백그라운드 생성을 막는다.
                os.killpg(proc.pid, signal.SIGKILL)
                proc.communicate()
                raise
        if proc.returncode:
            raise RuntimeError(f"codex exec exit {proc.returncode}: {(stderr or stdout)[-300:]}")
        events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        if any(e["type"] in ("turn.failed", "error") for e in events):
            raise RuntimeError("codex exec 실패: " + str(events[-1])[:300])
        turns = [e["usage"] for e in events if e["type"] == "turn.completed"]
        if not turns or not output.exists() or not output.read_text().strip():
            raise RuntimeError("codex exec 완료 응답 또는 사용량 누락")
        usage = {}
        for key in ("input_tokens", "output_tokens", "cached_input_tokens"):
            values = [u.get(key) for u in turns]
            if any(type(v) is not int or v < 0 for v in values):
                raise RuntimeError(f"codex exec 사용량 오류: {key}")
            usage[key] = sum(values)
        result = output.read_text()
        d = {"result": result, "usage": usage}
        if schema is not None:
            d["structured_output"] = json.loads(result)
        print(json.dumps({"event": "codex.completed", "model": JUDGE_MODEL,
                          "reasoning_effort": REASONING_EFFORT, "usage": usage,
                          "ms": int((time.monotonic() - started) * 1000)}), flush=True)
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
    d = _codex(user, system, SCORE_SCHEMA)
    out = d["structured_output"]
    scores = _validate([int(x) for x in out["scores"]])
    u = d.get("usage") or {}

    j = Judgment(
        id=inp.target.id, company=inp.target.company, title=inp.target.title,
        scores=scores, total=sum(scores), exclude=bool(out["exclude"]),
        reason=out["reason"].split("</")[0].strip(), quotes=list(out["quotes"]),
        confidence=float(out["confidence"]), rubric_version=RUBRIC_VERSION,
        usage={"in": u["input_tokens"],
               "out": u["output_tokens"],
               "cache_read": u["cached_input_tokens"],
               "usd": None, "model": JUDGE_MODEL, "reasoning_effort": REASONING_EFFORT,
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
def draft_application(target: dict, posting: str) -> dict[str, str]:
    """승인 공고 1건의 지원서류 5종 초안. target은 listed_target dict(company·title·scores·reason).
    판정의 약한 축·감점 사유를 프롬프트에 실어 그 약점을 보완하는 근거를 앞세우게 한다.
    사실베이스에 없는 주장 금지, 앵커 회사(APP_EXAMPLE)의 형식(섹션·표)만 따른다.
    스키마 없음 — 자유 텍스트를 `=== FILE: 이름 ===` 구분자로 split. APP_FILES 이름이
    하나라도 빠지면(개수 부족·파일명 오타) 재시도용 예외 — 이 검증은 LLM 단계에 있어야
    io 단계가 아니라 LLM 호출이 재시도된다."""
    readme_path = APPLICATIONS / "README.md"
    rules = readme_path.read_text() if readme_path.exists() else ""
    system = (
        f"<사실베이스>\n{FACTBASE.read_text()}\n</사실베이스>\n\n"
        f"<이력서>\n{RESUME.read_text()}\n</이력서>\n\n"
        f"<지원서류 규칙>\n{rules}\n</지원서류 규칙>\n\n"
        f"<형식 예시 — {APP_EXAMPLE}사>\n{_example_docs()}\n</형식 예시>"
    )
    scores = list(target["scores"]) + [0] * (5 - len(target["scores"]))
    axes = ["스택", "도메인", "레벨", "역할"]
    judgment = "\n".join(
        [f"{a}: {v}/{m}" for a, v, m in zip(axes, scores, _CAPS)]
        + [f"감점: {scores[4]}", f"총점: {sum(scores)}", f"사유: {target['reason']}"])
    prompt = (
        f"회사: {target['company']}\n포지션: {target['title']}\n\n"
        f"<판정>\n{judgment}\n</판정>\n\n공고 전문:\n{posting}\n\n"
        "위 정보로 지원서류 5개 문서를 작성하라. `=== FILE: 파일명 ===` 구분자로 나눠 "
        "하나의 출력으로 이어 써라. 파일명은 정확히 이 순서·이름으로: "
        + ", ".join(APP_FILES) + ".\n"
        "- 판정에서 점수가 낮은 축과 감점 사유를 확인하고, 사실베이스 안에서 그 약점을 보완하는 "
        "근거를 1_맞춤_이력서·2_자기소개서에 우선 배치할 것.\n"
        "- 공고의 자격요건·우대사항 항목마다 사실베이스 근거를 대응시킬 것. 근거가 없는 항목은 "
        "없다고 두고 지어내지 말 것. 사실베이스에 없는 주장은 절대 하지 말 것.\n"
        "- 형식 예시 문서의 회사 고유 내용(회사명·프로젝트명·수치·사례)은 절대 옮기지 말고 "
        "섹션·표 구조만 따를 것."
    )
    d = _codex(prompt, system, timeout=600)
    files: dict[str, str] = {}
    for chunk in d["result"].split("=== FILE: ")[1:]:
        name, _, body = chunk.partition(" ===")
        files[name.strip()] = body.strip("\n")
    missing = [n for n in APP_FILES if n not in files]
    if missing:
        raise RuntimeError(f"지원서류 파일 누락 {missing} — 출력 {sorted(files)} (재시도)")
    return {n: files[n] for n in APP_FILES}


@activity.defn
def propose_resume_update(snapshot_text: str) -> list[dict]:
    """PKB curated 발췌(snapshot_text)를 사실베이스·이력서.md와 대조해 갱신 제안만 낸다.
    이미 있는 내용은 제외, 날짜·숫자는 PKB 원문 그대로, 추정 금지. id는 여기서
    안 만든다(io_acts.save_resume_proposals가 내용 해시로 부여)."""
    system = (
        "너는 이력서 갱신 제안기다. PKB(개인 지식베이스) 최신 발췌를 사실베이스·이력서.md와 "
        "대조해 반영할 변경만 제안한다. 규칙: 사실베이스·이력서.md에 이미 있는 내용은 "
        "제안하지 않는다. 날짜·숫자는 PKB 원문 그대로 옮기고 추정하지 않는다. "
        "PKB 발췌에 근거 없는 내용은 절대 제안하지 않는다.\n\n"
        f"<사실베이스>\n{FACTBASE.read_text()}\n</사실베이스>\n\n"
        f"<이력서>\n{RESUME.read_text()}\n</이력서>"
    )
    prompt = (f"<PKB 발췌>\n{snapshot_text}\n</PKB 발췌>\n\n"
              "위 PKB 발췌를 기준으로 사실베이스·이력서.md 갱신 제안 목록을 만들어라. "
              "반영할 변경이 없으면 빈 목록을 반환하라.")
    d = _codex(prompt, system, schema=RESUME_SCHEMA)
    return list(d["structured_output"]["proposals"])


@activity.defn
def resume_chat(doc: str, turns: list[dict], message: str) -> dict:
    """이력서 편집 대화 한 턴. 문서 전문을 되받지 않고 current→proposed 치환 목록만 받는다.
    system은 세션 내 불변(사실베이스+규칙)이라 프롬프트 캐시가 먹는다."""
    system = (
        f"<사실베이스>\n{FACTBASE.read_text()}\n</사실베이스>\n\n"
        "너는 이력서 편집 조수다. 사실베이스에 없는 주장은 절대 만들지 않는다. "
        "수정은 `edits`로만 낸다. `current`는 문서에 정확히 한 번 나오도록 충분히 길게 "
        "인용한다. 내용을 새로 넣을 때도 인접한 기존 문장을 `current`로 인용하고 "
        "`proposed`에 그 문장 + 새 내용을 함께 쓴다. 고칠 게 없으면 `edits`를 빈 배열로 "
        "두고 `reply`만 쓴다."
    )
    convo = "\n".join(
        f"[사용자] {t['text']}" if t["role"] == "user" else f"[조수] {t['text']}"
        for t in turns)
    prompt = (f"<현재 문서>\n{doc}\n</현재 문서>\n\n<대화>\n{convo}\n</대화>\n\n{message}")
    d = _codex(prompt, system, schema=CHAT_SCHEMA, timeout=300)
    out = d["structured_output"]
    return {"reply": out["reply"], "edits": list(out["edits"])}


@activity.defn
def report(stats: dict) -> str:
    """사이클 요약 md — 서술은 LLM, 수치는 stats 그대로."""
    d = _codex(
        "다음 job-scouter 사이클 통계로 간결한 운영 보고서 md를 써라. "
        "섹션: 요약(2문장) / 등재·제외 / 강등·실패 / 비용·latency. "
        "수치를 지어내지 말 것:\n" + json.dumps(stats, ensure_ascii=False),
        "너는 운영 보고서 작성기다. 마크다운 본문만 출력한다.")
    path = JOBFEED / "reports" / f"{date.today()}_자동사이클.md"
    path.write_text(f"# {date.today()} 자동 사이클\n\n{d['result']}\n")
    return str(path)
