from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest
from fastapi.testclient import TestClient

import main
from main import app, save_todos, load_todos, TodoItem

client = TestClient(app)


@pytest.fixture(autouse=True)
def use_temp_todo_file(tmp_path, monkeypatch):
    # 실제 todo.json 대신 테스트마다 새 임시 파일 사용 (본인 데이터 보호 + 테스트 간 격리)
    # 정리할 것이 없으므로 yield 없이 끝낸다 — tmp_path 와 monkeypatch 가 자동으로 원상 복구 (SonarQube python:S9100)
    monkeypatch.setattr(main, "TODO_FILE", tmp_path / "todo.json")
    save_todos([])  # 테스트 전 초기화


def make(todo_id, title, completed=False, **extra):
    return TodoItem(id=todo_id, title=title, description=f"{title} 설명", completed=completed, **extra)


# ---------- 조회 (GET) ----------

def test_get_todos_empty():
    response = client.get("/todos")
    assert response.status_code == 200
    assert response.json() == []


def test_get_todos_with_items():
    save_todos([make(1, "Test")])  # save_todos 는 TodoItem 객체 리스트를 받음
    response = client.get("/todos")
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["title"] == "Test"


def test_get_todos_when_file_missing():
    main.TODO_FILE.unlink()                      # 파일이 지워져도 빈 목록으로 동작
    response = client.get("/todos")
    assert response.status_code == 200
    assert response.json() == []


# ---------- 검색 (v4.0.0) ----------

def test_search_todos_by_title():
    save_todos([make(1, "Buy milk"), make(2, "Write report"), make(3, "Buy bread")])
    response = client.get("/todos", params={"q": "buy"})
    assert response.status_code == 200
    assert [t["id"] for t in response.json()] == [1, 3]


def test_search_is_case_insensitive_and_trimmed():
    save_todos([make(1, "DevOps 과제")])
    response = client.get("/todos", params={"q": "  devops  "})
    assert [t["title"] for t in response.json()] == ["DevOps 과제"]


def test_search_korean_title():
    save_todos([make(1, "장보기"), make(2, "과제 제출")])
    response = client.get("/todos", params={"q": "과제"})
    assert [t["id"] for t in response.json()] == [2]


def test_search_matches_title_only():
    save_todos([make(1, "Alpha")])               # 설명은 "Alpha 설명"
    response = client.get("/todos", params={"q": "설명"})
    assert response.json() == []


def test_search_no_result():
    save_todos([make(1, "Test")])
    response = client.get("/todos", params={"q": "없는검색어"})
    assert response.status_code == 200
    assert response.json() == []


def test_search_empty_query_returns_all():
    save_todos([make(1, "A"), make(2, "B")])
    response = client.get("/todos", params={"q": ""})
    assert len(response.json()) == 2


# ---------- 추가 (POST) ----------

def test_create_todo():
    todo = {"title": "Test", "description": "Test description", "completed": False}  # id 는 보내지 않음
    response = client.post("/todos", json=todo)
    assert response.status_code == 201           # 생성 성공 = 201 Created
    assert response.json()["title"] == "Test"
    assert response.json()["id"] == 1            # id 는 서버가 부여
    assert len(load_todos()) == 1                # 파일에도 저장됐는지 확인


def test_create_todo_assigns_next_id():
    save_todos([make(1, "A"), make(5, "B")])
    response = client.post("/todos", json={"title": "C"})
    assert response.json()["id"] == 6            # 가장 큰 id + 1


def test_create_todo_defaults():
    response = client.post("/todos", json={"title": "Only title"})
    body = response.json()
    assert body["description"] == ""
    assert body["completed"] is False
    assert body["due_date"] is None
    assert body["priority"] == "medium"          # 우선순위 기본값 = 보통


def test_create_todo_with_due_date():
    response = client.post("/todos", json={"title": "Report", "due_date": "2026-10-06"})
    assert response.status_code == 201
    assert response.json()["due_date"] == "2026-10-06"
    assert load_todos()[0].due_date.isoformat() == "2026-10-06"   # date 로 저장·복원


def test_create_todo_invalid():
    todo = {"description": "Test description"}   # 필수 필드 title 누락
    response = client.post("/todos", json=todo)
    assert response.status_code == 422


@pytest.mark.parametrize("payload", [
    {"title": ""},                               # min_length=1
    {"title": "x" * 101},                        # max_length=100
    {"title": "Bad date", "due_date": "2026-13-40"},
    {"title": "Bad type", "completed": "maybe"},
])
def test_create_todo_validation_errors(payload):
    response = client.post("/todos", json=payload)
    assert response.status_code == 422
    assert load_todos() == []                    # 잘못된 요청은 저장되지 않음


# ---------- 우선순위 (v5.0.0) ----------

def test_create_todo_with_priority():
    response = client.post("/todos", json={"title": "급한 일", "priority": "high"})
    assert response.status_code == 201
    assert response.json()["priority"] == "high"
    assert load_todos()[0].priority == "high"


def test_create_todo_invalid_priority():
    response = client.post("/todos", json={"title": "Bad", "priority": "urgent"})
    assert response.status_code == 422
    assert load_todos() == []


def test_old_data_without_priority_is_medium():
    main.TODO_FILE.write_text('[{"id": 1, "title": "예전 항목"}]', encoding="utf-8")   # v4 이전 형식
    assert client.get("/todos").json()[0]["priority"] == "medium"


def test_sort_by_priority():
    save_todos([make(1, "L", priority="low"), make(2, "M1"), make(3, "H", priority="high"), make(4, "M2")])
    response = client.get("/todos", params={"sort": "priority"})
    assert response.status_code == 200
    assert [t["id"] for t in response.json()] == [3, 2, 4, 1]   # 높음 → 보통(등록순 유지) → 낮음


def test_default_sort_keeps_created_order():
    save_todos([make(1, "L", priority="low"), make(2, "H", priority="high")])
    assert [t["id"] for t in client.get("/todos").json()] == [1, 2]


def test_sort_by_priority_with_search():
    save_todos([make(1, "과제 A", priority="low"), make(2, "장보기", priority="high"), make(3, "과제 B", priority="high")])
    response = client.get("/todos", params={"q": "과제", "sort": "priority"})
    assert [t["id"] for t in response.json()] == [3, 1]


def test_invalid_sort_returns_422():
    response = client.get("/todos", params={"sort": "random"})
    assert response.status_code == 422


def test_update_priority():
    save_todos([make(1, "Test")])
    response = client.put("/todos/1", json={"title": "Test", "priority": "low"})
    assert response.json()["priority"] == "low"
    assert load_todos()[0].priority == "low"


# ---------- 보안 (v5.0.0 · OWASP Top 10 점검 반영) ----------

def test_description_too_long_is_rejected():
    response = client.post("/todos", json={"title": "Long", "description": "x" * 501})   # A04
    assert response.status_code == 422
    assert load_todos() == []


def test_security_headers_on_api():
    response = client.get("/todos")                                                     # A05
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_index_has_content_security_policy():
    csp = client.get("/").headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp


def test_changes_are_logged(caplog):
    with caplog.at_level("INFO", logger="uvicorn.error"):                               # A09
        todo_id = client.post("/todos", json={"title": "Log"}).json()["id"]
        client.put(f"/todos/{todo_id}", json={"title": "Log2"})
        client.delete(f"/todos/{todo_id}")
    assert [r.getMessage() for r in caplog.records] == [
        f"todo created: id={todo_id}", f"todo updated: id={todo_id}", f"todo deleted: id={todo_id}"]


def test_not_found_is_documented_in_openapi():
    paths = client.get("/openapi.json").json()["paths"]["/todos/{todo_id}"]
    assert "404" in paths["put"]["responses"]
    assert "404" in paths["delete"]["responses"]


# ---------- 수정 (PUT) ----------

def test_update_todo():
    save_todos([make(1, "Test")])
    updated_todo = {"title": "Updated", "description": "Updated description", "completed": True}
    response = client.put("/todos/1", json=updated_todo)
    assert response.status_code == 200
    assert response.json()["title"] == "Updated"
    assert load_todos()[0].completed is True


def test_update_todo_keeps_other_items():
    save_todos([make(1, "A"), make(2, "B")])
    client.put("/todos/2", json={"title": "B2"})
    assert [t.title for t in load_todos()] == ["A", "B2"]


def test_update_todo_not_found():
    updated_todo = {"title": "Updated", "description": "Updated description", "completed": True}
    response = client.put("/todos/1", json=updated_todo)
    assert response.status_code == 404


def test_update_todo_invalid():
    save_todos([make(1, "Test")])
    response = client.put("/todos/1", json={"title": ""})
    assert response.status_code == 422
    assert load_todos()[0].title == "Test"       # 원본 유지


# ---------- 삭제 (DELETE) ----------

def test_delete_todo():
    save_todos([make(1, "Test")])
    response = client.delete("/todos/1")
    assert response.status_code == 204           # 삭제 성공 = 204 No Content (응답 본문 없음)
    assert load_todos() == []


def test_delete_todo_not_found():
    response = client.delete("/todos/1")
    assert response.status_code == 404


# ---------- 화면 ----------

def test_index_page():
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Version 7.0.0" in response.text
    assert 'id="search"' in response.text        # 검색창이 화면에 있는지
    assert 'id="sort"' in response.text          # 정렬 선택이 화면에 있는지


# ---------- 현황 요약 / 모니터링 (v6.0.0) ----------

def test_stats_empty():
    response = client.get("/todos/stats")
    assert response.status_code == 200
    assert response.json() == {
        "total": 0, "completed": 0, "active": 0, "overdue": 0, "completion_rate": 0.0,
        "active_by_priority": {"high": 0, "medium": 0, "low": 0},
    }


def test_stats_counts():
    save_todos([
        make(1, "done", completed=True),
        make(2, "late", due_date="2000-01-01", priority="high"),
        make(3, "late but done", completed=True, due_date="2000-01-01"),
        make(4, "future", due_date="2999-12-31", priority="low"),
        make(5, "no due"),
    ])
    stats = client.get("/todos/stats").json()
    assert stats["total"] == 5
    assert stats["completed"] == 2
    assert stats["active"] == 3
    assert stats["overdue"] == 1                 # 완료된 항목은 기한이 지나도 세지 않는다
    assert stats["completion_rate"] == 40.0
    assert stats["active_by_priority"] == {"high": 1, "medium": 1, "low": 1}


def test_stats_route_is_not_treated_as_todo_id():
    save_todos([make(1, "A")])
    assert client.get("/todos/stats").json()["total"] == 1


def test_metrics_endpoint():
    client.get("/todos")
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "http_requests_total" in response.text
    assert "http_request_duration_seconds_bucket" in response.text


def test_metrics_hidden_from_openapi():
    assert "/metrics" not in client.get("/openapi.json").json()["paths"]


def metric_value(text, line_prefix):
    for line in text.splitlines():
        if line.startswith(line_prefix + " "):
            return float(line.rsplit(" ", 1)[1])
    raise AssertionError(f"{line_prefix} not found")


def test_todo_items_metric_follows_saved_todos():
    save_todos([make(1, "done", completed=True), make(2, "late", due_date="2000-01-01"), make(3, "todo")])
    text = client.get("/metrics").text
    assert metric_value(text, 'todo_items{status="completed"}') == 1
    assert metric_value(text, 'todo_items{status="active"}') == 2
    assert metric_value(text, 'todo_items{status="overdue"}') == 1
    assert metric_value(text, "todo_completion_rate_percent") == 33.3


def test_todo_changes_metric_counts_operations():
    def changes():
        text = client.get("/metrics").text
        return {op: metric_value(text, f'todo_changes_total{{operation="{op}"}}') for op in ("create", "update", "delete")}

    before = changes()
    client.post("/todos", json={"title": "A"})
    client.put("/todos/1", json={"title": "A", "completed": True})
    client.delete("/todos/1")
    client.delete("/todos/1")                    # 404 는 변경이 아니므로 세지 않는다
    after = changes()
    assert {op: after[op] - before[op] for op in after} == {"create": 1, "update": 1, "delete": 1}


def test_delete_completed_todos():
    save_todos([make(1, "done", completed=True), make(2, "todo"), make(3, "done too", completed=True)])
    response = client.delete("/todos/completed")
    assert response.status_code == 200
    assert response.json() == {"deleted": 2}
    assert [t.id for t in load_todos()] == [2]


def test_delete_completed_when_nothing_done():
    save_todos([make(1, "todo")])
    assert client.delete("/todos/completed").json() == {"deleted": 0}
    assert len(load_todos()) == 1


def test_delete_completed_counts_in_metrics():
    def deletes():
        return metric_value(client.get("/metrics").text, 'todo_changes_total{operation="delete"}')

    save_todos([make(1, "a", completed=True), make(2, "b", completed=True)])
    before = deletes()
    client.delete("/todos/completed")
    assert deletes() - before == 2


# ---------- 태그 / 마감일순 정렬 (v7.0.0) ----------

def test_create_todo_with_tags():
    response = client.post("/todos", json={"title": "보고서", "tags": [" 과제 ", "DevOps"]})
    assert response.status_code == 201
    assert response.json()["tags"] == ["과제", "DevOps"]          # 앞뒤 공백 제거
    assert load_todos()[0].tags == ["과제", "DevOps"]


def test_duplicate_tags_are_merged_ignoring_case():
    response = client.post("/todos", json={"title": "A", "tags": ["DevOps", "devops", "과제", "DEVOPS"]})
    assert response.json()["tags"] == ["DevOps", "과제"]           # 처음 입력한 표기를 남긴다


@pytest.mark.parametrize("tags", [["a", "b", "c", "d", "e", "f"], [""], ["   "], ["x" * 21]])
def test_invalid_tags_are_rejected(tags):
    response = client.post("/todos", json={"title": "A", "tags": tags})
    assert response.status_code == 422                             # 6개 이상 / 빈 태그 / 21자 이상
    assert load_todos() == []


def test_old_data_without_tags_has_empty_list():
    main.TODO_FILE.write_text('[{"id": 1, "title": "예전 항목"}]', encoding="utf-8")   # v6 이전 형식
    assert client.get("/todos").json()[0]["tags"] == []


def test_filter_by_tag_ignores_case():
    save_todos([make(1, "A", tags=["과제"]), make(2, "B", tags=["DevOps", "과제"]), make(3, "C")])
    assert [t["id"] for t in client.get("/todos", params={"tag": "과제"}).json()] == [1, 2]
    assert [t["id"] for t in client.get("/todos", params={"tag": " devops "}).json()] == [2]
    assert client.get("/todos", params={"tag": "없는태그"}).json() == []


def test_filter_by_tag_with_search_and_sort():
    save_todos([
        make(1, "과제 A", tags=["학교"], priority="low"),
        make(2, "장보기", tags=["학교"], priority="high"),
        make(3, "과제 B", tags=["학교"], priority="high"),
        make(4, "과제 C", priority="high"),
    ])
    response = client.get("/todos", params={"q": "과제", "tag": "학교", "sort": "priority"})
    assert [t["id"] for t in response.json()] == [3, 1]


def test_tag_list_counts():
    save_todos([make(1, "A", tags=["과제", "DevOps"]), make(2, "B", tags=["devops"]), make(3, "C", tags=["개인"]), make(4, "D")])
    response = client.get("/todos/tags")
    assert response.status_code == 200
    assert response.json() == [                                    # 많이 쓴 순, 같으면 이름순
        {"tag": "DevOps", "count": 2},
        {"tag": "개인", "count": 1},
        {"tag": "과제", "count": 1},
    ]


def test_tags_route_is_not_treated_as_todo_id():
    assert client.get("/todos/tags").json() == []


def test_update_tags():
    save_todos([make(1, "A", tags=["old"])])
    response = client.put("/todos/1", json={"title": "A", "tags": ["new"]})
    assert response.json()["tags"] == ["new"]
    assert client.get("/todos/tags").json() == [{"tag": "new", "count": 1}]


def test_sort_by_due_date_puts_no_due_last():
    save_todos([
        make(1, "없음"),
        make(2, "12월", due_date=date(2026, 12, 1)),
        make(3, "11월", due_date=date(2026, 11, 10)),
        make(4, "없음2"),
        make(5, "10월", due_date=date(2026, 10, 1)),
    ])
    response = client.get("/todos", params={"sort": "due"})
    assert response.status_code == 200
    assert [t["id"] for t in response.json()] == [5, 3, 2, 1, 4]   # 마감일 빠른 순, 없는 항목은 등록순으로 맨 뒤


# ---------- 동시 요청 (v7.0.0 결함 수정 — JMeter 부하 테스트에서 발견) ----------

def test_concurrent_creates_get_unique_ids():
    # 수정 전에는 60건 중 일부가 500(JSONDecodeError)으로 실패하고 같은 id·유실이 생겼다
    concurrent_client = TestClient(app, raise_server_exceptions=False)
    with ThreadPoolExecutor(max_workers=20) as pool:
        codes = list(pool.map(lambda i: concurrent_client.post("/todos", json={"title": f"동시 {i}"}).status_code, range(60)))
    assert codes == [201] * 60
    ids = [t.id for t in load_todos()]
    assert sorted(ids) == list(range(1, 61))                       # 유실·중복 없음


def test_concurrent_reads_and_updates_never_fail():
    save_todos([make(i, f"항목 {i}") for i in range(1, 11)])
    concurrent_client = TestClient(app, raise_server_exceptions=False)

    def work(i):
        todo_id = i % 10 + 1
        if i % 2:
            return concurrent_client.put(f"/todos/{todo_id}", json={"title": f"수정 {i}", "completed": True}).status_code
        return concurrent_client.get("/todos").status_code

    with ThreadPoolExecutor(max_workers=20) as pool:
        codes = list(pool.map(work, range(80)))
    assert set(codes) == {200}
    assert len(load_todos()) == 10
