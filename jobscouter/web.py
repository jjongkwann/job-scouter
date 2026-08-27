"""LAN 전용 웹앱(:8090) — 대시보드·승인·문서 열람. 무인증. 쓰기는 전부 Temporal
workflow 시작(파일 직접 수정 금지). Temporal 접근은 start_publish/recent_runs
두 함수로 분리해 테스트에서 monkeypatch한다. judge는 import하지 않는다.

화면 규격은 후보목록(jobfeed/template.html)과 한 벌 — 색 토큰·14px 시스템 고딕·
1220px 폭·9px 카드·999px 필·4px 왼쪽 레일(=평판 판정)을 그대로 쓴다."""
import difflib
import json
import re
import subprocess
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import markdown as mdlib
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from jinja2 import Environment
from markupsafe import escape
from temporalio.client import Client

from jobscouter.candidates import (MAX as _MAX, app_folders, candidate_rows, due_label as _due_label,
                                    dues as _dues, job_index, reputation as _reputation)
from jobscouter.config import (APP_FILES, APPLICATIONS, CHAT_DIR, JOBFEED, PROPOSALS, Q_WF,
                                REFERENCES, RESUME, RESUME_PROPOSALS, SID_RE, TEMPORAL,
                                PublishParams, _norm, git_path_at, resume_target)
from jobscouter.workflow import ApplyResume, Draft, EndChat, Publish, ResumeChat, RevertFile

# docs_url 등 기본 라우트를 끈다 — /docs는 이 앱의 문서 열람 라우트가 쓴다
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
_jenv = Environment(autoescape=True)
KST = ZoneInfo("Asia/Seoul")

# 무인증 LAN 앱의 브라우저 경유 공격 차단 — 이 레포 데이터에는 이력서·연락처가 있다.
# Host 허용: IPv4 리터럴 · localhost · 점 없는 LAN 이름 · *.local (DNS 리바인딩은 공개 도메인이 Host로 온다)
_HOST_OK = re.compile(r"(\d{1,3}(\.\d{1,3}){3}|localhost|[\w-]+|[\w-]+\.local)")
_SHA = re.compile(r"[0-9a-f]{7,40}")   # subprocess/경로에 쓰기 전 형식 검증 — resume_target()과 같은 이유
# 문서 본문은 사람·LLM이 쓴 마크다운을 raw HTML 허용으로 렌더링한다 — 스크립트는 CSP로 막는다
CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data: https:; form-action 'self'; base-uri 'none'"
CSP_CANDIDATES = CSP.replace("default-src 'none';", "default-src 'none'; script-src 'unsafe-inline';")  # build.py 산출물은 인라인 스크립트로 렌더링


@app.middleware("http")
async def _lan_guard(request: Request, call_next):
    host = request.headers.get("host", "").rsplit(":", 1)[0]
    if not _HOST_OK.fullmatch(host):
        return PlainTextResponse("허용되지 않은 Host", status_code=403)
    # 다른 사이트의 <form>이 승인·반영을 대신 제출하는 것(CSRF) 차단 — 브라우저가 붙이는 Sec-Fetch-Site 기준
    if request.method == "POST" and request.headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none"):
        return PlainTextResponse("cross-site 요청 거부", status_code=403)
    resp = await call_next(request)
    resp.headers.setdefault("Content-Security-Policy", CSP)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    return resp


def _safe_url(u) -> str:
    """외부 API에서 온 URL — http(s)만 링크로, 나머지는 '#' (javascript: 등 차단)."""
    return u if isinstance(u, str) and u.lower().startswith(("http://", "https://")) else "#"


_jenv.filters["safe_url"] = _safe_url

# 내비는 후보목록.html(원본 그대로 내보내는 페이지)에도 끼워 넣어야 하므로 CSS·마크업을 따로 둔다
NAV_CSS = """
.nav{display:flex;align-items:center;gap:6px;padding:0 0 12px;margin:0 0 22px;border-bottom:1px solid var(--line)}
.brand{font-size:13px;font-weight:700;letter-spacing:-.2px;margin-right:10px}
.pill{font:inherit;font-size:12px;padding:4px 11px;border-radius:999px;cursor:pointer;line-height:1.5;
  border:1px solid var(--line);background:var(--row);color:var(--fg);text-decoration:none;display:inline-block}
.pill:hover{border-color:var(--dim);color:var(--fg)}
.pill[aria-pressed="true"]{background:var(--fg);color:#fff;border-color:var(--fg)}
.nav .meta{margin-left:auto;font-size:11px;color:var(--dim)}
"""

NAV = [("/", "대시보드"), ("/candidates", "후보목록"), ("/reports", "보고서"),
       ("/resume", "이력서"), ("/applications", "지원서류"), ("/docs", "문서")]

_NAV = _jenv.from_string("""<div class="nav"><span class="brand">job-scouter</span>
{% for href, name in nav %}<a class="pill" href="{{ href }}" aria-pressed="{{ 'true' if name == active else 'false' }}">{{ name }}</a>
{% endfor %}<span class="meta">LAN 전용 · 인증 없음</span></div>""")

CSS = """
<style>
:root{--bg:#fcfcfb;--fg:#1a1a18;--dim:#71716b;--faint:#a3a39c;--line:#e6e6e1;--row:#fff;--hov:#f7f7f4;
  --good:#0f6b3f;--goodbg:#e7f4ed;--warn:#8a5a00;--warnbg:#fbf1de;--bad:#a52a2a;--badbg:#fbeaea;
  --neu:#4a5568;--neubg:#eef0f3;--accent:#1f5fbf;
  --rail-good:#16a34a;--rail-warn:#f59e0b;--rail-bad:#dc2626;--rail-none:#d4d4cf}
*{box-sizing:border-box}
html{color-scheme:light}
body{margin:0;padding:30px 18px 70px;background:var(--bg);color:var(--fg);
  font:14px/1.55 -apple-system,BlinkMacSystemFont,"Pretendard","Apple SD Gothic Neo",sans-serif}
a{color:var(--accent)} a:hover{color:var(--fg)}
.wrap{max-width:1220px;margin:0 auto}
h1{font-size:21px;margin:0 0 5px;letter-spacing:-.3px}
h2{font-size:14px;margin:26px 0 8px;letter-spacing:-.1px}
h2 .c{color:var(--dim);font-weight:400;font-size:12px;margin-left:6px}
.sub{color:var(--dim);font-size:13px;margin:0 0 18px;max-width:78ch}
.sub b{color:var(--fg)}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11.5px}
""" + NAV_CSS + """
.stats{display:flex;flex-wrap:wrap;gap:20px;padding:13px 16px;border:1px solid var(--line);border-radius:9px;background:var(--row);margin-bottom:16px}
.stat .n{font-size:19px;font-weight:700;font-variant-numeric:tabular-nums;line-height:1.2}
.stat .l{font-size:11px;color:var(--dim)}
.bar{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:14px;align-items:center}
.bar .lbl{font-size:11px;color:var(--dim);min-width:44px}
.list{border:1px solid var(--line);border-radius:9px;background:var(--row);overflow:hidden;margin-bottom:12px}
.head,.row{display:grid;gap:10px;align-items:center;padding:9px 14px;grid-template-columns:minmax(0,1fr)}
.head{font-size:11px;color:var(--dim);border-bottom:1px solid var(--line);background:var(--bg)}
.row{border-bottom:1px solid var(--line);background:var(--row);border-left:4px solid var(--rail-none)}
.row:last-child{border-bottom:0}
.row:hover{background:var(--hov)}
.row.v-good{border-left-color:var(--rail-good)}
.row.v-warn{border-left-color:var(--rail-warn)}
.row.v-bad{border-left-color:var(--rail-bad)}
.row.plain{border-left:0}
.dash .head,.dash .row{grid-template-columns:minmax(220px,1.1fr) 78px 44px 44px 44px 44px 44px 48px minmax(290px,1.6fr) 56px 150px}
.rp .head,.rp .row{grid-template-columns:150px 170px 64px minmax(300px,1.5fr) minmax(220px,1fr) 56px}
.rep .head,.rep .row{grid-template-columns:110px 90px minmax(0,1fr)}
.legend{display:flex;flex-wrap:wrap;gap:16px;align-items:center;padding:9px 14px;margin-bottom:2px;font-size:11.5px;color:var(--dim)}
.legend .k{display:flex;align-items:center;gap:6px}
.legend .sw{width:4px;height:14px;border-radius:2px;display:inline-block}
.pos{font-weight:600;letter-spacing:-.1px;line-height:1.35}
.pos a{color:inherit;text-decoration:none}
.pos a:hover{text-decoration:underline;text-underline-offset:2px}
.co{color:var(--dim);font-size:12px;margin-top:1px}
.co .due{font-variant-numeric:tabular-nums}
.co .due.gone,.co .due.u0{color:var(--bad)}
.co .due.gone{font-weight:600}
.co .due.u1{color:var(--warn)}
.fit{display:flex;align-items:center;gap:7px}
.fit .v{font-size:15px;font-weight:700;font-variant-numeric:tabular-nums;min-width:24px;text-align:right}
.fit .track{flex:1;height:5px;border-radius:3px;background:var(--neubg);overflow:hidden}
.fit .fill{height:100%;border-radius:3px;background:var(--neu)}
.fit.t1 .v{color:var(--good)} .fit.t1 .fill{background:var(--good)}
.fit.t2 .v{color:var(--fg)}
.fit.t3 .v{color:var(--faint)} .fit.t3 .fill{background:var(--faint)}
.sc{font-size:12px;text-align:center;font-variant-numeric:tabular-nums;color:var(--dim)}
.sc.hi{color:var(--good);font-weight:700}
.sc.lo{color:var(--faint)}
.sc.pen{color:var(--bad)}
.conf{font-size:12px;font-variant-numeric:tabular-nums;color:var(--dim);text-align:center}
.why{font-size:12px;line-height:1.45}
.why details{margin-top:4px;font-size:11px;color:var(--dim)}
.why summary{cursor:pointer;list-style:none;color:var(--accent)}
.why summary::-webkit-details-marker{display:none}
.why ul{margin:4px 0 0;padding-left:16px}
.st{font-size:11px;line-height:1.5}
.st span{display:inline-block;padding:1px 7px;border-radius:4px;background:var(--neubg);color:var(--neu);margin:1px 2px 1px 0}
.st .bad{background:var(--badbg);color:var(--bad)}
.st .good{background:var(--goodbg);color:var(--good)}
.st .warn{background:var(--warnbg);color:var(--warn)}
.in{font:inherit;font-size:12px;padding:4px 8px;border:1px solid var(--line);border-radius:6px;background:var(--row);color:var(--fg);width:100%}
.in::placeholder{color:var(--faint)}
.chk{width:16px;height:16px;margin:0;accent-color:var(--fg);vertical-align:middle}
.btn{font:inherit;font-size:12px;padding:5px 13px;border-radius:999px;cursor:pointer;border:1px solid var(--line);background:var(--row);color:var(--fg)}
.btn.primary{background:var(--fg);color:#fff;border-color:var(--fg)}
.actions{display:flex;align-items:center;gap:12px;padding:11px 14px;margin-top:10px;border:1px solid var(--line);border-radius:9px;background:var(--row);font-size:12px;color:var(--dim)}
.actions .btn{margin-left:auto}
.rubric{border:1px solid var(--line);border-radius:9px;background:var(--row);padding:0 16px;margin-bottom:16px;font-size:12.5px}
.rubric table{width:100%;border-collapse:collapse;margin:10px 0 12px}
.rubric th,.rubric td{text-align:left;padding:5px 10px 5px 0;border-bottom:1px solid var(--line);vertical-align:top}
.rubric th{font-size:11px;color:var(--dim);font-weight:600}
.rubric tr:last-child td{border-bottom:0}
.cols{display:grid;grid-template-columns:minmax(0,1fr) 260px;gap:16px;align-items:start}
.two{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;align-items:start}
.side{border:1px solid var(--line);border-radius:9px;background:var(--row);padding:12px 14px;margin-bottom:12px;font-size:12px}
.side h3{font-size:11px;color:var(--dim);font-weight:600;margin:0 0 8px}
.side .n{font-size:19px;font-weight:700;line-height:1.2}
.side p{margin:4px 0 0;color:var(--dim);line-height:1.45}
.files{display:flex;flex-direction:column;gap:2px}
.files a{display:block;padding:5px 8px;border-radius:6px;color:var(--fg);text-decoration:none;font-size:12px}
.files a:hover{background:var(--hov)}
.doc{border:1px solid var(--line);border-radius:9px;background:var(--row);padding:26px 30px;margin-bottom:16px;overflow-x:auto}
.doc h1{font-size:19px;margin:0 0 12px}
.doc h2{font-size:15px;margin:22px 0 8px;padding-bottom:6px;border-bottom:1px solid var(--line)}
.doc h3{font-size:13.5px;margin:16px 0 6px}
.doc p{margin:0 0 10px;font-size:13.5px;line-height:1.7;max-width:78ch}
.doc ul,.doc ol{margin:0 0 10px;padding-left:20px;max-width:80ch}
.doc li{margin:3px 0;font-size:13.5px;line-height:1.6}
.doc blockquote{margin:0 0 12px;padding:8px 14px;border-left:3px solid var(--line);color:var(--dim);font-size:13px}
.doc table{border-collapse:collapse;margin:0 0 14px;font-size:12.5px}
.doc th,.doc td{text-align:left;padding:5px 10px 5px 0;border-bottom:1px solid var(--line);vertical-align:top}
.doc th{font-size:11px;color:var(--dim);font-weight:600}
.doc pre{background:var(--neubg);padding:10px 12px;border-radius:6px;overflow-x:auto;font-size:11.5px}
.doc .fn{font-size:11px;color:var(--dim);margin:0 0 14px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
.card{border:1px solid var(--line);border-radius:9px;background:var(--row);padding:12px 14px;min-height:64px;text-decoration:none;color:inherit;display:block}
.card:hover{background:var(--hov);color:inherit}
.card .t{font-size:13.5px;font-weight:600;letter-spacing:-.1px}
.card .m{font-size:11px;color:var(--dim);margin-top:3px;font-variant-numeric:tabular-nums}
.card.none .t{color:var(--faint)}
/* 지원서류 — 공고 헤더·문서 칩. 후보목록 행의 어휘(4px 평판 레일·적합도 막대·굵은 추천도)를 카드로 옮긴 것 */
.app .head,.app .row{grid-template-columns:minmax(150px,.8fr) minmax(230px,1.5fr) 66px 76px 152px 96px}
.orphan .head,.orphan .row{grid-template-columns:minmax(150px,.9fr) minmax(0,1.6fr) 96px}
.row.gone{opacity:.55}
.co.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;margin-top:2px}
.jd{font-size:12.5px;line-height:1.35}
.jd .m{font-size:11px;color:var(--dim);margin-top:2px;font-variant-numeric:tabular-nums}
.rk{font-size:15px;font-weight:800;line-height:1.1;font-variant-numeric:tabular-nums}
.rk .n{font-size:10px;font-weight:600;color:var(--dim);display:block;margin-top:1px}
.rk.r1{color:var(--good)}.rk.r2{color:var(--fg)}.rk.r3{color:var(--dim)}
.due{font-size:12px;line-height:1.3}
.due .d{font-weight:700;font-variant-numeric:tabular-nums}
.due.u0 .d{color:var(--bad)}.due.u1 .d{color:var(--warn)}
.due.always .d{font-weight:400;color:var(--faint);font-size:11.5px}
.due.gone .d{color:var(--bad);text-decoration:line-through}
.loc{font-size:12px;line-height:1.3}
.loc .z{font-weight:700}
.loc.z0 .z,.loc.z1 .z{color:var(--good)}.loc.z2 .z{color:var(--warn)}
.loc.z3 .z,.loc.z4 .z{color:var(--bad)}.loc.z9 .z{color:var(--dim);font-weight:400}
.repc{font-size:12px;line-height:1.4}
.repc .s{font-weight:700;font-variant-numeric:tabular-nums}
.repc .s.v-good{color:var(--good)}.repc .s.v-warn{color:var(--warn)}.repc .s.v-bad{color:var(--bad)}
.repc .t{font-size:10.5px;color:var(--dim);font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.repc .m{font-size:11px;color:var(--dim);margin-top:3px;line-height:1.4}
.repc.none{color:var(--faint)}
.docs{display:flex;align-items:center;gap:6px}
.pips{display:flex;gap:3px}
.pip{width:17px;height:17px;border-radius:4px;background:var(--neubg);color:var(--faint);font-size:9.5px;
  font-weight:700;display:flex;align-items:center;justify-content:center;font-variant-numeric:tabular-nums}
.pip.on{background:var(--goodbg);color:var(--good)}
.dn{font-size:11px;color:var(--dim);font-variant-numeric:tabular-nums}
.dn.part{color:var(--warn);font-weight:600}
.mt{font-size:11px;color:var(--dim);font-variant-numeric:tabular-nums}
.jh{border:1px solid var(--line);border-left:4px solid var(--rail-none);border-radius:9px;
  background:var(--row);padding:14px 16px 12px;margin-bottom:16px}
.jh.v-good{border-left-color:var(--rail-good)}
.jh.v-warn{border-left-color:var(--rail-warn)}
.jh.v-bad{border-left-color:var(--rail-bad)}
.jh.gone{opacity:.62}
.jh-top{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;
  padding-bottom:12px;border-bottom:1px solid var(--line)}
.jh-pos{font-size:16px;font-weight:700;letter-spacing:-.2px;line-height:1.3;
  display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.jh-co{color:var(--dim);font-size:12px;margin-top:3px}
.jh-top .rk{font-size:17px;text-align:right}
.jh-grid{display:grid;grid-template-columns:250px 96px 158px minmax(0,1fr);gap:20px;
  padding:12px 0;border-bottom:1px solid var(--line)}
.jh-l{font-size:11px;color:var(--dim);margin-bottom:5px}
.jh-s{font-size:11px;color:var(--dim);margin-top:4px;line-height:1.45}
.jh-act{display:flex;align-items:center;gap:8px;padding-top:11px;flex-wrap:wrap}
.jh-act .meta{font-size:11px;color:var(--dim);margin-right:auto}
.pill.miss{border-style:dashed;color:var(--faint)}
.oth{padding:7px 0;border-bottom:1px solid var(--line)}
.oth:last-child{border-bottom:0}
.oth .m{font-size:11px;color:var(--dim);margin-top:2px;font-variant-numeric:tabular-nums}
.empty{padding:32px;text-align:center;color:var(--dim);border:1px dashed var(--line);border-radius:9px;background:var(--row);font-size:13px;margin-bottom:12px}
.notice{padding:10px 14px;border:1px solid var(--line);border-radius:9px;background:var(--row);font-size:12.5px;margin-bottom:12px;line-height:1.5}
.notice.bad{border-color:var(--rail-bad);background:var(--badbg);color:var(--bad)}
footer{margin-top:32px;padding-top:18px;border-top:1px solid var(--line);color:var(--dim);font-size:12.5px}
footer p{margin:0 0 7px}
@media(max-width:1060px){.dash .head,.rp .head,.rep .head,.app .head,.orphan .head{display:none}
  .dash .row,.rp .row,.rep .row,.app .row,.orphan .row{grid-template-columns:1fr;gap:6px;padding:13px 14px}
  .jh-grid{grid-template-columns:1fr;gap:12px}
  .sc{text-align:left}.cols,.two{grid-template-columns:1fr}.cards{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style>
"""

_BASE = _jenv.from_string("""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }} — job-scouter</title>""" + CSS + """</head><body><div class="wrap">
{{ nav_html|safe }}
<h1>{{ title }}</h1>
{% if sub %}<p class="sub">{{ sub|safe }}</p>{% endif %}
{{ body|safe }}
{% if source %}<footer><p>원본: {{ source|safe }}</p></footer>{% endif %}
</div></body></html>""")

_STATS = _jenv.from_string("""<div class="stats">{% for n, l in items %}
<div class="stat"><div class="n">{{ n }}</div><div class="l">{{ l }}</div></div>{% endfor %}</div>""")

_DASHBOARD = _jenv.from_string("""
{% if pub and pub.status == 'RUNNING' %}<div class="notice">Publish 실행 중 ({{ pub.start }}) — 승인 {{ pub.ids|length }}건 · 거부 {{ pub.reject_ids|length }}건 처리 중.
등재·거부는 먼저 반영되고, 지원서류 초안과 보고서는 몇 분 더 걸립니다. 끝나기 전에는 제출할 수 없습니다 — 새로고침하면 갱신됩니다.</div>
{% elif pub and pub.status == 'FAILED' %}<div class="notice bad">마지막 Publish 실패 ({{ pub.start }}): {{ pub.error }}
— 등재·거부는 앞 단계라 반영됐을 수 있고, 초안·보고서는 만들어지지 않았습니다. 초안은 <code>worker draft &lt;공고id&gt;</code>로 다시 만듭니다.</div>{% endif %}
<div class="legend"><span>행 왼쪽 색띠 = 평판 판정 (후보목록과 동일)</span>
<span class="k"><i class="sw" style="background:var(--rail-good)"></i>괜찮음</span>
<span class="k"><i class="sw" style="background:var(--rail-warn)"></i>주의</span>
<span class="k"><i class="sw" style="background:var(--rail-bad)"></i>회피</span>
<span class="k"><i class="sw" style="background:var(--rail-none)"></i>정보 없음</span></div>
<form method="post" action="/publish">
<div class="list dash">
<div class="head"><div>포지션 / 회사</div><div>적합도</div><div class="sc">스택</div><div class="sc">도메인</div>
<div class="sc">레벨</div><div class="sc">역할</div><div class="sc">감점</div><div class="conf">conf</div>
<div>판정 사유 · 인용</div><div style="text-align:center">승인</div><div>거부 사유</div></div>
{% for p in proposals %}
<div class="row v-{{ p.rail }}">
<div><div class="pos"><a href="{{ p.url|safe_url }}" target="_blank" rel="noopener">{{ p.title }}</a></div><div class="co">{{ p.company }}{% if p.due %} · <span class="due {{ p.due_cls }}">{{ p.due }}</span>{% endif %}</div></div>
<div class="fit {{ p.tier }}"><span class="v">{{ p.total }}</span><span class="track"><span class="fill" style="width:{{ p.total }}%"></span></span></div>
{% for v, cls in p.cells %}<div class="sc {{ cls }}">{{ v }}</div>{% endfor %}
<div class="conf">{{ '%.2f'|format(p.confidence or 0) }}</div>
<div class="why">{{ p.reason }}<details><summary>인용 {{ p.quotes|length }}건</summary><ul>
{% for q in p.quotes %}<li>{{ q }}</li>{% endfor %}</ul></details></div>
<div style="text-align:center"><input class="chk" type="checkbox" name="approve" value="{{ p.id }}"></div>
<div><input class="in" type="text" name="why_{{ p.id }}" placeholder="거부 사유"></div>
</div>
{% else %}
<div class="empty">대기 중인 후보 없음 — 다음 DailyScan은 매일 09:07</div>
{% endfor %}
</div>
<div class="actions">{% if busy %}<span>실행 중인 Publish가 끝나면 제출할 수 있습니다</span>
{% else %}<span>승인 체크 · 거부 사유 입력 후 제출하면 Publish 워크플로가 등재·판례·지원서류 초안·보고서를 한 번에 처리합니다</span>
<button class="btn primary" type="submit">제출</button>{% endif %}</div>
</form>

<h2>평판 미조사 회사<span class="c">{{ unresearched|length }}</span></h2>
{% if unresearched %}<div class="st">{% for c in unresearched %}<span>{{ c }}</span>{% endfor %}</div>
<p class="sub" style="margin-top:6px">잡플래닛은 자동 조회하지 않습니다. <code>/job-scout</code>로 조사해 <code>jobfeed/기업평판.md</code>를 push하면 다음 Publish부터 색띠와 추천도에 반영됩니다.</p>
{% else %}<p class="sub">없음</p>{% endif %}

<h2>최근 실행</h2>
<div class="rubric">{% if runs_error %}<p style="color:var(--bad)">Temporal 연결 실패: {{ runs_error }}</p>
{% elif runs %}<table><tr><th style="width:160px">종류</th><th style="width:120px">상태</th><th>시작 (KST)</th></tr>
{% for r in runs %}<tr><td>{{ r.type }}</td><td class="st"><span class="{{ 'good' if r.status == 'COMPLETED' else ('bad' if r.status in ('FAILED', 'TERMINATED', 'TIMED_OUT') else '') }}">{{ r.status }}</span></td><td>{{ r.start }}</td></tr>{% endfor %}
</table>{% else %}<p>없음</p>{% endif %}</div>
""")

_RESUME_PROPOSALS = _jenv.from_string("""
<form method="post" action="/resume/apply">
<div class="list rp">
<div class="head"><div>대상</div><div>섹션</div><div>종류</div><div>현재 → 제안</div><div>근거 (PKB)</div><div style="text-align:center">반영</div></div>
{% for it in items %}
<div class="row plain">
<div class="st"><span>{{ it.target }}</span></div>
<div style="font-size:12px">{{ it.section }}</div>
<div class="st"><span class="{{ {'add': 'good', '추가': 'good', 'remove': 'bad', '삭제': 'bad'}.get(it.kind, 'warn') }}">{{ it.kind }}</span></div>
<div style="font-size:12.5px;line-height:1.5">{% if it.current %}<del style="color:var(--faint)">{{ it.current }}</del><br>{% endif %}→ {{ it.proposed }}</div>
<div style="font-size:11.5px;color:var(--dim);line-height:1.45">{{ it.evidence }}</div>
<div style="text-align:center"><input class="chk" type="checkbox" name="apply" value="{{ it.id }}"></div>
</div>
{% else %}
<div class="empty">대기 중인 제안 없음 — ResumeSync는 매주 월 08:00, PKB가 그대로면 제안을 만들지 않습니다</div>
{% endfor %}
</div>
<div class="actions"><span>체크한 제안만 ApplyResume이 사실베이스에 반영하고 검색 색인을 다시 만든 뒤 커밋합니다</span>
<button class="btn primary" type="submit">반영</button></div>
</form>
""")

_ROWS = _jenv.from_string("""
<div class="list rep">{% if items %}{% for it in items %}<div class="row plain">
<div style="font-variant-numeric:tabular-nums;font-size:12.5px">{{ it.date }}</div>
<div class="st"><span class="{{ it.cls }}">{{ it.kind }}</span></div>
<div class="pos"><a href="{{ it.href }}">{{ it.name }}</a></div></div>{% endfor %}
{% else %}<div class="empty">없음</div>{% endif %}</div>""")

_GROUPS = _jenv.from_string("""
<div class="two">{% for col in cols %}<div>{% for title, items in col %}
<h2 style="margin-top:0">{{ title }}<span class="c">{{ items|length }}</span></h2>
<div class="list">{% for href, name in items %}<div class="row plain"><div class="pos" style="font-weight:500"><a href="{{ href }}">{{ name }}</a></div></div>{% endfor %}</div>
{% endfor %}</div>{% endfor %}</div>
{% if not cols %}<div class="empty">없음</div>{% endif %}""")

_APPS = _jenv.from_string("""
<h2>공고에 연결된 폴더<span class="c">{{ items|length }}</span></h2>
<div class="list app">
<div class="head"><div>회사 · 폴더</div><div>연결된 공고</div><div>추천도</div><div>마감</div>
<div>문서 (0_JD … 4_포트폴리오)</div><div>최종 수정</div></div>
{% for it in items %}<div class="row v-{{ it.c.rep_key }}{{ ' gone' if it.c.closed }}">
<div><div class="pos"><a href="/applications/job/{{ it.c.id }}">{{ it.c.company }}</a></div>
<div class="co mono">{{ it.slug }}</div></div>
<div class="jd"><div>{{ it.c.title }}</div><div class="m">{{ it.c.id }}{% if it.others %} · 이 회사 공고 {{ it.others + 1 }}건{% endif %}</div></div>
<div class="rk {{ 'r1' if it.c.rec >= 85 else 'r2' if it.c.rec >= 70 else 'r3' }}">{{ it.c.rec }}
<span class="n">{% if it.c.rank %}#{{ it.c.rank }}{% else %}마감{% endif %}</span></div>
<div class="due {{ it.c.due_cls }}"><span class="d">{{ it.c.due }}</span></div>
<div class="docs"><div class="pips">{% for p in it.pips %}<span class="pip{{ ' on' if p.on }}">{{ p.n }}</span>{% endfor %}</div>
<span class="dn{{ '' if it.docs|length == 5 else ' part' }}">{{ '5종' if it.docs|length == 5 else '%d / 5'|format(it.docs|length) }}</span></div>
<div class="mt">{{ it.mtime }}</div></div>
{% else %}<div class="empty">공고에 연결된 폴더가 아직 없습니다</div>{% endfor %}
</div>""")

_ORPHANS = _jenv.from_string("""
{% if items %}<h2>공고를 못 찾은 폴더<span class="c">{{ items|length }}</span></h2>
<div class="notice">문서에 적힌 공고가 후보목록에서 <b>내려간</b> 경우와, 공고 링크가 <b>아예 없는</b> 경우입니다.
후자는 문서 어딘가에 원티드·점핏 링크를 한 줄 적어 주면 다음 열람부터 이어집니다.</div>
<div class="list orphan">
{% for it in items %}<div class="row plain">
<div><div class="pos"><a href="/applications/{{ it.slug }}">{{ it.slug }}</a></div>
<div class="co">md {{ it.files|length }}{% if it.ids %} · {{ it.ids|join(', ') }}{% endif %}</div></div>
<div style="font-size:12.5px;color:var(--dim)">{{ it.why }}</div>
<div class="st"><span class="{{ it.cls }}">{{ it.badge }}</span></div>
</div>{% endfor %}
</div>{% endif %}""")

_JOBHEAD = _jenv.from_string("""
<div class="jh v-{{ c.rep_key }}{{ ' gone' if c.closed }}">
<div class="jh-top"><div>
<div class="jh-pos">{{ c.title }}
<span class="st"><span class="{{ 'bad' if c.closed }}">{{ '공고 마감' if c.closed else ('초안 없음' if not folder else '미지원') }}</span></span></div>
<div class="jh-co">{{ c.company }} ·
<a href="{{ c.url|safe_url }}" target="_blank" rel="noopener">{{ '점핏' if c.id.startswith('j') else '원티드' }} {{ c.id }} ↗</a>
{% if folder %} · <code>applications/{{ folder.slug }}</code>{% endif %}</div></div>
<div class="rk {{ 'r1' if c.rec >= 85 else 'r2' if c.rec >= 70 else 'r3' }}">{{ c.rec }}
<span class="n">추천도{% if c.rank %} · #{{ c.rank }}{% endif %}</span></div></div>
<div class="jh-grid">
<div><div class="jh-l">적합도</div>
<div class="fit {{ c.tier }}"><span class="v">{{ c.total }}</span>
<span class="track"><span class="fill" style="width:{{ c.total }}%"></span></span></div>
<div class="jh-s">스택 {{ c.scores[0] }} · 도메인 {{ c.scores[1] }} · 레벨 {{ c.scores[2] }} · 역할 {{ c.scores[3] }} · 감점 {{ c.scores[4] or '—' }}</div></div>
<div><div class="jh-l">마감</div><div class="due {{ c.due_cls }}"><span class="d">{{ c.due }}</span></div></div>
<div><div class="jh-l">근무지 · 통근</div><div class="loc z{{ c.zone }}"><span class="z">{{ c.zone_label }}</span></div>
<div class="jh-s">{{ c.addr }}</div></div>
<div><div class="jh-l">평판</div>
{% if c.rep %}<div class="repc"><span class="s v-{{ c.rep_key }}">{{ c.rep_label }} {{ c.rep[1] }}</span>
<span class="t">/ {{ c.rep[2] }}건 · ★{{ c.rep[3] }}</span><div class="m">{{ c.rep[4] }}</div></div>
{% else %}<div class="repc none">{{ c.rep_note }}</div>{% endif %}</div>
</div>
<div class="jh-act">
{% if folder %}<span class="meta">최종 수정 {{ folder.mtime }} · 문서 {{ folder.docs|length }}/5</span>{% endif %}
<a class="pill" href="/candidates">후보목록에서 보기</a>
<form method="post" action="/applications/draft" style="margin:0">
<input type="hidden" name="id" value="{{ c.id }}">
<button class="btn{{ '' if folder else ' primary' }}" type="submit">{{ '초안 다시 만들기' if folder else '5종 초안 만들기' }}</button>
</form></div>
</div>""")

_JOBDOCS = _jenv.from_string("""
<div class="cols"><div>
{% if tabs %}<div class="bar"><span class="lbl">문서</span>
{% for t in tabs %}{% if t.missing %}<span class="pill miss">{{ t.name }} 없음</span>
{% else %}<a class="pill" href="?doc={{ t.name }}" aria-pressed="{{ 'true' if t.on else 'false' }}">{{ t.name }}</a>{% endif %}{% endfor %}</div>
<div class="doc"><p class="fn">{{ cur }}</p>{{ html|safe }}</div>
{% else %}<div class="empty">아직 문서가 없습니다.<br>
<span style="font-size:12px">초안 생성은 몇 분 걸립니다 — 끝나면 <code>0_JD</code>부터 <code>4_포트폴리오_구성</code>까지 5종이 이 자리에 채워집니다.</span></div>{% endif %}
</div><div>
{% if others %}<div class="side"><h3>이 회사의 다른 공고 {{ others|length }}건</h3>
{% for o in others %}<div class="oth"><a href="/applications/job/{{ o.id }}">{{ o.title }}</a>
<div class="m">추천도 {{ o.rec }}{% if o.rank %} · #{{ o.rank }}{% endif %} · {{ o.due }} · 적합도 {{ o.total }}</div></div>{% endfor %}
</div>{% endif %}
{% if folder and folder.files|length > folder.docs|length %}<div class="side"><h3>표준 5종이 아닌 파일</h3>
<div class="files">{% for f in folder.files %}{% if f not in ['0_JD.md','1_맞춤_이력서.md','2_자기소개서.md','3_면접지식맵.md','4_포트폴리오_구성.md'] %}
<a href="?doc={{ f }}">{{ f }}</a>{% endif %}{% endfor %}</div></div>{% endif %}
</div></div>""")

_NOTICE = _jenv.from_string("""
<div class="notice bad"><b>저장하지 못했습니다.</b> {{ cause }}</div>
{% if conflict %}<p class="sub">대상 문서가 대화를 시작한 뒤에 바뀌었습니다(다른 창에서 수정했거나
ResumeSync 반영이 있었을 수 있습니다). <b>덮어쓰지 않고 멈췄으니 두 수정 모두 그대로 있습니다.</b>
바뀐 내용을 확인한 뒤, 이 대화는 버리고 새로 시작하는 편이 안전합니다.</p>{% endif %}
<div class="bar"><a class="pill" href="/resume/chat/{{ sid }}?key={{ key }}">대화로 돌아가기</a>
<a class="pill" href="/resume/history?key={{ key }}">문서 이력 보기</a>
<a class="pill" href="/resume">이력서</a></div>""")


_DOCS = _jenv.from_string("""
{% if sections %}{% if sections|length > 1 %}<div class="bar"><span class="lbl">문서</span>
{% for name, html in sections %}<a class="pill" href="#{{ loop.index }}">{{ name }}</a>{% endfor %}</div>{% endif %}
{% for name, html in sections %}<div class="doc" id="{{ loop.index }}"><p class="fn">{{ name }}</p>{{ html|safe }}</div>{% endfor %}
{% else %}<div class="empty">없음</div>{% endif %}""")

_RESUME = _jenv.from_string("""
<div class="cols"><div>
{% for name, html, key in sections %}<div class="doc" id="{{ loop.index }}"><p class="fn">{{ name }} · <a href="/resume/history?key={{ key }}">이력</a> · <a href="/resume/chat?key={{ key }}">대화로 고치기</a></p>{{ html|safe }}</div>{% endfor %}
</div><div>
<div class="side"><h3>진행 중 대화</h3>
{% if chats %}<div class="files">{% for c in chats %}<a href="/resume/chat/{{ c.sid }}?key={{ c.target }}">{{ c.target }} · {{ c.n }}턴</a>{% endfor %}</div>
{% else %}<p>없음</p>{% endif %}</div>
<div class="side"><h3>갱신 제안</h3><div class="n">{{ pending }}<span style="font-size:12px;font-weight:400;color:var(--dim)"> 건 대기</span></div>
<p>ResumeSync 매주 월 08:00 · PKB와 대조해 차이만 제안</p>
<p style="margin-top:8px"><a class="pill" href="/resume/proposals">갱신 제안 보기</a></p></div>
<div class="side"><h3>문서</h3><div class="files">{% for name, html, key in sections %}<a href="#{{ loop.index }}">{{ name }}</a>{% endfor %}</div></div>
<div class="side"><h3>규칙</h3><p>사실베이스는 사람이 검증한 문장만 담습니다. 판정·초안·검색(jobscout_facts)이 모두 이 문서를 읽습니다.</p></div>
</div></div>""")

_HISTORY_LOG = _jenv.from_string("""
<div class="list">
{% for c in commits %}<div class="row plain" style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
<div style="font-variant-numeric:tabular-nums;font-size:12px;color:var(--dim)">{{ c.date }}</div>
<code>{{ c.sha }}</code>
<div style="flex:1 1 200px;font-size:12.5px">{{ c.subject }}</div>
<a class="pill" href="/resume/history?key={{ key }}&sha={{ c.sha }}">diff 보기</a>
<form method="post" action="/resume/revert" style="margin:0">
<input type="hidden" name="key" value="{{ key }}"><input type="hidden" name="sha" value="{{ c.sha }}">
<button class="btn" type="submit">이 버전으로 되돌리기</button>
</form>
</div>
{% else %}<div class="empty">커밋 이력 없음</div>{% endfor %}
</div>""")

_HISTORY = _jenv.from_string("""
<div class="two"><div>
<h2 style="margin-top:0">커밋 이력<span class="c">{{ commits|length }}</span></h2>
{{ log_html|safe }}
</div><div>
<div class="side"><h3>diff{% if sha %} · {{ sha }}{% endif %}</h3>
{% if diff_html %}<pre style="margin:8px 0 0;overflow-x:auto;font-size:11.5px">{{ diff_html|safe }}</pre>
{% else %}<p>왼쪽에서 「diff 보기」를 눌러 확인</p>{% endif %}</div>
</div></div>""")

_CHAT = _jenv.from_string("""
<div class="two"><div>
<div class="list">
{% for t in turns %}<div class="row plain">
{% if t.role == 'user' %}<div style="font-size:12.5px"><b>나</b> {{ t.text }}</div>
{% else %}<div style="font-size:12.5px"><b>조수</b> {{ t.text }}
<span class="st"><span class="good">적용 {{ t.applied }}건</span></span>
{% if t.skipped %}<div style="font-size:11px;color:var(--dim);margin-top:4px">{% for s in t.skipped %}<div>{{ s }}</div>{% endfor %}</div>{% endif %}
</div>{% endif %}
</div>
{% else %}<div class="empty">아직 대화 없음</div>{% endfor %}
</div>
<form method="post" action="/resume/chat/{{ sid }}" class="actions" style="margin-top:10px">
<input type="hidden" name="key" value="{{ key }}">
<textarea class="in" name="message" rows="3" placeholder="수정 요청을 입력하세요" style="flex:1"></textarea>
<button class="btn primary" type="submit">보내기</button>
</form>
</div><div>
<div class="side"><h3>변경사항</h3>
{% if diff_html %}<pre style="margin:8px 0 0;overflow-x:auto;font-size:11.5px">{{ diff_html|safe }}</pre>
{% else %}<p>아직 수정 없음</p>{% endif %}</div>
<form method="post" action="/resume/chat/{{ sid }}/end" class="actions">
<input type="hidden" name="key" value="{{ key }}">
<button class="btn primary" type="submit" name="save" value="1">저장</button>
<button class="btn" type="submit" name="save" value="0">버림</button>
</form>
</div></div>""")


def _nav(active: str) -> str:
    return _NAV.render(nav=NAV, active=active)


def _render(title: str, body: str, active: str = "", sub: str = "", source: str = "") -> HTMLResponse:
    return HTMLResponse(_BASE.render(title=title, body=body, nav_html=_nav(active),
                                     sub=sub, source=source))


def _render_md(text: str) -> str:
    return mdlib.markdown(text, extensions=["tables", "fenced_code"])


def _guard(rel: str) -> None:
    """경로 조작 차단 — 절대경로·`..` 세그먼트."""
    if rel.startswith("/") or ".." in Path(rel).parts:
        raise HTTPException(400, "잘못된 경로")


def _git_log(rel: str, n: int = 30) -> list[dict]:
    """[{"sha","date","subject"}] — 해당 파일을 건드린 커밋만. --follow라 이름을 바꾸기 전
    이력도 이어진다(JK.md → 이력서.md). 읽기 전용 — 자격증명 불필요."""
    r = subprocess.run(
        ["git", "-C", str(JOBFEED.parent), "log", f"-{n}", "--follow",
         "--format=%h%x09%ad%x09%s", "--date=format:%Y-%m-%d %H:%M", "--", rel],
        capture_output=True, text=True, timeout=20)
    out = []
    for ln in r.stdout.splitlines():
        sha, _, rest = ln.partition("\t")
        date, _, subject = rest.partition("\t")
        out.append({"sha": sha, "date": date, "subject": subject})
    return out


def _git_show(sha: str, rel: str) -> str:
    """한 커밋이 그 파일에 낸 diff 원문. sha는 호출 전에 검증돼 있어야 한다.
    이름을 바꾸기 전 커밋은 옛 이름으로만 나온다 — git_path_at으로 그 시점 경로를 찾는다."""
    rel = git_path_at(str(JOBFEED.parent), sha, rel)
    r = subprocess.run(
        ["git", "-C", str(JOBFEED.parent), "show", "-p", sha, "--", rel],
        capture_output=True, text=True, timeout=20)
    return r.stdout


def _color_diff(text: str) -> str:
    """diff 각 줄을 이스케이프한 뒤 +/- 본문 줄만 --good/--bad 토큰으로 색을 준다
    (+++/--- 헤더 줄은 제외)."""
    out = []
    for ln in text.splitlines():
        esc = str(escape(ln))
        if ln.startswith("+") and not ln.startswith("+++"):
            out.append(f'<span style="color:var(--good)">{esc}</span>')
        elif ln.startswith("-") and not ln.startswith("---"):
            out.append(f'<span style="color:var(--bad)">{esc}</span>')
        else:
            out.append(esc)
    return "\n".join(out)


def _load_proposals() -> list[dict]:
    path = JOBFEED / PROPOSALS
    if not path.exists():
        return []
    props = json.loads(path.read_text())
    return sorted(props.values(), key=lambda p: -p.get("total", 0))


def _decorate(p: dict, rep: dict[str, str], dues: dict[str, str], today: date) -> dict:
    """템플릿용 파생 필드 — 후보목록 rowHTML과 같은 규칙(hi ≥85%, lo ≤40%, 총점 등급)."""
    sc = list(p.get("scores") or []) + [0] * 5
    cells = [(v, "hi" if v / m >= .85 else ("lo" if v / m <= .4 else "")) for v, m in zip(sc, _MAX)]
    cells.append((sc[4] or "·", "pen" if sc[4] else ""))
    total = p.get("total", 0)
    due, due_cls = _due_label(dues.get(str(p["id"])), today)
    return {**p, "cells": cells, "tier": "t1" if total >= 80 else "t2" if total >= 70 else "t3",
            "rail": rep.get(_norm(p.get("company", "")), "none"), "due": due, "due_cls": due_cls}


# --- Temporal 접근 — 이 세 함수만 client를 만든다. 테스트에서 monkeypatch. ---

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


async def start_draft(cid: str) -> str:
    client = await Client.connect(TEMPORAL)
    handle = await client.start_workflow(
        Draft.run, cid, id=f"draft-{cid}", task_queue=Q_WF)
    return handle.id


async def start_revert(key: str, sha: str) -> str:
    client = await Client.connect(TEMPORAL)
    handle = await client.start_workflow(
        RevertFile.run, {"key": key, "sha": sha},
        id=f"revert-{sha[:7]}-{uuid4().hex[:6]}", task_queue=Q_WF)
    return handle.id


def load_chat(sid: str) -> dict | None:
    """채팅 세션 버퍼 읽기 전용 열람 — web은 이 버퍼에 쓰지 않는다(워크플로만 시작)."""
    path = CHAT_DIR / f"{sid}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


async def start_resume_chat(sid: str, key: str, message: str) -> dict:
    """한 턴 실행 후 결과(갱신된 세션 dict)를 기다린다.
    ponytail: 턴 POST가 LLM 응답까지 블록한다(최대 6분) — LAN 개인 도구라 이걸로 충분.
    지연이 거슬리면 워크플로를 시작만 하고 페이지에서 폴링하는 방식으로 바꾼다."""
    buf = load_chat(sid)
    n = len(buf["turns"]) if buf else 0
    client = await Client.connect(TEMPORAL)
    return await client.execute_workflow(
        ResumeChat.run, {"sid": sid, "key": key, "message": message},
        id=f"chat-{sid}-{n}", task_queue=Q_WF)


async def end_chat(sid: str, save: bool) -> str:
    client = await Client.connect(TEMPORAL)
    return await client.execute_workflow(
        EndChat.run, {"sid": sid, "save": save},
        id=f"endchat-{sid}", task_queue=Q_WF)


async def recent_runs() -> list[dict]:
    # dev 서버(SQLite)는 ORDER BY를 지원하지 않는다 — 넉넉히 받아 여기서 정렬
    client = await Client.connect(TEMPORAL)
    out = []
    async for wf in client.list_workflows(
            " OR ".join(f"WorkflowType='{t}'" for t in
                        ("DailyScan", "Publish", "ResumeSync", "ApplyResume", "Draft")),
            limit=30):
        out.append({"type": wf.workflow_type,
                    "status": wf.status.name if wf.status else "?",
                    "start": wf.start_time.astimezone(KST).strftime("%Y-%m-%d %H:%M")})
    return sorted(out, key=lambda r: r["start"], reverse=True)[:6]


async def latest_publish() -> dict | None:
    """가장 최근 Publish 한 건. 실행 중이면 입력(승인·거부 id) — 대시보드가 그 행을 '처리 중'으로
    숨기고 제출을 막는다. 실패면 원인 메시지 — 제출 직후 화면이 그대로라 실패를 모르고 지나치지 않게."""
    client = await Client.connect(TEMPORAL)
    latest = None
    async for wf in client.list_workflows("WorkflowType='Publish'", limit=30):
        if latest is None or wf.start_time > latest.start_time:
            latest = wf
    if latest is None:
        return None
    info = {"id": latest.id, "status": latest.status.name if latest.status else "?",
            "start": latest.start_time.astimezone(KST).strftime("%Y-%m-%d %H:%M"),
            "ids": [], "reject_ids": [], "error": ""}
    handle = client.get_workflow_handle(latest.id)
    if info["status"] == "RUNNING":
        hist = await handle.fetch_history()
        payload = hist.events[0].workflow_execution_started_event_attributes.input.payloads[0]
        params = json.loads(payload.data)
        info["ids"] = [str(i) for i in params.get("ids") or []]
        info["reject_ids"] = [str(r["id"]) for r in params.get("rejects") or []]
    elif info["status"] == "FAILED":
        try:
            await handle.result()
        except Exception as e:   # WorkflowFailureError → ActivityError → ApplicationError 순으로 원인이 감싸여 있다
            err = e
            while getattr(err, "cause", None):
                err = err.cause
            info["error"] = getattr(err, "message", None) or str(err)
    return info


async def _latest_publish_safe() -> dict | None:
    try:
        return await latest_publish()
    except Exception:
        return None


# --- 라우트 ---

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    rep = _reputation()
    pub = await _latest_publish_safe()
    busy = set(pub["ids"]) | set(pub["reject_ids"]) if pub and pub["status"] == "RUNNING" else set()
    dues, today = _dues(), datetime.now(KST).date()
    proposals = [_decorate(p, rep, dues, today) for p in _load_proposals() if str(p["id"]) not in busy]
    unresearched = sorted({p["company"] for p in proposals if _norm(p["company"]) not in rep})
    runs, runs_error = None, None
    try:
        runs = await recent_runs()
    except Exception as e:
        runs_error = str(e)
    stats = _STATS.render(items=[(len(proposals), "승인 대기"),
                                 (sum(1 for p in proposals if p.get("total", 0) >= 75), "적합도 75+"),
                                 (sum(1 for p in proposals if p["due_cls"] == "gone"), "마감 지남"),
                                 (len(unresearched), "평판 미조사 회사"), ("09:07", "다음 DailyScan")])
    body = stats + _DASHBOARD.render(proposals=proposals, unresearched=unresearched,
                                     runs=runs, runs_error=runs_error, pub=pub,
                                     busy=bool(busy) or (pub is not None and pub["status"] == "RUNNING"))
    return _render("승인 대기", body, active="대시보드",
                   sub="<b>DailyScan</b>이 매일 09:07 새 공고를 판정한 뒤 아직 결정하지 않은 후보입니다. "
                       "승인하면 <b>후보목록에 등재</b>되고 지원서류 초안 5종이 만들어지며, 거부 사유를 적으면 판례로 남아 다음 판정에 참고됩니다.",
                   source="<code>jobfeed/proposals.json</code> · 판례 <code>data/judgments.jsonl</code> · 평판 <code>jobfeed/기업평판.md</code>")


@app.post("/publish")
async def publish(request: Request):
    pub = await _latest_publish_safe()
    if pub and pub["status"] == "RUNNING":
        # 동시에 두 Publish가 같은 repo에 커밋·push하면 충돌한다 — 끝난 뒤 다시
        raise HTTPException(409, "Publish 실행 중 — 끝난 뒤 다시 제출")
    form = await request.form()
    ids = form.getlist("approve")
    rejects = [{"id": k[len("why_"):], "why": v.strip()}
               for k, v in form.multi_items()
               if k.startswith("why_") and str(v).strip()]
    await start_publish(list(ids), rejects)
    return RedirectResponse("/", status_code=302)


@app.get("/candidates", response_class=HTMLResponse)
def candidates():
    """build.py 산출물을 그대로 내보내되 사이트 내비와 지원서류 색인만 끼워 넣는다.
    원본은 build.py --open으로 단독으로도 열려야 하므로 손대지 않는다 —
    template.html은 window.__APPS__가 없으면 지원서류 칩을 그리지 않는다."""
    path = JOBFEED / "후보목록.html"
    if not path.exists():
        return _render("후보목록", '<div class="empty">아직 없음 — Publish 실행 후 생성됨</div>', active="후보목록")
    html = path.read_text()
    html = html.replace("</head>", f"<style>{NAV_CSS}</style></head>", 1)
    apps = {cid: {"slug": f["slug"], "n": len(f["docs"])}
            for f in app_folders() for cid in f["ids"]}
    # 폴더명에는 `/`가 못 들어가지만 </script> 조기 종료는 값과 무관하게 막아 둔다
    inject = ("<script>window.__APPS__="
              + json.dumps(apps, ensure_ascii=False).replace("</", "<\\/") + ";</script>")
    nav = _nav("후보목록")
    if '<div class="wrap">' in html:
        html = html.replace('<div class="wrap">', '<div class="wrap">' + nav, 1)
    else:
        html = html.replace("<body>", "<body>" + nav, 1)
    html = html.replace("<body>", "<body>" + inject, 1)
    return HTMLResponse(html, headers={"Content-Security-Policy": CSP_CANDIDATES})


@app.get("/reports", response_class=HTMLResponse)
def reports_index():
    d = JOBFEED / "reports"
    names = sorted((p.stem for p in d.glob("*.md")), reverse=True) if d.exists() else []
    items = []
    for n in names:
        date, _, kind = n.partition("_")
        items.append({"date": date, "kind": kind or "-", "name": n, "href": f"/reports/{n}",
                      "cls": "good" if kind == "자동사이클" else ""})
    return _render("보고서", _ROWS.render(items=items), active="보고서",
                   sub=f"{len(items)}건. <b>매칭조사</b>는 <code>/job-scout</code>로 직접 조사한 날의 기록, "
                       "<b>자동사이클</b>은 Publish가 쓰는 사이클 요약입니다.",
                   source="<code>jobfeed/reports/*.md</code>")


@app.get("/reports/{name}", response_class=HTMLResponse)
def report(name: str):
    _guard(name)
    path = JOBFEED / "reports" / f"{name}.md"
    if not path.exists():
        raise HTTPException(404, "보고서 없음")
    return _render(name, _DOCS.render(sections=[(path.name, _render_md(path.read_text()))]), active="보고서")


def _chat_sessions() -> list[dict]:
    """진행 중(미저장) 채팅 세션 목록 — CHAT_DIR 바로 아래 json만(끝난 세션은 done/으로 옮겨져 안 걸림)."""
    if not CHAT_DIR.exists():
        return []
    out = []
    for p in sorted(CHAT_DIR.glob("*.json")):
        try:
            s = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        out.append({"sid": s["sid"], "target": s["target"], "n": len(s["turns"]) // 2})
    return out


@app.get("/resume", response_class=HTMLResponse)
def resume():
    sections = []   # (표시명, html, resume_target 키) — 키는 이력·대화 링크가 쓴다
    if RESUME.exists():
        sections.append(("이력서.md", _render_md(RESUME.read_text()), "이력서.md"))
    body = _RESUME.render(sections=sections, pending=len(_load_resume_proposals()), chats=_chat_sessions())
    return _render("이력서", body, active="이력서",
                   sub="이력서 정본 <b>이력서.md</b> 한 문서를 그대로 렌더링합니다. 「대화로 고치기」·"
                       "「이력」은 이 문서 하나에 걸립니다. 판정·초안의 근거인 사실베이스는 "
                       '<a href="/docs">/docs</a>에서 볼 수 있고, 갱신은 ResumeSync 제안을 승인해야만 반영됩니다.',
                   source="<code>이력서.md</code>")


@app.get("/resume/history", response_class=HTMLResponse)
def resume_history(key: str, sha: str = ""):
    try:
        path = resume_target(key)
    except ValueError:
        raise HTTPException(400, "허용되지 않은 이력서 대상")
    try:
        rel = str(path.relative_to(JOBFEED.parent))
    except ValueError:
        # 정상 배치에서는 FACTBASE도 JOBFEED.parent(데이터 repo) 안쪽 — env가 밖으로 잘못 잡힌 경우
        raise HTTPException(400, f"{key}는 데이터 repo 밖에 있어 이력을 볼 수 없습니다")
    diff_html = ""
    if sha:
        if not _SHA.fullmatch(sha):
            raise HTTPException(400, "잘못된 sha 형식")
        diff_html = _color_diff(_git_show(sha, rel))
    commits = _git_log(rel)
    body = _HISTORY.render(commits=commits, log_html=_HISTORY_LOG.render(commits=commits, key=key),
                           diff_html=diff_html, sha=sha)
    return _render(f"수정 이력 — {key}", body, active="이력서",
                   sub=f"<code>{escape(key)}</code>의 git 커밋 이력입니다. 되돌리기는 과거 내용을 "
                       "새 커밋으로 다시 올릴 뿐 히스토리는 지우지 않으므로, 되돌린 것도 다시 되돌릴 수 있습니다. "
                       '<a href="/resume">이력서 보기로 돌아가기</a>')


@app.post("/resume/revert")
async def resume_revert(request: Request):
    form = await request.form()
    key, sha = form.get("key", ""), form.get("sha", "")
    if not _SHA.fullmatch(sha):
        raise HTTPException(400, "잘못된 sha 형식")
    try:
        resume_target(key)
    except ValueError:
        raise HTTPException(400, "허용되지 않은 이력서 대상")
    await start_revert(key, sha)
    return RedirectResponse(f"/resume/history?key={key}", status_code=302)


@app.get("/resume/chat")
def resume_chat_new(key: str):
    try:
        resume_target(key)
    except ValueError:
        raise HTTPException(400, "허용되지 않은 이력서 대상")
    sid = uuid4().hex[:12]
    return RedirectResponse(f"/resume/chat/{sid}?key={key}", status_code=302)


@app.get("/resume/chat/{sid:path}", response_class=HTMLResponse)
def resume_chat_page(sid: str, key: str = ""):
    # sid는 경로 세그먼트 하나여야 하지만, %2f로 인코딩된 슬래시가 라우팅 단계에서
    # 실제 슬래시로 풀려 여러 세그먼트가 될 수 있다 — :path로 받아 여기서 형식 검증한다
    if not SID_RE.fullmatch(sid):
        raise HTTPException(400, "잘못된 세션 id")
    buf = load_chat(sid)
    target_key = buf["target"] if buf else key   # 첫 턴 전(버퍼 없음)엔 쿼리의 key를 쓴다
    try:
        resume_target(target_key)
    except ValueError:
        raise HTTPException(400, "허용되지 않은 이력서 대상")
    diff_html = ""
    if buf:
        diff = "\n".join(difflib.unified_diff(
            buf["base_doc"].splitlines(), buf["doc"].splitlines(), "저장 전", "현재", lineterm=""))
        diff_html = _color_diff(diff)
    body = _CHAT.render(sid=sid, key=target_key, turns=buf["turns"] if buf else [], diff_html=diff_html)
    return _render(f"대화로 고치기 — {target_key}", body, active="이력서",
                   sub=f"<code>{escape(target_key)}</code>를 대화로 고칩니다. 저장 전까지는 세션 버퍼일 뿐이라 "
                       '원본은 바뀌지 않습니다. <a href="/resume">이력서 보기로 돌아가기</a>')


@app.post("/resume/chat/{sid}")
async def resume_chat_post(sid: str, request: Request):
    if not SID_RE.fullmatch(sid):
        raise HTTPException(400, "잘못된 세션 id")
    form = await request.form()
    key, message = form.get("key", ""), form.get("message", "").strip()
    try:
        resume_target(key)
    except ValueError:
        raise HTTPException(400, "허용되지 않은 이력서 대상")
    if message:   # 빈 메시지는 무시하고 그냥 돌아간다
        await start_resume_chat(sid, key, message)
    return RedirectResponse(f"/resume/chat/{sid}?key={key}", status_code=302)


@app.post("/resume/chat/{sid}/end")
async def resume_chat_end(sid: str, request: Request):
    if not SID_RE.fullmatch(sid):
        raise HTTPException(400, "잘못된 세션 id")
    form = await request.form()
    try:
        await end_chat(sid, form.get("save") == "1")
    except Exception as e:
        # 저장 거부(대상 파일이 세션 중 바뀜)가 여기로 온다. 세션 버퍼는 그대로 남아 있으므로
        # 스택트레이스 500 대신 이유와 다음 행동을 보여준다 — 2026-08-27 라이브 검증에서 발견.
        # Temporal이 activity 예외를 두 겹으로 감싸 str(e)는 "Workflow execution failed"뿐이다 —
        # 실제 사유는 __cause__ 끝에 있다(같은 검증에서 발견).
        root = e
        while root.__cause__ is not None:
            root = root.__cause__
        cause = str(root).split("\n")[0][:200]
        s = load_chat(sid) or {}
        body = _NOTICE.render(
            cause=cause, sid=sid, key=s.get("target", ""),
            conflict="세션 시작 후" in cause)
        return _render("저장 실패", body, active="이력서", sub="")
    return RedirectResponse("/resume", status_code=302)


def _load_resume_proposals() -> list[dict]:
    path = JOBFEED / RESUME_PROPOSALS
    if not path.exists():
        return []
    return json.loads(path.read_text()).get("items", [])


@app.get("/resume/proposals", response_class=HTMLResponse)
def resume_proposals():
    items = _load_resume_proposals()
    stats = _STATS.render(items=[(len(items), "대기 제안"), ("월 08:00", "ResumeSync")])
    return _render("이력서 갱신 제안", stats + _RESUME_PROPOSALS.render(items=items), active="이력서",
                   sub="매주 월요일 <b>ResumeSync</b>가 PKB(경력·소개 문서)와 사실베이스를 대조해 차이만 제안합니다. "
                       "PKB가 지난주와 같으면 제안을 만들지 않습니다(해시 게이트). "
                       '<a href="/resume">이력서 보기로 돌아가기</a>',
                   source="<code>jobfeed/resume_proposals.json</code>")


@app.post("/resume/apply")
async def resume_apply(request: Request):
    form = await request.form()
    ids = form.getlist("apply")
    await start_apply_resume(list(ids))
    return RedirectResponse("/resume/proposals", status_code=302)


# --- 후보목록 ↔ 지원서류 ------------------------------------------------------
# 연결 키는 회사명이 아니라 **공고 id**다(candidates.py.app_folders 참조). 파생값 계산은
# jobscouter/candidates.py 한 곳 — app_folders·job_index·candidate_rows는 위에서 import.


def _folder_view(folder: dict, doc: str) -> tuple[str, list, str]:
    """(선택된 문서명, 탭 목록, 본문 html). doc이 없거나 이상하면 첫 문서로."""
    files = folder["files"]
    if not files:
        return ("", [], "")
    cur = doc if doc in files else files[0]
    tabs = [{"name": f, "on": f == cur} for f in files]
    tabs += [{"name": f, "on": False, "missing": True} for f in APP_FILES if f not in files]
    return (cur, tabs, _render_md((APPLICATIONS / folder["slug"] / cur).read_text()))


def _rank_key(c: dict) -> float:
    """정렬용 — rank는 candidate_rows()가 이미 반올림 전 추천도로 매겨 둔 순위. None(마감)은 맨 뒤로."""
    return c["rank"] if c["rank"] is not None else float("inf")


@app.get("/applications", response_class=HTMLResponse)
def applications_index():
    cands = {c["id"]: c for c in candidate_rows()}
    linked, orphans = [], []
    for f in app_folders():
        hits = [cands[i] for i in f["ids"] if i in cands]
        if hits:
            c = min(hits, key=_rank_key)
            same = [x for x in cands.values() if _norm(x["company"]) == _norm(c["company"])]
            linked.append({**f, "c": c, "others": len(same) - 1,
                           "pips": [{"n": n[0], "on": n in f["docs"]} for n in APP_FILES]})
        else:
            orphans.append({**f, "why": ("문서의 공고 id가 후보목록에 없음 — 내려갔거나 거부된 공고"
                                         if f["ids"] else "문서 어디에도 공고 링크가 없음"),
                            "badge": "공고 내려감" if f["ids"] else "id 없음",
                            "cls": "warn" if f["ids"] else "bad"})
    linked.sort(key=lambda x: _rank_key(x["c"]))
    stats = _STATS.render(items=[
        (len(cands), "등재 공고"), (len(linked) + len(orphans), "지원서류 폴더"),
        (len(linked), "공고에 연결됨"),
        (sum(1 for o in orphans if o["ids"]), "공고 내려감"),
        (sum(1 for o in orphans if not o["ids"]), "id 없음 — 수동 연결"),
    ])
    body = stats + _APPS.render(items=linked) + _ORPHANS.render(items=orphans)
    return _render("지원서류", body, active="지원서류",
                   sub="폴더와 등재 공고를 <b>공고 id</b>로 이어 한 줄로 보여줍니다 — 회사명이 아니라 "
                       "문서에 적힌 <code>wanted.co.kr/wd/{id}</code>가 연결 키입니다. "
                       "승인한 공고는 Publish가 <b>JD·맞춤 이력서·자기소개서·면접지식맵·포트폴리오 구성</b> "
                       "5종 초안을 만들어 두고, 검토는 사람이 합니다.",
                   source="<code>applications/&lt;폴더&gt;/*.md</code> · <code>jobfeed/candidates.json</code>")


@app.post("/applications/draft")
async def applications_draft(request: Request):
    form = await request.form()
    cid = form.get("id", "")
    if cid not in {c["id"] for c in candidate_rows()}:
        raise HTTPException(400, "등재되지 않은 공고 — 등재된 공고만 초안을 만든다")
    await start_draft(cid)
    return RedirectResponse(f"/applications/job/{cid}", status_code=302)


@app.get("/applications/job/{cid}", response_class=HTMLResponse)
def application_job(cid: str, doc: str = ""):
    """공고 한 건의 지원 화면 — 후보목록 행이 오는 곳. 문서가 없으면 초안 만들기만 보인다."""
    cands = {c["id"]: c for c in candidate_rows()}
    c = cands.get(cid)
    if not c:
        raise HTTPException(404, "등재되지 않은 공고")
    folder = job_index().get(cid)
    others = [x for x in cands.values()
              if _norm(x["company"]) == _norm(c["company"]) and x["id"] != cid]
    others.sort(key=_rank_key)
    cur, tabs, html = _folder_view(folder, doc) if folder else ("", [], "")
    body = _JOBHEAD.render(c=c, folder=folder) + _JOBDOCS.render(
        c=c, folder=folder, cur=cur, tabs=tabs, html=html, others=others)
    return _render(c["company"], body, active="지원서류",
                   sub=f"<code>applications/{escape(folder['slug'])}</code> · 문서 {len(folder['docs'])}/5"
                       if folder else "이 공고에 연결된 지원서류 폴더가 아직 없습니다.")


@app.get("/applications/{slug}", response_class=HTMLResponse)
def application(slug: str, doc: str = ""):
    """공고에 연결되지 않은 폴더 — 문서만 보여준다. 연결되면 /applications/job/{id}로 간다."""
    _guard(slug)
    d = APPLICATIONS / slug
    if not d.exists():
        raise HTTPException(404, "지원서류 없음")
    folder = next((f for f in app_folders() if f["slug"] == slug), None)
    linked = next((i for i in (folder["ids"] if folder else [])
                   if i in {c["id"] for c in candidate_rows()}), None)
    if linked:
        return RedirectResponse(f"/applications/job/{linked}", status_code=302)
    cur, tabs, html = _folder_view(folder, doc)
    body = _JOBDOCS.render(c=None, folder=folder, cur=cur, tabs=tabs, html=html, others=[])
    return _render(slug, body, active="지원서류",
                   sub=f"<code>applications/{escape(slug)}</code> · md {len(folder['files'])} · "
                       "후보목록의 공고와 연결되지 않았습니다 — 문서에 공고 링크를 적으면 이어집니다.")


@app.get("/docs", response_class=HTMLResponse)
def docs_index():
    groups: dict[str, list] = {}
    if REFERENCES.exists():
        for p in sorted(REFERENCES.rglob("*.md")):
            rel = p.relative_to(REFERENCES)
            groups.setdefault(str(rel.parent) if rel.parent != Path(".") else "references", []) \
                .append((f"/docs/{rel}", rel.name))
    ordered = sorted(groups.items(), key=lambda kv: -len(kv[1]))
    cols = [ordered[1:], ordered[:1]] if len(ordered) > 1 else [ordered]   # 큰 그룹은 오른쪽 열에
    total = sum(len(v) for v in groups.values())
    return _render("문서", _GROUPS.render(cols=cols if total else []), active="문서",
                   sub=f"{total}건. <code>references/</code>의 마크다운 — 작성 규칙·면접 대비 노트·사실베이스·로드맵.",
                   source="<code>references/**/*.md</code>")


@app.get("/docs/{path:path}", response_class=HTMLResponse)
def docs_page(path: str):
    _guard(path)
    full = REFERENCES / path
    if full.suffix != ".md" or not full.exists():
        raise HTTPException(404, "문서 없음")
    return _render(path, _DOCS.render(sections=[(full.name, _render_md(full.read_text()))]), active="문서")
