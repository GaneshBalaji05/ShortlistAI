from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run() -> None:
    login = (ROOT / "static" / "login.html").read_text(encoding="utf-8")
    controller = (ROOT / "static" / "login-controller.js").read_text(encoding="utf-8")
    view = (ROOT / "static" / "login-view-icon.js").read_text(encoding="utf-8")
    sw = (ROOT / "static" / "sw.js").read_text(encoding="utf-8")
    runtime = (ROOT / "main" / "__init__.py").read_text(encoding="utf-8")

    # The HTML must load one auth controller directly. Auth cannot depend on a
    # service worker taking control or injecting scripts after navigation.
    assert login.count("/static/login-controller.js?v=1") == 1
    assert "data-login-controller" in login
    assert login.count("/static/login-view-icon.js?v=4") == 1

    # Legacy token auth must no longer live in the document where it could race
    # the hardened cookie controller.
    assert "saveSession(" not in login
    assert "SESSION_KEY='shortlistai-auth-session'" not in login
    assert "/api/auth/login" not in login
    assert ".onsubmit=" not in login

    # Server HttpOnly cookie is the sole authentication source of truth.
    assert "credentials: 'same-origin'" in controller
    assert "verifyCookieSession" in controller
    assert "resumeExistingSession" in controller
    assert "await robustPost('/api/auth/login'" in controller
    assert "await robustPost('/api/auth/register'" in controller
    assert "window.__shortlistAIAuthReady = true" in controller
    assert "localStorage.setItem(LEGACY_SESSION_KEY" not in controller
    assert "sessionStorage.setItem(LEGACY_SESSION_KEY" not in controller

    # The service worker is intentionally exposed at the site root so its scope
    # can cover both / and /app. The runtime must explicitly allow root scope.
    assert "serviceWorker.register('/sw.js?v=10', {scope: '/'})" in controller
    assert '@app.get("/sw.js")' in runtime
    assert '"Service-Worker-Allowed": "/"' in runtime
    assert '"Cache-Control": "no-cache"' in runtime

    # The view switcher has no authority over auth wiring anymore.
    assert "login-fetch-fix" not in view
    assert "loadLoginFetchRecovery" not in view
    assert "/api/auth/" not in view

    # PWA navigation is network-only and the service worker never mutates HTML.
    assert "const CACHE = 'shortlistai-v10'" in sw
    assert "request.mode === 'navigate'" in sw
    assert "cache: 'no-store'" in sw
    assert "url.pathname.startsWith('/api/')" in sw
    assert "injectLoginViewIcon" not in sw
    assert "html.replace" not in sw

    print("single-controller login/PWA contract passed")


if __name__ == "__main__":
    run()
