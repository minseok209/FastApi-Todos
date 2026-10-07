import pytest
from fastapi.testclient import TestClient

import main
from main import app, save_todos, load_todos, TodoItem

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_and_teardown(tmp_path, monkeypatch):
    # 실제 todo.json 대신 테스트마다 새 임시 파일 사용 (본인 데이터 보호 + 테스트 간 격리)
    monkeypatch.setattr(main, "TODO_FILE", tmp_path / "todo.json")
    save_todos([])  # 테스트 전 초기화
    yield
    # 테스트 후 정리: tmp_path 와 monkeypatch 가 자동으로 원상 복구


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
    assert "Version 5.0.0" in response.text
    assert 'id="search"' in response.text        # 검색창이 화면에 있는지
    assert 'id="sort"' in response.text          # 정렬 선택이 화면에 있는지
