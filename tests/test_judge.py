import sys

import pytest

import jobscouter.io_acts  # noqa: F401 — 격리 검사를 위해 먼저 로드
import jobscouter.workflow  # noqa: F401

_LEAK = "jobscouter.judge" in sys.modules  # io·workflow 로드 직후 상태를 기록

from jobscouter import judge as J  # noqa: E402
from jobscouter.config import JudgeInput, Target  # noqa: E402


def test_io_modules_never_import_judge():
    """자격증명 격리 — io·workflow 모듈 로드가 judge(claude 실행 경계)를 끌고 오면 실패."""
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
    (tmp_path / "rubric_v1.md").write_text("루브릭\n{factbase}")
    (tmp_path / "facts.md").write_text("사실")
    monkeypatch.setattr(J, "PROMPTS", tmp_path)
    monkeypatch.setattr(J, "FACTBASE", tmp_path / "facts.md")
    called = []

    def fake_claude(prompt, system, max_usd, schema=None):
        called.append((prompt, system, max_usd, schema))
        return {"structured_output": {
                    "scores": [30, 18, 20, 16, 0], "exclude": False,
                    "reason": "필수에 Python", "quotes": ["Python 경험"],
                    "confidence": 0.9},
                "usage": {"input_tokens": 100, "cache_creation_input_tokens": 900,
                          "cache_read_input_tokens": 0, "output_tokens": 50},
                "total_cost_usd": 0.01}

    monkeypatch.setattr(J, "_claude", fake_claude)
    inp = JudgeInput(target=Target(id="1", company="c", title="t",
                                   src="wanted", url="u"),
                     requirements="Python 경험")
    j1 = J.judge(inp)
    j2 = J.judge(inp)
    assert (j1.cached, j2.cached) == (False, True)
    assert len(called) == 1                       # 두 번째는 claude 안 감
    assert called[0][1] == "루브릭\n사실"          # {factbase} 치환
    assert j1.usage["in"] == 1000 and j1.usage["usd"] == 0.01
    assert j2.total == 84 and j2.rubric_version == "v1"


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

    def fake_claude(prompt, system, max_usd, schema=None, timeout=240):
        called.append(prompt)
        assert timeout == 600
        assert "사실" in system and "예시 0_JD.md" in system and "지원서류 규칙" in system
        return {"result": out_text}

    monkeypatch.setattr(J, "_claude", fake_claude)
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
    monkeypatch.setattr(J, "_claude", lambda *a, **k: {
        "result": "=== FILE: 0_JD.md ===\n내용만 하나"})
    with pytest.raises(RuntimeError, match="누락"):
        J.draft_application(_TARGET, "공고 전문")


def test_draft_application_raises_on_wrong_filename(tmp_path, monkeypatch):
    """5개를 냈어도 이름이 하나 틀리면 재시도용 예외 — 이름 검증은 io가 아니라 LLM 단계."""
    _setup_app_env(tmp_path, monkeypatch)
    names = J.APP_FILES[:-1] + ["4_포트폴리오.md"]
    out_text = "\n\n".join(f"=== FILE: {n} ===\n내용" for n in names)
    monkeypatch.setattr(J, "_claude", lambda *a, **k: {"result": out_text})
    with pytest.raises(RuntimeError, match="누락.*4_포트폴리오_구성.md"):
        J.draft_application(_TARGET, "공고 전문")


def test_propose_resume_update_reads_factbase_and_resume_and_uses_schema(tmp_path, monkeypatch):
    monkeypatch.setattr(J, "FACTBASE", tmp_path / "facts.md")
    (tmp_path / "facts.md").write_text("## 경력\n\n3년차 백엔드")
    monkeypatch.setattr(J, "RESUME", tmp_path / "이력서.md")
    (tmp_path / "이력서.md").write_text("이력서 소개")
    called = []

    def fake_claude(prompt, system, max_usd, schema=None, timeout=240):
        called.append((prompt, system, max_usd, schema))
        return {"structured_output": {"proposals": [
            {"target": "factbase", "section": "경력", "kind": "change",
             "current": "3년차 백엔드", "proposed": "4년차 백엔드", "evidence": "PKB: 경력노트"},
        ]}}

    monkeypatch.setattr(J, "_claude", fake_claude)
    out = J.propose_resume_update("PKB 발췌 텍스트")
    assert out == [{"target": "factbase", "section": "경력", "kind": "change",
                    "current": "3년차 백엔드", "proposed": "4년차 백엔드",
                    "evidence": "PKB: 경력노트"}]
    prompt, system, max_usd, schema = called[0]
    assert "3년차 백엔드" in system and "이력서 소개" in system   # 사실베이스·이력서.md를 직접 읽음
    assert "PKB 발췌 텍스트" in prompt
    assert schema is J.RESUME_SCHEMA
    assert "id" not in out[0]   # id는 io_acts가 부여


def test_resume_chat_returns_reply_and_edits(tmp_path, monkeypatch):
    monkeypatch.setattr(J, "FACTBASE", tmp_path / "facts.md")
    (tmp_path / "facts.md").write_text("사실베이스 내용")
    called = []

    def fake_claude(prompt, system, max_usd, schema=None, timeout=240):
        called.append((prompt, system, max_usd, schema, timeout))
        return {"structured_output": {
            "edits": [{"current": "a", "proposed": "b", "why": "c"}],
            "reply": "답변입니다"}}

    monkeypatch.setattr(J, "_claude", fake_claude)
    turns = [{"role": "user", "text": "이전 메시지"}, {"role": "assistant", "text": "이전 답변"}]
    out = J.resume_chat("문서 원문", turns, "새 메시지")

    assert out == {"reply": "답변입니다",
                   "edits": [{"current": "a", "proposed": "b", "why": "c"}]}
    prompt, system, max_usd, schema, timeout = called[0]
    assert "사실베이스 내용" in system   # 사실베이스가 system에 실림
    assert schema is J.CHAT_SCHEMA
    assert "문서 원문" in prompt and "이전 메시지" in prompt and "새 메시지" in prompt
