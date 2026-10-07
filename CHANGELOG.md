# Release Notes

최신 버전을 위에 누적해서 기록한다.

## Version 5.0.0

### Added
- Todo 우선순위(높음 / 보통 / 낮음) 지정 — 추가 폼·편집 시트에서 선택, 목록에 색상 배지로 표시
- 우선순위순 정렬 (화면 정렬 선택 + API `GET /todos?sort=priority`, 같은 우선순위는 등록 순서 유지)
- 우선순위가 없는 기존 데이터는 자동으로 `보통`으로 읽음 (하위 호환)

### Changed
- Jenkins Pipeline에 SonarQube 정적 분석(SonarQube Analysis)과 품질 게이트(Quality Gate) 단계 추가 — 기준 미달 시 배포 중단
- `docker-compose.yml`에 SonarQube 서버(9000) 추가, `fastapi-app/sonar-project.properties` 추가
- 배포 대상을 개인 서버 `163.239.77.83:5002`로 변경

### Testing
- 우선순위·정렬 단위 테스트 8개 추가 (총 33개, `main.py` 커버리지 98%)
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
