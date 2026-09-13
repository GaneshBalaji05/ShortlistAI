from __future__ import annotations

import json
import re
from typing import Iterable, List

TALENT_POOL_ORDER = [
    "Java",
    "Python",
    "Cloud",
    "AWS",
    "Azure",
    "GCP",
    "Data Engineer",
    "AWS Data Engineer",
    "Azure Data Engineer",
    "GCP Data Engineer",
    "Databricks",
    "AI / GenAI",
    "Cybersecurity",
    "QA Automation",
    "Mobile",
    "Product Management",
    "Recruiting / Talent Acquisition",
]


def _has(text: str, *phrases: str) -> bool:
    value = " " + re.sub(r"\s+", " ", (text or "").lower()) + " "
    return any((" " + p.lower() + " ") in value for p in phrases)


def classify_talent_pools(*parts: str) -> List[str]:
    """Return evidence-based talent pools from resume/profile text.

    A candidate can belong to multiple pools. The function intentionally uses
    conservative keyword rules and does not infer missing experience.
    """
    text = " ".join(p or "" for p in parts)
    lower = text.lower()
    pools = set()

    if re.search(r"\bjava\b", lower) or "spring boot" in lower:
        pools.add("Java")
    if re.search(r"\bpython\b", lower) or any(x in lower for x in ("fastapi", "django", "flask")):
        pools.add("Python")

    aws = bool(re.search(r"\baws\b", lower) or "amazon web services" in lower)
    azure = bool(re.search(r"\bazure\b", lower))
    gcp = bool(re.search(r"\bgcp\b", lower) or "google cloud" in lower)
    if aws:
        pools.add("AWS")
    if azure:
        pools.add("Azure")
    if gcp:
        pools.add("GCP")
    if aws or azure or gcp or any(x in lower for x in ("cloud architect", "cloud engineer", "kubernetes", "terraform")):
        pools.add("Cloud")

    data_engineer = any(
        x in lower
        for x in (
            "data engineer",
            "data engineering",
            "databricks",
            "pyspark",
            "spark",
            "etl",
            "data factory",
            "data pipeline",
            "data lake",
            "snowflake",
        )
    )
    if data_engineer:
        pools.add("Data Engineer")
        if aws:
            pools.add("AWS Data Engineer")
        if azure:
            pools.add("Azure Data Engineer")
        if gcp:
            pools.add("GCP Data Engineer")
    if "databricks" in lower:
        pools.add("Databricks")

    if any(x in lower for x in ("generative ai", "genai", "gen ai", "agentic ai", "large language model", " llm", "rag ", "langchain", "langgraph", "prompt engineering")):
        pools.add("AI / GenAI")
    if any(x in lower for x in ("cybersecurity", "cyber security", "soc analyst", "penetration testing", "vulnerability assessment", "siem")):
        pools.add("Cybersecurity")
    if any(x in lower for x in ("qa automation", "automation testing", "selenium", "playwright", "cypress", "appium")):
        pools.add("QA Automation")
    if any(x in lower for x in ("android", "kotlin", "ios", "swiftui", "uikit", "react native", "flutter")):
        pools.add("Mobile")
    if any(x in lower for x in ("product manager", "product management", "product owner", "roadmap")):
        pools.add("Product Management")
    if any(x in lower for x in ("talent acquisition", "technical recruiter", "it recruiter", "recruitment", "candidate sourcing", "linkedin recruiter", "naukri")):
        pools.add("Recruiting / Talent Acquisition")

    return [name for name in TALENT_POOL_ORDER if name in pools]


def encode_talent_pools(values: Iterable[str] | None) -> str:
    seen = []
    for value in values or []:
        value = str(value).strip()
        if value and value not in seen:
            seen.append(value)
    return json.dumps(seen, ensure_ascii=False)


def decode_talent_pools(value: str | None) -> List[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except Exception:
        parsed = [x.strip() for x in value.split(",") if x.strip()]
    if not isinstance(parsed, list):
        return []
    return [str(x).strip() for x in parsed if str(x).strip()]


# main.py imports this module before defining its routes. Schedule narrowly scoped
# runtime patches after route creation so production keeps the current entrypoint.
try:
    from boolean_search import schedule_main_candidate_search_patch

    schedule_main_candidate_search_patch()
except ImportError:
    pass

try:
    from final_review import schedule_final_review_patch

    schedule_final_review_patch()
except ImportError:
    pass

try:
    from auth_runtime import schedule_main_auth_patch

    schedule_main_auth_patch()
except ImportError:
    pass

try:
    from data_foundation import schedule_data_foundation_patch

    schedule_data_foundation_patch()
except ImportError:
    pass
