"""배포된 서버(개인 서버 Docker 컨테이너)에 실제 HTTP 요청을 보내는 통합 테스트.

    BASE_URL=http://163.239.77.83:5002 pytest api-tests --html=api_report/report.html --self-contained-html

단위 테스트(fastapi-app/tests)와 달리 실제 서버의 데이터를 사용하므로,
테스트가 만든 항목에만 고유한 접두어를 붙이고 끝나면 모두 지운다.
"""
import os
import time
import uuid

import httpx2
import pytest

BASE_URL = os.environ.get("BASE_URL", "http://163.239.77.83:5002").rstrip("/")
PREFIX = f"api-test-{uuid.uuid4().hex[:8]}"      # 이번 실행에서 만든 항목 표시
UNKNOWN_ID = 999_999_999                          # 존재하지 않는 id


@pytest.fixture(scope="session")
def api():
    with httpx2.Client(base_url=BASE_URL, timeout=10) as client:
        # 배포 직후에는 컨테이너가 아직 뜨는 중일 수 있으니 최대 60초 기다린다
        deadline = time.monotonic() + 60
        while True:
            try:
                if client.get("/todos").status_code == 200:
                    break
            except httpx2.TransportError:
                pass
            if time.monotonic() > deadline:
                pytest.fail(f"{BASE_URL} 가 60초 안에 응답하지 않음")
            time.sleep(2)

        yield client

        # 정리: 테스트가 실패해 중간에 남은 항목까지 이번 실행 것만 삭제
        for todo in client.get("/todos", params={"q": PREFIX}).json():
            client.delete(f"/todos/{todo['id']}")


def ids(response):
    return [t["id"] for t in response.json()]


def test_crud_flow(api):
    # 1) 추가 → 201
    created = api.post("/todos", json={"title": f"{PREFIX} 통합 테스트", "description": "배포 환경", "due_date": "2026-10-06"})
    assert created.status_code == 201
    todo = created.json()
    assert todo["title"] == f"{PREFIX} 통합 테스트"
    assert todo["due_date"] == "2026-10-06"

    # 2) 조회 → 200, 방금 추가한 항목이 목록에 있음
    listed = api.get("/todos")
    assert listed.status_code == 200
    assert todo["id"] in ids(listed)

    # 3) 수정 → 200, 변경 내용이 조회에도 반영됨
    updated = api.put(f"/todos/{todo['id']}", json={"title": f"{PREFIX} 수정됨", "description": "완료 처리", "completed": True})
    assert updated.status_code == 200
    assert updated.json()["completed"] is True
    after = next(t for t in api.get("/todos").json() if t["id"] == todo["id"])
    assert after["title"] == f"{PREFIX} 수정됨"

    # 4) 삭제 → 204 (본문 없음), 목록에서 사라짐
    deleted = api.delete(f"/todos/{todo['id']}")
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert todo["id"] not in ids(api.get("/todos"))


def test_search_by_title(api):
    a = api.post("/todos", json={"title": f"{PREFIX} Apple 검색"}).json()
    b = api.post("/todos", json={"title": f"{PREFIX} Banana"}).json()

    found = api.get("/todos", params={"q": f"{PREFIX} apple"})   # 대소문자 무시
    assert found.status_code == 200
    assert ids(found) == [a["id"]]
    assert b["id"] not in ids(found)


def test_search_no_result(api):
    response = api.get("/todos", params={"q": f"{PREFIX}-없는-검색어"})
    assert response.status_code == 200
    assert response.json() == []


def test_create_without_title_returns_422(api):
    response = api.post("/todos", json={"description": "title 없음"})
    assert response.status_code == 422


def test_create_with_invalid_due_date_returns_422(api):
    response = api.post("/todos", json={"title": f"{PREFIX} 날짜 오류", "due_date": "2026-13-40"})
    assert response.status_code == 422


def test_delete_unknown_id_returns_404(api):
    response = api.delete(f"/todos/{UNKNOWN_ID}")
    assert response.status_code == 404


def test_update_unknown_id_returns_404(api):
    response = api.put(f"/todos/{UNKNOWN_ID}", json={"title": "없음"})
    assert response.status_code == 404


def test_priority_and_sort(api):
    low = api.post("/todos", json={"title": f"{PREFIX} 정렬 낮음", "priority": "low"}).json()
    high = api.post("/todos", json={"title": f"{PREFIX} 정렬 높음", "priority": "high"}).json()
    assert high["priority"] == "high"

    response = api.get("/todos", params={"q": f"{PREFIX} 정렬", "sort": "priority"})
    assert response.status_code == 200
    assert ids(response) == [high["id"], low["id"]]          # 높음이 먼저


def test_invalid_priority_returns_422(api):
    response = api.post("/todos", json={"title": f"{PREFIX} 잘못된 우선순위", "priority": "urgent"})
    assert response.status_code == 422


def test_index_page_is_version_5(api):
    response = api.get("/")
    assert response.status_code == 200
    assert "Version 5.0.0" in response.text
