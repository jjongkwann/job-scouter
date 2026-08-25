"""수동 판정 대조 — rows에서 마감 안 된 최근 n건 + skipped s건을 재판정해 비교.

    uv run python scripts/eval_judge.py --n 15 --skipped 5 [--rag]
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv

load_dotenv()
from jobscouter.config import DATA, JOBFEED, JudgeInput, Target
from jobscouter.io_acts import fetch_requirements
from jobscouter.judge import judge

AXES = ["스택", "도메인", "레벨", "역할", "감점"]


def _target(cid, company, title):
    cid = str(cid)
    src = "jumpit" if cid.startswith("j") else "wanted"
    url = (f"https://jumpit.saramin.co.kr/position/{cid[1:]}" if src == "jumpit"
           else f"https://www.wanted.co.kr/wd/{cid}")
    return Target(id=cid, company=company, title=title, src=src, url=url)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=15)
    p.add_argument("--skipped", type=int, default=5)
    p.add_argument("--rag", action="store_true")  # Phase 3에서 사용
    a = p.parse_args()

    cand = json.loads((JOBFEED / "candidates.json").read_text())
    rows = [r for r in cand["rows"] if r[7] != "closed"][-a.n:]
    skipped = list(cand["skipped"].items())[-a.skipped:]

    ctx = ""
    if a.rag:
        from jobscouter.search import search_context_text  # Task 8
    lines = [f"# eval {date.today()} — rag={'on' if a.rag else 'off'}",
             "", "| 회사 | 수동 | 자동 | Δ총점 | 축 일치 | conf |", "|---|---|---|---:|---|---|"]
    diffs, axis_hits, excl_ok = [], 0, 0

    for r in rows:
        t = _target(r[2], r[1], r[0])
        try:
            req = fetch_requirements(t)
        except Exception as e:
            lines.append(f"| {r[1]} | — | 요건 수집 실패: {e} | | | |")
            continue
        if a.rag:
            ctx = search_context_text(t, req)
        try:
            j = judge(JudgeInput(target=t, requirements=req, search_context=ctx))
        except Exception as e:
            lines.append(f"| {r[1]} | {r[3]} | 판정 실패: {str(e)[:60]} | | | |")
            continue
        manual = r[3] + [0] * (5 - len(r[3]))
        match = sum(int(m == g) for m, g in zip(manual, j.scores))
        axis_hits += match
        d = j.total - sum(manual)
        diffs.append(abs(d))
        lines.append(f"| {r[1]} | {manual} {sum(manual)} | {j.scores} {j.total} "
                     f"| {d:+d} | {match}/5 | {j.confidence:.2f} |")

    lines += ["", "## skipped 대조 (exclude 일치 기대)", "",
              "| 회사 | 수동 사유 | 자동 exclude | 자동 사유 |", "|---|---|---|---|"]
    for cid, (company, title, why) in skipped:
        t = _target(cid, company, title)
        try:
            req = fetch_requirements(t)
        except Exception as e:
            lines.append(f"| {company} | {why[:40]} | 요건 수집 실패 | {e} |")
            continue
        if a.rag:
            ctx = search_context_text(t, req)
        try:
            j = judge(JudgeInput(target=t, requirements=req, search_context=ctx))
        except Exception as e:
            lines.append(f"| {company} | {why[:40]} | 판정 실패 | {str(e)[:60]} |")
            continue
        excl_ok += int(j.exclude or j.total < 70)
        lines.append(f"| {company} | {why[:40]} | {j.exclude} ({j.total}점) "
                     f"| {j.reason[:60]} |")

    n = len(diffs) or 1
    lines += ["", f"**총점 MAE {sum(diffs)/n:.1f} · 축 일치 {axis_hits}/{n*5} · "
              f"skipped exclude 일치 {excl_ok}/{len(skipped)}**"]
    out = DATA / f"eval_{date.today()}{'_rag' if a.rag else ''}.md"
    out.write_text("\n".join(lines))
    print("\n".join(lines[-3:]))
    print("→", out)


if __name__ == "__main__":
    main()
