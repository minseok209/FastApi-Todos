"""Playwright UI 테스트 — 실제 브라우저(Chromium)로 To-Do 화면을 조작한다.

    pytest ui-tests --html=ui_report/report.html --self-contained-html            # 개인 서버(기본값)
    pytest ui-tests --base-url http://127.0.0.1:8000 --headed --slowmo 300         # 로컬, 화면 보면서

실제 서버 데이터를 쓰므로 이번 실행에서 만든 항목에만 고유 접두어를 붙이고, 테스트마다 지운다.
"""
import re
import uuid

import pytest
from playwright.sync_api import Page, expect

PREFIX = f"ui-{uuid.uuid4().hex[:6]}"


@pytest.fixture
def todo_page(page: Page):
    page.goto("/")
    expect(page.locator("#count")).not_to_be_empty()         # 첫 목록 로딩 완료
    yield page
    for todo in page.request.get("/todos", params={"q": PREFIX}).json():
        page.request.delete(f"/todos/{todo['id']}")


def add(page: Page, title, description="", due="", priority="medium"):
    page.fill("#title", title)
    page.fill("#description", description)
    page.fill("#due", due)
    page.select_option("#priority", priority)
    page.get_by_role("button", name="추가").click()
    row = item(page, title)
    expect(row).to_be_visible()
    return row


def item(page: Page, title):
    return page.locator("#todo-list li", has_text=title)


# ---------- 화면 기본 ----------

def test_initial_screen(todo_page: Page, shot):
    expect(todo_page).to_have_title("To-Do List")
    expect(todo_page.get_by_role("heading", level=1)).to_have_text("To-Do")
    expect(todo_page.locator("footer")).to_have_text("Version 5.0.0")
    expect(todo_page.locator("#priority")).to_have_value("medium")           # 우선순위 기본값 = 보통
    expect(todo_page.locator("#sort")).to_have_value("created")
    expect(todo_page.get_by_placeholder("제목 검색")).to_be_visible()
    expect(todo_page.get_by_role("button", name="추가")).to_be_disabled()   # 제목이 비어 있으면 비활성
    expect(todo_page.locator("#filters button[aria-pressed=true]")).to_have_text("전체")
    shot("첫화면")


def test_mobile_layout_has_no_horizontal_scroll(todo_page: Page, shot):
    todo_page.set_viewport_size({"width": 375, "height": 812})
    add(todo_page, f"{PREFIX} 모바일에서도 긴 제목이 화면 밖으로 넘치지 않는지 확인하는 항목입니다", "설명")
    overflow = todo_page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert overflow <= 0
    shot("모바일")


# ---------- 추가 ----------

def test_add_todo(todo_page: Page, shot):
    row = add(todo_page, f"{PREFIX} 보고서 작성", "5주차 과제", "2099-10-06")
    expect(row).to_contain_text("5주차 과제")
    expect(row).to_contain_text("마감 2099-10-06")
    expect(todo_page.locator("#title")).to_have_value("")                    # 입력칸 초기화
    expect(todo_page.get_by_role("button", name="추가")).to_be_disabled()
    shot("추가완료")


def test_add_button_disabled_without_title(todo_page: Page, shot):
    todo_page.fill("#description", "제목 없이 설명만")
    expect(todo_page.get_by_role("button", name="추가")).to_be_disabled()
    todo_page.fill("#title", "   ")                                          # 공백만 입력
    expect(todo_page.get_by_role("button", name="추가")).to_be_disabled()
    todo_page.fill("#title", f"{PREFIX} 제목")
    expect(todo_page.get_by_role("button", name="추가")).to_be_enabled()
    shot("버튼활성화")


def test_overdue_label(todo_page: Page, shot):
    row = add(todo_page, f"{PREFIX} 지난 마감", due="2020-01-01")
    expect(row.locator(".due")).to_have_text("마감 2020-01-01 · 기한 지남")
    expect(row.locator(".due")).to_have_class(re.compile("overdue"))
    shot("기한지남")


# ---------- 검색 (v4.0.0) ----------

def test_search_filters_by_title_and_shows_count(todo_page: Page, shot):
    add(todo_page, f"{PREFIX} 장보기")
    add(todo_page, f"{PREFIX} DevOps 과제 제출")
    add(todo_page, f"{PREFIX} devops 발표 준비")

    todo_page.fill("#search", f"{PREFIX} DEVOPS")                            # 대소문자 무시
    expect(todo_page.locator("#todo-list li")).to_have_count(2)
    expect(item(todo_page, f"{PREFIX} 장보기")).to_have_count(0)
    expect(todo_page.locator("#count")).to_have_text(re.compile(r"^검색 결과 2개 · 전체 \d+개$"))
    expect(todo_page.locator("#todo-list mark").first).to_have_text(re.compile(f"{PREFIX} devops", re.I))
    shot("검색결과")

    todo_page.fill("#search", "")                                            # 검색어 지우면 원래대로
    expect(todo_page.locator("#count")).to_have_text(re.compile(r"^\d+ / 전체 \d+개$"))
    expect(item(todo_page, f"{PREFIX} 장보기")).to_be_visible()


def test_search_no_result_message(todo_page: Page, shot):
    todo_page.fill("#search", f"{PREFIX}-없는검색어")
    expect(todo_page.locator("#todo-list li")).to_have_count(0)
    expect(todo_page.locator("#empty")).to_be_visible()
    expect(todo_page.locator("#empty")).to_contain_text("검색 결과가 없습니다")
    expect(todo_page.locator("#count")).to_have_text(re.compile(r"^검색 결과 0개"))
    shot("검색결과없음")


def test_search_combined_with_filter(todo_page: Page, shot):
    add(todo_page, f"{PREFIX} 필터A")
    done = add(todo_page, f"{PREFIX} 필터B")
    done.get_by_role("checkbox").check()
    expect(done.locator(".title")).to_have_class(re.compile("done"))

    todo_page.fill("#search", f"{PREFIX} 필터")
    todo_page.get_by_role("button", name="완료", exact=True).click()
    expect(todo_page.locator("#todo-list li")).to_have_count(1)
    expect(item(todo_page, f"{PREFIX} 필터B")).to_be_visible()
    shot("검색+완료필터")


# ---------- 우선순위 (v5.0.0) ----------

def test_add_with_priority_shows_badge(todo_page: Page, shot):
    row = add(todo_page, f"{PREFIX} 급한 일", priority="high")
    expect(row.locator(".badge")).to_have_text("높음")
    expect(row.locator(".badge")).to_have_class(re.compile("high"))
    expect(todo_page.locator("#priority")).to_have_value("medium")           # 추가 후 기본값으로 돌아감
    shot("우선순위배지")


def test_sort_by_priority(todo_page: Page, shot):
    add(todo_page, f"{PREFIX} 정렬 낮음", priority="low")
    add(todo_page, f"{PREFIX} 정렬 보통")
    add(todo_page, f"{PREFIX} 정렬 높음", priority="high")
    todo_page.fill("#search", f"{PREFIX} 정렬")
    titles = todo_page.locator("#todo-list li .title")
    expect(titles).to_have_text([f"{PREFIX} 정렬 낮음", f"{PREFIX} 정렬 보통", f"{PREFIX} 정렬 높음"])   # 등록순

    todo_page.select_option("#sort", "priority")
    expect(titles).to_have_text([f"{PREFIX} 정렬 높음", f"{PREFIX} 정렬 보통", f"{PREFIX} 정렬 낮음"])
    shot("우선순위정렬")


def test_edit_priority(todo_page: Page):
    row = add(todo_page, f"{PREFIX} 우선순위 변경")
    row.get_by_role("button", name="편집").click()
    expect(todo_page.locator("#edit-priority")).to_have_value("medium")
    todo_page.select_option("#edit-priority", "low")
    todo_page.locator("#edit-dialog").get_by_role("button", name="저장").click()
    expect(item(todo_page, f"{PREFIX} 우선순위 변경").locator(".badge")).to_have_text("낮음")


# ---------- 완료 / 필터 ----------

def test_complete_and_filter(todo_page: Page, shot):
    row = add(todo_page, f"{PREFIX} 완료할 일")
    row.get_by_role("checkbox").check()
    expect(row.locator(".title")).to_have_class(re.compile("done"))

    todo_page.get_by_role("button", name="미완료").click()
    expect(item(todo_page, f"{PREFIX} 완료할 일")).to_have_count(0)
    todo_page.get_by_role("button", name="완료", exact=True).click()
    expect(item(todo_page, f"{PREFIX} 완료할 일")).to_be_visible()
    expect(todo_page.locator("#filters button[aria-pressed=true]")).to_have_text("완료")
    shot("완료필터")


# ---------- 편집 ----------

def test_edit_todo_with_sheet(todo_page: Page, shot):
    row = add(todo_page, f"{PREFIX} 수정 전", "원래 설명")
    row.get_by_role("button", name="편집").click()
    dialog = todo_page.locator("#edit-dialog")
    expect(dialog).to_be_visible()
    expect(todo_page.locator("#edit-title")).to_have_value(f"{PREFIX} 수정 전")
    todo_page.fill("#edit-title", f"{PREFIX} 수정 후")
    todo_page.fill("#edit-description", "바뀐 설명")
    shot("편집시트")

    dialog.get_by_role("button", name="저장").click()
    expect(dialog).to_be_hidden()
    expect(item(todo_page, f"{PREFIX} 수정 후")).to_contain_text("바뀐 설명")
    expect(item(todo_page, f"{PREFIX} 수정 전")).to_have_count(0)
    shot("편집완료")


def test_edit_cancel_keeps_original(todo_page: Page):
    row = add(todo_page, f"{PREFIX} 취소 테스트")
    row.get_by_role("button", name="편집").click()
    todo_page.fill("#edit-title", "바뀌면 안 됨")
    todo_page.get_by_role("button", name="취소").click()
    expect(todo_page.locator("#edit-dialog")).to_be_hidden()
    expect(item(todo_page, f"{PREFIX} 취소 테스트")).to_be_visible()


# ---------- 삭제 ----------

def test_delete_confirm_and_dismiss(todo_page: Page, shot):
    row = add(todo_page, f"{PREFIX} 삭제할 일")

    todo_page.once("dialog", lambda d: d.dismiss())                         # 확인창에서 취소
    row.get_by_role("button", name="삭제").click()
    expect(row).to_be_visible()

    todo_page.once("dialog", lambda d: d.accept())                          # 확인창에서 확인
    row.get_by_role("button", name="삭제").click()
    expect(item(todo_page, f"{PREFIX} 삭제할 일")).to_have_count(0)
    shot("삭제완료")
