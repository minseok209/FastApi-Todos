import json
import logging
import os
import sqlite3
import sys
import time
from contextlib import asynccontextmanager, closing, contextmanager
from datetime import date
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from prometheus_client import REGISTRY, Counter
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, Field, StringConstraints, field_validator

BASE_DIR = Path(__file__).resolve().parent       # main.py 가 있는 폴더
# 할 일은 SQLite DB 에 저장한다 (이전에는 todo.json 파일 하나에 목록 전체를 다시 썼다)
#   - 기본 위치: fastapi-app/data/todo.db, 환경 변수 TODO_DB 로 바꿀 수 있다
#   - 컨테이너에서는 /app/data 를 볼륨으로 붙여 재배포해도 데이터가 남는다
DB_FILE = Path(os.environ.get("TODO_DB", BASE_DIR / "data" / "todo.db"))
LEGACY_TODO_FILE = BASE_DIR / "todo.json"        # 예전 저장 파일 — DB 를 처음 만들 때 한 번만 가져온다
INDEX_FILE = BASE_DIR / "templates" / "index.html"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()                                    # 서버가 뜰 때 DB·테이블 준비 (처음이면 todo.json 가져오기)
    yield


app = FastAPI(title="To-Do List API", lifespan=lifespan)

# 동시 요청 처리 (v7.0.0 결함 → DB 전환으로 해결)
# FastAPI 는 일반 def 엔드포인트를 스레드 풀에서 동시에 실행한다. 파일 저장 방식에서는 잠금(RLock)으로 막았지만
# 프로세스 하나 안에서만 통했다. 이제는 SQLite 트랜잭션이 직렬화를 맡는다 —
#   - 요청마다 연결을 새로 열고, 추가·수정·삭제는 SQL 한 문장(원자적)으로 처리
#   - WAL 모드: 쓰는 중에도 읽기가 막히지 않는다 / busy timeout: 다른 쓰기가 끝날 때까지 기다린다
DB_TIMEOUT_SECONDS = 30
logger = logging.getLogger("uvicorn.error")      # 변경 이력을 uvicorn 로그(docker logs)에 남긴다 (OWASP A09)
access_logger = logging.getLogger("custom.access")
access_logger.setLevel(logging.INFO)
access_logger.addHandler(logging.StreamHandler(sys.stdout))
access_logger.propagate = False
logging.getLogger("uvicorn.access").disabled = True

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
Tag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]   # 태그 1~20자 (v7.0.0)
MAX_TAGS = 5
PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}  # 우선순위순 정렬 기준 (작을수록 위)


class TodoIn(BaseModel):                         # 클라이언트가 보내는 데이터 (id 없음)
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)   # 길이 제한 — 거대한 요청으로 파일이 커지는 것 방지 (OWASP A04)
    completed: bool = False
    due_date: date | None = None                 # 마감일 (없으면 null) — 기존 데이터도 그대로 읽힌다
    priority: Priority = "medium"                # 우선순위 (없으면 보통) — 기존 데이터도 그대로 읽힌다
    tags: list[Tag] = Field(default_factory=list, max_length=MAX_TAGS)   # 태그 최대 5개 (v7.0.0) — 없던 기존 데이터는 빈 목록

    @field_validator("tags")
    @classmethod
    def dedupe_tags(cls, tags: list[str]) -> list[str]:
        # 대소문자만 다른 같은 태그는 하나로 (처음 입력한 표기를 남긴다)
        seen: set[str] = set()
        unique = []
        for tag in tags:
            if tag.casefold() not in seen:
                seen.add(tag.casefold())
                unique.append(tag)
        return unique


class TodoItem(TodoIn):                          # 서버가 돌려주는 데이터 (id 있음)
    id: int


class TagCount(BaseModel):                       # 태그별 개수 (v7.0.0)
    tag: str
    count: int


class TodoStats(BaseModel):                      # 할 일 현황 요약 (v6.0.0)
    total: int
    completed: int
    active: int                                  # 미완료
    overdue: int                                 # 미완료인데 마감일이 지난 것
    completion_rate: float                       # 완료율 (%) — 할 일이 없으면 0
    active_by_priority: dict[str, int]           # 남은 할 일의 우선순위별 개수


# ---------- DB (SQLite) ----------

# id 는 INTEGER PRIMARY KEY — 값을 주지 않으면 SQLite 가 "가장 큰 id + 1" 을 매긴다 (파일 방식과 같은 규칙)
# tags 는 목록이라 JSON 문자열로, due_date 는 "2026-10-06" 문자열로 저장한다
CREATE_TODOS_TABLE = """
CREATE TABLE IF NOT EXISTS todos (
    id          INTEGER PRIMARY KEY,
    title       TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    completed   INTEGER NOT NULL DEFAULT 0 CHECK (completed IN (0, 1)),
    due_date    TEXT,
    priority    TEXT    NOT NULL DEFAULT 'medium' CHECK (priority IN ('high', 'medium', 'low')),
    tags        TEXT    NOT NULL DEFAULT '[]'
)
"""
# SQL 은 모두 고정 문자열 + ? 자리표시자 — 값은 절대 문자열로 이어 붙이지 않는다 (SQL 인젝션 방지, SonarQube python:S2077)
SELECT_TODOS = "SELECT id, title, description, completed, due_date, priority, tags FROM todos ORDER BY id"
INSERT_TODO = "INSERT INTO todos (title, description, completed, due_date, priority, tags) VALUES (?, ?, ?, ?, ?, ?)"
INSERT_TODO_WITH_ID = "INSERT INTO todos (id, title, description, completed, due_date, priority, tags) VALUES (?, ?, ?, ?, ?, ?, ?)"
UPDATE_TODO = "UPDATE todos SET title = ?, description = ?, completed = ?, due_date = ?, priority = ?, tags = ? WHERE id = ?"


def connect() -> sqlite3.Connection:
    # isolation_level=None: 문장마다 바로 커밋(autocommit). 여러 문장을 묶을 때만 transaction() 을 쓴다
    conn = sqlite3.connect(DB_FILE, timeout=DB_TIMEOUT_SECONDS, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection):
    """BEGIN IMMEDIATE ~ COMMIT — 시작하자마자 쓰기 잠금을 잡아 중간에 다른 쓰기가 끼어들지 못하게 한다. 오류면 ROLLBACK."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def todo_values(todo: TodoIn) -> tuple:
    return (
        todo.title,
        todo.description,
        int(todo.completed),
        todo.due_date.isoformat() if todo.due_date else None,
        todo.priority,
        json.dumps(todo.tags, ensure_ascii=False),
    )


def row_to_todo(row: sqlite3.Row) -> TodoItem:
    return TodoItem(
        id=row["id"],
        title=row["title"],
        description=row["description"],
        completed=bool(row["completed"]),
        due_date=row["due_date"],
        priority=row["priority"],
        tags=json.loads(row["tags"]),
    )


def insert_todos(conn: sqlite3.Connection, todos: list[TodoItem]) -> None:
    conn.executemany(INSERT_TODO_WITH_ID, [(t.id, *todo_values(t)) for t in todos])


def read_legacy_todos() -> list[TodoItem]:
    # 예전 todo.json — priority·tags 가 없던 오래된 형식도 기본값(보통·빈 목록)으로 읽힌다
    if not LEGACY_TODO_FILE.exists():
        return []
    return [TodoItem(**t) for t in json.loads(LEGACY_TODO_FILE.read_text(encoding="utf-8"))]


def init_db() -> None:
    """테이블이 없으면 만들고, 그때 한 번만 todo.json 의 기존 데이터를 옮겨 온다."""
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect()) as conn:
        conn.execute("PRAGMA journal_mode=WAL")   # DB 파일에 저장되는 설정 — 한 번만 하면 된다
        with transaction(conn):
            exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'todos'").fetchone()
            if exists:
                return
            conn.execute(CREATE_TODOS_TABLE)
            legacy = read_legacy_todos()
            insert_todos(conn, legacy)
    logger.info("todo database created: %s (imported %s items from todo.json)", DB_FILE, len(legacy))


def load_todos() -> list[TodoItem]:
    with closing(connect()) as conn:
        return [row_to_todo(row) for row in conn.execute(SELECT_TODOS)]


def save_todos(todos: list[TodoItem]) -> None:
    """목록 전체를 이 내용으로 바꾼다 (테스트 데이터 준비용 — API 는 한 건씩 SQL 로 처리)."""
    with closing(connect()) as conn, transaction(conn):
        conn.execute("DELETE FROM todos")
        insert_todos(conn, todos)


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
    """Prometheus 가 /metrics 를 읽을 때마다 DB 에서 현재 할 일 현황을 계산해 내보낸다."""

    @staticmethod
    def items_family() -> GaugeMetricFamily:
        return GaugeMetricFamily("todo_items", "Current number of To-Do items by status", labels=["status"])

    @staticmethod
    def rate_family(value: float | None = None) -> GaugeMetricFamily:
        return GaugeMetricFamily("todo_completion_rate_percent", "Completed To-Do items (%)", value=value)

    def describe(self):
        # REGISTRY.register() 는 메트릭 이름 확인을 위해 import 시점에 호출한다.
        # describe 가 없으면 collect 를 대신 불러 DB 를 읽으려 하는데, 그때는 아직 DB 가 준비되기 전이다
        return [self.items_family(), self.rate_family()]

    def collect(self):
        stats = todo_stats(load_todos())
        items = self.items_family()
        for status in ("completed", "active", "overdue"):
            items.add_metric([status], getattr(stats, status))
        yield items
        yield self.rate_family(stats.completion_rate)


REGISTRY.register(TodoCollector())


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.update(SECURITY_HEADERS)
    return response


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        client = request.client.host if request.client else "-"
        path = quote(request.scope["path"])
        version = request.scope["http_version"]
        access_logger.info('%s - "%s %s HTTP/%s" %d %.3fs',
                           client, request.method, path, version, status,
                           time.perf_counter() - started)


@app.get("/todos")                               # 목록 조회 — ?q=검색어 로 제목 검색 (대소문자 무시)
def get_todos(q: str = "", tag: str = "", sort: Literal["created", "priority", "due"] = "created") -> list[TodoItem]:
    todos = load_todos()
    keyword = q.strip().casefold()
    if keyword:
        todos = [t for t in todos if keyword in t.title.casefold()]
    wanted = tag.strip().casefold()
    if wanted:                                   # ?tag=과제 — 그 태그가 붙은 항목만 (대소문자 무시, v7.0.0)
        todos = [t for t in todos if wanted in (x.casefold() for x in t.tags)]
    if sort == "priority":                       # ?sort=priority — 높음 → 보통 → 낮음, 같으면 등록 순서 유지
        todos.sort(key=lambda t: PRIORITY_RANK[t.priority])
    elif sort == "due":                          # ?sort=due — 마감일 빠른 순, 마감일 없는 항목은 맨 뒤 (v7.0.0)
        todos.sort(key=lambda t: t.due_date or date.max)
    return todos


@app.get("/todos/tags")                          # 태그 목록 — 많이 쓴 순, 같으면 이름순 (v7.0.0)
def get_todo_tags() -> list[TagCount]:
    counts: dict[str, int] = {}
    names: dict[str, str] = {}                   # 대소문자 무시로 묶고, 처음 나온 표기로 보여준다
    for todo in load_todos():
        for tag in todo.tags:
            key = tag.casefold()
            names.setdefault(key, tag)
            counts[key] = counts.get(key, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [TagCount(tag=names[key], count=count) for key, count in ranked]


@app.get("/todos/stats")                         # 현황 요약 — 전체·완료·미완료·기한 지남·완료율 (v6.0.0)
def get_todo_stats() -> TodoStats:
    return todo_stats(load_todos())


@app.post("/todos", status_code=201)             # 추가 — id 는 DB 가 매긴다 (가장 큰 id + 1)
def create_todo(payload: TodoIn) -> TodoItem:
    with closing(connect()) as conn:             # INSERT 한 문장이라 동시 요청에도 id 가 겹치지 않는다
        cursor = conn.execute(INSERT_TODO, todo_values(payload))
    todo = TodoItem(id=cursor.lastrowid, **payload.model_dump())
    TODO_CHANGES.labels("create").inc()
    logger.info("todo created: id=%s", todo.id)
    return todo


@app.delete("/todos/completed")                  # 완료 항목 한꺼번에 삭제 (v6.0.0) — /todos/{todo_id} 보다 먼저 선언해야 한다
def delete_completed_todos() -> dict[str, int]:
    with closing(connect()) as conn:
        deleted = conn.execute("DELETE FROM todos WHERE completed = 1").rowcount
    if deleted:
        TODO_CHANGES.labels("delete").inc(deleted)
        logger.info("completed todos deleted: count=%s", deleted)
    return {"deleted": deleted}


@app.put("/todos/{todo_id}", responses=NOT_FOUND_RESPONSE)                    # 수정
def update_todo(todo_id: int, payload: TodoIn) -> TodoItem:
    with closing(connect()) as conn:
        cursor = conn.execute(UPDATE_TODO, (*todo_values(payload), todo_id))
    if cursor.rowcount == 0:                     # 바뀐 행이 없으면 없는 id — 404 는 엔드포인트가 직접 던진다 (SonarQube python:S8415)
        raise HTTPException(404, NOT_FOUND_DETAIL)
    TODO_CHANGES.labels("update").inc()
    logger.info("todo updated: id=%s", todo_id)
    return TodoItem(id=todo_id, **payload.model_dump())


@app.delete("/todos/{todo_id}", status_code=204, responses=NOT_FOUND_RESPONSE)  # 삭제
def delete_todo(todo_id: int) -> None:
    with closing(connect()) as conn:
        deleted = conn.execute("DELETE FROM todos WHERE id = ?", (todo_id,)).rowcount
    if deleted == 0:
        raise HTTPException(404, NOT_FOUND_DETAIL)
    TODO_CHANGES.labels("delete").inc()
    logger.info("todo deleted: id=%s", todo_id)


@app.get("/", include_in_schema=False)           # 화면 서빙
def read_root() -> FileResponse:
    return FileResponse(INDEX_FILE, media_type="text/html", headers={"Content-Security-Policy": INDEX_CSP})
