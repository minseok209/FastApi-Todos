import base64
from pathlib import Path

import pytest

try:
    from pytest_html import extras as html_extras   # --html 옵션을 쓸 때만 필요
except ImportError:
    html_extras = None

SHOT_DIR = Path("ui_report/screenshots")
shots_key = pytest.StashKey[list]()


@pytest.fixture
def shot(page, request):
    """shot("이름") → 전체 화면 캡처를 파일로 저장하고 pytest-html 리포트에도 첨부."""
    def take(name):
        SHOT_DIR.mkdir(parents=True, exist_ok=True)
        png = page.screenshot(path=SHOT_DIR / f"{request.node.name}-{name}.png", full_page=True)
        request.node.stash.setdefault(shots_key, []).append((name, png))
    return take


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    report = yield
    if report.when == "call" and html_extras:
        report.extras = getattr(report, "extras", []) + [
            html_extras.png(base64.b64encode(png).decode(), name)
            for name, png in item.stash.get(shots_key, [])
        ]
    return report
