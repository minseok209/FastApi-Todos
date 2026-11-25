# 개인과제 추가사항: 할 일 저장소를 파일에서 DB로 변경

> **추가사항**: "개인과제: 할일은 file 아닌 DB로 변경"
>
> FastApi-Todos 앱의 할 일 저장소를 `todo.json` 파일에서 **SQLite 데이터베이스**로 바꾼 작업을 정리한 문서입니다.
> 변경 이유, 설계, 코드 변경 내용, 배포 방법, 검증 결과, 문제 해결 과정을 순서대로 적었습니다.

| 항목 | 내용 |
|---|---|
| 작업일 | 2026-11-25 |
| 저장소 | https://github.com/minseok209/FastApi-Todos |
| 관련 커밋 | `0d58da4`, `0969f72`, `f29514c` (main 브랜치) |
| 사용 DB | SQLite 3 (Python 표준 라이브러리 `sqlite3`) |
| DB 파일 위치 | 컨테이너 안 `/app/data/todo.db` (로컬 실행 시 `fastapi-app/data/todo.db`) |
| 배포 대상 | 개인 서버 `163.239.77.83` — `:5001` (docker compose), `:5002` (Jenkins) |
| 결과 | 단위 테스트 67개 통과 · 커버리지 100% · SonarQube Quality Gate 통과 · 두 서버 배포 완료 |

---

## 목차

1. [배경: 왜 파일에서 DB로 바꾸는가](#1-배경-왜-파일에서-db로-바꾸는가)
2. [변경 전 구조와 문제점](#2-변경-전-구조와-문제점)
3. [DB 선택: 왜 SQLite인가](#3-db-선택-왜-sqlite인가)
4. [DB 설계](#4-db-설계)
5. [코드 변경 상세 (`main.py`)](#5-코드-변경-상세-mainpy)
6. [기존 데이터 마이그레이션](#6-기존-데이터-마이그레이션)
7. [동시성 처리: 잠금에서 트랜잭션으로](#7-동시성-처리-잠금에서-트랜잭션으로)
8. [Docker·배포 설정 변경](#8-docker배포-설정-변경)
9. [테스트](#9-테스트)
10. [서버 배포 및 검증 절차](#10-서버-배포-및-검증-절차)
11. [문제 해결 기록 (Troubleshooting)](#11-문제-해결-기록-troubleshooting)
12. [변경 파일·커밋 요약](#12-변경-파일커밋-요약)
13. [보고서 캡처 체크리스트](#13-보고서-캡처-체크리스트)
14. [정리 및 소감](#14-정리-및-소감)

---

## 1. 배경: 왜 파일에서 DB로 바꾸는가

### 1.1 처음부터 "임시"였던 파일 저장

강의자료 **CSEd2 형상관리와Git (28쪽) 개인과제 #1. 샘플앱 만들기**의 지시는 다음과 같았습니다.

> Python, FastAPI를 이용한 간단한 나만의 'TodoList' 웹프로그램 만들기
> **일단 DB 사용 없이 Jason 파일에 CRUD 하면 됨**

"일단"이라는 말처럼 JSON 파일 저장은 시작 단계용이었습니다. 이후 개인과제 #2~#9에는 공통으로 "To-do List 프로그램 기능은 매주 지속적으로 보강함"이라는 문구가 있고, 이번 추가사항에서 저장소를 DB로 바꾸라는 요구가 나왔습니다.

### 1.2 강의자료 속 관련 근거

| 자료 | 내용 | 이번 작업과의 관계 |
|---|---|---|
| CSEd2 (27쪽, 팀과제) | 기술 조건 "UI + OpenAPI기반의 Backend + **DB**" | 실제 서비스는 DB가 기본 구성이라는 기준 |
| CSEd4 docker (24쪽) | Docker Compose 기능: "데이터베이스와 같은 서비스를 사용할 때 **볼륨을 설정하여 데이터 유지**" | DB 파일을 볼륨에 두어 재배포해도 데이터가 남게 한 근거 |
| CSEd4 docker (25쪽) | compose 예시: nginx + mysql 두 서비스 | DB를 컨테이너 구성에 포함하는 예 |
| CSEd8 JMeter | 응답이 느린 예상 원인: "잘못된 데이터베이스 설계나 구현" | 동시 요청 성능·안정성 개선의 근거 |

### 1.3 이전 주차에 실제로 겪은 문제

v7.0.0(10주차 JMeter 부하 테스트)에서 **동시 요청 시 데이터 손상** 결함이 발견됐습니다.

- 60건을 동시에 추가했더니 **500 오류 18건**, 실제로 저장된 건 **17건뿐**이었습니다.
- 원인: 쓰는 중인 `todo.json`을 다른 요청이 읽어 `JSONDecodeError`가 났고, 두 요청이 같은 목록을 읽은 뒤 각자 저장해서 한쪽 추가분이 사라졌습니다.
- 당시에는 `threading.RLock`(프로세스 안의 잠금)으로 막았지만, 이 방법은 **uvicorn 프로세스가 1개일 때만** 통합니다. 코드 주석에도 "워커를 여러 개 띄우면 파일 잠금이나 DB가 필요하다"고 적어 두었습니다.

이번 DB 전환이 그 숙제를 해결합니다.

---

## 2. 변경 전 구조와 문제점

### 2.1 변경 전 저장 방식

```
요청 (추가/수정/삭제)
   │
   ▼
TODO_LOCK 잡기 (threading.RLock)
   │
   ▼
todo.json 전체 읽기 → 파이썬 리스트로 변환 → 한 건 수정 → 리스트 전체를 JSON으로 다시 쓰기
   │
   ▼
TODO_LOCK 풀기
```

```python
# 변경 전 코드 (요약)
TODO_FILE = BASE_DIR / "todo.json"
TODO_LOCK = threading.RLock()

def load_todos():
    with TODO_LOCK:
        raw = TODO_FILE.read_text(encoding="utf-8")
    return [TodoItem(**t) for t in json.loads(raw)]

def save_todos(todos):
    data = json.dumps([t.model_dump(mode="json") for t in todos], indent=2, ensure_ascii=False)
    with TODO_LOCK:
        TODO_FILE.write_text(data, encoding="utf-8")

@app.post("/todos")
def create_todo(payload):
    with TODO_LOCK:
        todos = load_todos()
        new_id = max((t.id for t in todos), default=0) + 1
        save_todos(todos + [TodoItem(id=new_id, **payload.model_dump())])
```

### 2.2 문제점 정리

| # | 문제 | 설명 |
|---|---|---|
| 1 | **매번 파일 전체를 다시 씀** | 한 건만 바꿔도 목록 전체를 읽고 다시 씁니다. 할 일이 많아질수록 느려집니다. |
| 2 | **동시성 보장 범위가 좁음** | `RLock`은 한 프로세스 안에서만 통합니다. `uvicorn --workers 4`처럼 프로세스를 늘리면 다시 데이터가 깨집니다. |
| 3 | **쓰기 도중 장애에 약함** | 파일을 쓰는 도중 컨테이너가 죽으면 JSON이 반쯤 써진 채 남아, 다음 실행에서 읽기 자체가 실패할 수 있습니다. |
| 4 | **재배포하면 데이터가 초기화됨** | `todo.json`이 Docker 이미지 안에 들어 있었습니다. 새 이미지로 컨테이너를 바꾸면 웹에서 추가한 할 일이 모두 사라지고 이미지에 들어 있던 1건으로 돌아갔습니다. |
| 5 | **데이터 규칙을 강제할 수 없음** | 우선순위 값이나 완료 여부 같은 규칙을 파일 차원에서 검사할 방법이 없습니다. |

---

## 3. DB 선택: 왜 SQLite인가

| 기준 | SQLite | MySQL / PostgreSQL |
|---|---|---|
| 추가 설치 | 없음 (Python 표준 라이브러리 `sqlite3`) | DB 서버 컨테이너, 계정·비밀번호 관리 필요 |
| 추가 컨테이너 | 없음 | 1개 이상 추가 (메모리·관리 부담) |
| 의존성(`requirements.txt`) | 변경 없음 | 드라이버(`psycopg`, `pymysql` 등) 추가 |
| 트랜잭션·ACID | 지원 | 지원 |
| 여러 프로세스 동시 접근 | 지원 (파일 잠금 + WAL) | 지원 |
| 비밀값 관리 | 없음 | DB 비밀번호를 `.env`·Jenkins Credentials로 관리해야 함 |
| 앱 규모 적합성 | 단일 서버·소규모 앱에 적합 | 대규모·다중 서버에 적합 |

**결론**: 개인 과제의 Todo 앱은 서버 1대에서 돌아가는 소규모 앱입니다. 별도 DB 서버를 띄우면 관리할 것(컨테이너, 비밀번호, 네트워크)만 늘어납니다. SQLite는 **설치 없이 진짜 DB의 트랜잭션·제약조건·동시성 처리**를 그대로 쓸 수 있어서 가장 적합하다고 판단했습니다.

> 참고: 팀 프로젝트(SlotLock)는 여러 서비스가 같은 데이터를 써야 해서 PostgreSQL을 사용합니다. 규모와 요구사항에 따라 DB를 고른 것입니다.

---

## 4. DB 설계

### 4.1 테이블 스키마

```sql
CREATE TABLE IF NOT EXISTS todos (
    id          INTEGER PRIMARY KEY,
    title       TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    completed   INTEGER NOT NULL DEFAULT 0 CHECK (completed IN (0, 1)),
    due_date    TEXT,
    priority    TEXT    NOT NULL DEFAULT 'medium' CHECK (priority IN ('high', 'medium', 'low')),
    tags        TEXT    NOT NULL DEFAULT '[]'
);
```

### 4.2 컬럼 설계 이유

| 컬럼 | SQL 타입 | 파이썬(Pydantic) 타입 | 설계 이유 |
|---|---|---|---|
| `id` | `INTEGER PRIMARY KEY` | `int` | 값을 주지 않으면 SQLite가 **"현재 가장 큰 id + 1"** 을 자동으로 매깁니다. 파일 방식의 `max(id) + 1` 규칙과 같아서 API 동작이 바뀌지 않습니다. (`AUTOINCREMENT`를 쓰지 않은 이유도 이것입니다.) |
| `title` | `TEXT NOT NULL` | `str` (1~100자) | 제목은 필수입니다. 길이 검사는 API 입력 단계(Pydantic)에서 합니다. |
| `description` | `TEXT NOT NULL DEFAULT ''` | `str` (최대 500자) | 설명이 없으면 빈 문자열입니다. |
| `completed` | `INTEGER` + `CHECK (0, 1)` | `bool` | SQLite에는 불리언 타입이 없어 0/1로 저장하고, CHECK로 다른 값을 막습니다. |
| `due_date` | `TEXT` (NULL 허용) | `date \| None` | `"2026-10-06"` 같은 ISO 날짜 문자열입니다. 이 형식은 문자열 정렬 순서가 날짜 순서와 같습니다. |
| `priority` | `TEXT` + `CHECK` | `"high" \| "medium" \| "low"` | API 검사를 거치지 않고 DB에 직접 넣더라도 잘못된 값은 DB가 거부합니다. |
| `tags` | `TEXT DEFAULT '[]'` | `list[str]` (최대 5개) | 태그는 목록이라 `["과제", "DevOps"]` 같은 JSON 문자열로 저장합니다. 한글이 그대로 보이도록 `ensure_ascii=False`를 씁니다. |

> **태그를 별도 테이블로 나누지 않은 이유**: 태그 필터(`?tag=`)와 태그 목록(`/todos/tags`)은 대소문자를 무시하고(`casefold`) 처음 쓴 표기를 유지하는 등 파이썬 쪽 규칙이 있습니다. 기존 API 결과를 한 글자도 바꾸지 않는 것을 우선해서, 이번에는 JSON 컬럼으로 두고 필터링 로직은 그대로 유지했습니다.

### 4.3 API와 SQL의 대응

| API | 변경 전 (파일) | 변경 후 (DB) |
|---|---|---|
| `GET /todos` | 파일 전체 읽기 | `SELECT ... FROM todos ORDER BY id` |
| `POST /todos` | 전체 읽기 → `max(id)+1` 계산 → 전체 다시 쓰기 | `INSERT INTO todos (...) VALUES (?, ?, ?, ?, ?, ?)` → `cursor.lastrowid`로 새 id |
| `PUT /todos/{id}` | 전체 읽기 → 위치 찾기 → 전체 다시 쓰기 | `UPDATE todos SET ... WHERE id = ?` → 바뀐 행이 0개면 404 |
| `DELETE /todos/{id}` | 전체 읽기 → 위치 찾기 → 전체 다시 쓰기 | `DELETE FROM todos WHERE id = ?` → 지운 행이 0개면 404 |
| `DELETE /todos/completed` | 전체 읽기 → 미완료만 남겨 전체 다시 쓰기 | `DELETE FROM todos WHERE completed = 1` → 지운 개수 반환 |
| `GET /todos/stats`, `/todos/tags`, `/metrics` | 파일 전체 읽기 후 계산 | `SELECT` 후 계산 (계산 로직은 그대로) |

**요청·응답 형식은 전혀 바뀌지 않았습니다.** 화면(`index.html`), JMeter 테스트 계획, 배포 후 API 테스트(`api-tests`), UI 테스트(`ui-tests`)는 수정 없이 그대로 동작합니다.

---

## 5. 코드 변경 상세 (`main.py`)

### 5.1 설정: DB 경로

```python
# 할 일은 SQLite DB 에 저장한다 (이전에는 todo.json 파일 하나에 목록 전체를 다시 썼다)
#   - 기본 위치: fastapi-app/data/todo.db, 환경 변수 TODO_DB 로 바꿀 수 있다
#   - 컨테이너에서는 /app/data 를 볼륨으로 붙여 재배포해도 데이터가 남는다
DB_FILE = Path(os.environ.get("TODO_DB", BASE_DIR / "data" / "todo.db"))
LEGACY_TODO_FILE = BASE_DIR / "todo.json"        # 예전 저장 파일 — DB 를 처음 만들 때 한 번만 가져온다
DB_TIMEOUT_SECONDS = 30
```

- DB 파일을 파일 하나가 아니라 **`data/` 폴더 안**에 둡니다. SQLite는 WAL 모드에서 `todo.db` 옆에 `todo.db-wal`, `todo.db-shm` 파일을 만들기 때문에 폴더 단위로 권한과 볼륨을 관리해야 합니다.
- 환경 변수 `TODO_DB`로 위치를 바꿀 수 있어서, 테스트나 로컬 실험 때 실제 데이터를 건드리지 않습니다.

### 5.2 SQL 문장: 모두 고정 문자열 + `?` 자리표시자

```python
SELECT_TODOS = "SELECT id, title, description, completed, due_date, priority, tags FROM todos ORDER BY id"
INSERT_TODO = "INSERT INTO todos (title, description, completed, due_date, priority, tags) VALUES (?, ?, ?, ?, ?, ?)"
INSERT_TODO_WITH_ID = "INSERT INTO todos (id, title, description, completed, due_date, priority, tags) VALUES (?, ?, ?, ?, ?, ?, ?)"
UPDATE_TODO = "UPDATE todos SET title = ?, description = ?, completed = ?, due_date = ?, priority = ?, tags = ? WHERE id = ?"
```

- 사용자가 입력한 값은 **SQL 문자열에 절대 이어 붙이지 않고** `?` 자리에 따로 넘깁니다. SQL 인젝션(OWASP A03)을 원천 차단합니다.
- 처음에는 컬럼 목록을 f-string으로 조립했지만, SonarQube가 f-string SQL을 보안 핫스팟(`python:S2077`)으로 표시할 수 있어 고정 문자열 상수로 바꿨습니다(커밋 `0969f72`).

### 5.3 연결: 요청마다 새로 열고 닫기

```python
def connect() -> sqlite3.Connection:
    # isolation_level=None: 문장마다 바로 커밋(autocommit). 여러 문장을 묶을 때만 transaction() 을 쓴다
    conn = sqlite3.connect(DB_FILE, timeout=DB_TIMEOUT_SECONDS, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn
```

| 설정 | 의미 |
|---|---|
| 요청마다 새 연결 | FastAPI는 일반 `def` 엔드포인트를 스레드 풀에서 동시에 실행합니다. SQLite 연결은 스레드끼리 공유하면 안 되므로 요청마다 열고 `closing()`으로 닫습니다. |
| `timeout=30` | 다른 요청이 쓰는 중이면 최대 30초까지 기다립니다(busy timeout). 바로 "database is locked" 오류를 내지 않습니다. |
| `isolation_level=None` | 자동 커밋 모드입니다. `INSERT` 한 문장은 그 자체로 하나의 트랜잭션이 됩니다. |
| `row_factory = sqlite3.Row` | 결과를 `row["title"]`처럼 컬럼 이름으로 읽을 수 있게 합니다. |

### 5.4 트랜잭션 도우미

```python
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
```

- 여러 문장을 한 덩어리로 처리해야 할 때(테이블 생성 + 기존 데이터 가져오기, 전체 교체) 사용합니다.
- `BEGIN IMMEDIATE`: 트랜잭션을 시작하자마자 쓰기 잠금을 잡습니다. 그냥 `BEGIN`으로 시작해 나중에 쓰기로 바꾸면 WAL 모드에서 잠금 충돌이 날 수 있는데, 이를 피합니다.
- 중간에 오류가 나면 `ROLLBACK`으로 **전부 되돌립니다.** 파일 방식에서 생길 수 있던 "반쯤 저장된 상태"가 생기지 않습니다.

### 5.5 파이썬 객체 ↔ DB 행 변환

```python
def todo_values(todo: TodoIn) -> tuple:
    return (
        todo.title,
        todo.description,
        int(todo.completed),                                  # bool → 0/1
        todo.due_date.isoformat() if todo.due_date else None, # date → "2026-10-06"
        todo.priority,
        json.dumps(todo.tags, ensure_ascii=False),            # list → '["과제"]'
    )

def row_to_todo(row: sqlite3.Row) -> TodoItem:
    return TodoItem(
        id=row["id"],
        title=row["title"],
        description=row["description"],
        completed=bool(row["completed"]),                     # 0/1 → bool
        due_date=row["due_date"],                             # 문자열 → date (Pydantic이 변환)
        priority=row["priority"],
        tags=json.loads(row["tags"]),                         # JSON 문자열 → list
    )
```

DB에서 읽은 값도 `TodoItem`(Pydantic 모델)을 거치므로, API 입력과 같은 검사 규칙이 적용됩니다.

### 5.6 엔드포인트 변경 예시

**추가 (`POST /todos`)**

```python
@app.post("/todos", status_code=201)             # 추가 — id 는 DB 가 매긴다 (가장 큰 id + 1)
def create_todo(payload: TodoIn) -> TodoItem:
    with closing(connect()) as conn:             # INSERT 한 문장이라 동시 요청에도 id 가 겹치지 않는다
        cursor = conn.execute(INSERT_TODO, todo_values(payload))
    todo = TodoItem(id=cursor.lastrowid, **payload.model_dump())
    TODO_CHANGES.labels("create").inc()
    logger.info("todo created: id=%s", todo.id)
    return todo
```

**수정 (`PUT /todos/{id}`)**

```python
@app.put("/todos/{todo_id}", responses=NOT_FOUND_RESPONSE)
def update_todo(todo_id: int, payload: TodoIn) -> TodoItem:
    with closing(connect()) as conn:
        cursor = conn.execute(UPDATE_TODO, (*todo_values(payload), todo_id))
    if cursor.rowcount == 0:                     # 바뀐 행이 없으면 없는 id
        raise HTTPException(404, NOT_FOUND_DETAIL)
    ...
```

- 예전에는 "목록에서 위치 찾기(`find_index`)"를 했지만, 이제는 **바뀐 행 수(`rowcount`)** 로 존재 여부를 판단합니다. `find_index` 함수는 필요 없어져서 지웠습니다.
- Prometheus 카운터(`todo_changes_total`)와 변경 로그(OWASP A09)는 그대로 유지했습니다.

### 5.7 서버 시작 시 DB 준비 (`lifespan`)

```python
@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()                                    # 서버가 뜰 때 DB·테이블 준비 (처음이면 todo.json 가져오기)
    yield

app = FastAPI(title="To-Do List API", lifespan=lifespan)
```

- 예전에는 `import` 시점에 `todo.json`이 없으면 만들었습니다. 이제는 FastAPI의 **lifespan(서버 시작 이벤트)** 에서 DB를 준비합니다.
- 테스트에서 `import main`만 해도 실제 폴더에 DB 파일이 생기는 부작용이 없어졌습니다.

### 5.8 Prometheus 수집기 보완 (`describe()` 추가)

```python
class TodoCollector(Collector):
    def describe(self):
        # REGISTRY.register() 는 메트릭 이름 확인을 위해 import 시점에 호출한다.
        # describe 가 없으면 collect 를 대신 불러 DB 를 읽으려 하는데, 그때는 아직 DB 가 준비되기 전이다
        return [self.items_family(), self.rate_family()]

    def collect(self):
        stats = todo_stats(load_todos())
        ...
```

- `prometheus_client`는 수집기를 등록할 때 `describe()`가 없으면 `collect()`를 한 번 호출합니다. 파일 방식에서는 문제가 없었지만, DB 방식에서는 **DB가 만들어지기 전(import 시점)** 에 읽으려다 `unable to open database file` 오류가 났습니다.
- `describe()`를 추가해서 등록할 때는 메트릭 이름만 알려 주고, 실제 값은 `/metrics`를 요청할 때만 DB에서 읽도록 했습니다.

---

## 6. 기존 데이터 마이그레이션

### 6.1 동작 방식

```python
def init_db() -> None:
    """테이블이 없으면 만들고, 그때 한 번만 todo.json 의 기존 데이터를 옮겨 온다."""
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect()) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        with transaction(conn):
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'todos'"
            ).fetchone()
            if exists:
                return                           # 이미 DB가 있으면 아무것도 안 함
            conn.execute(CREATE_TODOS_TABLE)
            legacy = read_legacy_todos()         # todo.json 읽기 (없으면 빈 목록)
            insert_todos(conn, legacy)           # 원래 id 그대로 넣기
    logger.info("todo database created: %s (imported %s items from todo.json)", DB_FILE, len(legacy))
```

| 상황 | 동작 |
|---|---|
| DB가 없고 `todo.json`이 있음 | 테이블을 만들고 `todo.json`의 항목을 **원래 id 그대로** 옮깁니다. |
| DB가 없고 `todo.json`도 없음 | 빈 테이블만 만듭니다. |
| DB가 이미 있음 | 아무것도 하지 않습니다. **`todo.json`을 다시 가져오지 않습니다.** |

### 6.2 "딱 한 번만" 가져오는 이유

"DB가 비어 있으면 가져온다"로 만들면, 사용자가 할 일을 모두 지운 뒤 서버를 다시 시작했을 때 지운 항목이 `todo.json`에서 되살아납니다. 그래서 기준을 **"테이블이 처음 만들어질 때"** 로 잡았습니다.

### 6.3 여러 프로세스가 동시에 시작해도 안전

`uvicorn --workers 4`처럼 프로세스 4개가 동시에 `init_db()`를 실행해도, `BEGIN IMMEDIATE`로 쓰기 잠금을 잡은 **뒤에** 테이블 존재 여부를 확인하므로 테이블 생성과 가져오기는 한 번만 일어납니다. 실제로 워커 4개로 띄웠을 때 `todo database created` 로그가 **1번만** 찍힌 것을 확인했습니다.

### 6.4 예전 형식 호환

`todo.json`에는 v4 이전처럼 `priority`, `tags`가 없는 항목도 있을 수 있습니다. `TodoItem` 모델의 기본값 덕분에 각각 `"medium"`, `[]`로 채워져 들어갑니다. 실제 서버의 기존 항목도 이렇게 변환됐습니다.

```json
// 변경 전 todo.json
{"title": "20211602", "description": "...", "completed": false, "id": 1}

// 변경 후 GET /todos 응답
{"title": "20211602", "description": "...", "completed": false,
 "due_date": null, "priority": "medium", "tags": [], "id": 1}
```

---

## 7. 동시성 처리: 잠금에서 트랜잭션으로

| 구분 | 변경 전 (파일 + RLock) | 변경 후 (SQLite) |
|---|---|---|
| 직렬화 주체 | 파이썬 `threading.RLock` | SQLite 자체 잠금 + 트랜잭션 |
| 보장 범위 | **한 프로세스 안**의 스레드끼리만 | **여러 프로세스**까지 (같은 DB 파일을 쓰는 모든 프로세스) |
| 읽기 중 쓰기 | 잠금 때문에 읽기도 대기 | **WAL 모드**: 쓰는 중에도 읽기가 막히지 않음 |
| 쓰기 충돌 시 | 잠금 대기 | busy timeout(30초)까지 대기 후 진행 |
| 쓰기 도중 장애 | 파일이 반쯤 써질 수 있음 | 트랜잭션 단위로 전부 반영되거나 전부 취소(원자성) |
| id 충돌 | 잠금 안에서 `max+1` 계산 | `INSERT` 한 문장이 원자적으로 id 할당 |

**WAL(Write-Ahead Logging) 모드**는 `PRAGMA journal_mode=WAL`로 켭니다. 이 설정은 DB 파일에 저장되므로 처음 한 번만 실행하면 됩니다. 변경 내용을 먼저 `todo.db-wal`에 기록하고 나중에 본 파일에 합치는 방식이라, 쓰는 동안에도 다른 요청이 이전 상태를 그대로 읽을 수 있습니다.

---

## 8. Docker·배포 설정 변경

### 8.1 `fastapi-app/Dockerfile`

```dockerfile
# 변경 전
# 데이터 파일만 appuser 소유로 → 앱은 todo.json 만 수정할 수 있다
COPY --chown=appuser:appuser todo.json ./

# 변경 후
# 예전 데이터 파일 — DB 를 처음 만들 때 읽기만 하므로 root 소유 그대로 둔다
COPY todo.json ./
# SQLite DB 폴더만 appuser 소유로 → 앱은 /app/data 안에만 쓸 수 있다
# (DB 파일 옆에 -wal·-shm 파일도 생기므로 파일이 아닌 폴더 단위로 권한을 준다)
# 이 폴더에 볼륨을 붙이면(docker run -v ...:/app/data) 재배포해도 할 일이 남는다
RUN mkdir /app/data && chown appuser:appuser /app/data
```

- 6주차 SonarQube·OWASP 작업에서 정한 **최소 권한 원칙**을 그대로 지켰습니다. 코드와 `todo.json`은 root 소유(읽기 전용)이고, 실행 사용자 `appuser`는 `/app/data` 폴더에만 쓸 수 있습니다.
- `todo.json`은 이제 마이그레이션용으로 읽기만 하므로 `appuser` 소유일 필요가 없어졌습니다.

### 8.2 `docker-compose.yml` (5001번 앱)

```yaml
services:
  fastapi-app:
    ...
    # 할 일 DB(SQLite) 저장 위치 — 컨테이너를 다시 만들어도 데이터 유지
    volumes:
      - todo-data:/app/data

volumes:
  todo-data:                                    # 할 일 DB(SQLite)
  ...
```

- **이름 있는 볼륨(named volume)** 을 씁니다. 처음 붙일 때 Docker가 이미지 안 `/app/data` 폴더의 소유자(`appuser`)를 그대로 가져오므로 권한 문제가 생기지 않습니다.
- 실제 볼륨 이름은 compose 프로젝트 이름(폴더명)이 앞에 붙어 `fastapi-todos_todo-data`가 됩니다.

### 8.3 `Jenkinsfile`, `Jenkinsfile.jmeter` (5002번, 팀 서버 8055번)

```bash
docker run -d --name "$CONTAINER_NAME" \
  --restart unless-stopped \
  --security-opt no-new-privileges:true \
  --cap-drop ALL \
  -p "$HOST_PORT:$CONTAINER_PORT" \
  -v "${CONTAINER_NAME}-data:/app/data" \      # ← 추가
  "$IMAGE"
```

- 볼륨 이름을 **컨테이너 이름 + `-data`** 로 정했습니다(`FastApi-app-sonar-data`, `fastapi-jmeter-minseok-data`).
- 팀 서버는 팀원 5명이 계정을 같이 쓰므로, 볼륨 이름에도 본인 컨테이너 이름을 넣어 다른 팀원의 볼륨과 겹치지 않게 했습니다.
- Jenkins가 `docker rm -f`로 컨테이너를 지워도 볼륨은 남기 때문에, 다음 배포에서 같은 데이터를 이어서 씁니다.

### 8.4 `.gitignore`, `.dockerignore`

| 파일 | 추가 내용 | 이유 |
|---|---|---|
| `.gitignore` | `fastapi-app/data/` | 로컬에서 실행할 때 생기는 DB 파일을 GitHub에 올리지 않기 위해 |
| `fastapi-app/.dockerignore` | `data/`, `*.db`, `*.db-wal`, `*.db-shm` | 로컬 DB가 Docker 빌드 컨텍스트에 들어가지 않게 하기 위해 |

### 8.5 바뀌지 않은 것

- `requirements.txt`: 변경 없음 (`sqlite3`는 표준 라이브러리)
- `templates/index.html`: 변경 없음 (API 형식이 같으므로)
- `jmeter/fastapi_test_plan.jmx`, `api-tests/`, `ui-tests/`: 변경 없음

---

## 9. 테스트

### 9.1 단위 테스트 구조 변경 (`fastapi-app/tests/test_main.py`)

테스트마다 **새 임시 DB**를 쓰도록 fixture를 바꿨습니다. 실제 데이터는 건드리지 않고, 테스트끼리 서로 영향을 주지 않습니다.

```python
@pytest.fixture(autouse=True)
def use_temp_db(tmp_path, monkeypatch):
    # 실제 DB 대신 테스트마다 새 임시 DB 사용 (본인 데이터 보호 + 테스트 간 격리)
    monkeypatch.setattr(main, "DB_FILE", tmp_path / "todo.db")
    monkeypatch.setattr(main, "LEGACY_TODO_FILE", tmp_path / "todo.json")   # 없는 파일 → 가져올 데이터 없음
    main.init_db()


def use_legacy_file(text):
    # 예전 todo.json 이 있는 상태에서 DB 를 처음 만드는 상황
    main.DB_FILE.unlink()
    main.LEGACY_TODO_FILE.write_text(text, encoding="utf-8")
    main.init_db()
```

기존 테스트의 `save_todos([...])`, `load_todos()` 호출은 함수 이름과 사용법을 그대로 유지해서 거의 수정하지 않았습니다. `save_todos`는 이제 "테이블 전체를 이 목록으로 교체"하는 테스트 데이터 준비용 함수입니다.

### 9.2 새로 추가하거나 바꾼 테스트

| 테스트 | 확인하는 내용 |
|---|---|
| `test_init_db_imports_legacy_json_once` | `todo.json`의 항목(id 3)을 가져오고, 지운 뒤 `init_db()`를 다시 실행해도 **되살아나지 않음** |
| `test_init_db_without_legacy_file_is_empty` | `todo.json`이 없으면 빈 DB로 시작 |
| `test_created_id_continues_after_legacy_import` | 가져온 항목의 id가 7이면 새 항목은 **8**부터 (id 규칙 유지) |
| `test_app_startup_creates_database` | 실제 서버 시작(lifespan) 시 **폴더가 없어도** DB 파일을 만듦 |
| `test_failed_write_rolls_back` | 같은 id 두 개를 넣다가 실패하면 **ROLLBACK**되어 원래 데이터가 그대로 남음 |
| `test_old_data_without_priority_is_medium` | (변경) 예전 형식 `todo.json` → DB로 가져올 때 우선순위 기본값 적용 |
| `test_old_data_without_tags_has_empty_list` | (변경) 예전 형식 `todo.json` → DB로 가져올 때 태그 기본값 적용 |
| `test_concurrent_creates_get_unique_ids` | (기존 유지) 동시 추가 60건 → 모두 201, id 1~60 중복·유실 없음 |
| `test_concurrent_reads_and_updates_never_fail` | (기존 유지) 동시 조회·수정 80건 → 모두 200 |

삭제한 테스트: `test_get_todos_when_file_missing` (파일 삭제 상황은 DB 방식에서는 해당 없음 → `test_init_db_without_legacy_file_is_empty`로 대체)

### 9.3 단위 테스트 결과

```
67 passed
Name      Stmts   Miss  Cover
-----------------------------
main.py     216      0   100%
```

- 로컬(Windows, Python 3.14)과 Jenkins(Ubuntu, Python 3.13.3) 모두 **67개 통과**
- `main.py` 라인 커버리지 **100%** (트랜잭션 ROLLBACK 경로 포함)

### 9.4 실서버 스모크 테스트 (워커 4개)

변경 전에는 불가능했던 **uvicorn 멀티 프로세스** 환경에서 동시 요청을 보내 확인했습니다. 테스트용 DB는 임시 폴더에 만들어 실제 데이터와 분리했습니다.

```bash
TODO_DB=<임시폴더>/smoke.db uvicorn main:app --port 8765 --workers 4
```

| 확인 항목 | 결과 |
|---|---|
| 서버 시작 시 `todo.json` 가져오기 | 기존 1건 정상 import, `database created` 로그 **1번만** (4개 워커 중 하나만 생성) |
| 동시 추가 200건 (스레드 30개) | **201 Created × 200**, 오류 0 |
| id 중복·유실 | 행 201개, 고유 id 201개, 최대 id 201 → **중복·유실 없음** |
| 수정 `PUT /todos/2` | 200 |
| 완료 항목 일괄 삭제 | `{"deleted": 1}` |
| 없는 id 삭제 `DELETE /todos/999` | 404 |
| `/todos/stats` | total 200, active 200 (계산 정상) |
| `/metrics` | `todo_items{status="active"} 200.0` (Prometheus 연동 정상) |
| 서버 로그 | Traceback 0건 |

> v7.0.0에서는 프로세스 1개에서도 60건 동시 추가 시 18건이 실패했습니다. 이제는 **프로세스 4개, 200건**에서도 실패가 없습니다.

---

## 10. 서버 배포 및 검증 절차

### 10.1 배포 전: 기존 데이터 백업 (MobaXterm, 개인 서버)

새 이미지로 바꾸면 컨테이너 안의 `todo.json`이 사라지므로 먼저 백업했습니다.

```bash
cd ~/FastApi-Todos
docker ps --format '{{.Names}}\t{{.Ports}}'
docker cp FastApi-app:/app/todo.json ./todo-backup-5001.json
docker cp FastApi-app-sonar:/app/todo.json ./todo-backup-5002.json
cat todo-backup-5001.json
mkdir -p ~/backup && mv ~/FastApi-Todos/todo-backup-500*.json ~/backup/
```

백업 결과: 두 컨테이너 모두 이미지에 원래 들어 있던 1건뿐이었습니다. 새 DB가 처음 만들어질 때 똑같이 가져오므로 따로 옮길 데이터는 없었습니다.

### 10.2 코드 push (Windows PC)

```bash
git push origin main
```

> 주의: 커밋은 Windows PC에서 만들었으므로 push도 Windows에서 해야 합니다. 서버에서 push하면 올라갈 커밋도 없고, GitHub는 비밀번호 인증을 지원하지 않아 실패합니다(→ 11.4).

### 10.3 5001번 배포 (docker compose, MobaXterm)

```bash
cd ~/FastApi-Todos && git pull
docker compose up -d --build fastapi-app
```

```
✔ Image fastapi-todos-fastapi-app Built
✔ Volume fastapi-todos_todo-data  Created      ← 볼륨 새로 생성
✔ Container FastApi-app           Recreated
```

### 10.4 5001번 검증

**① DB 파일 생성과 권한 확인**

```bash
docker exec FastApi-app ls -l /app/data
```
```
-rw-r--r-- 1 appuser appuser 8192 Nov 25 07:00 todo.db
```
→ `appuser` 소유로 생성됨 (Dockerfile 권한 설정이 정상 적용)

**② 기존 데이터 가져오기 확인**

```bash
curl -s localhost:5001/todos
```
```json
[{"title":"20211602","description":"...","completed":false,"due_date":null,"priority":"medium","tags":[],"id":1}]
```
→ `todo.json`의 1건이 DB로 들어옴, 없던 `priority`·`tags`는 기본값으로 채워짐

**③ 볼륨 연결 확인**

```bash
docker inspect FastApi-app --format '{{json .Mounts}}'
```
```json
[{"Type":"volume","Name":"fastapi-todos_todo-data","Destination":"/app/data","RW":true, ...}]
```

**④ 재배포 후 데이터 유지 확인 (핵심 검증)**

```bash
# 1) 할 일 추가
curl -s -X POST localhost:5001/todos -H 'Content-Type: application/json' -d '{"title":"DB 유지 확인"}'
# → {"title":"DB 유지 확인", ..., "id":2}

# 2) 컨테이너를 완전히 새로 만들기
docker compose up -d --force-recreate fastapi-app

# 3) 다시 조회
curl -s localhost:5001/todos
# → [{"...","id":1}, {"title":"DB 유지 확인", ..., "id":2}]   ← 그대로 남아 있음
```

| | 변경 전 (파일) | 변경 후 (DB + 볼륨) |
|---|---|---|
| 컨테이너를 다시 만든 뒤 | 이미지 안의 1건으로 **초기화** | 추가한 할 일까지 **유지** |

확인 후 테스트 항목은 삭제했습니다.

```bash
curl -s -X DELETE localhost:5001/todos/2
```

### 10.5 5002번 배포 (Jenkins)

1. Jenkins → `Jenkins Deploy Sonarqube` → **지금 빌드**
2. 파이프라인: Checkout → 의존성 설치 → Test & Coverage → SonarQube Analysis → **Quality Gate** → Build → Push → Deploy → Integration Test
3. 빌드 #3, #4는 Quality Gate에서 실패했고, 원인을 고친 뒤 **#5에서 성공**했습니다(→ 11.1).

```bash
docker exec FastApi-app-sonar ls -l /app/data
```
```
-rw-r--r-- 1 appuser appuser 8192 Nov 25 07:39 todo.db
```
→ 07:39는 빌드 #5 배포 시각과 일치하며, 새 DB 버전이 배포된 것을 확인했습니다.

### 10.6 최종 배포 상태

| 대상 | 배포 방식 | DB 파일 | 볼륨 | 데이터 유지 |
|---|---|---|---|---|
| `163.239.77.83:5001` `FastApi-app` | docker compose | `/app/data/todo.db` ✅ | `fastapi-todos_todo-data` | ✅ 재생성 후 유지 확인 |
| `163.239.77.83:5002` `FastApi-app-sonar` | Jenkins #5 | `/app/data/todo.db` ✅ | `FastApi-app-sonar-data` | ✅ (같은 구조) |

---

## 11. 문제 해결 기록 (Troubleshooting)

### 11.1 Jenkins 빌드 #3, #4 실패: SonarQube Quality Gate ERROR

**증상**

```
SonarQube task '...' completed. Quality gate is 'ERROR'
Stage "Build" skipped due to earlier failure(s)
Stage "Push" skipped due to earlier failure(s)
Stage "Deploy" skipped due to earlier failure(s)
ERROR: Pipeline aborted due to quality gate failure: ERROR
Finished: FAILURE
```

테스트(67 passed)와 SonarQube 분석(ANALYSIS SUCCESSFUL)은 성공했지만, Jenkinsfile의 `waitForQualityGate abortPipeline: true` 때문에 품질 기준 미달로 빌드·배포가 중단됐습니다.

**1차 추정과 조치 (빌드 #3 → #4)**

- SQL을 f-string으로 조립한 부분이 보안 핫스팟(`python:S2077`)으로 잡혔다고 추정했습니다.
- SQL 문장을 모두 고정 문자열 상수로 바꿨습니다(커밋 `0969f72`). → **빌드 #4도 실패**했습니다. 추정이 틀렸습니다.
- 다만 이 수정은 SQL을 더 안전하게 쓰는 방법이라 그대로 유지했습니다.

**실제 원인 확인**

SonarQube에 로그인해서 Quality Gate 조건을 직접 조회했습니다.

| 조건 | 기준 | 실제 | 결과 |
|---|---|---|---|
| 새 코드 커버리지 | 80% 이상 | 100% | OK |
| 새 코드 중복 | 3% 이하 | 0% | OK |
| 보안 핫스팟 | 모두 검토 | 0개 | OK |
| **새 이슈** | **0개** | **1개** | **ERROR** |

걸린 이슈: `tests/test_main.py` 81줄, **`python:S5778` (MAJOR)** "Refactor this exception test to have only one invocation possibly throwing an exception."

```python
# 문제 코드: pytest.raises 블록 안에 예외가 날 수 있는 호출이 여러 개
with pytest.raises(sqlite3.IntegrityError):
    save_todos([make(2, "A"), make(2, "B")])   # make()에서 예외가 나도 테스트가 통과해 버림
```

`make()` 호출에서 예상과 다른 이유로 예외가 나도 테스트가 통과할 수 있어서 지적된 것입니다.

**최종 조치 (커밋 `f29514c`)**

```python
duplicate_ids = [make(2, "A"), make(2, "B")]   # 블록 밖에서 미리 만들고
with pytest.raises(sqlite3.IntegrityError):    # 블록 안에는 예외가 날 수 있는 호출 하나만
    save_todos(duplicate_ids)
```

**결과: 빌드 #5** Quality Gate **OK** (새 이슈 0, 커버리지 100%, 중복 0%) → Build → Push → Deploy 완료

| 빌드 | 커밋 | Quality Gate | 결과 |
|---|---|---|---|
| #3 | `0d58da4` | ERROR (새 이슈 1) | 실패 |
| #4 | `0969f72` | ERROR (새 이슈 1, 원인 미해결) | 실패 |
| #5 | `f29514c` | **OK** | **성공 · 5002 배포** |

**교훈**: Jenkins 로그에는 Quality Gate가 ERROR라는 사실만 나오고 **어느 조건이 왜** 실패했는지는 나오지 않습니다. 추정으로 고치기 전에 SonarQube 대시보드(New Code 탭)나 API(`/api/qualitygates/project_status`)로 실패 조건부터 확인해야 합니다. 또한 SonarQube는 `sonar.tests`로 지정한 **테스트 코드도 검사**합니다.

### 11.2 테스트 수집 단계 오류: `unable to open database file`

**증상**: 첫 테스트 실행 때 테스트를 하나도 실행하지 못하고 수집 단계에서 오류가 났습니다.

```
main.py: in collect
    stats = todo_stats(load_todos())
E   sqlite3.OperationalError: unable to open database file
```

**원인**: `REGISTRY.register(TodoCollector())`가 import 시점에 `collect()`를 호출했는데, 그때는 아직 DB가 준비되기 전이었습니다(5.8 참고).

**조치**: `TodoCollector`에 `describe()`를 추가해 등록 시점에는 DB를 읽지 않게 했습니다.

### 11.3 5002가 바뀌지 않음: `/app/data: No such file or directory`

**증상**: push 후에도 `docker exec FastApi-app-sonar ls -l /app/data`가 실패했습니다.

**원인**: `Jenkinsfile`에 자동 실행 설정(`triggers`)이 없어서 push만으로는 Jenkins가 빌드하지 않습니다. 5002는 예전 이미지로 계속 떠 있었습니다.

**조치**: Jenkins에서 **지금 빌드**를 직접 실행했습니다. 이 작업은 저장소의 Jenkinsfile을 SCM에서 가져와 쓰기 때문에, 새로 추가한 `-v` 볼륨 설정도 자동으로 반영됐습니다.

### 11.4 서버에서 `git push` 실패

**증상**

```
remote: Invalid username or token. Password authentication is not supported for Git operations.
fatal: https://github.com/minseok209/FastApi-Todos.git/에 대한 인증이 실패하였습니다
```

**원인**
1. 커밋은 Windows PC에서 만들었으므로 서버 저장소에는 올릴 커밋이 없었습니다.
2. GitHub는 2021년부터 git 작업에 계정 비밀번호를 받지 않고, Personal Access Token만 허용합니다.

**조치**: Windows PC(Git Credential Manager 설정됨)에서 push했습니다. 서버는 `git pull`로 받기만 합니다.

> 참고: GitHub 사용자 이름은 `minseok209`입니다. 이메일은 웹사이트 로그인용이고, git 인증에는 사용자 이름과 토큰을 씁니다.

### 11.5 (부수 문제) Jenkins 실패 메일 오류

```
hudson.AbortException: Email not sent. No recipients of any kind specified ('to', 'cc', 'bcc').
```

`Jenkinsfile`의 `NOTIFY_EMAIL`이 `'[받을 이메일 주소]'` 자리표시자로 남아 있어서, 빌드가 실패할 때 메일을 보내지 못한 것입니다. 빌드 결과와는 상관없고, 성공한 빌드에서는 실행되지 않습니다.

---

## 12. 변경 파일·커밋 요약

### 12.1 변경 파일

| 파일 | 변경 내용 |
|---|---|
| `fastapi-app/main.py` | 저장소를 SQLite로 교체: 연결·트랜잭션·스키마·마이그레이션, SQL 기반 CRUD, lifespan, `TodoCollector.describe()`, `RLock`·`find_index` 제거 |
| `fastapi-app/tests/test_main.py` | 임시 DB fixture, 마이그레이션·시작·ROLLBACK 테스트 추가, 예전 형식 테스트를 마이그레이션 테스트로 변경 |
| `fastapi-app/Dockerfile` | `/app/data`만 `appuser` 쓰기 가능, `todo.json`은 root 소유 읽기 전용 |
| `fastapi-app/.dockerignore` | 로컬 DB 파일 제외 |
| `docker-compose.yml` | `fastapi-app`에 `todo-data:/app/data` 볼륨 |
| `Jenkinsfile` | `docker run`에 `-v "${CONTAINER_NAME}-data:/app/data"` |
| `Jenkinsfile.jmeter` | 같은 볼륨 설정 (팀 서버 8055) |
| `.gitignore` | `fastapi-app/data/` 제외 |
| `CHANGELOG.md` | `Unreleased` 항목에 변경 내역 기록 |

### 12.2 커밋 이력

| 커밋 | 메시지 | 내용 |
|---|---|---|
| `0d58da4` | `feat: store todos in SQLite instead of todo.json` | DB 전환 본 작업 (9개 파일) |
| `0969f72` | `fix: use constant SQL strings to pass SonarQube quality gate` | SQL f-string → 고정 문자열 상수 |
| `f29514c` | `test: keep a single call inside pytest.raises in rollback test` | SonarQube `python:S5778` 수정 → Quality Gate 통과 |

### 12.3 Release Note 초안 (다음 버전에 사용)

```markdown
## Version X.0.0

### Changed
- 할 일 저장소를 todo.json 파일에서 SQLite DB(/app/data/todo.db)로 변경
  - 추가·수정·삭제를 SQL 한 문장으로 처리 (목록 전체를 다시 쓰지 않음)
  - 동시 요청은 SQLite 트랜잭션·WAL 모드가 처리 → uvicorn 워커를 여러 개 띄워도 안전
  - API 요청·응답 형식과 id 규칙(가장 큰 id + 1)은 그대로
- DB를 처음 만들 때 기존 todo.json 데이터를 한 번만 가져옴 (예전 형식도 기본값으로 변환)
- Docker Compose·Jenkins 배포에 볼륨을 붙여 재배포해도 할 일이 유지됨

### Fixed
- SonarQube Quality Gate 실패(python:S5778, 테스트 코드) 수정 — Jenkins #3·#4 실패 → #5 성공

### Testing
- 단위 테스트 67개 통과, main.py 커버리지 100%
- 워커 4개 환경에서 동시 추가 200건 → 모두 성공, id 중복·유실 없음
- 서버에서 컨테이너를 다시 만든 뒤에도 데이터가 유지됨을 확인
```

---

## 13. 보고서 캡처 체크리스트

보고서(PDF)에 넣을 화면입니다. 이미 실행한 화면은 MobaXterm 기록에서 캡처하거나 같은 명령을 다시 실행해 찍으면 됩니다.

| # | 캡처할 화면 | 위치 / 명령 | 보여 주는 것 |
|---|---|---|---|
| 1 | 코드 변경 (GitHub 커밋 화면) | GitHub → 커밋 `0d58da4` | 파일 저장 → DB 저장으로 바뀐 코드 |
| 2 | 단위 테스트 결과 | Jenkins #5 → Pytest HTML Report / Coverage Report | 67 passed, 커버리지 100% |
| 3 | 배포 후 볼륨 생성 | MobaXterm `docker compose up -d --build fastapi-app` | `Volume fastapi-todos_todo-data Created` |
| 4 | DB 파일 생성 | `docker exec FastApi-app ls -l /app/data` | `todo.db` (appuser 소유) |
| 5 | **데이터 유지 검증** | POST → `--force-recreate` → GET 순서의 터미널 화면 | 컨테이너를 다시 만든 뒤에도 id 2가 남아 있음 |
| 6 | 브라우저 화면 | `http://163.239.77.83:5001` (주소창 포함) | 화면은 그대로 정상 동작 |
| 7 | Jenkins 빌드 기록 | Jenkins → `Jenkins Deploy Sonarqube` 빌드 목록 | #3·#4 실패 → #5 성공 |
| 8 | SonarQube Quality Gate | `http://163.239.77.83:9000/dashboard?id=fastapi_app` (New Code) | Passed, 새 이슈 0 |
| 9 | 5002 DB 확인 | `docker exec FastApi-app-sonar ls -l /app/data` | Jenkins 배포에도 DB 적용 |

---

## 14. 정리 및 소감

### 14.1 무엇이 좋아졌나

| 관점 | 변경 전 | 변경 후 |
|---|---|---|
| 데이터 보존 | 재배포하면 초기화 | 볼륨에 저장되어 **재배포해도 유지** |
| 동시성 | 프로세스 1개에서만 안전 | **여러 프로세스**에서도 안전 (트랜잭션 + WAL) |
| 장애 내성 | 쓰는 도중 장애 시 파일 손상 가능 | 트랜잭션 원자성 (전부 반영 또는 전부 취소) |
| 성능 | 한 건 바꿔도 전체 파일 재작성 | 해당 행만 SQL로 변경 |
| 데이터 무결성 | 파일에 규칙 없음 | `NOT NULL`, `CHECK` 제약조건 |
| 보안 | — | `?` 자리표시자로 SQL 인젝션 차단, `/app/data`만 쓰기 가능 |
| 호환성 | — | API 형식·화면·JMeter·API/UI 테스트 **수정 없이** 그대로 동작 |

### 14.2 배운 점

1. **"임시" 구현의 한계는 부하와 운영에서 드러난다.** 파일 저장은 혼자 쓸 때는 문제가 없었지만, JMeter 동시 요청(v7.0.0)과 컨테이너 재배포에서 데이터 손상·초기화라는 실제 문제가 됐습니다. DB의 트랜잭션과 Docker 볼륨이 각각 이 두 문제를 해결합니다.
2. **API 계약을 지키면 저장소를 바꿔도 다른 부분은 그대로 둘 수 있다.** 요청·응답 형식을 유지했더니 화면, 부하 테스트, 통합 테스트를 하나도 고치지 않아도 됐습니다.
3. **품질 게이트는 추정이 아니라 근거로 대응해야 한다.** Jenkins 로그만 보고 원인을 추정해 고쳤다가 한 번 더 실패했습니다. SonarQube에서 실패 조건을 직접 확인하니 원인(테스트 코드 1곳)이 바로 보였습니다.
4. **배포 경로마다 따로 확인해야 한다.** 같은 코드라도 5001(compose 수동 배포)과 5002(Jenkins 배포)는 반영 시점과 방법이 달라서, 각각 DB 파일과 볼륨을 확인해야 했습니다.
