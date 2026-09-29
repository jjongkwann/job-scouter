"""로그인한 Mac Chrome으로 받은 제안을 읽어 로컬 데이터만 갱신한다. 수락·거절·push 없음."""
import argparse
import json
import subprocess
import tempfile
import time
from datetime import datetime
from email import policy
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from jobscouter.candidates import KST
from jobscouter.offers import merge

ORIGIN = "https://www.wanted.co.kr"
HISTORY = "/api/chaos/proposal/v1/history"


def apple(script: str) -> str:
    return subprocess.run(["osascript", "-e", 'with timeout of 20 seconds\n'
                           'tell application "Google Chrome"\n' + script +
                           '\nend tell\nend timeout'],
                          capture_output=True, text=True, check=True, timeout=25).stdout.strip()


def read_json(target: str, url: str, folder: Path, index: int) -> dict:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "www.wanted.co.kr" or not parsed.path.startswith(HISTORY):
        raise ValueError("원티드 제안 조회 URL만 허용합니다")
    apple(f"set URL of {target} to {json.dumps(url)}")
    for _ in range(100):
        if apple(f"return loading of {target}") == "false":
            break
        time.sleep(.2)
    else:
        raise TimeoutError("원티드 제안 페이지 로딩 시간 초과")
    path = folder / f"{index}.mhtml"
    apple(f"save {target} in POSIX file {json.dumps(str(path))} as \"single file\"")
    # Chrome 저장은 비동기다. 완성된 JSON을 읽을 때까지 기다린다.
    for _ in range(100):
        if path.exists():
            msg = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    soup = BeautifulSoup(part.get_payload(decode=True).decode("utf-8"), "html.parser")
                    pre = soup.find("pre")
                    if pre:
                        try:
                            return json.loads(pre.get_text())
                        except json.JSONDecodeError:
                            pass
        time.sleep(.2)
    raise RuntimeError("원티드 JSON을 읽지 못했습니다. Chrome의 원티드 로그인을 확인하세요")


def normalize(row: dict, detail: dict) -> dict:
    received = next(h for h in row["histories"] if h["type"] == "OFFER")
    latest = row["histories"][0]
    kind = "면접" if row["offer_type"] == "INTERVIEW" else "지원"
    status = {"OFFER": f"{kind} 제안 받음", "USER_REJECT": f"{kind} 제안 거절",
              "USER_APPLY": f"{kind} 제안 수락", "USER_ACCEPT": f"{kind} 제안 수락",
              "USER_EXPIRE_REJECT": "응답 기간 만료"}.get(latest["type"], latest["type"])
    proposal = detail["proposal"]
    return {"id": str(received["id"]), "company": row["company"]["name"],
            "company_id": str(row["company"]["id"]),
            "title": proposal["job_title"], "job_id": str(proposal["job_id"]) if proposal.get("job_id") else "",
            "received_at": received["created_time"], "status_at": latest["created_time"],
            "status": status, "status_code": latest["type"],
            "expires_at": proposal.get("expired_time") or row.get("expired_time") or "",
            "offer_type": row["offer_type"], "offer_mode": row["offer_mode"],
            "message": proposal.get("message") or ""}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--jobfeed", type=Path, required=True)
    args = p.parse_args()
    if not (args.jobfeed / "candidates.json").is_file():
        p.error("기존 candidates.json이 있는 jobfeed 경로를 지정하세요")
    work = Path(__file__).resolve().parents[1] / "data"
    work.mkdir(exist_ok=True)
    window = apple('return id of front window')
    tab = apple(f'set t to make new tab at end of tabs of window id {window} with properties {{URL:"about:blank"}}\nreturn id of t')
    target = f"tab id {tab} of window id {window}"
    try:
        with tempfile.TemporaryDirectory(prefix="wanted-offers-", dir=work) as tmp:
            folder = Path(tmp)
            url, seen, rows = ORIGIN + HISTORY + "?type=OFFER&limit=20", set(), []
            while url:
                if url in seen:
                    raise ValueError("원티드 페이지네이션 반복 — 저장하지 않았습니다")
                seen.add(url)
                page = read_json(target, url, folder, len(seen))
                if not isinstance(page.get("data"), list):
                    raise ValueError("원티드 제안 목록 응답 오류 — 저장하지 않았습니다")
                rows.extend(page["data"])
                next_page = page["links"]["next"]
                url = ORIGIN + next_page if next_page and next_page.startswith("/") else next_page
            # history 페이지가 겹쳐도 같은 최초 OFFER 이벤트는 한 번만 수집한다.
            unique = {}
            for row in rows:
                oid = next(h["id"] for h in row["histories"] if h["type"] == "OFFER")
                unique.setdefault(oid, row)
            rows = list(unique.values())
            items = []
            for i, row in enumerate(rows):
                received = next(h for h in row["histories"] if h["type"] == "OFFER")
                oid = int(received["id"])
                detail = read_json(target, f"{ORIGIN}{HISTORY}/{oid}", folder, len(seen) + i + 1)
                items.append(normalize(row, detail["data"]))
                print(f"상세 {i + 1}/{len(rows)}: {row['company']['name']}", flush=True)
            data = merge(args.jobfeed, items, datetime.now(KST).isoformat(timespec="seconds"))
            print(f"수집 {len(items)}건 · 보존된 수신 이력 {len(data['items'])}건 · 로컬 저장 완료")
    finally:
        apple(f"close {target}")


if __name__ == "__main__":
    main()
