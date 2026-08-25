# 서버 설정

워커(io·llm)와 Temporal은 서버(OrbStack docker)에 컨테이너 3개로 상시
가동한다. Elasticsearch는 서버 호스트에 네이티브로 떠 있고(:9200, localhost 바인드),
컨테이너는 `host.docker.internal`로 붙는다. jobfeed 데이터는 GitHub private repo를
서버 호스트에 clone해 컨테이너에 마운트한다.

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
docker compose -f deploy/compose.yaml ps                 # 3개 다 Up
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

## 6. 운영 명령 (작업 머신에서)

작업 머신의 `.env`에서 `JOBSCOUTER_TEMPORAL=<server-ip>:7233`으로 서버를 가리키면,
로컬 워커 없이도 signal·조회가 된다:

```bash
uv run python -m jobscouter.worker status
uv run python -m jobscouter.worker browser-done "메모"
uv run python -m jobscouter.worker approve <id> ...
```

워커가 서버 컨테이너에서 상시 가동 중이므로, signal을 보내면 곧바로 이어진다.
