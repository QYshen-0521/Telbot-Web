"""Static console shell and browser CORS for the optional Pi API."""

from fastapi.testclient import TestClient

from telbot.http_app import app

client = TestClient(app)


def test_index_is_browseable_shell() -> None:
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert "设备未连接" in html
    assert 'href="styles.css"' in html
    assert 'src="app.js"' in html
    assert 'id="controlFieldset"' in html
    assert "disabled" in html
    assert "如何工作" in html
    assert "重新检测" in html


def test_root_assets_match_pages_layout() -> None:
    css = client.get("/styles.css")
    script = client.get("/app.js")
    assert css.status_code == 200
    assert "text/css" in css.headers["content-type"]
    assert script.status_code == 200
    body = script.text
    assert "http://telbot.local:8765" in body
    assert "http://127.0.0.1:8765" in body
    assert "telbot.apiBase" in body
    assert "telbot.tunnelUrl" in body
    legacy = client.get("/web/app.js")
    assert legacy.status_code == 200
    assert legacy.text == body
    missing = client.get("/web/missing.js")
    assert missing.status_code == 404


def test_health_allows_cross_origin_browser() -> None:
    origin = "https://qyshen-0521.github.io"
    response = client.get("/health?quick=1", headers={"Origin": origin})
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["access-control-allow-origin"] == "*"
    assert response.headers["access-control-allow-private-network"] == "true"


def test_cors_preflight_allows_control_requests() -> None:
    response = client.options(
        "/text",
        headers={
            "Origin": "https://qyshen-0521.github.io",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
            "Access-Control-Request-Private-Network": "true",
        },
    )
    assert response.status_code in {200, 204}
    assert response.headers["access-control-allow-origin"] == "*"
    allow_methods = response.headers["access-control-allow-methods"]
    assert "POST" in allow_methods
    assert response.headers["access-control-allow-private-network"] == "true"
