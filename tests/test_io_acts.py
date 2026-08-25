import json

import pytest

import jobscouter.io_acts as io_acts
from jobscouter.config import Target


def _touch_jobfeed(tmp_path, monkeypatch):
    monkeypatch.setattr(io_acts, "JOBFEED", tmp_path)
    (tmp_path / "candidates.json").write_text(json.dumps({
        "rows": [["포지션", "나쁜회사", 111, [30, 10, 16, 20],
                  ["bad", 1.0, 10, "1,1", "요약"], None, [], None],
                 ["포지션", "등재회사", 222, [30, 10, 16, 20], None, "사유", [], None]],
        "skipped": {"333": ["스킵회사", "포지션", "사유"]},
    }, ensure_ascii=False))
    jobs = [
        {"src": "wanted", "id": 111, "title": "A", "company": "나쁜회사", "url": "u"},
        {"src": "wanted", "id": 222, "title": "B", "company": "등재회사", "url": "u"},
        {"src": "wanted", "id": 333, "title": "C", "company": "스킵회사", "url": "u"},
        {"src": "wanted", "id": 444, "title": "D", "company": "(주)나쁜회사", "url": "u"},
        {"src": "jumpit", "id": 555, "title": "E", "company": "새회사", "url": "u"},
    ]
    (tmp_path / "jobs.jsonl").write_text(
        "\n".join(json.dumps(j, ensure_ascii=False) for j in jobs))


def test_load_targets(tmp_path, monkeypatch):
    _touch_jobfeed(tmp_path, monkeypatch)
    got = io_acts.load_targets()
    ids = [t.id for t in got]
    # 111 등재됨·222 등재됨·333 스킵·444 🚫회사 정규화 매칭 → 미점수는 j555뿐
    assert ids == ["j555"]


def test_fetch_requirements_jumpit_plural_and_cap(monkeypatch):
    monkeypatch.setattr(io_acts, "_get", lambda url: {
        "result": {"qualifications": "필수: " + "가" * 400,
                   "qualification": None,  # 단수 키 함정 — 이걸 읽으면 None
                   "responsibility": "줄1\n줄2\n줄3"}})
    t = Target(id="j555", company="새회사", title="E", src="jumpit", url="u")
    text = io_acts.fetch_requirements(t)
    assert text.startswith("필수: 가")
    assert len(text) <= io_acts.REQ_CAP
    assert "줄3" not in text  # responsibility는 첫 2줄만 (캡 안에 들어올 때)


def test_to_row_format():
    j = {"id": "j555", "company": "새회사", "title": "백엔드",
         "scores": [30, 18, 20, 16, -5], "total": 79, "exclude": False,
         "reason": "필수에 Python", "confidence": 0.9, "rubric_version": "v1"}
    r = io_acts.to_row(j)
    assert len(r) == 8 and r[2] == "j555" and r[4] is None and r[5]
    j["id"] = "365172"
    assert io_acts.to_row(j)[2] == 365172   # 원티드는 int — 기존 관례


def test_commit_rows_rejects_mixed_rubric():
    js = [{"id": "1", "rubric_version": "v1"}, {"id": "2", "rubric_version": "v2"}]
    with pytest.raises(RuntimeError, match="혼재"):
        io_acts.commit_rows(js, dry_run=True)
