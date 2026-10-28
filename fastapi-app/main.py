import json
import logging
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from prometheus_client import REGISTRY, Counter
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent       # main.py 가 있는 폴더
TODO_FILE = BASE_DIR / "todo.json"
INDEX_FILE = BASE_DIR / "templates" / "index.html"

if not TODO_FILE.exists():                       # 없으면 빈 목록으로 만들어 둔다
    TODO_FILE.write_text("[]", encoding="utf-8")

app = FastAPI(title="To-Do List API")
logger = logging.getLogger("uvicorn.error")      # 변경 이력을 uvicorn 로그(docker logs)에 남긴다 (OWASP A09)

# Prometheus 메트릭 엔드포인트(/metrics) — 요청 수·응답 시간 등을 자동으로 수집 (7주차)
Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

# 할 일 추가·수정·삭제 횟수 — 사이트에서 한 작업이 Grafana 그래프에 그대로 보이게 한다
TODO_CHANGES = Counter("todo_changes_total", "To-Do changes by operation", ["operation"])
for _operation in ("create", "update", "delete"):
    TODO_CHANGES.labels(_operation)              # 0 으로 미리 만들어 두어야 첫 변경 전에도 그래프에 선이 나온다

NOT_FOUND_DETAIL = "To-Do item not found"
NOT_FOUND_RESPONSE = {404: {"description": NOT_FOUND_DETAIL}}   # OpenAPI 문서에 404 응답 명시 (SonarQube python:S8415)

# 모든 응답에 붙이는 보안 헤더 (OWASP A05)
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",         # 브라우저가 Content-Type 을 추측하지 않게
    "X-Frame-Options": "DENY",                   # 다른 사이트가 iframe 으로 감싸지 못하게 (클릭재킹 방지)
    "Referrer-Policy": "no-referrer",
}
# 화면(index.html)에만 붙이는 CSP — 스크립트·스타일이 파일 안에 있으므로 inline 만 허용하고 외부 출처는 막는다
INDEX_CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)

Priority = Literal["high", "medium", "low"]      # 우선순위: 높음 / 보통 / 낮음
PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}  # 우선순위순 정렬 기준 (작을수록 위)


class TodoIn(BaseModel):                         # 클라이언트가 보내는 데이터 (id 없음)
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)   # 길이 제한 — 거대한 요청으로 파일이 커지는 것 방지 (OWASP A04)
    completed: bool = False
    due_date: date | None = None                 # 마감일 (없으면 null) — 기존 데이터도 그대로 읽힌다
    priority: Priority = "medium"                # 우선순위 (없으면 보통) — 기존 데이터도 그대로 읽힌다


class TodoItem(TodoIn):                          # 서버가 돌려주는 데이터 (id 있음)
    id: int


class TodoStats(BaseModel):                      # 할 일 현황 요약 (v6.0.0)
    total: int
    completed: int
    active: int                                  # 미완료
    overdue: int                                 # 미완료인데 마감일이 지난 것
    completion_rate: float                       # 완료율 (%) — 할 일이 없으면 0
    active_by_priority: dict[str, int]           # 남은 할 일의 우선순위별 개수


def load_todos() -> list[TodoItem]:
    raw = TODO_FILE.read_text(encoding="utf-8") if TODO_FILE.exists() else "[]"
    return [TodoItem(**t) for t in json.loads(raw)]


def save_todos(todos: list[TodoItem]) -> None:
    # mode="json": date 를 "2026-09-30" 문자열로 바꿔야 json.dumps 가 저장할 수 있다
    data = json.dumps([t.model_dump(mode="json") for t in todos], indent=2, ensure_ascii=False)
    TODO_FILE.write_text(data, encoding="utf-8")


def find_index(todos: list[TodoItem], todo_id: int) -> int:
    # 없으면 404 — 예외는 엔드포인트가 직접 던지고 responses 에 문서화한다 (SonarQube python:S8415)
    for i, todo in enumerate(todos):
        if todo.id == todo_id:
            return i
    return -1


def todo_stats(todos: list[TodoItem]) -> TodoStats:
    today = date.today()
    active = [t for t in todos if not t.completed]
    completed = len(todos) - len(active)
    return TodoStats(
        total=len(todos),
        completed=completed,
        active=len(active),
        overdue=sum(1 for t in active if t.due_date is not None and t.due_date < today),
        completion_rate=round(100 * completed / len(todos), 1) if todos else 0.0,
        active_by_priority={p: sum(1 for t in active if t.priority == p) for p in PRIORITY_RANK},
    )


class TodoCollector(Collector):
    """Prometheus 가 /metrics 를 읽을 때마다 todo.json 에서 현재 할 일 현황을 계산해 내보낸다."""

    def collect(self):
        stats = todo_stats(load_todos())
        items = GaugeMetricFamily("todo_items", "Current number of To-Do items by status", labels=["status"])
        for status in ("completed", "active", "overdue"):
            items.add_metric([status], getattr(stats, status))
        yield items
        yield GaugeMetricFamily("todo_completion_rate_percent", "Completed To-Do items (%)", value=stats.completion_rate)


REGISTRY.register(TodoCollector())


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.update(SECURITY_HEADERS)
    return response


@app.get("/todos")                               # 목록 조회 — ?q=검색어 로 제목 검색 (대소문자 무시)
def get_todos(q: str = "", sort: Literal["created", "priority"] = "created") -> list[TodoItem]:
    todos = load_todos()
    keyword = q.strip().casefold()
    if keyword:
        todos = [t for t in todos if keyword in t.title.casefold()]
    if sort == "priority":                       # ?sort=priority — 높음 → 보통 → 낮음, 같으면 등록 순서 유지
        todos.sort(key=lambda t: PRIORITY_RANK[t.priority])
    return todos


@app.get("/todos/stats")                         # 현황 요약 — 전체·완료·미완료·기한 지남·완료율 (v6.0.0)
def get_todo_stats() -> TodoStats:
    return todo_stats(load_todos())


@app.post("/todos", status_code=201)             # 추가 — id 는 서버가 매긴다
def create_todo(payload: TodoIn) -> TodoItem:
    todos = load_todos()
    new_id = max((t.id for t in todos), default=0) + 1
    todo = TodoItem(id=new_id, **payload.model_dump())
    save_todos(todos + [todo])
    TODO_CHANGES.labels("create").inc()
    logger.info("todo created: id=%s", todo.id)
    return todo


@app.delete("/todos/completed")                  # 완료 항목 한꺼번에 삭제 (v6.0.0) — /todos/{todo_id} 보다 먼저 선언해야 한다
def delete_completed_todos() -> dict[str, int]:
    todos = load_todos()
    remaining = [t for t in todos if not t.completed]
    deleted = len(todos) - len(remaining)
    if deleted:
        save_todos(remaining)
        TODO_CHANGES.labels("delete").inc(deleted)
        logger.info("completed todos deleted: count=%s", deleted)
    return {"deleted": deleted}


@app.put("/todos/{todo_id}", responses=NOT_FOUND_RESPONSE)                    # 수정
def update_todo(todo_id: int, payload: TodoIn) -> TodoItem:
    todos = load_todos()
    index = find_index(todos, todo_id)
    if index < 0:
        raise HTTPException(404, NOT_FOUND_DETAIL)
    todo = TodoItem(id=todo_id, **payload.model_dump())
    todos[index] = todo
    save_todos(todos)
    TODO_CHANGES.labels("update").inc()
    logger.info("todo updated: id=%s", todo_id)
    return todo


@app.delete("/todos/{todo_id}", status_code=204, responses=NOT_FOUND_RESPONSE)  # 삭제
def delete_todo(todo_id: int) -> None:
    todos = load_todos()
    index = find_index(todos, todo_id)
    if index < 0:
        raise HTTPException(404, NOT_FOUND_DETAIL)
    del todos[index]
    save_todos(todos)
    TODO_CHANGES.labels("delete").inc()
    logger.info("todo deleted: id=%s", todo_id)


@app.get("/", include_in_schema=False)           # 화면 서빙
def read_root() -> FileResponse:
    return FileResponse(INDEX_FILE, media_type="text/html", headers={"Content-Security-Policy": INDEX_CSP})