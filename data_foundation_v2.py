import sys
import threading
import time

import data_foundation as foundation
from final_review import STAGE_RANK, canonical_stage


_original_upsert = foundation._upsert_candidate


def _pipeline_stage_value(existing: str, incoming: str) -> str:
    old = canonical_stage(existing)
    new = canonical_stage(incoming)
    if old in {"Hired", "Dropped"}:
        return old
    return new if STAGE_RANK.get(new, 0) > STAGE_RANK.get(old, 0) else old


def _pipeline_upsert(con, legacy, incoming: dict, reason: str):
    payload = dict(incoming)
    payload["stage"] = canonical_stage(payload.get("stage"))
    return _original_upsert(con, legacy, payload, reason)


# The foundation module resolves these functions from module globals at runtime,
# so replace only the stage/upsert adapters while keeping its storage implementation.
foundation._stage_value = _pipeline_stage_value
foundation._upsert_candidate = _pipeline_upsert


def schedule_data_foundation_v2_patch(timeout_seconds: float = 15.0) -> None:
    """Install only after final-review and tenant-security patches are both active."""

    def worker() -> None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            package = sys.modules.get("main")
            legacy = getattr(package, "legacy", None) if package is not None else None
            if legacy is None:
                legacy = sys.modules.get("shortlistai_legacy_main")
            app = getattr(legacy, "app", None) if legacy is not None else None
            state = getattr(app, "state", None) if app is not None else None
            if (
                legacy is not None
                and app is not None
                and state is not None
                and getattr(state, "shortlistai_tenant_security", False)
                and getattr(state, "_shortlistai_final_review_installed", False)
            ):
                try:
                    foundation.install_data_foundation(app, legacy)
                except Exception as exc:
                    print(f"ShortlistAI data foundation v2 patch failed: {exc}", file=sys.stderr)
                return
            time.sleep(0.01)
        print("ShortlistAI data foundation v2 patch timed out waiting for final-review/security runtime.", file=sys.stderr)

    threading.Thread(target=worker, name="shortlistai-data-foundation-v2", daemon=True).start()
