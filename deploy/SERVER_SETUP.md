# 서버 설정

워커(io·llm)와 Temporal은 서버(docker)에 컨테이너 3개로 상시
가동한다. Elasticsearch는 서버 호스트에 네이티브로 떠 있고(:9200, localhost 바인드),
컨테이너는 `host.docker.internal`로 붙는다. jobfeed 데이터는 GitHub private repo를
서버 호스트에 clone해 컨테이너에 마운트한다.

## 0. 코드 clone (서버 호스트)

서버는 이 저장소를 clone해서 쓴다 — 어떤 리비전이 돌고 있는지 `git log`로 확인되고,
갱신이 `git pull`로 끝난다. rsync로 밀어 넣지 않는다.

```bash
git clone https://github.com/<org>/job-scouter.git ~/workspace/job-scouter
```

`deploy/.env`는 gitignore 대상이라 clone에 딸려오지 않는다 — 2절에서 만든다.

## 1. 데이터 repo clone (서버 호스트)

```bash
gh auth setup-git                      # HTTPS clone/push에 gh 인증 사용
git clone https://github.com/<org>/<private-data-repo>.git ~/jobscouter-data
mkdir -p ~/.temporal
```

컨테이너의 `git push`(candidates.json 자동 등재)는 host의 `~/.git-credentials`를
ro 마운트해 쓴다 — `git config --system credential.helper store`는 이미지에
빌드돼 있으니, credential 파일만 만들면 된다:

```bash
echo "https://<github-user>:$(gh auth token)@github.com" > ~/.git-credentials
chmod 600 ~/.git-credentials
```

## 2. 인증·환경변수

llm 컨테이너의 `claude -p`는 **서버 호스트의 Claude Code 로그인**을 그대로 쓴다 —
compose가 `~/.claude/.credentials.json`을 마운트한다(호스트에서 `claude`를 한 번
로그인해 두면 끝). 호스트에 로그인이 없으면 작업 머신에서 `claude setup-token`으로
토큰을 발급해 `deploy/.env`의 `CLAUDE_CODE_OAUTH_TOKEN`에 넣는다(마운트보다 우선).

```bash
cp deploy/server.env.example deploy/.env
# DATA_REPO=<데이터 repo clone 절대경로>
# GIT_AUTHOR_NAME / GIT_AUTHOR_EMAIL  (자동 커밋 작성자)
```

`deploy/.env`는 gitignore 대상 — 작업 머신 로컬 개발용 `.env`와 별개다.

## 3. 컨테이너 기동

저장소 루트에서:

```bash
docker compose -f deploy/compose.yaml up -d --build
```

## 4. 검증

```bash
docker compose -f deploy/compose.yaml ps                 # temporal·io·llm·web 4개 Up
curl -s -o /dev/null -w '%{http_code}' http://localhost:8090/   # 200 — 웹 대시보드
temporal operator cluster health --address localhost:7233   # SERVING (서버 로컬)
docker compose -f deploy/compose.yaml logs io llm         # 워커 시작 로그 확인
```

**주의**: :7233/:8233은 LAN 전용 — 포트포워딩·외부 공개 금지. Temporal 이력에
activity 입출력(사실베이스 발췌 포함)이 남는다. ES는 호스트 `localhost` 바인드
그대로 — 컨테이너는 `host.docker.internal`로 붙으니 LAN 개방이 필요 없다.

## 5. 재색인

판례·평판·사실베이스 갱신 후:

```bash
docker compose -f deploy/compose.yaml exec io uv run python scripts/index_es.py
```

## 6. 운영

사람은 웹 대시보드 `http://<server-ip>:8090/`에서 본다 — 제안 승인/거부, 후보목록,
보고서, 이력서·사실베이스, 지원서류, 이력서 갱신 제안. 스케줄(`daily-scan` 매일 09:07,
`resume-sync` 매주 월 08:00 KST)은 작업 머신에서 한 번 등록한다:

```bash
uv run python -m jobscouter.worker schedule
uv run python -m jobscouter.worker status          # 실행 중 워크플로
uv run python -m jobscouter.worker scan            # 수동 스캔
uv run python -m jobscouter.worker resume-sync     # 수동 이력서 갱신 제안
```

작업 머신 `.env`의 `JOBSCOUTER_TEMPORAL=<server-ip>:7233`으로 서버를 가리키면
로컬 워커 없이 위 명령이 동작한다 — 스케줄 등록도 작업 머신에서 한 번 하면 되고,
서버에 접속할 필요가 없다(Temporal 클라이언트 호출이라서).

코드 갱신은 서버에서:

```bash
cd ~/workspace/job-scouter && git pull
docker compose -f deploy/compose.yaml up -d --build io llm web
```

`temporal` 컨테이너는 재기동하지 않는다 — 워크플로 이력이 SQLite에 있고, 워커만
새 이미지로 바뀌면 대기 중인 워크플로가 그대로 이어진다.
