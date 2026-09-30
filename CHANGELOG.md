# Release Notes

최신 버전을 위에 누적해서 기록한다.

## Version 4.0.0

### Added
- Todo 제목 검색 기능 추가 (화면 검색창 + API `GET /todos?q=검색어`, 대소문자 무시)
- 검색 결과 개수 표시 (`검색 결과 N개 · 전체 M개`), 검색어 강조 표시, 결과 없음 안내

### Changed
- 화면을 Apple(iOS) 스타일로 전면 개편: 큰 제목, 카드형 목록, 세그먼트 필터, 원형 체크박스, 다크 모드 지원
- 수정 시 `prompt()` 창 대신 편집 시트(dialog) 사용, 제목이 비어 있으면 추가 버튼 비활성화
- Jenkins Pipeline을 Test → Docker Build → Push → Deploy → API Test 구조로 변경
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
