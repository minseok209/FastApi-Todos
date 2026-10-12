# OWASP Top 10 보안 점검 보고서 — FastAPI To-Do (Version 5.0.0)

| 항목 | 내용 |
|---|---|
| 대상 | `fastapi-app/` (main.py, templates/index.html, Dockerfile), Jenkins 파이프라인, 배포 컨테이너 |
| 기준 | OWASP Top 10 (2021) A01 ~ A10 |
| 점검 도구 | Claude Code(코드 리뷰·수정·테스트), SonarQube 정적 분석, pip-audit(의존성 취약점) |
| 점검일 | 2026-10-13 |
| 작성 | 20211602 최민석 (Claude Code 사용) |

## 1. 요약

| OWASP 항목 | 결과 | 조치 |
|---|---|---|
| A01 접근 제어 취약점 | ⚠️ 위험 수용 | 인증·권한 기능 없음 → 다음 버전 과제로 기록 |
| A02 암호화 실패 | ⚠️ 권고 | HTTP 평문 통신. 비밀값은 저장소에 두지 않음 (양호) |
| A03 인젝션 | ✅ 양호 | SQL·셸 실행 없음, 입력 검증, 화면은 `textContent`만 사용 |
| A04 안전하지 않은 설계 | 🔧 **수정** | 설명(description) 길이 무제한 → 최대 500자 |
| A05 보안 설정 오류 | 🔧 **수정** | 보안 헤더·CSP 추가, Dockerfile 전체 복사 제거 |
| A06 취약하고 오래된 구성요소 | ✅ 양호 | pip-audit: 알려진 취약점 없음 |
| A07 식별·인증 실패 | ⚠️ 위험 수용 | A01과 같음. 관리 도구(Jenkins·SonarQube) 기본 비밀번호는 변경함 |
| A08 소프트웨어·데이터 무결성 실패 | ✅ 양호 | 테스트·품질 게이트 통과 후에만 배포, 웹훅 Secret 검증 |
| A09 보안 로깅·모니터링 실패 | 🔧 **수정** | 추가·수정·삭제를 서버 로그에 기록 |
| A10 서버 측 요청 위조(SSRF) | ✅ 해당 없음 | 서버가 사용자 입력으로 외부 요청을 보내지 않음 |

수정 3건(A04·A05·A09), 양호·해당 없음 4건, 위험 수용·권고 3건.

## 2. 항목별 상세

### A01 접근 제어 취약점 / A07 식별·인증 실패 — ⚠️ 위험 수용
- **발견**: API(`/todos`)에 로그인·권한 확인이 없어, 서버 주소를 아는 사람은 누구나 할 일을 추가·수정·삭제할 수 있다.
  Docker로 공개한 포트(5001, 5002)는 ufw 방화벽 규칙을 거치지 않으므로 학교 대역 밖에서도 접근될 수 있다.
- **판단**: 실습용 1인 앱이고 저장 데이터가 민감하지 않아 이번 버전에서는 위험을 수용한다.
- **권고**: 다음 버전에서 로그인(세션 또는 API 키) 추가, 필요 없는 포트는 `127.0.0.1`에만 바인딩.
- **양호한 점**: Jenkins·SonarQube 관리자 기본 비밀번호(admin/admin)는 변경했고, Jenkins 접속은 ufw로 학교 대역만 허용한다.

### A02 암호화 실패 — ⚠️ 권고
- **발견**: 앱·Jenkins·SonarQube 모두 HTTPS 없이 HTTP로 통신한다.
- **양호한 점**: SonarQube 토큰·웹훅 Secret·Docker Hub 토큰·SSH 키는 모두 Jenkins Credentials에만 저장하고
  저장소·파이프라인 코드에는 적지 않는다 (`sonar-project.properties`에 토큰 없음, 콘솔 로그에서도 마스킹).
- **권고**: 운영 환경에서는 Nginx 등 리버스 프록시에서 HTTPS 적용.

### A03 인젝션 — ✅ 양호
- 데이터는 JSON 파일에 `json` 모듈로만 읽고 쓰며 SQL·셸 명령을 실행하지 않는다.
- 모든 입력은 Pydantic 모델로 검증한다 (제목 1~100자, 우선순위는 `high/medium/low`만, 날짜 형식, `sort`는 `created/priority`만 — 그 외는 422).
- 화면(index.html)은 `textContent`와 DOM API로만 그리며 `innerHTML`·`eval`을 쓰지 않아 저장형 XSS가 생기지 않는다.

### A04 안전하지 않은 설계 — 🔧 수정
- **발견**: 제목은 100자로 제한되어 있었지만 설명(description)은 길이 제한이 없어, 매우 큰 요청을 반복하면 `todo.json`이 커져 서버가 느려질 수 있었다.
- **수정**: `description: str = Field(default="", max_length=500)` — 501자 이상은 422로 거부.
- **남은 위험(권고)**: 요청 횟수 제한(rate limit)이 없고, 파일 저장 방식이라 동시에 수정하면 마지막 저장만 남을 수 있다 → 사용자가 늘면 DB로 전환.

### A05 보안 설정 오류 — 🔧 수정
- **발견 1**: 응답에 보안 헤더가 없었다.
- **수정 1**: 모든 응답에 `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`(클릭재킹 방지), `Referrer-Policy: no-referrer`를 붙이는 미들웨어 추가.
  화면(`/`)에는 외부 스크립트를 막는 `Content-Security-Policy`(`default-src 'self'`, `frame-ancestors 'none'` 등) 추가.
- **발견 2**: Dockerfile이 `COPY . .`로 빌드 폴더 전체를 이미지에 복사했다 (SonarQube `docker:S6470`, Security High).
- **수정 2**: `main.py`, `templates/index.html`, `todo.json`만 이름으로 복사. 코드는 root 소유로 두고 `todo.json`만 실행 사용자(appuser)가 쓸 수 있게 했다.
- **양호한 점**: 컨테이너는 root가 아닌 사용자로 실행하고 `--cap-drop ALL`, `--security-opt no-new-privileges`를 적용한다.
- **권고**: `/docs`(Swagger UI)는 실습 편의를 위해 열어 두었으며 운영 시에는 끄는 것을 권장.

### A06 취약하고 오래된 구성요소 — ✅ 양호
- `pip-audit -r fastapi-app/requirements.txt` 결과 **No known vulnerabilities found** (2026-10-13).
- 의존성은 보안 패치가 들어간 최소 버전 이상으로 지정한다 (`starlette>=1.7.0`, `pytest>=9.0.3` 등).
- Docker 빌드는 `--pull`로 매번 최신 `python:3.13-slim` 베이스 이미지를 받는다.

### A08 소프트웨어·데이터 무결성 실패 — ✅ 양호
- 파이프라인 순서: 단위 테스트 → SonarQube 분석 → **품질 게이트** → 빌드 → 배포 → 통합 테스트. 앞 단계가 실패하면 배포하지 않는다.
- SonarQube → Jenkins 웹훅은 Secret으로 서명을 검증한다 (가짜 "통과" 알림 차단).
- 이미지에 빌드 번호 태그를 붙여 어떤 빌드가 배포됐는지 추적·롤백할 수 있다.
- **권고**: 베이스 이미지를 digest로 고정하고 이미지 서명(cosign 등) 도입.

### A09 보안 로깅·모니터링 실패 — 🔧 수정
- **발견**: 할 일이 추가·수정·삭제돼도 기록이 남지 않아 누가 데이터를 바꿨는지 추적할 수 없었다.
- **수정**: 추가·수정·삭제 시 `todo created/updated/deleted: id=N`을 uvicorn 로그에 기록 → `docker logs FastApi-app-sonar`로 확인.
- **권고**: 접속 IP 기록, 로그 보관·알림 연동.

### A10 서버 측 요청 위조(SSRF) — ✅ 해당 없음
- 서버 코드에 외부로 HTTP 요청을 보내는 부분이 없다 (`requests`, `httpx`, `subprocess` 사용 없음).

## 3. 검증

| 검증 | 결과 |
|---|---|
| 단위 테스트 (`fastapi-app/tests`) | 38개 통과, `main.py` 커버리지 99% — 보안 테스트 5개 포함 (설명 501자 거부, 보안 헤더, CSP, 변경 로그, 404 문서화) |
| 배포 환경 API 통합 테스트 (`api-tests`) | 10개 통과 |
| Playwright UI 테스트 (`ui-tests`) | 15개 통과 — CSP 적용 후에도 화면 정상 동작 |
| SonarQube 2차 분석 | Security·Reliability·Maintainability 이슈 0, Quality Gate Passed, 커버리지 98.8% |
| pip-audit | 알려진 취약점 없음 |

## 4. Claude Code 활용 방법

1. 저장소 전체(main.py, index.html, Dockerfile, Jenkinsfile)를 읽게 하고 OWASP Top 10 항목별로 해당 여부를 점검하도록 요청했다.
2. 위험한 함수(`innerHTML`, `eval`, `subprocess`, 외부 요청)와 저장소의 비밀값(토큰·비밀번호)을 직접 검색해 근거를 확인했다.
3. `pip-audit`로 의존성 취약점을 실제로 조회했다.
4. 수정이 필요한 항목은 코드 수정과 함께 테스트를 추가하고, 단위·API·UI 테스트를 모두 다시 실행해 기존 기능이 깨지지 않았는지 확인했다.
5. 바로 고치기 어려운 항목(인증, HTTPS)은 이유와 권고를 남기고 위험 수용으로 분류했다.
