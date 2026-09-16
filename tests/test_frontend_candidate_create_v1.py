from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run() -> None:
    index = (ROOT / "static" / "index.html").read_text(encoding="utf-8")

    manual_start = index.index("$('addCandidate').onclick=async()=>{")
    manual_end = index.index("async function moveCand", manual_start)
    manual = index[manual_start:manual_end]

    # First safe caller slice: manual Add Candidate only.
    assert "await api('/api/v1/candidates'" in manual
    assert "method:'POST'" in manual
    assert "credentials:'same-origin'" in manual
    assert "await api('/api/candidates'" not in manual

    # Do not migrate adjacent Candidate callers in this slice.
    assert "candidates=await api(`/api/candidates?q=${q}&stage=${st}`)" in index
    assert "api(`/api/candidates/${id}/stage`" in index
    assert "api(`/api/candidates/${id}/notes`" in index
    assert "api(`/api/candidates/${id}/evaluate`" in index
    assert "const c=await api(`/api/candidates/${id}`)" in index

    # Bulk AI Match remains explicitly outside this migration.
    assert "fetch('/analyze',{method:'POST',body:fd})" in index

    print("Frontend manual Candidate create v1 contract passed")


if __name__ == "__main__":
    run()
