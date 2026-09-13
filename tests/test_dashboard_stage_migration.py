from pathlib import Path

import main


def candidate(stage, l1="Pending Scheduling", l2="Not Started", rating="", source="Test"):
    return {
        "stage": stage,
        "l1_status": l1,
        "l2_status": l2,
        "rating": rating,
        "source": source,
    }


def test_dashboard_summary_counts_canonical_and_legacy_terminal_stages():
    rows = [
        candidate("Hired", "Cleared", "Cleared", "Strong"),
        candidate("Joined", "Cleared", "Cleared", "Average"),
        candidate("Dropped", "Not Applicable", "Not Applicable", "Weak"),
        candidate("Rejected", "Not Applicable", "Not Applicable"),
        candidate("Selected", "Cleared", "Cleared"),
    ]
    summary = main._summary(rows)
    assert summary["hired"] == 2
    assert summary["dropped"] == 2
    assert summary["in_pipeline"] == 1
    assert summary["stage_distribution"]["Hired"] == 2
    assert summary["stage_distribution"]["Dropped"] == 2
    assert summary["stage_distribution"]["Selected"] == 1


def test_workflow_defaults_understand_new_pipeline_names():
    assert main._workflow_status("Interview Scheduled", {}) == ("Scheduled", "Not Started")
    assert main._workflow_status("L1", {}) == ("Cleared", "Pending Scheduling")
    assert main._workflow_status("Hired", {}) == ("Cleared", "Cleared")
    assert main._workflow_status("Dropped", {}) == ("Not Applicable", "Not Applicable")
    assert main._workflow_status("Joined", {}) == ("Cleared", "Cleared")


def test_dashboard_javascript_uses_stage_compatibility_layer():
    js = (Path(__file__).resolve().parents[1] / "static" / "dashboard-v2.js").read_text(encoding="utf-8")
    assert "const canonicalStage" in js
    assert "canonicalStage(c.stage) === 'Hired'" in js
    assert "canonicalStage(c.stage) === 'Dropped'" in js
    assert "['Selected','Hired'].includes(canonicalStage(c.stage))" in js
