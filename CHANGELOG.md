# Release Notes

최신 버전을 위에 누적해서 기록한다.

## Version 7.0.0

### Added
- 태그(카테고리) — 할 일마다 태그 최대 5개(각 1~20자), 추가 폼·편집 시트에서 쉼표로 입력, 목록에 `#태그` 칩으로 표시
- 태그 필터 — 검색창 아래 태그 칩(사용 개수 표시)이나 항목의 태그를 누르면 그 태그만 보기, 다시 누르면 해제 (상태 필터·검색과 함께 동작)
- 태그 API — `GET /todos?tag=과제` (대소문자 무시), `GET /todos/tags` (`[{"tag": "과제", "count": 2}]`, 많이 쓴 순)
- 마감일순 정렬 — 정렬 선택에 `마감일순` 추가, API `GET /todos?sort=due` (마감일 없는 항목은 맨 뒤)
- 대소문자만 다른 중복 태그는 하나로 합침, 태그가 없는 기존 데이터는 빈 목록으로 읽음 (하위 호환)

### Fixed
- **동시 요청 시 데이터 손상** — JMeter 부하 테스트(동시 사용자)에서 발견. FastAPI 가 요청을 여러 스레드에서 동시에 처리하는데
  `todo.json` 읽기·쓰기에 잠금이 없어, 쓰는 중인 파일을 읽은 요청이 `JSONDecodeError`(500)로 실패하고
  두 요청이 같은 목록을 읽고 저장해 추가한 항목이 사라짐 (60건 동시 추가 → 500 오류 18건, 실제 저장 17건).
  파일 읽기·쓰기와 "읽기 → 수정 → 저장" 전체를 잠금(`threading.RLock`)으로 묶어 수정 → 60건 모두 201, 중복·유실 없음
- Jenkins 부하 테스트 파이프라인 첫 빌드(#1) 실패 — 샌드박스가 막는 `Double.parseDouble` 대신 파이썬 종료 코드로 오류율을 판정,
  첫 빌드에서 매개변수가 비어 부하가 10명 × 1회로 줄던 문제는 기본값(20명 × 30회)으로 보완 → #2 성공

### Changed (성능·부하 테스트 환경)
- `jmeter/fastapi_test_plan.jmx` — 실제 엔드포인트 9개(화면·목록·현황·추가·검색·태그·태그 목록·수정·삭제) 시나리오,
  JSON 헤더·본문, 추가한 id 를 추출해 수정·삭제 (테스트 후 데이터가 남지 않음), `-JTHREADS/-JRAMP_UP/-JLOOPS` 로 부하 조절
- `jmeter/Dockerfile` — JMeter 5.6.3 (Log4Shell 대상 5.4.1 대신), `eclipse-temurin:17-jre`, sha512 검증, root 아닌 `jmeter` 계정
- `Jenkinsfile.jmeter` — Test → Build → Push → 팀 서버 배포(`163.239.77.76:8055`) → JMeter 부하 테스트 → JMeter HTML Report → 오류율 1% 초과 시 UNSTABLE
- `docker-compose.yml` — InfluxDB 1.12.4 (외부 포트 없음) + JMeter(`--profile loadtest`) 추가, 모든 서비스를 `loadtest-net` 네트워크로 연결
- Grafana — InfluxDB 데이터 소스와 `JMeter 부하 테스트 (InfluxDB)` 대시보드(처리량·응답 시간·동시 사용자·오류·엔드포인트별 요약) 자동 등록

### Testing
- 태그·마감일순 정렬·동시 요청 단위 테스트 15개 추가 (총 63개, `main.py` 커버리지 99%)
- 배포 환경 API 테스트에 태그 필터·태그 목록·태그 개수 제한·마감일순 정렬 추가
- 로컬 JMeter 실행: 20명 × 20회 × 9요청 = 3,600건, 평균 60.5ms, 오류 0%

## Version 6.0.0

### Added
- 할 일 현황 요약 카드 — 완료율(%)과 진행 막대, 전체·완료·미완료·기한 지남·남은 높음 우선순위 개수 (검색·필터와 상관없이 전체 기준)
- 현황 API `GET /todos/stats` (`total`, `completed`, `active`, `overdue`, `completion_rate`, `active_by_priority`)
- `기한 지남` 필터 추가 (전체 / 미완료 / 완료 / 기한 지남), 현황 카드의 완료·미완료·기한 지남 숫자를 누르면 해당 목록으로 바로 이동
- 마감 D-day 표시 — `D-6`, 3일 이내는 주황색 `D-2`·`오늘 마감`, 지난 항목은 빨간색 `기한 지남`
- 완료 항목 일괄 삭제 버튼 `완료 항목 삭제 (N)` + API `DELETE /todos/completed` (`{"deleted": N}`)
- Prometheus 메트릭 엔드포인트 `/metrics` (`prometheus-fastapi-instrumentator`) — 요청 수·응답 시간 자동 수집, Swagger 목록에서는 숨김
- 커스텀 메트릭: `todo_items{status=completed|active|overdue}`, `todo_completion_rate_percent`, `todo_changes_total{operation=create|update|delete}`

### Changed (모니터링 환경)
- `docker-compose.yml`에 Prometheus(서버 내부 `127.0.0.1:7070`), Grafana(3000), node-exporter, cAdvisor 추가 — 모두 이미지 버전 고정, `no-new-privileges`, 외부 포트 최소화
- `prometheus/prometheus.yml` — `fastapi`, `node`, `cadvisor` 3개 타깃을 15초마다 수집
- Grafana 데이터 소스(Prometheus)와 `FastApi-Todos 모니터링` 대시보드(시스템·애플리케이션·To-Do 현황 16개 패널) 자동 등록
- `scripts/traffic.py` — 조회·추가·오류·동시 접속 부하를 단계별로 보내 그래프 변화를 관찰하는 스크립트

### Fixed
- `scripts/traffic.py` 동시 접속 단계에서 요청마다 새 연결을 열어 Windows 임시 포트가 고갈되던 문제(`WinError 10048`) — 스레드별 keep-alive 연결 재사용, `--start`로 중간 단계부터 재실행
- 단위 테스트의 화면 버전 확인을 `Version 6.0.0`으로 수정

### Testing
- 현황 요약·`/metrics`·커스텀 메트릭·완료 항목 일괄 삭제 단위 테스트 10개 추가 (총 48개, `main.py` 커버리지 99%)
- 배포 환경 API 테스트에 현황 요약·`/metrics`·완료 항목 일괄 삭제 확인 추가

## Version 5.0.0

### Added
- Todo 우선순위(높음 / 보통 / 낮음) 지정 — 추가 폼·편집 시트에서 선택, 목록에 색상 배지로 표시
- 우선순위순 정렬 (화면 정렬 선택 + API `GET /todos?sort=priority`, 같은 우선순위는 등록 순서 유지)
- 우선순위가 없는 기존 데이터는 자동으로 `보통`으로 읽음 (하위 호환)

### Changed
- Jenkins Pipeline에 SonarQube 정적 분석(SonarQube Analysis)과 품질 게이트(Quality Gate) 단계 추가 — 기준 미달 시 배포 중단
- `docker-compose.yml`에 SonarQube 서버(9000) 추가, `fastapi-app/sonar-project.properties` 추가
- 배포 대상을 개인 서버 `163.239.77.83:5002`로 변경

### Fixed (SonarQube 1차 분석 결과 반영)
- [Security/High] `docker:S6470` Dockerfile의 `COPY . .`(빌드 컨텍스트 전체 복사)를 필요한 파일만 이름으로 복사하도록 변경, 코드는 root 소유·`todo.json`만 appuser 소유
- [Maintainability/High] `python:S8415` 404 `HTTPException`을 수정·삭제 엔드포인트의 `responses`에 문서화 (OpenAPI에 404 표시)
- [Maintainability/Medium] `python:S9100` 정리 작업이 없는 pytest fixture의 불필요한 `yield` 제거

### Security (Claude Code OWASP Top 10 점검 반영)
- A04: 설명(description) 최대 500자 제한
- A05: 보안 헤더 추가 (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, 화면에 `Content-Security-Policy`)
- A06: `pip-audit`로 의존성 취약점 점검 — 알려진 취약점 없음
- A09: 할 일 추가·수정·삭제를 서버 로그에 기록
- 점검 보고서: [`docs/OWASP_Top10_Report.md`](docs/OWASP_Top10_Report.md)

### Testing
- 우선순위·정렬 단위 테스트 8개 + 보안 테스트 5개 추가 (총 38개, `main.py` 커버리지 99%)
- 배포 환경 API 테스트(우선순위 정렬, 잘못된 우선순위 422)와 Playwright UI 테스트(배지, 정렬, 편집) 추가

## Version 4.0.0

### Added
- Todo 제목 검색 기능 추가 (화면 검색창 + API `GET /todos?q=검색어`, 대소문자 무시)
- 검색 결과 개수 표시 (`검색 결과 N개 · 전체 M개`), 검색어 강조 표시, 결과 없음 안내

### Changed
- 화면을 Apple(iOS) 스타일로 전면 개편: 큰 제목, 카드형 목록, 세그먼트 필터, 원형 체크박스, 다크 모드 지원
- 수정 시 `prompt()` 창 대신 편집 시트(dialog) 사용, 제목이 비어 있으면 추가 버튼 비활성화
- Jenkins Pipeline을 Test → Docker Build → Push → Deploy → Integration Test 구조로 변경
- 의존성을 보안 패치 버전으로 올림 (`fastapi>=0.142.0`, `starlette>=1.7.0` 등), `httpx` → `httpx2`
- Docker 이미지에서 테스트 파일 제외 (`.dockerignore`)

### Testing
- Pytest 기반 API 자동 테스트 추가 (`fastapi-app/tests`, 25개)
- pytest-cov 코드 커버리지 측정 추가 (`main.py` 98%)
- 배포 환경 API 통합 테스트 추가 (`api-tests`, 추가 201 → 조회 200 → 수정 200 → 삭제 204, 422 / 404 오류)
- Playwright 기반 UI 자동 테스트 추가 (`ui-tests`, 12개)

## Version 3.0.0

### Added
- Todo 마감일(due date) 추가, 기한이 지난 미완료 항목 강조
- Docker 배포 설정 (Dockerfile, .dockerignore, docker-compose.yml)

### Fixed
- 컨테이너 이름과 호스트 포트를 환경변수로 받아 서버별로 다르게 배포할 수 있도록 수정
- `__pycache__` 추적 해제, 잘못된 이름의 `todo.jason` 삭제

## Version 2.0.0

### Added
- Todo 전체 / 미완료 / 완료 필터
- 필터 적용 시 표시 개수 / 전체 개수 표시
- 표시할 항목이 없을 때 안내 문구
- 화면 하단 버전 표시
