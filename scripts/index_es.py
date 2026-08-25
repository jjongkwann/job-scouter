"""jobscout 인덱스 3종 재생성 + 색인. 멱등 — 매 실행 지우고 다시.

    uv run python scripts/index_es.py
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
from elasticsearch.helpers import bulk

load_dotenv()

from jobscouter.config import FACTBASE, JOBFEED
from jobscouter.search import INDICES, MAPPING, embed, es


def fact_docs():
    """사실베이스를 ## 절 단위로 청크. 2000자 넘는 절은 문단으로 재분할."""
    text = FACTBASE.read_text()
    for sec in re.split(r"\n(?=## )", text):
        sec = sec.strip()
        if not sec:
            continue
        chunks = ([sec] if len(sec) <= 2000 else
                  [p for p in sec.split("\n\n") if p.strip()])
        for c in chunks:
            yield {"content": c[:2000], "company": "", "kind": "fact"}


def precedent_docs():
    cand = json.loads((JOBFEED / "candidates.json").read_text())
    for r in cand["rows"]:
        scores = r[3] + [0] * (5 - len(r[3]))
        rep = f" 평판: {r[4][4]}" if r[4] else (f" 평판없음: {r[5]}" if r[5] else "")
        yield {"id": str(r[2]), "company": r[1], "kind": "listed",
               "content": f"[등재 {sum(scores)}점 {scores}] {r[1]} | {r[0]}{rep}"}
    for cid, v in cand["skipped"].items():
        # 레거시 스킵 항목은 [company, title, why] 대신 결합 문자열 하나뿐 (실측)
        if isinstance(v, list):
            company, title, why = v
            content = f"[제외] {company} | {title} | 사유: {why}"
        else:
            company, content = "", f"[제외] {v}"
        yield {"id": str(cid), "company": company, "kind": "skipped", "content": content}


def reputation_docs():
    """기업평판.md의 표 행 단위 — 첫 셀을 회사명으로 본다."""
    rep = JOBFEED / "기업평판.md"
    if not rep.exists():
        return
    for ln in rep.read_text().splitlines():
        cells = [c.strip() for c in ln.split("|")]
        if ln.startswith("|") and len(cells) > 3 and cells[1] and \
                not set(cells[1]) <= {"-", ":", " "}:
            yield {"company": cells[1], "kind": "reputation",
                   "content": ln[:1500]}


def main():
    client = es()
    sources = dict(zip(INDICES, (fact_docs, precedent_docs, reputation_docs)))
    for index, source in sources.items():
        if client.indices.exists(index=index):
            client.indices.delete(index=index)
        client.indices.create(index=index, mappings=MAPPING)
        docs = list(source())
        vecs = embed([d["content"] for d in docs])
        bulk(client, ({"_index": index, **d, "embedding": v}
                      for d, v in zip(docs, vecs)))
        print(f"{index}: {len(docs)}건")


if __name__ == "__main__":
    main()
