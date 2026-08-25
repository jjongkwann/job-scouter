# 서버 설정

워크플로 서버(Temporal)와 ES는 LAN 안의 상시 가동 머신에, 워커는 jobfeed 저장소와
로그인 크롬이 있는 작업용 머신에 둔다. 서버 주소는 `.env`의 `JOBSCOUTER_TEMPORAL` /
`JOBSCOUTER_ES`.

## 1. Temporal 서버 (docker compose)

```bash
scp deploy/compose.yaml <server>:jobscouter-compose.yaml
ssh <server>
mkdir -p ~/.temporal
docker compose -f ~/jobscouter-compose.yaml up -d
docker ps --filter name=temporal        # Up
```

작업용 머신에서 검증:
```bash
temporal operator cluster health --address <server-ip>:7233   # SERVING
open http://<server-ip>:8233                                  # UI
```

SQLite가 볼륨(`~/.temporal/temporal.db`)에 있어 컨테이너를 지워도 워크플로 이력·대기
상태가 유지되고, `restart: always`라 재부팅 시 자동 복구된다.

**주의**: :7233/:8233은 LAN 전용 — 포트포워딩·외부 공개 금지. Temporal 이력에
activity 입출력(사실베이스 발췌 포함)이 남는다.

## 2. Elasticsearch LAN 개방

ES가 127.0.0.1에만 바인드돼 있으면 워커가 못 붙는다. `elasticsearch.yml`:

```yaml
network.host: ["127.0.0.1", "<server-ip>"]
discovery.type: single-node   # 비루프백 바인드 시 프로덕션 부트스트랩 검사 우회
```

ES 재시작 후 작업용 머신에서 `curl -s http://<server-ip>:9200`. 기존 인덱스는
건드리지 않는다 — job-scouter는 `jobscout_*` 인덱스만 만든다.
