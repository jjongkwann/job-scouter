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
