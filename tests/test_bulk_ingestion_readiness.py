from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = (ROOT / "final_review.py").read_text(encoding="utf-8")
FRONTEND = (ROOT / "static" / "final-review.js").read_text(encoding="utf-8")


class BulkIngestionReadinessContract(unittest.TestCase):
    """Prevent the storage-scale probe from being mistaken for resumable ingestion."""

    def test_current_upload_architecture_is_client_batched_not_resumable(self):
        self.assertRegex(BACKEND, r"BULK_REQUEST_LIMIT\s*=\s*50")
        self.assertRegex(FRONTEND, r"BULK_LIMIT\s*=\s*800")
        self.assertRegex(FRONTEND, r"BATCH_SIZE\s*=\s*40")
        self.assertIn("for(let start=0;start<files.length;start+=BATCH_SIZE)", FRONTEND)
        self.assertIn("fetch('/analyze'", FRONTEND)

        # #34 is not complete until a persisted ingestion batch/item contract exists.
        combined = BACKEND + "\n" + FRONTEND
        self.assertNotIn("ingestion_batches", combined)
        self.assertNotIn("ingestion_items", combined)
        self.assertNotRegex(combined, r"/api/(?:v1/)?ingestion(?:/|\b)")

    def test_600_profile_probe_is_storage_searchability_only(self):
        # The existing probe deliberately bypasses HTTP ingestion and inserts fixtures
        # directly. It is useful for storage/search scale, but must not be reported as
        # proof of resumable 500-800 profile ingestion.
        self.assertIn("for index in range(600)", BACKEND)
        self.assertIn("INSERT INTO candidates", BACKEND)
        self.assertIn('status["bulk_count"] = len(probe_rows)', BACKEND)
        self.assertNotIn("resumable_ingestion_ready", BACKEND)

    def test_release_gate_uses_storage_not_ingestion_wording(self):
        workflow = (ROOT / ".github" / "workflows" / "final-review-hardening.yml").read_text(encoding="utf-8")
        self.assertIn("600-profile storage/searchability probe", workflow)
        self.assertIn("resumable 500-800 ingestion is not yet verified", workflow)
        self.assertNotIn("600-profile persistence probe passed", workflow)


if __name__ == "__main__":
    unittest.main()
