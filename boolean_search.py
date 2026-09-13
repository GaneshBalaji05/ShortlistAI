from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, List, Sequence


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
        for key, item in value.items():
            yield str(key)
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


def candidate_search_text(candidate: dict[str, Any]) -> str:
    return "\n".join(_flatten_values(candidate)).lower()


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
