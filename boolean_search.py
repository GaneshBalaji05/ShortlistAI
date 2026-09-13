from __future__ import annotations

import json
import re
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Iterable, List, Optional, Sequence


class BooleanSearchError(ValueError):
    pass


@dataclass(frozen=True)
class Token:
    kind: str
    value: str = ""


_TOKEN_RE = re.compile(
    r'''\s*(?:(?P<LPAREN>\()|(?P<RPAREN>\))|(?P<PHRASE>"(?:\\.|[^"\\])*")|(?P<WORD>[^\s()"]+))'''
)


def tokenize(query: str) -> List[Token]:
    query = (query or "").strip()
    if not query:
        return []
    tokens: List[Token] = []
    pos = 0
    while pos < len(query):
        match = _TOKEN_RE.match(query, pos)
        if not match:
            raise BooleanSearchError(f"Invalid search syntax near: {query[pos:pos+20]!r}")
        pos = match.end()
        kind = match.lastgroup or ""
        value = match.group(kind) or ""
        if kind == "PHRASE":
            value = bytes(value[1:-1], "utf-8").decode("unicode_escape")
            if not value.strip():
                raise BooleanSearchError("Quoted phrases cannot be empty.")
            tokens.append(Token("TERM", value))
        elif kind == "WORD":
            upper = value.upper()
            if upper in {"AND", "OR", "NOT"}:
                tokens.append(Token(upper))
            else:
                tokens.append(Token("TERM", value))
        else:
            tokens.append(Token(kind))
    return tokens


class _Parser:
    def __init__(self, tokens: Sequence[Token]):
        self.tokens = list(tokens)
        self.pos = 0

    def peek(self) -> Token | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self, kind: str | None = None) -> Token:
        token = self.peek()
        if token is None:
            raise BooleanSearchError("Unexpected end of Boolean search expression.")
        if kind and token.kind != kind:
            raise BooleanSearchError(f"Expected {kind}, found {token.kind}.")
        self.pos += 1
        return token

    def parse(self):
        if not self.tokens:
            return None
        node = self.parse_or()
        if self.peek() is not None:
            raise BooleanSearchError(f"Unexpected token: {self.peek().kind}.")
        return node

    def parse_or(self):
        node = self.parse_and()
        while self.peek() and self.peek().kind == "OR":
            self.take("OR")
            node = ("OR", node, self.parse_and())
        return node

    def parse_and(self):
        node = self.parse_not()
        while True:
            token = self.peek()
            if token is None or token.kind in {"RPAREN", "OR"}:
                break
            if token.kind == "AND":
                self.take("AND")
                if self.peek() is None or self.peek().kind in {"AND", "OR", "RPAREN"}:
                    raise BooleanSearchError("AND must be followed by a search term, NOT, or parenthesized expression.")
            elif token.kind not in {"TERM", "LPAREN", "NOT"}:
                break
            node = ("AND", node, self.parse_not())
        return node

    def parse_not(self):
        if self.peek() and self.peek().kind == "NOT":
            self.take("NOT")
            return ("NOT", self.parse_not())
        return self.parse_primary()

    def parse_primary(self):
        token = self.peek()
        if token is None:
            raise BooleanSearchError("Expected a search term or parenthesized expression.")
        if token.kind == "TERM":
            return ("TERM", self.take("TERM").value)
        if token.kind == "LPAREN":
            self.take("LPAREN")
            if self.peek() and self.peek().kind == "RPAREN":
                raise BooleanSearchError("Empty parentheses are not allowed.")
            node = self.parse_or()
            if not self.peek() or self.peek().kind != "RPAREN":
                raise BooleanSearchError("Missing closing parenthesis in Boolean search expression.")
            self.take("RPAREN")
            return node
        raise BooleanSearchError(f"Unexpected token: {token.kind}.")


def parse_boolean_query(query: str):
    return _Parser(tokenize(query)).parse()


def _flatten_values(value: Any) -> Iterable[str]:
    if value is None:
        return
    if isinstance(value, dict):
        for item in value.values():
            yield from _flatten_values(item)
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _flatten_values(item)
        return
    if isinstance(value, (str, int, float, bool)):
        yield str(value)
        return
    try:
        yield json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        yield str(value)


# Search only candidate-owned evidence. System metadata such as talent-pool labels,
# assigned job titles, pipeline stage, AI missing-skill output and rating is excluded
# so a Java pool label or a JD requirement cannot make a Python/JavaScript resume
# appear in a Java keyword search.
SEARCHABLE_CANDIDATE_FIELDS = (
    "name",
    "email",
    "phone",
    "experience",
    "skills",
    "resume_text",
    "resume_filename",
    "notice_period",
    "current_ctc",
    "expected_ctc",
)

PROFILE_METADATA_EXCLUDE = {
    "screening_status",
    "interview_level",
    "l1_status",
    "l2_status",
    "role_name",
    "recruiter_name",
    "source_history",
}


def _searchable_profile(profile: Any) -> dict:
    if not isinstance(profile, dict):
        return {}
    return {
        key: value
        for key, value in profile.items()
        if key not in PROFILE_METADATA_EXCLUDE
    }


def candidate_search_text(candidate: dict[str, Any]) -> str:
    parts: list[str] = []
    for field in SEARCHABLE_CANDIDATE_FIELDS:
        parts.extend(_flatten_values(candidate.get(field)))
    parts.extend(_flatten_values(_searchable_profile(candidate.get("profile_details"))))
    return "\n".join(parts).lower()


def _term_pattern(term: str) -> re.Pattern[str]:
    term = re.sub(r"\s+", " ", (term or "").strip().lower())
    if not term:
        raise BooleanSearchError("Search terms cannot be empty.")
    pieces = [re.escape(p) for p in term.split(" ") if p]
    body = r"\s+".join(pieces)
    left = r"(?<![a-z0-9])" if term[0].isalnum() else ""
    right = r"(?![a-z0-9])" if term[-1].isalnum() else ""
    return re.compile(left + body + right, re.IGNORECASE)


def _eval(node, text: str) -> bool:
    kind = node[0]
    if kind == "TERM":
        return bool(_term_pattern(node[1]).search(text))
    if kind == "NOT":
        return not _eval(node[1], text)
    if kind == "AND":
        return _eval(node[1], text) and _eval(node[2], text)
    if kind == "OR":
        return _eval(node[1], text) or _eval(node[2], text)
    raise BooleanSearchError(f"Unknown Boolean node: {kind}")


def matches_boolean(query: str, candidate: dict[str, Any]) -> bool:
    ast = parse_boolean_query(query)
    if ast is None:
        return True
    return _eval(ast, candidate_search_text(candidate))


def install_candidate_search_route(app, original_list_candidates, http_exception_cls) -> None:
    """Replace only GET /api/candidates with Boolean-aware q filtering."""
    state = getattr(app, "state", None)
    if state is not None and getattr(state, "_shortlistai_boolean_search_installed", False):
        return

    app.router.routes = [
        route
        for route in app.router.routes
        if not (
            getattr(route, "path", None) == "/api/candidates"
            and "GET" in (getattr(route, "methods", set()) or set())
        )
    ]

    @app.get("/api/candidates")
    def boolean_list_candidates(
        job_id: Optional[int] = None,
        stage: Optional[str] = None,
        q: Optional[str] = None,
        talent_pool: Optional[str] = None,
        min_experience: Optional[float] = None,
        max_experience: Optional[float] = None,
        location: Optional[str] = None,
        notice_period: Optional[str] = None,
    ):
        rows = original_list_candidates(
            job_id=job_id,
            stage=stage,
            q=None,
            talent_pool=talent_pool,
            min_experience=min_experience,
            max_experience=max_experience,
            location=location,
            notice_period=notice_period,
        )
        if not q or not q.strip():
            return rows
        try:
            return [row for row in rows if matches_boolean(q, row)]
        except BooleanSearchError as exc:
            raise http_exception_cls(status_code=400, detail=str(exc)) from exc

    if state is not None:
        state._shortlistai_boolean_search_installed = True


def schedule_main_candidate_search_patch(module_name: str = "main", timeout_seconds: float = 10.0) -> None:
    """Install the Boolean route after main.py finishes defining its routes."""
    def worker() -> None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            module = sys.modules.get("shortlistai_legacy_main") or sys.modules.get(module_name)
            target = getattr(module, "legacy", module) if module is not None else None
            if target is not None and all(hasattr(target, name) for name in ("app", "list_candidates", "HTTPException")):
                try:
                    install_candidate_search_route(target.app, target.list_candidates, target.HTTPException)
                except Exception as exc:
                    print(f"ShortlistAI Boolean search patch failed: {exc}", file=sys.stderr)
                return
            time.sleep(0.01)
        print("ShortlistAI Boolean search patch timed out waiting for main module.", file=sys.stderr)

    threading.Thread(target=worker, name="shortlistai-boolean-search", daemon=True).start()
