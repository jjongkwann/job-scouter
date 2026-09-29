import json

import pytest

from jobscouter import offers
from scripts.sync_wanted_offers import normalize


def test_merge_preserves_history_and_validates_before_writing(tmp_path):
    old = {"id": "1", "company": "회사", "title": "개발자", "status": "검토 중"}
    offers.merge(tmp_path, [old], "2026-09-21")
    data = offers.merge(tmp_path, [{**old, "status": "기간 만료"},
                                  {**old, "id": "2", "title": "다른 포지션"}], "2026-09-22")
    assert len(data["items"]) == 2 and data["items"][0]["status"] == "기간 만료"
    offers.merge(tmp_path, [{**old, "id": "2"}], "2026-09-23")
    path = tmp_path / offers.FILENAME
    before = path.read_text()
    assert len(json.loads(before)["items"]) == 2
    for bad in ([{**old, "id": "../escape"}], [old, old], [{**old, "job_id": "j123"}]):
        with pytest.raises(ValueError):
            offers.merge(tmp_path, bad, "2026-09-24")
        assert path.read_text() == before


def test_wanted_uses_original_offer_id_and_detail_job_id():
    row = {"histories": [{"id": 99, "type": "USER_REJECT", "created_time": "2026-09-22T10:00:00"},
                         {"id": 10, "type": "OFFER", "created_time": "2026-09-21T10:00:00"}],
           "company": {"id": 42, "name": "회사"}, "position": {"id": 123},
           "offer_type": "INTERVIEW", "offer_mode": "SEMI_AUTO"}
    detail = {"proposal": {"job_id": 456, "job_title": "개발자", "message": "면접 제안",
                           "expired_time": "2026-10-21T23:59:59"}}
    got = offers.Offer.model_validate(normalize(row, detail))
    assert (got.id, got.job_id, got.received_at) == ("10", "456", "2026-09-21T10:00:00")
    assert got.status == "면접 제안 거절" and got.status_at == "2026-09-22T10:00:00"
