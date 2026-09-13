import os
import tempfile
import unittest

from shortlistai.db.models import Base
from shortlistai.db.runtime import is_postgres_url, normalize_database_url, resolve_database_url


class DatabaseRuntimeTests(unittest.TestCase):
    def test_normalizes_render_style_postgres_urls(self):
        self.assertEqual(
            normalize_database_url("postgres://user:pass@db.example/shortlist"),
            "postgresql+psycopg://user:pass@db.example/shortlist",
        )
        self.assertEqual(
            normalize_database_url("postgresql://user:pass@db.example/shortlist"),
            "postgresql+psycopg://user:pass@db.example/shortlist",
        )
        self.assertTrue(is_postgres_url("postgres://user:pass@db.example/shortlist"))

    def test_database_url_wins_over_sqlite_path(self):
        env = {
            "DATABASE_URL": "postgresql://user:pass@db.example/shortlist",
            "SQLITE_PATH": "/tmp/should-not-win.db",
        }
        self.assertEqual(
            resolve_database_url(env),
            "postgresql+psycopg://user:pass@db.example/shortlist",
        )

    def test_sqlite_remains_safe_fallback_during_migration(self):
        path = tempfile.mktemp(suffix=".db")
        resolved = resolve_database_url({"SQLITE_PATH": path})
        self.assertTrue(resolved.startswith("sqlite:///"))
        self.assertTrue(resolved.endswith(path))

    def test_workspace_tables_are_native_and_non_nullable(self):
        expected = {"jobs", "candidates", "notes", "activity_log", "interviews"}
        self.assertTrue(expected.issubset(Base.metadata.tables))
        for table_name in expected:
            table = Base.metadata.tables[table_name]
            self.assertIn("workspace_id", table.c)
            self.assertFalse(table.c.workspace_id.nullable)
            targets = {fk.target_fullname for fk in table.c.workspace_id.foreign_keys}
            self.assertEqual(targets, {"workspaces.id"})


if __name__ == "__main__":
    unittest.main()
