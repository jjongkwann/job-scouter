# 포트폴리오 편집 스튜디오

open-slide 2.0.1로 기본본과 120개 공고별 포트폴리오를 편집합니다. A4 이력서와 검수된 PDF/PPTX는 기존 지원서류 묶음에 보존합니다.

## 편집

저장소 루트에서 실행합니다.

```sh
npm --prefix slide-studio ci
npm --prefix slide-studio run dev
```

- 기본본: http://127.0.0.1:5173/slides/s/portfolio-base
- 덧셈컴퍼니: http://127.0.0.1:5173/slides/s/portfolio-385747
- 원본: `data/application-slide-studio/slides/<slide-id>/index.tsx`

Edit에서 글자나 도형을 선택해 수정하고 Save로 저장합니다. Format의 COMMENT에는 변경 요청을 적을 수 있습니다. 코멘트는 해당 JSX의 `@slide-comment`로 저장됩니다. 에이전트에 코멘트 반영을 요청할 때는 `node_modules/@open-slide/core/skills/apply-comments/SKILL.md`와 `slide-authoring/SKILL.md`를 따릅니다. 경력·성과 수치는 사실베이스와 대조하고, 공통 변경은 기본본과 해당 공고별 소스에 함께 반영합니다.

편집 서버는 이 컴퓨터의 127.0.0.1에서만 실행합니다. 운영 사이트에는 아래 명령으로 만든 정적 결과물을 제공합니다.

```sh
npm --prefix slide-studio run build
```

빌드 결과는 `data/application-slide-studio/dist`입니다. API는 이 폴더와 `manifest.json`을 읽기 전용으로 제공하며, `/slides/s/<slide-id>`를 직접 열 수 있습니다. 설치와 첫 연결 이후에는 슬라이드 변경을 빌드하면 동기화된 운영 데이터 폴더에 반영됩니다. API/web 코드까지 바뀔 때만 해당 컨테이너를 재배포합니다.

브라우저 Download 메뉴에서 편집형 PPTX와 PDF를 내보낼 수 있습니다. 새로 내보낸 파일은 기존 검수본을 자동으로 덮어쓰지 않습니다. 한글 줄바꿈과 페이지 수를 확인한 후 제출본으로 사용합니다.

## 최초 이전 기록

`scripts/migrate_open_slide.py`는 검수된 PPTX의 글자·도형·선을 개별 React 요소로 옮긴 일회성 이전 도구입니다. 기존 편집 소스나 manifest가 있으면 중단하므로 편집 후 다시 실행하지 않습니다. 원본 해시와 공고 묶음은 `data/application-slide-studio/manifest.json`에 남습니다.
