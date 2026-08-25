# io·llm 워커 공용 이미지. judge/report(llm)는 컨테이너 안에서 `claude -p`를 실행하므로
# Node.js(Claude Code CLI)와 uv(파이썬)가 둘 다 필요하다.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code
RUN pip install --no-cache-dir uv

# jobfeed 스크립트의 macOS 알림(osascript)은 리눅스에 없다 — no-op 심으로 스크립트 무수정 유지
RUN printf '#!/bin/sh\nexit 0\n' > /usr/local/bin/osascript && chmod +x /usr/local/bin/osascript

# 호스트의 ~/.git-credentials(ro 마운트)로 candidates.json push 인증
RUN git config --system credential.helper store && git config --system safe.directory "*"   # 마운트된 repo는 호스트 소유

WORKDIR /app

# 의존성 레이어 먼저(소스 변경으로 무거운 torch 재설치 안 되게)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY . .
RUN uv sync --frozen --no-dev

# CMD 없음 — compose가 서비스별 command로 지정(worker io / worker llm)
