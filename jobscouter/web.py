"""LAN 전용 웹앱(:8090) — 대시보드·승인·문서 열람. 무인증. 쓰기는 전부 Temporal
workflow 시작(파일 직접 수정 금지). Temporal 접근은 start_publish/recent_runs
두 함수로 분리해 테스트에서 monkeypatch한다. judge는 import하지 않는다."""
import json
from pathlib import Path
from uuid import uuid4

import markdown as mdlib
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Environment
from temporalio.client import Client

from jobscouter.config import (APPLICATIONS, DRAFTS, FACTBASE, JK_MD,
                                JOBFEED, PROPOSALS, Q_WF, REFERENCES,
                                RESUME_PROPOSALS, TEMPORAL, PublishParams, _norm)
from jobscouter.workflow import ApplyResume, Publish

# docs_url 등 기본 라우트를 끈다 — /docs는 이 앱의 문서 열람 라우트가 쓴다
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
_jenv = Environment(autoescape=True)


def _safe_url(u) -> str:
    """외부 API에서 온 URL — http(s)만 링크로, 나머지는 '#' (javascript: 등 차단)."""
    return u if isinstance(u, str) and u.lower().startswith(("http://", "https://")) else "#"


_jenv.filters["safe_url"] = _safe_url

CSS = """
<style>
body { font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 72rem; padding: 0 1rem; color: #222; }
nav { margin-bottom: 1.5rem; }
nav a { margin-right: .75rem; }
table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
th, td { border: 1px solid #ccc; padding: .4rem .6rem; text-align: left; vertical-align: top; }
th { background: #f2f2f2; }
input[type=text] { width: 12rem; }
details summary { cursor: pointer; }
h1 { font-size: 1.5rem; } h2 { font-size: 1.2rem; margin-top: 2rem; }
</style>
"""

_BASE = _jenv.from_string("""<!doctype html><html><head><meta charset="utf-8">
<title>{{ title }} — job-scouter</title>""" + CSS + """</head><body>
<nav><a href="/">대시보드</a> · <a href="/candidates">후보목록</a> · <a href="/reports">보고서</a>
· <a href="/resume">이력서</a> · <a href="/applications">지원서류</a> · <a href="/docs">문서</a></nav>
<h1>{{ title }}</h1>
{{ body|safe }}
</body></html>""")

_LIST = _jenv.from_string("""
{% if items %}<ul>{% for href, name in items %}<li><a href="{{ href }}">{{ name }}</a></li>{% endfor %}</ul>
{% else %}<p>없음</p>{% endif %}""")

_SECTIONS = _jenv.from_string("""
{% if sections %}{% for name, html in sections %}<h2>{{ name }}</h2><div>{{ html|safe }}</div>{% endfor %}
{% else %}<p>없음</p>{% endif %}""")

_DASHBOARD = _jenv.from_string("""
<form method="post" action="/publish">
<table>
<tr><th>회사</th><th>포지션</th><th>점수(스택/도메인/레벨/역할/감점)</th><th>총점</th><th>conf</th>
<th>사유</th><th>인용</th><th>승인</th><th>거부 사유</th></tr>
{% for p in proposals %}
<tr>
<td>{{ p.company }}</td>
<td><a href="{{ p.url|safe_url }}" target="_blank" rel="noopener">{{ p.title }}</a></td>
<td>{{ p.scores|join(' / ') }}</td>
<td>{{ p.total }}</td>
<td>{{ '%.2f'|format(p.confidence or 0) }}</td>
<td>{{ p.reason }}</td>
<td><details><summary>{{ p.quotes|length }}건</summary><ul>
{% for q in p.quotes %}<li>{{ q }}</li>{% endfor %}</ul></details></td>
<td><input type="checkbox" name="approve" value="{{ p.id }}"></td>
<td><input type="text" name="why_{{ p.id }}" placeholder="거부 사유"></td>
</tr>
{% else %}
<tr><td colspan="9">대기 중인 후보 없음</td></tr>
{% endfor %}
</table>
<button type="submit">제출</button>
</form>

<h2>평판 미조사 회사</h2>
{% if unresearched %}<ul>{% for c in unresearched %}<li>{{ c }}</li>{% endfor %}</ul>
{% else %}<p>없음</p>{% endif %}

<h2>최근 실행</h2>
{% if runs_error %}<p>Temporal 연결 실패: {{ runs_error }}</p>
{% elif runs %}<table><tr><th>종류</th><th>상태</th><th>시작</th></tr>
{% for r in runs %}<tr><td>{{ r.type }}</td><td>{{ r.status }}</td><td>{{ r.start }}</td></tr>{% endfor %}
</table>
{% else %}<p>없음</p>{% endif %}
""")

_RESUME_PROPOSALS = _jenv.from_string("""
<p><a href="/resume">이력서 보기로 돌아가기</a></p>
<form method="post" action="/resume/apply">
<table>
<tr><th>대상</th><th>섹션</th><th>종류</th><th>현재 → 제안</th><th>근거</th><th>반영</th></tr>
{% for it in items %}
<tr>
<td>{{ it.target }}</td>
<td>{{ it.section }}</td>
<td>{{ it.kind }}</td>
<td>{% if it.current %}<del>{{ it.current }}</del><br>{% endif %}→ {{ it.proposed }}</td>
<td>{{ it.evidence }}</td>
<td><input type="checkbox" name="apply" value="{{ it.id }}"></td>
</tr>
{% else %}
<tr><td colspan="6">대기 중인 제안 없음</td></tr>
{% endfor %}
</table>
<button type="submit">반영</button>
</form>
""")


def _render(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(_BASE.render(title=title, body=body))


def _render_md(text: str) -> str:
    return mdlib.markdown(text, extensions=["tables", "fenced_code"])


def _guard(rel: str) -> None:
    """경로 조작 차단 — 절대경로·`..` 세그먼트."""
    if rel.startswith("/") or ".." in Path(rel).parts:
        raise HTTPException(400, "잘못된 경로")


def _load_proposals() -> list[dict]:
    path = JOBFEED / PROPOSALS
    if not path.exists():
        return []
    props = json.loads(path.read_text())
    return sorted(props.values(), key=lambda p: -p.get("total", 0))


def _reputed_companies() -> set[str]:
    """기업평판.md 표 첫 셀(회사명)을 _norm으로 모은 집합 — 헤더·구분선 행은 제외."""
    path = JOBFEED / "기업평판.md"
    if not path.exists():
        return set()
    out = set()
    for ln in path.read_text().splitlines():
        if not ln.startswith("|"):
            continue
        cells = ln.split("|")
        if len(cells) < 2:
            continue
        name = cells[1].strip()
        if not name or name == "회사" or set(name) <= {"-", ":"}:
            continue
        out.add(_norm(name))
    return out


# --- Temporal 접근 — 이 두 함수만 client를 만든다. 테스트에서 monkeypatch. ---

async def start_publish(ids: list[str], rejects: list[dict]) -> str:
    client = await Client.connect(TEMPORAL)
    handle = await client.start_workflow(
        Publish.run, PublishParams(ids=list(ids), rejects=rejects),
        id=f"publish-{uuid4().hex[:8]}", task_queue=Q_WF)
    return handle.id


async def start_apply_resume(ids: list[str]) -> str:
    client = await Client.connect(TEMPORAL)
    handle = await client.start_workflow(
        ApplyResume.run, list(ids),
        id=f"apply-resume-{uuid4().hex[:8]}", task_queue=Q_WF)
    return handle.id


async def recent_runs() -> list[dict]:
    client = await Client.connect(TEMPORAL)
    out = []
    async for wf in client.list_workflows(
            "WorkflowType='DailyScan' OR WorkflowType='Publish' ORDER BY StartTime DESC",
            limit=5):
        out.append({"type": wf.workflow_type,
                    "status": wf.status.name if wf.status else "?",
                    "start": wf.start_time.isoformat()})
    return out


# --- 라우트 ---

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    proposals = _load_proposals()
    reputed = _reputed_companies()
    unresearched = sorted({p["company"] for p in proposals
                           if _norm(p["company"]) not in reputed})
    runs, runs_error = None, None
    try:
        runs = await recent_runs()
    except Exception as e:
        runs_error = str(e)
    return _render("대시보드", _DASHBOARD.render(
        proposals=proposals, unresearched=unresearched,
        runs=runs, runs_error=runs_error))


@app.post("/publish")
async def publish(request: Request):
    form = await request.form()
    ids = form.getlist("approve")
    rejects = [{"id": k[len("why_"):], "why": v.strip()}
               for k, v in form.multi_items()
               if k.startswith("why_") and str(v).strip()]
    await start_publish(list(ids), rejects)
    return RedirectResponse("/", status_code=302)


@app.get("/candidates", response_class=HTMLResponse)
def candidates():
    path = JOBFEED / "후보목록.html"
    if not path.exists():
        return _render("후보목록", "<p>아직 없음 — Publish 실행 후 생성됨.</p>")
    return HTMLResponse(path.read_text())


@app.get("/reports", response_class=HTMLResponse)
def reports_index():
    d = JOBFEED / "reports"
    names = sorted(p.stem for p in d.glob("*.md")) if d.exists() else []
    return _render("보고서", _LIST.render(items=[(f"/reports/{n}", n) for n in names]))


@app.get("/reports/{name}", response_class=HTMLResponse)
def report(name: str):
    _guard(name)
    path = JOBFEED / "reports" / f"{name}.md"
    if not path.exists():
        raise HTTPException(404, "보고서 없음")
    return _render(name, _render_md(path.read_text()))


@app.get("/resume", response_class=HTMLResponse)
def resume():
    sections = []
    if JK_MD.exists():
        sections.append(("JK.md", _render_md(JK_MD.read_text())))
    if FACTBASE.exists():
        sections.append((FACTBASE.name, _render_md(FACTBASE.read_text())))
    if DRAFTS.exists():
        for p in sorted(DRAFTS.glob("*.md")):
            sections.append((p.name, _render_md(p.read_text())))
    body = '<p><a href="/resume/proposals">갱신 제안 보기</a></p>' + _SECTIONS.render(sections=sections)
    return _render("이력서", body)


def _load_resume_proposals() -> list[dict]:
    path = JOBFEED / RESUME_PROPOSALS
    if not path.exists():
        return []
    return json.loads(path.read_text()).get("items", [])


@app.get("/resume/proposals", response_class=HTMLResponse)
def resume_proposals():
    return _render("이력서 갱신 제안", _RESUME_PROPOSALS.render(items=_load_resume_proposals()))


@app.post("/resume/apply")
async def resume_apply(request: Request):
    form = await request.form()
    ids = form.getlist("apply")
    await start_apply_resume(list(ids))
    return RedirectResponse("/resume/proposals", status_code=302)


@app.get("/applications", response_class=HTMLResponse)
def applications_index():
    names = sorted(p.name for p in APPLICATIONS.iterdir() if p.is_dir()) \
        if APPLICATIONS.exists() else []
    return _render("지원서류", _LIST.render(
        items=[(f"/applications/{n}", n) for n in names]))


@app.get("/applications/{slug}", response_class=HTMLResponse)
def application(slug: str):
    _guard(slug)
    d = APPLICATIONS / slug
    if not d.exists():
        raise HTTPException(404, "지원서류 없음")
    sections = [(p.name, _render_md(p.read_text())) for p in sorted(d.glob("*.md"))]
    return _render(slug, _SECTIONS.render(sections=sections))


@app.get("/docs", response_class=HTMLResponse)
def docs_index():
    names = sorted(str(p.relative_to(REFERENCES)) for p in REFERENCES.rglob("*.md")) \
        if REFERENCES.exists() else []
    return _render("문서", _LIST.render(items=[(f"/docs/{n}", n) for n in names]))


@app.get("/docs/{path:path}", response_class=HTMLResponse)
def docs_page(path: str):
    _guard(path)
    full = REFERENCES / path
    if full.suffix != ".md" or not full.exists():
        raise HTTPException(404, "문서 없음")
    return _render(path, _render_md(full.read_text()))
