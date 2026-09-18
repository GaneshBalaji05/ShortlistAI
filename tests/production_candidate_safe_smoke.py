import http.cookiejar
import json
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.environ.get("SHORTLISTAI_PRODUCTION_ROOT", "https://shortlistai-app.onrender.com").rstrip("/")


def _open_with_retry(opener, request, *, attempts=12):
    last = None
    for attempt in range(attempts):
        try:
            return opener.open(request, timeout=60)
        except urllib.error.HTTPError:
            raise
        except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
            last = exc
            if attempt == attempts - 1:
                raise
            print(f"Production endpoint not ready ({attempt + 1}/{attempts}); retrying")
            time.sleep(10)
    raise last  # pragma: no cover


def json_request(path, *, method="GET", payload=None, opener=None, expected=200):
    opener = opener or urllib.request.build_opener()
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(ROOT + path, data=data, method=method, headers=headers)
    try:
        response = _open_with_retry(opener, request)
        status = response.status
        raw = response.read().decode("utf-8", errors="ignore")
        body = json.loads(raw or "{}")
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read().decode("utf-8", errors="ignore")
        try:
            body = json.loads(raw or "{}")
        except json.JSONDecodeError:
            body = {"raw": raw}
    if status != expected:
        raise AssertionError(f"{method} {path}: HTTP {status}, expected {expected}: {body}")
    return body


def get_text(path):
    opener = urllib.request.build_opener()
    request = urllib.request.Request(ROOT + path, method="GET")
    with _open_with_retry(opener, request) as response:
        if response.status != 200:
            raise AssertionError(f"GET {path}: HTTP {response.status}")
        return response.read().decode("utf-8", errors="ignore")


def run():
    # Prove the canonical write route is protected before any authentication.
    json_request(
        "/api/v1/candidates",
        method="POST",
        payload={"name": "QA Safe Smoke", "stage": "RandomStage"},
        expected=401,
    )

    # Use the intentionally public demo-login contract already used by the production auth smoke.
    html = get_text("/")
    match = re.search(
        r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})\s*·\s*([A-Za-z0-9]{8,})",
        html,
    )
    if not match:
        raise AssertionError("Production demo-login contract is missing")
    email, password = match.group(1), match.group(2)

    jar = http.cookiejar.CookieJar()
    client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    logged = json_request(
        "/api/auth/login",
        method="POST",
        payload={"email": email, "password": password, "remember": False},
        opener=client,
        expected=200,
    )
    if not logged.get("ok") or not logged.get("demo"):
        raise AssertionError("Production demo login failed")

    session = json_request("/api/auth/session", opener=client, expected=200)
    if not session.get("ok") or not session.get("demo"):
        raise AssertionError("Production demo session failed")

    # Canonical v1 auth/workspace context must be available. Do not print IDs.
    me = json_request("/api/v1/me", opener=client, expected=200)
    context = me.get("data") or {}
    if not isinstance(context.get("workspace_id"), int) or not isinstance(context.get("user_id"), int):
        raise AssertionError("Canonical /api/v1/me did not expose authenticated integer context")

    # Canonical candidate read path must be reachable with the same session.
    candidates = json_request("/api/v1/candidates?limit=1&offset=0", opener=client, expected=200)
    if not isinstance(candidates.get("data"), list):
        raise AssertionError("Canonical candidate list did not return data list")
    meta = candidates.get("meta") or {}
    if not isinstance(meta.get("total"), int):
        raise AssertionError("Canonical candidate list missing integer total")

    # Safe write-path smoke 1: invalid stage must fail BEFORE repository write.
    invalid_stage = json_request(
        "/api/v1/candidates",
        method="POST",
        payload={
            "name": "QA Production Safe Invalid Stage",
            "email": "qa-safe-invalid-stage@invalid.example",
            "stage": "DefinitelyNotARealStage",
        },
        opener=client,
        expected=400,
    )
    if invalid_stage.get("detail") != "Invalid stage":
        raise AssertionError(f"Unexpected invalid-stage response: {invalid_stage}")

    # Safe write-path smoke 2: request body must not be able to override workspace ownership.
    workspace_override = json_request(
        "/api/v1/candidates",
        method="POST",
        payload={
            "name": "QA Production Safe Workspace Override",
            "email": "qa-safe-workspace-override@invalid.example",
            "workspace_id": 999999999,
            "stage": "Sourced",
        },
        opener=client,
        expected=422,
    )
    if "detail" not in workspace_override:
        raise AssertionError("Workspace override was not rejected by request validation")

    # Safe write-path smoke 3: a missing job is validated before candidate insert.
    missing_job = json_request(
        "/api/v1/candidates",
        method="POST",
        payload={
            "name": "QA Production Safe Missing Job",
            "email": "qa-safe-missing-job@invalid.example",
            "job_id": 2147483647,
            "stage": "Sourced",
        },
        opener=client,
        expected=404,
    )
    if missing_job.get("detail") != "Job not found":
        raise AssertionError(f"Unexpected missing-job response: {missing_job}")

    # Confirm no accidental rows with our unique smoke identities were created.
    # The list API has no search parameter, so use the legacy protected search path for a no-match check.
    for probe in (
        "qa-safe-invalid-stage@invalid.example",
        "qa-safe-workspace-override@invalid.example",
        "qa-safe-missing-job@invalid.example",
    ):
        legacy_rows = json_request(
            "/api/candidates?" + urllib.parse.urlencode({"q": probe}),
            opener=client,
            expected=200,
        )
        if not isinstance(legacy_rows, list):
            raise AssertionError("Legacy protected candidate search did not return a list")
        if legacy_rows:
            raise AssertionError(f"Production-safe smoke unexpectedly created candidate data for {probe}")

    json_request("/api/auth/logout", method="POST", opener=client, expected=200)
    json_request("/api/auth/session", opener=client, expected=401)

    print(
        "Candidate production safe smoke passed: canonical auth/context/read path, "
        "invalid-stage 400, workspace override rejection, missing-job 404, and zero candidate writes"
    )


if __name__ == "__main__":
    run()
