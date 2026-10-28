"""To-Do 사이트에 단계별로 트래픽을 보내 Grafana 그래프 변화를 관찰한다 (7주차 과제 (2)).

    python scripts/traffic.py                                  # 개인 서버 http://163.239.77.83:5001
    python scripts/traffic.py --base-url http://127.0.0.1:8000 # 로컬

표준 라이브러리만 사용. 단계마다 시작·끝 시각을 출력하므로 그래프의 어느 구간이 어떤 작업인지 맞춰 볼 수 있다.
이번 실행에서 만든 항목은 제목 앞에 고유 접두어가 붙고, 마지막 단계에서 모두 지운다.
"""
import argparse
import json
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

PREFIX = f"traffic-{uuid.uuid4().hex[:6]}"


def request(base, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            raw = res.read()
            return res.status, json.loads(raw) if raw and res.headers.get_content_type() == "application/json" else None
    except urllib.error.HTTPError as e:
        return e.code, None


def phase(name, seconds, job):
    start = datetime.now()
    print(f"[{start:%H:%M:%S}] 시작 {name}")
    counts = job(seconds)
    end = datetime.now()
    print(f"[{end:%H:%M:%S}] 끝   {name} : {counts}")
    return start, end


def until(seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        yield


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://163.239.77.83:5001")
    parser.add_argument("--seconds", type=int, default=90, help="부하 단계 하나의 길이 (기본 90초)")
    args = parser.parse_args()
    base, secs = args.base_url.rstrip("/"), args.seconds
    created = []

    def browse(seconds):                          # 화면을 여는 사용자처럼 조회만 (초당 약 5회)
        n = 0
        for _ in until(seconds):
            for path in ("/", "/todos", "/todos/stats"):
                request(base, "GET", path)
                n += 1
            time.sleep(0.6)
        return {"GET": n}

    def write(seconds):                           # 할 일 추가 → 절반 완료 처리 (POST·PUT, 2xx)
        stats = {"POST": 0, "PUT": 0}
        i = 0
        for _ in until(seconds):
            i += 1
            due = (date.today() - timedelta(days=1)) if i % 3 == 0 else (date.today() + timedelta(days=7))
            status, todo = request(base, "POST", "/todos", {
                "title": f"{PREFIX} 할 일 {i}", "due_date": due.isoformat(),
                "priority": ("high", "medium", "low")[i % 3]})
            if status == 201:
                created.append(todo)
                stats["POST"] += 1
                if i % 2 == 0:
                    request(base, "PUT", f"/todos/{todo['id']}", {**todo, "completed": True})
                    stats["PUT"] += 1
            time.sleep(1)
        return stats

    def errors(seconds):                          # 없는 id 수정·삭제(404), 빈 제목·잘못된 우선순위(422)
        stats = {}
        for _ in until(seconds):
            for method, path, body in (("DELETE", "/todos/999999", None),
                                       ("PUT", "/todos/999999", {"title": "없음"}),
                                       ("POST", "/todos", {"title": ""}),
                                       ("POST", "/todos", {"title": "x", "priority": "urgent"})):
                status, _ = request(base, method, path, body)
                stats[status] = stats.get(status, 0) + 1
            time.sleep(0.5)
        return stats

    def burst(seconds):                           # 동시 사용자 10명이 쉬지 않고 조회 (부하 → 응답 시간·CPU 상승)
        def worker(_):
            n = 0
            for _ in until(seconds):
                request(base, "GET", "/todos")
                n += 1
            return n
        with ThreadPoolExecutor(10) as pool:
            return {"GET": sum(pool.map(worker, range(10)))}

    def cleanup(_):                               # 이번 실행에서 만든 항목 삭제 (DELETE, 204)
        for todo in created:
            request(base, "DELETE", f"/todos/{todo['id']}")
        return {"DELETE": len(created)}

    def idle(seconds):
        time.sleep(seconds)
        return {}

    print(f"대상: {base}  (접두어 {PREFIX})")
    phase("1. 대기 (기준선: Prometheus 수집 요청만)", 60, idle)
    phase("2. 조회 위주 사용", secs, browse)
    phase("3. 할 일 추가·완료 처리", secs, write)
    phase("4. 잘못된 요청 (404·422)", secs, errors)
    phase("5. 동시 접속 부하 (10명)", secs, burst)
    phase("6. 만든 항목 삭제", 0, cleanup)
    phase("7. 대기 (원래 상태로 돌아오는지)", 60, idle)


if __name__ == "__main__":
    main()
