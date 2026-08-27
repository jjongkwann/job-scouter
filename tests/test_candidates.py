import json
from datetime import date

import pytest

from jobscouter import candidates as C
from jobscouter import config

ZONES = [[4, "통근 불가", "^(부산|대구|광주광역시|대전|울산|세종|강원|충[북남청]|전[북남라]|경[북남상]|제주)"],
         [0, "집 근처", "테스트시"],
         [1, "40분대", "(강남|서초)구"],
         [2, "60~80분", "서울|수원"],
         [3, "수도권 외곽", "인천|부천|경기"],
         [4, "통근 불가", "."]]


@pytest.fixture
def repo(tmp_path, monkeypatch):
    jobfeed = tmp_path / "jobfeed"
    jobfeed.mkdir()
    (tmp_path / "settings.json").write_text(json.dumps({"keywords": ["LLM"], "zones": ZONES}))
    (jobfeed / "candidates.json").write_text(json.dumps({"rows": [
        ["백엔드", "테스트회사", 222, [30, 18, 20, 16, -5], ["good", 3.9, 80, 4.1, "메모"], "", ["prep"], "2999-01-01", "서울 강남구 테헤란로"],
        ["플랫폼", "다른회사", "j5", [20, 15, 15, 12], None, "정보 없음", [], "closed", "경기 부천시"],
        ["데이터", "세번째", 333, [35, 25, 20, 20], ["bad", 2.1, 50, 2.0, "회피"], "", [], None, None],
    ], "skipped": {}}, ensure_ascii=False))
    (jobfeed / "기업평판.md").write_text("| 회사 | 총점 | 리뷰 | 판정 |\n|---|---|---|---|\n| 테스트회사 | 3.9 | 80 | ✅ |\n| 다른회사 | 2.0 | 5 | 🚫 |\n")
    (jobfeed / "jobs.jsonl").write_text(json.dumps({"src": "wanted", "id": 222, "due": "2999-01-01"}) + "\n")
    apps = tmp_path / "applications"
    (apps / "test_co").mkdir(parents=True)
    (apps / "test_co" / "0_JD.md").write_text("> https://www.wanted.co.kr/wd/222\n")
    monkeypatch.setattr(config, "JOBFEED", jobfeed)
    monkeypatch.setattr(config, "SETTINGS", tmp_path / "settings.json")
    monkeypatch.setattr(C, "JOBFEED", jobfeed)
    monkeypatch.setattr(C, "APPLICATIONS", apps)
    return tmp_path


def test_zone_uses_settings_and_catches_known_traps(repo):
    assert C.zone("경기 테스트시 중앙로 1")[0] == 0
    assert C.zone("강남구 영동대로 106길 23")[0] == 1      # 시도 생략
    assert C.zone("울산 중구 종가6길 7, 10층")[0] == 4     # 서울 중구로 오인 금지
    assert C.zone("경기 부천시 원미구")[0] == 3
    assert C.zone(None) == (9, "미확인")


def test_zone_without_settings_is_unknown(repo, monkeypatch):
    monkeypatch.setattr(config, "SETTINGS", repo / "없음.json")
    assert C.zone("서울 강남구") == (9, "미확인")


def test_validate_matches_build_check():
    ok = ["a", "co", 1, [30, 18, 20, 16, -5], ["good", 3.9, 80, 4.1, ""], "", [], None]
    assert C.validate([ok]) == []
    bad = [["a", "co", 1, [40, 18, 20, 16], None, "사유", [], None],         # 상한 초과
           ["b", "co", 1, [30, 18, 20, 16, 5], None, "사유", [], None],     # 감점 양수
           ["c", "co", 2, [30, 18, 20, 16], ["good", 3.9, None, 4.1, ""], "", [], None],   # 리뷰수 없음
           ["d", "co", 3, [30, 18, 20, 16], None, "사유", [], "언제"],       # 마감 형식
           ["e", "co", 4, [30, 18, 20, 16], None, "", [], None, None, "x"]]  # 필드 10개
    errs = C.validate(bad)
    assert len(errs) == 6          # 중복 id 1 + 위 5
    assert any("중복" in e for e in errs)


def test_candidate_rows_rec_rank_due(repo):
    rows = {r["id"]: r for r in C.candidate_rows(today=date(2026, 8, 27))}
    a, b, c = rows["222"], rows["j5"], rows["333"]
    assert a["zone"] == 1 and a["zone_label"] == "40분대"
    assert a["rec"] == round(79 * (1.0 + 0.12 * min(80 / 40, 1)) + 3)   # good 보너스 + 40분대
    assert c["rec"] == round(100 * 0.65 + 0)                            # bad 계수, 주소 없음 → 미확인 0
    assert b["closed"] and b["rank"] is None and b["due_cls"] == "gone"
    assert a["rank"] == 1 and c["rank"] == 2
    assert a["days_left"] > 0 and b["days_left"] is None and c["days_left"] is None
    assert a["url"] == "https://www.wanted.co.kr/wd/222"
    assert b["url"] == "https://jumpit.saramin.co.kr/position/5"


def test_reputation_and_folders(repo):
    assert C.reputation() == {"테스트회사": "good", "다른회사": "bad"}
    assert C.dues() == {"222": "2999-01-01"}
    f = C.app_folders()
    assert f == [{"slug": "test_co", "ids": ["222"], "files": ["0_JD.md"], "docs": ["0_JD.md"], "mtime": f[0]["mtime"]}]
    assert C.job_index()["222"]["slug"] == "test_co"
