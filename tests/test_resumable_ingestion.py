from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, func, select

from shortlistai.db.models import Base, Candidate, User, Workspace
from shortlistai.db.repositories import WorkspaceRepository
from shortlistai.services.ingestion import (
    IngestionConflict,
    IngestionNotFound,
    IngestionStore,
    ingestion_items,
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ResumableIngestionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "ingestion.db"
        self.url = f"sqlite:///{self.path}"
        self.engine = create_engine(self.url)
        Base.metadata.create_all(self.engine)
        with self.engine.begin() as con:
            con.execute(
                Workspace.__table__.insert(),
                [
                    {"id": 1, "name": "Workspace One", "created_at": now()},
                    {"id": 2, "name": "Workspace Two", "created_at": now()},
                ],
            )
            con.execute(
                User.__table__.insert(),
                [
                    {
                        "id": 1,
                        "workspace_id": 1,
                        "full_name": "QA One",
                        "email": "qa-one@example.test",
                        "password_hash": "x",
                        "password_salt": "x",
                        "role": "Workspace Admin",
                        "created_at": now(),
                        "last_login_at": None,
                    },
                    {
                        "id": 2,
                        "workspace_id": 2,
                        "full_name": "QA Two",
                        "email": "qa-two@example.test",
                        "password_hash": "x",
                        "password_salt": "x",
                        "role": "Workspace Admin",
                        "created_at": now(),
                        "last_login_at": None,
                    },
                ],
            )
            con.execute(
                Candidate.__table__.insert(),
                [
                    {
                        "workspace_id": 1,
                        "name": f"Synthetic {i}",
                        "email": f"synthetic-{i}@example.test",
                        "phone": "",
                        "experience": 4.0,
                        "skills": "Python",
                        "resume_text": f"Synthetic profile {i} " + "Python data engineering " * 8,
                        "source": "resumable-ingestion-test",
                        "notice_period": "",
                        "current_ctc": "",
                        "expected_ctc": "",
                        "job_id": None,
                        "stage": "Applied",
                        "ai_score": None,
                        "rating": None,
                        "created_at": now(),
                        "updated_at": now(),
                        "ai_details": None,
                        "resume_filename": f"synthetic-{i}.txt",
                        "profile_details": "{}",
                        "talent_pools": "[]",
                    }
                    for i in range(1, 521)
                ],
            )
        self.store = IngestionStore(self.engine, 1)

    def tearDown(self):
        self.engine.dispose()
        self.tmp.cleanup()

    def manifest(self, count: int, prefix: str = "profile"):
        return [
            {
                "idempotency_key": f"{prefix}-{i:04d}",
                "source_filename": f"{prefix}-{i:04d}.txt",
            }
            for i in range(1, count + 1)
        ]

    def test_500_items_survive_interruption_and_resume_without_duplicate_items(self):
        batch = self.store.create_batch(
            created_by=1,
            job_id=None,
            source="500-profile durability test",
            items=self.manifest(500),
        )
        batch_id = batch["id"]
        self.assertEqual(batch["total_count"], 500)
        self.assertEqual(batch["pending_count"], 500)

        # Complete 249 items, then leave item 250 in processing to model a killed worker.
        for i in range(1, 250):
            key = f"profile-{i:04d}"
            self.store.claim_item(
                batch_id=batch_id,
                idempotency_key=key,
                source_filename=f"{key}.txt",
                content_hash=f"{i:064x}",
            )
            self.store.complete_item(
                batch_id=batch_id,
                idempotency_key=key,
                candidate_id=i,
                merged=False,
            )

        interrupted_key = "profile-0250"
        self.store.claim_item(
            batch_id=batch_id,
            idempotency_key=interrupted_key,
            source_filename="profile-0250.txt",
            content_hash=f"{250:064x}",
        )
        before_restart = self.store.get_batch(batch_id)
        self.assertEqual(before_restart["processed_count"], 249)
        self.assertEqual(before_restart["processing_count"], 1)
        self.assertEqual(before_restart["pending_count"], 251)

        # Re-open the same database as a restarted process. Reclaiming a processing item
        # is intentional: candidate upsert is independently idempotent, then the item can
        # be finalized safely.
        self.engine.dispose()
        self.engine = create_engine(self.url)
        restarted = IngestionStore(self.engine, 1)
        reclaimed = restarted.claim_item(
            batch_id=batch_id,
            idempotency_key=interrupted_key,
            source_filename="profile-0250.txt",
            content_hash=f"{250:064x}",
        )
        self.assertFalse(reclaimed["already_done"])
        self.assertEqual(reclaimed["attempts"], 2)
        restarted.complete_item(
            batch_id=batch_id,
            idempotency_key=interrupted_key,
            candidate_id=250,
            merged=False,
        )

        for i in range(251, 501):
            key = f"profile-{i:04d}"
            restarted.claim_item(
                batch_id=batch_id,
                idempotency_key=key,
                source_filename=f"{key}.txt",
                content_hash=f"{i:064x}",
            )
            restarted.complete_item(
                batch_id=batch_id,
                idempotency_key=key,
                candidate_id=i,
                merged=False,
            )

        finished = restarted.get_batch(batch_id)
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(finished["processed_count"], 500)
        self.assertEqual(finished["created_count"], 500)
        self.assertEqual(finished["merged_count"], 0)
        self.assertEqual(finished["failed_count"], 0)
        self.assertEqual(finished["pending_count"], 0)
        self.assertEqual(
            finished["processed_count"] + finished["pending_count"] + finished["failed_count"],
            finished["total_count"],
        )
        with self.engine.connect() as con:
            item_count = con.execute(
                select(func.count()).select_from(ingestion_items).where(
                    ingestion_items.c.batch_id == batch_id
                )
            ).scalar_one()
        self.assertEqual(item_count, 500)
        self.assertEqual(WorkspaceRepository(self.engine, 1).count_rows("candidates"), 520)

        # A successful item replay is a no-op and cannot create another ingestion item.
        replay = restarted.claim_item(
            batch_id=batch_id,
            idempotency_key="profile-0001",
            source_filename="profile-0001.txt",
            content_hash=f"{1:064x}",
        )
        self.assertTrue(replay["already_done"])

    def test_partial_failures_are_recorded_and_retryable(self):
        batch = self.store.create_batch(
            created_by=1,
            job_id=None,
            source="partial failure test",
            items=self.manifest(10, prefix="partial"),
        )
        batch_id = batch["id"]
        for i in range(1, 11):
            key = f"partial-{i:04d}"
            self.store.claim_item(
                batch_id=batch_id,
                idempotency_key=key,
                source_filename=f"{key}.txt",
                content_hash=f"{1000+i:064x}",
            )
            if i in {3, 7}:
                self.store.fail_item(
                    batch_id=batch_id,
                    idempotency_key=key,
                    error_code="parse_failed",
                    error_message="Synthetic unreadable file",
                )
            else:
                self.store.complete_item(
                    batch_id=batch_id,
                    idempotency_key=key,
                    candidate_id=500 + i,
                    merged=False,
                )

        status = self.store.get_batch(batch_id)
        self.assertEqual(status["status"], "completed_with_errors")
        self.assertEqual(status["processed_count"], 8)
        self.assertEqual(status["failed_count"], 2)
        self.assertEqual(status["pending_count"], 0)
        self.assertEqual(status["processed_count"] + status["pending_count"] + status["failed_count"], 10)

        for i in (3, 7):
            key = f"partial-{i:04d}"
            self.store.claim_item(
                batch_id=batch_id,
                idempotency_key=key,
                source_filename=f"{key}.txt",
                content_hash=f"{1000+i:064x}",
            )
            self.store.complete_item(
                batch_id=batch_id,
                idempotency_key=key,
                candidate_id=500 + i,
                merged=False,
            )
        retried = self.store.get_batch(batch_id)
        self.assertEqual(retried["status"], "completed")
        self.assertEqual(retried["processed_count"], 10)
        self.assertEqual(retried["failed_count"], 0)

    def test_workspace_isolation_and_content_hash_conflict(self):
        batch = self.store.create_batch(
            created_by=1,
            job_id=None,
            source="isolation test",
            items=self.manifest(1, prefix="isolated"),
        )
        batch_id = batch["id"]
        other = IngestionStore(self.engine, 2)
        with self.assertRaises(IngestionNotFound):
            other.get_batch(batch_id)
        with self.assertRaises(IngestionNotFound):
            other.claim_item(
                batch_id=batch_id,
                idempotency_key="isolated-0001",
                source_filename="isolated-0001.txt",
                content_hash="a" * 64,
            )

        self.store.claim_item(
            batch_id=batch_id,
            idempotency_key="isolated-0001",
            source_filename="isolated-0001.txt",
            content_hash="a" * 64,
        )
        with self.assertRaises(IngestionConflict):
            self.store.claim_item(
                batch_id=batch_id,
                idempotency_key="isolated-0001",
                source_filename="isolated-0001.txt",
                content_hash="b" * 64,
            )


if __name__ == "__main__":
    unittest.main()
