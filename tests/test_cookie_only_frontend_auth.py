from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run():
    theme = (ROOT / "static" / "theme-v2.js").read_text(encoding="utf-8")
    theme_css = (ROOT / "static" / "theme-v2.css").read_text(encoding="utf-8")
    index = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    login = (ROOT / "static" / "login-controller.js").read_text(encoding="utf-8")

    # Browser auth must use the HttpOnly cookie/server session as the source of truth.
    assert "(!authSession || !authSession.token)" not in theme
    assert "location.pathname === '/app'" not in theme
    assert "fetch(`/api/auth/session?_=${Date.now()}`" in theme
    assert "credentials:'same-origin'" in theme

    # Logout must revoke the cookie-backed server session; no readable token is required.
    assert "fetch('/api/auth/logout', {method:'POST', credentials:'same-origin'})" in theme
    assert "body:JSON.stringify({token" not in theme
    assert "async function logoutSession()" in theme

    # Both mobile and desktop must expose controls wired to the same cookie logout flow.
    assert "mobile-signout" in theme
    assert "mobileSignout.textContent = 'Sign out'" in theme
    assert "mobileSignout.onclick = logoutSession" in theme
    assert "footer.querySelector('.signout').onclick = logoutSession" in theme

    # Responsive contract: the mobile header is hidden on desktop, displayed below
    # 900px, and the desktop sidebar account is hidden in the same mobile breakpoint.
    assert ".mobile-header{display:none}" in index
    assert ".mobile-header{display:flex;align-items:center;justify-content:space-between" in index
    assert "@media(max-width:900px)" in index
    assert ".sidebar-account{display:none}" in theme_css
    assert ".force-desktop .sidebar-account{display:block!important}" in theme_css

    # Login controller must still verify the cookie before entering the workspace.
    assert "await verifyCookieSession();" in login
    assert "window.location.replace(target.toString())" in login
    assert "clearLegacySessionState();" in login

    print("Cookie-only frontend auth regression passed")


if __name__ == "__main__":
    run()
