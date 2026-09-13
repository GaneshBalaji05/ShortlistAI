from __future__ import annotations

from pathlib import Path

import main


REQUIRED_ROUTES = {
    ("GET", "/"),
    ("GET", "/app"),
    ("POST", "/api/auth/register"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/forgot-password"),
    ("POST", "/api/auth/reset-password"),
    ("GET", "/api/jobs"),
    ("GET", "/api/candidates"),
    ("GET", "/api/talent-pools"),
    ("GET", "/api/dashboard-v2"),
    ("GET", "/api/interviews"),
    ("GET", "/api/export/tracker"),
}


def route_contract() -> set[tuple[str, str]]:
    contract: set[tuple[str, str]] = set()
    for route in main.app.routes:
        path = getattr(route, "path", "")
        for method in getattr(route, "methods", set()) or set():
            contract.add((method, path))
    return contract


def run() -> None:
    routes = route_contract()
    missing = sorted(REQUIRED_ROUTES - routes)
    assert not missing, f"production runtime is missing required routes: {missing}"

    assert getattr(main.app.state, "shortlistai_tenant_security", False) is True, (
        "tenant security middleware must be installed synchronously on the production app"
    )
    assert getattr(main.legacy, "db", None).__name__ == "workspace_db", (
        "legacy ATS database access must be routed through workspace-scoped storage"
    )

    render = Path("render.yaml").read_text(encoding="utf-8")
    assert "uvicorn main:app" in render, "Render blueprint must use the tested production entrypoint"
    assert "export_runtime:app" not in render, "legacy deployment entrypoint drift returned"

    print("production runtime contract passed")


if __name__ == "__main__":
    run()
