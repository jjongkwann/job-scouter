from jobscouter.eligibility import career_label, minimum_years, needs_experience_review


def test_structured_career_and_user_review_boundary():
    assert career_label(7, None) == "7년 이상"
    assert career_label(7, 100) == "7년 이상"
    assert career_label(3, 7) == "3~7년"
    assert career_label(None, None, True) == "신입"
    for career in ("5년 이상", "6~15년", "3~7년", "경력", "7년 우대", "신입/경력"):
        assert not needs_experience_review(career)
    for career in ("7년 이상", "8~15년", "10~12년"):
        assert needs_experience_review(career)
    assert minimum_years("3~7년") == 3
