"""App route profile tests."""

from dataworks_agent import main


def _route_paths(app):
    return set(app.openapi().get("paths", {}))


def test_create_app_hides_experimental_platform_routes_by_default(monkeypatch):
    monkeypatch.setattr(main.settings, "enable_experimental_platform_routes", False)

    app = main.create_app()
    paths = _route_paths(app)

    assert "/agent/chat" in paths
    assert not any(path.startswith("/api/semantic") for path in paths)
    assert not any(path.startswith("/api/runtime") for path in paths)
    assert not any(path.startswith("/api/mcp-server") for path in paths)


def test_create_app_can_enable_experimental_platform_routes(monkeypatch):
    monkeypatch.setattr(main.settings, "enable_experimental_platform_routes", True)

    app = main.create_app()
    paths = _route_paths(app)

    assert any(path.startswith("/api/semantic") for path in paths)
    assert any(path.startswith("/api/runtime") for path in paths)
    assert any(path.startswith("/api/mcp-server") for path in paths)
