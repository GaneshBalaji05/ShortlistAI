from __future__ import annotations

import os
import sqlite3
import tempfile
import threading
import time
from queue import Queue

import auth_runtime
import tenant_security

WRITERS = 4
ROWS_PER_WRITER = 125
READERS = 3


def run() -> None:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    original_path = auth_runtime.DB_PATH
    errors: Queue[str] = Queue()
    stop_readers = threading.Event()

    try:
        auth_runtime.DB_PATH = path
        tenant_security._schema_db = None

        setup = tenant_security._raw()
        try:
            setup.executescript(
                """
                CREATE TABLE stress_parent(
                    id INTEGER PRIMARY KEY
                );
                CREATE TABLE stress_rows(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    writer_id INTEGER NOT NULL,
                    sequence_no INTEGER NOT NULL,
                    parent_id INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(writer_id, sequence_no),
                    FOREIGN KEY(parent_id) REFERENCES stress_parent(id)
                );
                INSERT INTO stress_parent(id) VALUES(1);
                """
            )
            setup.commit()
        finally:
            setup.close()

        # Prove FK enforcement is real on the same connection path used below.
        fk = tenant_security._raw()
        try:
            try:
                fk.execute(
                    "INSERT INTO stress_rows(writer_id,sequence_no,parent_id,payload,created_at) VALUES(?,?,?,?,?)",
                    (-1, -1, 999, "bad-fk", "2026-09-14"),
                )
                fk.commit()
            except sqlite3.IntegrityError:
                fk.rollback()
            else:
                raise AssertionError("foreign key violation was accepted")
        finally:
            fk.close()

        def writer(writer_id: int) -> None:
            con = None
            try:
                con = tenant_security._raw()
                for seq in range(ROWS_PER_WRITER):
                    con.execute(
                        """INSERT INTO stress_rows(
                            writer_id,sequence_no,parent_id,payload,created_at
                        ) VALUES(?,?,?,?,?)""",
                        (writer_id, seq, 1, f"writer-{writer_id}-row-{seq}", "2026-09-14"),
                    )
                    # Commit frequently enough to create realistic lock hand-offs.
                    if (seq + 1) % 5 == 0:
                        con.commit()
                        time.sleep(0.001)
                con.commit()
            except Exception as exc:  # pragma: no cover - asserted through queue
                if con is not None:
                    try:
                        con.rollback()
                    except Exception:
                        pass
                errors.put(f"writer {writer_id}: {type(exc).__name__}: {exc}")
            finally:
                if con is not None:
                    con.close()

        def reader(reader_id: int) -> None:
            con = None
            try:
                con = tenant_security._raw()
                last_count = 0
                while not stop_readers.is_set():
                    count = int(con.execute("SELECT COUNT(*) FROM stress_rows").fetchone()[0])
                    if count < last_count:
                        raise AssertionError(
                            f"reader {reader_id} observed count regression {last_count}->{count}"
                        )
                    last_count = count
                    time.sleep(0.001)
            except Exception as exc:  # pragma: no cover - asserted through queue
                errors.put(f"reader {reader_id}: {type(exc).__name__}: {exc}")
            finally:
                if con is not None:
                    con.close()

        reader_threads = [threading.Thread(target=reader, args=(i,)) for i in range(READERS)]
        writer_threads = [threading.Thread(target=writer, args=(i,)) for i in range(WRITERS)]

        for thread in reader_threads:
            thread.start()
        for thread in writer_threads:
            thread.start()
        for thread in writer_threads:
            thread.join(timeout=20)
            assert not thread.is_alive(), "writer thread exceeded concurrency test timeout"

        stop_readers.set()
        for thread in reader_threads:
            thread.join(timeout=5)
            assert not thread.is_alive(), "reader thread exceeded concurrency test timeout"

        failures = []
        while not errors.empty():
            failures.append(errors.get())
        assert not failures, "concurrent SQLite errors: " + " | ".join(failures)

        expected = WRITERS * ROWS_PER_WRITER
        verify = tenant_security._raw()
        try:
            total = int(verify.execute("SELECT COUNT(*) FROM stress_rows").fetchone()[0])
            distinct_keys = int(
                verify.execute(
                    "SELECT COUNT(*) FROM (SELECT writer_id,sequence_no FROM stress_rows GROUP BY writer_id,sequence_no)"
                ).fetchone()[0]
            )
            integrity = str(verify.execute("PRAGMA integrity_check").fetchone()[0]).lower()
            fk_violations = verify.execute("PRAGMA foreign_key_check").fetchall()
            journal = str(verify.execute("PRAGMA journal_mode").fetchone()[0]).lower()
            timeout_ms = int(verify.execute("PRAGMA busy_timeout").fetchone()[0])
            synchronous = int(verify.execute("PRAGMA synchronous").fetchone()[0])

            assert total == expected, f"silent write loss: expected {expected}, found {total}"
            assert distinct_keys == expected, "duplicate/missing writer sequence keys detected"
            assert integrity == "ok", integrity
            assert not fk_violations, fk_violations
            assert journal == "wal", journal
            assert timeout_ms >= tenant_security.SQLITE_BUSY_TIMEOUT_MS, timeout_ms
            assert synchronous == 1, synchronous  # NORMAL
        finally:
            verify.close()

        # Persistence verification after every writer/reader connection has closed.
        reopened = sqlite3.connect(path)
        try:
            persisted = int(reopened.execute("SELECT COUNT(*) FROM stress_rows").fetchone()[0])
            assert persisted == expected, f"restart persistence mismatch: {persisted} != {expected}"
        finally:
            reopened.close()

        print(
            f"SQLite concurrency stress passed: {expected} writes, {READERS} concurrent readers, no loss/corruption"
        )
    finally:
        stop_readers.set()
        tenant_security._schema_db = None
        auth_runtime.DB_PATH = original_path
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(path + suffix)
            except OSError:
                pass


if __name__ == "__main__":
    run()
