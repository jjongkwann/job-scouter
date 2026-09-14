import json
import subprocess
import sys
import time

import pytest

import jobscouter.io_acts  # noqa: F401 — 격리 검사를 위해 먼저 로드
import jobscouter.workflow  # noqa: F401

_LEAK = "jobscouter.judge" in sys.modules  # io·workflow 로드 직후 상태를 기록

from jobscouter import judge as J  # noqa: E402
from jobscouter.config import RUBRIC_VERSION, JudgeInput, Target  # noqa: E402


def test_io_modules_never_import_judge():
    """자격증명 격리 — io·workflow 모듈 로드가 judge(codex 실행 경계)를 끌고 오면 실패."""
    assert not _LEAK


def test_validate_caps():
    assert J._validate([35, 25, 20, 20, -25]) == [35, 25, 20, 20, -25]
    with pytest.raises(ValueError):
        J._validate([36, 0, 0, 0, 0])       # 스택 상한 초과
    with pytest.raises(ValueError):
        J._validate([30, 10, 16, 20, 5])    # 감점이 양수
    with pytest.raises(ValueError):
        J._validate([30, 10, 16, 20])       # 4원소


def test_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(J, "_CACHE", tmp_path / "j.jsonl")
    monkeypatch.setattr(J, "DATA", tmp_path)
    monkeypatch.setattr(J, "factbase_hash", lambda: "abc123")
    (tmp_path / f"rubric_{RUBRIC_VERSION}.md").write_text("루브릭\n{factbase}")
    (tmp_path / "facts.md").write_text("사실")
    monkeypatch.setattr(J, "PROMPTS", tmp_path)
    monkeypatch.setattr(J, "FACTBASE", tmp_path / "facts.md")
    called = []

    def fake_codex(prompt, system, schema=None):
        called.append((prompt, system, schema))
        return {"structured_output": {
                    "scores": [30, 18, 20, 16, 0], "exclude": False,
                    "reason": "필수에 Python", "quotes": ["Python 경험"],
                    "confidence": 0.9},
                "usage": {"input_tokens": 1000, "cached_input_tokens": 900,
                          "output_tokens": 50}}

    monkeypatch.setattr(J, "_codex", fake_codex)
    inp = JudgeInput(target=Target(id="1", company="c", title="t",
                                   src="wanted", url="u"),
                     requirements="Python 경험")
    old = {"key": "1|v2|abc123", "judgment": {"usage": {"usd": 0.01}}}
    J._CACHE.write_text(json.dumps(old) + "\n")
    j1 = J.judge(inp)
    j2 = J.judge(inp)
    assert (j1.cached, j2.cached) == (False, True)
    assert len(called) == 1                       # 두 번째는 codex 안 감
    assert called[0][1] == "루브릭\n사실"          # {factbase} 치환
    assert j1.usage["in"] == 1000 and j1.usage["usd"] is None
    assert j1.usage["cache_read"] == 900
    assert j1.usage["model"] == "gpt-6-astra"
    assert j1.usage["reasoning_effort"] == "xhigh"
    assert j2.total == 84 and j2.rubric_version == RUBRIC_VERSION
    assert json.loads(J._CACHE.read_text().splitlines()[0]) == old
    monkeypatch.setattr(J, "REASONING_EFFORT", "high")
    assert not J.judge(inp).cached


def _setup_app_env(tmp_path, monkeypatch):
    apps = tmp_path / "applications"
    (apps / "example").mkdir(parents=True)
    (apps / "README.md").write_text("지원서류 규칙")
    for name in J.APP_FILES:
        (apps / "example" / name).write_text(f"예시 {name}")
    monkeypatch.setattr(J, "APPLICATIONS", apps)
    monkeypatch.setattr(J, "APP_EXAMPLE", "example")
    monkeypatch.setattr(J, "FACTBASE", tmp_path / "facts.md")
    (tmp_path / "facts.md").write_text("사실")
    monkeypatch.setattr(J, "RESUME", tmp_path / "이력서.md")
    (tmp_path / "이력서.md").write_text("이력서 소개")


_TARGET = {"id": "222", "company": "회사", "title": "포지션", "src": "wanted", "url": "u",
           "scores": [30, 10, 20, 16, -5], "reason": "필수 Kotlin 미보유"}


def test_draft_application_splits_5_files_and_passes_judgment(tmp_path, monkeypatch):
    _setup_app_env(tmp_path, monkeypatch)
    out_text = "\n\n".join(f"=== FILE: {n} ===\n내용 {n}" for n in J.APP_FILES)
    called = []

    def fake_codex(prompt, system, schema=None, timeout=240):
        called.append(prompt)
        assert timeout == 1200
        assert "사실" in system and "예시 0_JD.md" in system and "지원서류 규칙" in system
        return {"result": out_text}

    monkeypatch.setattr(J, "_codex", fake_codex)
    files = J.draft_application(_TARGET, "공고 전문")
    assert list(files) == J.APP_FILES
    assert files["0_JD.md"] == "내용 0_JD.md"
    prompt = called[0]
    assert "회사: 회사" in prompt and "공고 전문" in prompt
    # 판정 블록 — 축별 점수/상한·감점·총점·사유가 실린다
    assert "<판정>" in prompt and "도메인: 10/25" in prompt and "감점: -5" in prompt
    assert "총점: 71" in prompt and "필수 Kotlin 미보유" in prompt


def test_draft_application_raises_if_fewer_than_5(tmp_path, monkeypatch):
    _setup_app_env(tmp_path, monkeypatch)
    monkeypatch.setattr(J, "_codex", lambda *a, **k: {
        "result": "=== FILE: 0_JD.md ===\n내용만 하나"})
    with pytest.raises(RuntimeError, match="누락"):
        J.draft_application(_TARGET, "공고 전문")


def test_draft_application_raises_on_wrong_filename(tmp_path, monkeypatch):
    """5개를 냈어도 이름이 하나 틀리면 재시도용 예외 — 이름 검증은 io가 아니라 LLM 단계."""
    _setup_app_env(tmp_path, monkeypatch)
    names = J.APP_FILES[:-1] + ["4_포트폴리오.md"]
    out_text = "\n\n".join(f"=== FILE: {n} ===\n내용" for n in names)
    monkeypatch.setattr(J, "_codex", lambda *a, **k: {"result": out_text})
    with pytest.raises(RuntimeError, match="누락.*4_포트폴리오_구성.md"):
        J.draft_application(_TARGET, "공고 전문")


def test_propose_resume_update_reads_factbase_and_resume_and_uses_schema(tmp_path, monkeypatch):
    monkeypatch.setattr(J, "FACTBASE", tmp_path / "facts.md")
    (tmp_path / "facts.md").write_text("## 경력\n\n3년차 백엔드")
    monkeypatch.setattr(J, "RESUME", tmp_path / "이력서.md")
    (tmp_path / "이력서.md").write_text("이력서 소개")
    called = []

    def fake_codex(prompt, system, schema=None, timeout=240):
        called.append((prompt, system, schema))
        return {"structured_output": {"proposals": [
            {"target": "factbase", "section": "경력", "kind": "change",
             "current": "3년차 백엔드", "proposed": "4년차 백엔드", "evidence": "PKB: 경력노트"},
        ]}}

    monkeypatch.setattr(J, "_codex", fake_codex)
    out = J.propose_resume_update("PKB 발췌 텍스트")
    assert out == [{"target": "factbase", "section": "경력", "kind": "change",
                    "current": "3년차 백엔드", "proposed": "4년차 백엔드",
                    "evidence": "PKB: 경력노트"}]
    prompt, system, schema = called[0]
    assert "3년차 백엔드" in system and "이력서 소개" in system   # 사실베이스·이력서.md를 직접 읽음
    assert "PKB 발췌 텍스트" in prompt
    assert schema is J.RESUME_SCHEMA
    assert "id" not in out[0]   # id는 io_acts가 부여


def test_resume_chat_returns_reply_and_edits(tmp_path, monkeypatch):
    monkeypatch.setattr(J, "FACTBASE", tmp_path / "facts.md")
    (tmp_path / "facts.md").write_text("사실베이스 내용")
    called = []

    def fake_codex(prompt, system, schema=None, timeout=240):
        called.append((prompt, system, schema, timeout))
        return {"structured_output": {
            "edits": [{"current": "a", "proposed": "b", "why": "c"}],
            "reply": "답변입니다"}}

    monkeypatch.setattr(J, "_codex", fake_codex)
    turns = [{"role": "user", "text": "이전 메시지"}, {"role": "assistant", "text": "이전 답변"}]
    out = J.resume_chat("문서 원문", turns, "새 메시지")

    assert out == {"reply": "답변입니다",
                   "edits": [{"current": "a", "proposed": "b", "why": "c"}]}
    prompt, system, schema, timeout = called[0]
    assert "사실베이스 내용" in system   # 사실베이스가 system에 실림
    assert schema is J.CHAT_SCHEMA
    assert "문서 원문" in prompt and "이전 메시지" in prompt and "새 메시지" in prompt


_USAGE = {"input_tokens": 1000, "output_tokens": 20, "cached_input_tokens": 500}


def _fake_codex(tmp_path, monkeypatch, body):
    cli = tmp_path / "codex"
    cli.write_text(f"#!{sys.executable}\n" + body)
    cli.chmod(0o700)
    monkeypatch.setattr(J, "CODEX", str(cli))
    monkeypatch.setattr(J, "DATA", tmp_path)


def test_codex_command_jsonl_and_cleanup(tmp_path, monkeypatch):
    _fake_codex(tmp_path, monkeypatch, '''
import json, pathlib, sys
args = sys.argv[1:]
assert args[:3] == ["exec", "--model", "gpt-6-astra"]
assert 'model_reasoning_effort="xhigh"' in args
assert "--ignore-user-config" in args and "--ignore-rules" in args
assert args[args.index("--sandbox") + 1] == "read-only"
assert "--max-budget-usd" not in args
assert sys.stdin.read() == "사용자"
assert pathlib.Path("instructions.md").read_text() == "사실" * 100000
schema = json.loads(pathlib.Path(args[args.index("--output-schema") + 1]).read_text())
assert schema["additionalProperties"] is False
pathlib.Path(args[args.index("--output-last-message") + 1]).write_text('{"ok": true}')
print(json.dumps({"type": "item.completed", "item": {"type": "error", "message": "nonfatal"}}))
print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 1000, "output_tokens": 20, "cached_input_tokens": 500}}))
''')
    d = J._codex("사용자", "사실" * 100000, {"type": "object", "additionalProperties": False})
    assert d["structured_output"] == {"ok": True}
    assert d["usage"] == _USAGE
    assert not list(tmp_path.glob("codex-*"))


@pytest.mark.parametrize("event,output,code", [
    ({"type": "turn.failed", "error": {"message": "quota"}}, "text", 0),
    ({"type": "turn.completed", "usage": _USAGE}, "", 0),
    ({"type": "turn.completed", "usage": {}}, "text", 0),
    ({"type": "turn.completed", "usage": _USAGE}, "text", 1),
])
def test_codex_rejects_failed_or_unmetered_output(tmp_path, monkeypatch, event, output, code):
    _fake_codex(tmp_path, monkeypatch,
        "import pathlib, sys\n"
        f"pathlib.Path('output.txt').write_text({output!r})\n"
        f"print({json.dumps(event)!r})\n"
        f"sys.exit({code})\n")
    with pytest.raises(RuntimeError):
        J._codex("prompt", "system")
    assert not list(tmp_path.glob("codex-*"))


def test_codex_timeout_kills_child_process(tmp_path, monkeypatch):
    marker = tmp_path / "orphan"
    child = f"import time,pathlib;time.sleep(1);pathlib.Path({str(marker)!r}).touch()"
    _fake_codex(tmp_path, monkeypatch,
        "import subprocess,sys,time\n"
        f"subprocess.Popen([sys.executable, '-c', {child!r}])\n"
        "time.sleep(10)\n")
    with pytest.raises(subprocess.TimeoutExpired):
        J._codex("prompt", "system", timeout=0.2)
    time.sleep(1.1)
    assert not marker.exists()
    assert not list(tmp_path.glob("codex-*"))


def test_report_uses_codex_and_writes_markdown(tmp_path, monkeypatch):
    (tmp_path / "reports").mkdir()
    monkeypatch.setattr(J, "JOBFEED", tmp_path)
    calls = []
    monkeypatch.setattr(J, "_codex", lambda *args: calls.append(args) or {"result": "요약"})
    path = J.report({"listed": 2})
    assert '"listed": 2' in calls[0][0]
    assert "요약" in (tmp_path / path).read_text()
