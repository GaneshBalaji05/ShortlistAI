from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from sqlalchemy import and_, delete, func, insert, select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from shortlistai.db.models import Base


TENANT_TABLES = {"jobs", "candidates", "notes", "activity_log", "interviews"}
ID_TABLES = TENANT_TABLES


class RepositoryConflict(RuntimeError):
    """Raised when a database invariant would be violated by a repository operation."""


class RepositoryNotFound(RuntimeError):
    """Raised when a workspace-scoped reference cannot be resolved safely."""


def _table(table_name: str):
    try:
        return Base.metadata.tables[table_name]
    except KeyError as exc:
        raise ValueError(f"Unsupported table: {table_name}") from exc


@dataclass(frozen=True)
class AuthRepository:
    """Database-agnostic auth persistence using the SQLAlchemy schema.

    Password hashing, cookies, and email delivery stay in the auth service layer. This
    repository owns only persistence and works against both the SQLite rollback store and
    PostgreSQL.
    """

    engine: Engine

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        users = _table("users")
        normalized = str(email or "").strip().lower()
        with self.engine.connect() as connection:
            row = connection.execute(
                select(users).where(func.lower(users.c.email) == normalized)
            ).mappings().first()
            return dict(row) if row else None

    def get_user(self, user_id: int) -> dict[str, Any] | None:
        users = _table("users")
        with self.engine.connect() as connection:
            row = connection.execute(select(users).where(users.c.id == int(user_id))).mappings().first()
            return dict(row) if row else None

    def get_workspace(self, workspace_id: int) -> dict[str, Any] | None:
        workspaces = _table("workspaces")
        with self.engine.connect() as connection:
            row = connection.execute(
                select(workspaces).where(workspaces.c.id == int(workspace_id))
            ).mappings().first()
            return dict(row) if row else None

    def create_workspace_user(
        self,
        *,
        workspace_name: str,
        full_name: str,
        email: str,
        password_hash: str,
        password_salt: str,
        role: str,
        created_at: str,
        last_login_at: str | None,
    ) -> tuple[int, int]:
        workspaces = _table("workspaces")
        users = _table("users")
        try:
            with self.engine.begin() as connection:
                workspace_id = int(
                    connection.execute(
                        insert(workspaces)
                        .values(name=workspace_name, created_at=created_at)
                        .returning(workspaces.c.id)
                    ).scalar_one()
                )
                user_id = int(
                    connection.execute(
                        insert(users)
                        .values(
                            workspace_id=workspace_id,
                            full_name=full_name,
                            email=email,
                            password_hash=password_hash,
                            password_salt=password_salt,
                            role=role,
                            created_at=created_at,
                            last_login_at=last_login_at,
                        )
                        .returning(users.c.id)
                    ).scalar_one()
                )
                return workspace_id, user_id
        except IntegrityError as exc:
            raise RepositoryConflict("User or workspace insert violated a database constraint") from exc

    def update_last_login(self, user_id: int, timestamp: str) -> bool:
        users = _table("users")
        with self.engine.begin() as connection:
            result = connection.execute(
                update(users).where(users.c.id == int(user_id)).values(last_login_at=timestamp)
            )
            return result.rowcount > 0

    def create_session(
        self,
        *,
        token_hash: str,
        user_id: int,
        created_at: str,
        expires_at: str,
    ) -> None:
        sessions = _table("auth_sessions")
        with self.engine.begin() as connection:
            connection.execute(
                insert(sessions).values(
                    token_hash=token_hash,
                    user_id=int(user_id),
                    created_at=created_at,
                    expires_at=expires_at,
                )
            )

    def get_session_user(self, token_hash: str) -> dict[str, Any] | None:
        sessions = _table("auth_sessions")
        users = _table("users")
        workspaces = _table("workspaces")
        stmt = (
            select(
                sessions.c.token_hash,
                sessions.c.expires_at,
                users.c.id,
                users.c.workspace_id,
                users.c.full_name,
                users.c.email,
                users.c.password_hash,
                users.c.password_salt,
                users.c.role,
                users.c.created_at,
                users.c.last_login_at,
                workspaces.c.name.label("workspace_name"),
            )
            .select_from(
                sessions.join(users, users.c.id == sessions.c.user_id).outerjoin(
                    workspaces, workspaces.c.id == users.c.workspace_id
                )
            )
            .where(sessions.c.token_hash == token_hash)
        )
        with self.engine.connect() as connection:
            row = connection.execute(stmt).mappings().first()
            return dict(row) if row else None

    def delete_session(self, token_hash: str) -> bool:
        sessions = _table("auth_sessions")
        with self.engine.begin() as connection:
            return connection.execute(
                delete(sessions).where(sessions.c.token_hash == token_hash)
            ).rowcount > 0

    def delete_sessions_for_user(self, user_id: int) -> int:
        sessions = _table("auth_sessions")
        with self.engine.begin() as connection:
            return int(
                connection.execute(delete(sessions).where(sessions.c.user_id == int(user_id))).rowcount
                or 0
            )

    def replace_password_reset(
        self,
        *,
        user_id: int,
        token_hash: str,
        created_at: str,
        expires_at: str,
    ) -> None:
        tokens = _table("password_reset_tokens")
        with self.engine.begin() as connection:
            connection.execute(delete(tokens).where(tokens.c.user_id == int(user_id)))
            connection.execute(
                insert(tokens).values(
                    token_hash=token_hash,
                    user_id=int(user_id),
                    created_at=created_at,
                    expires_at=expires_at,
                    used_at=None,
                )
            )

    def get_password_reset(self, token_hash: str) -> dict[str, Any] | None:
        tokens = _table("password_reset_tokens")
        users = _table("users")
        stmt = (
            select(
                tokens.c.token_hash,
                tokens.c.user_id,
                tokens.c.created_at,
                tokens.c.expires_at,
                tokens.c.used_at,
                users.c.email,
            )
            .select_from(tokens.join(users, users.c.id == tokens.c.user_id))
            .where(tokens.c.token_hash == token_hash)
        )
        with self.engine.connect() as connection:
            row = connection.execute(stmt).mappings().first()
            return dict(row) if row else None

    def reset_password(
        self,
        *,
        token_hash: str,
        user_id: int,
        password_hash: str,
        password_salt: str,
        used_at: str,
    ) -> None:
        users = _table("users")
        tokens = _table("password_reset_tokens")
        sessions = _table("auth_sessions")
        with self.engine.begin() as connection:
            connection.execute(
                update(users)
                .where(users.c.id == int(user_id))
                .values(password_hash=password_hash, password_salt=password_salt)
            )
            connection.execute(
                update(tokens)
                .where(tokens.c.token_hash == token_hash)
                .values(used_at=used_at)
            )
            connection.execute(delete(sessions).where(sessions.c.user_id == int(user_id)))


@dataclass(frozen=True)
class WorkspaceRepository:
    """Explicit workspace-scoped data-access boundary for ATS persistence.

    Every tenant-owned read and mutation contains ``workspace_id`` in the query. Foreign
    references are also checked against the same workspace before a write is accepted, so
    an ID from another workspace cannot be attached accidentally even when the database FK
    itself only references the numeric primary key.
    """

    engine: Engine
    workspace_id: int

    def _tenant_table(self, table_name: str):
        if table_name not in TENANT_TABLES:
            raise ValueError(f"Unsupported tenant table: {table_name}")
        return _table(table_name)

    def _workspace_row_exists(self, connection: Connection, table_name: str, row_id: int) -> bool:
        table = self._tenant_table(table_name)
        return connection.execute(
            select(table.c.id).where(
                and_(table.c.id == int(row_id), table.c.workspace_id == int(self.workspace_id))
            )
        ).first() is not None

    def _assert_workspace_reference(
        self, connection: Connection, table_name: str, row_id: Any, label: str
    ) -> None:
        if row_id in (None, ""):
            return
        try:
            resolved = int(row_id)
        except (TypeError, ValueError) as exc:
            raise RepositoryNotFound(f"Invalid {label} reference") from exc
        if not self._workspace_row_exists(connection, table_name, resolved):
            raise RepositoryNotFound(f"{label.title()} not found in this workspace")

    def _validate_references(
        self, connection: Connection, table_name: str, payload: Mapping[str, Any]
    ) -> None:
        if table_name in {"candidates", "interviews"} and "job_id" in payload:
            self._assert_workspace_reference(connection, "jobs", payload.get("job_id"), "job")
        if table_name in {"notes", "activity_log", "interviews"} and "candidate_id" in payload:
            self._assert_workspace_reference(
                connection, "candidates", payload.get("candidate_id"), "candidate"
            )

    def list_rows(self, table_name: str, *, limit: int = 200) -> list[dict[str, Any]]:
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        table = self._tenant_table(table_name)
        with self.engine.connect() as connection:
            stmt = select(table).where(table.c.workspace_id == self.workspace_id).limit(limit)
            return [dict(row) for row in connection.execute(stmt).mappings().all()]

    def get_row(self, table_name: str, row_id: int) -> dict[str, Any] | None:
        table = self._tenant_table(table_name)
        with self.engine.connect() as connection:
            stmt = select(table).where(
                and_(table.c.id == int(row_id), table.c.workspace_id == self.workspace_id)
            )
            row = connection.execute(stmt).mappings().first()
            return dict(row) if row else None

    def create_row(self, table_name: str, values: Mapping[str, Any]) -> int:
        table = self._tenant_table(table_name)
        payload = dict(values)
        supplied_workspace = payload.get("workspace_id")
        if supplied_workspace not in (None, self.workspace_id):
            raise ValueError("Cross-workspace insert rejected")
        payload["workspace_id"] = self.workspace_id
        with self.engine.begin() as connection:
            self._validate_references(connection, table_name, payload)
            stmt = insert(table).values(**payload).returning(table.c.id)
            return int(connection.execute(stmt).scalar_one())

    def update_row(self, table_name: str, row_id: int, values: Mapping[str, Any]) -> bool:
        table = self._tenant_table(table_name)
        payload = dict(values)
        if "workspace_id" in payload and payload["workspace_id"] != self.workspace_id:
            raise ValueError("Cross-workspace update rejected")
        payload.pop("workspace_id", None)
        if not payload:
            return False
        with self.engine.begin() as connection:
            self._validate_references(connection, table_name, payload)
            stmt = (
                update(table)
                .where(and_(table.c.id == int(row_id), table.c.workspace_id == self.workspace_id))
                .values(**payload)
            )
            return connection.execute(stmt).rowcount > 0

    def delete_row(self, table_name: str, row_id: int) -> bool:
        table = self._tenant_table(table_name)
        with self.engine.begin() as connection:
            stmt = delete(table).where(
                and_(table.c.id == int(row_id), table.c.workspace_id == self.workspace_id)
            )
            return connection.execute(stmt).rowcount > 0

    def list_candidate_identities(self, candidate_id: int) -> list[dict[str, Any]]:
        identities = _table("candidate_identities")
        with self.engine.connect() as connection:
            self._assert_workspace_reference(connection, "candidates", candidate_id, "candidate")
            rows = connection.execute(
                select(identities).where(
                    and_(
                        identities.c.workspace_id == self.workspace_id,
                        identities.c.candidate_id == int(candidate_id),
                    )
                )
            ).mappings().all()
            return [dict(row) for row in rows]

    def find_candidate_by_identity(self, identity_type: str, identity_value: str) -> int | None:
        identities = _table("candidate_identities")
        with self.engine.connect() as connection:
            row = connection.execute(
                select(identities.c.candidate_id).where(
                    and_(
                        identities.c.workspace_id == self.workspace_id,
                        identities.c.identity_type == str(identity_type),
                        identities.c.identity_value == str(identity_value),
                    )
                )
            ).first()
            return int(row[0]) if row else None

    def replace_candidate_identities(
        self,
        candidate_id: int,
        identities: Iterable[tuple[str, str]],
        *,
        created_at: str,
    ) -> None:
        identity_table = _table("candidate_identities")
        cleaned = {
            (str(identity_type).strip(), str(identity_value).strip())
            for identity_type, identity_value in identities
            if str(identity_type).strip() and str(identity_value).strip()
        }
        with self.engine.begin() as connection:
            self._assert_workspace_reference(connection, "candidates", candidate_id, "candidate")
            for identity_type, identity_value in cleaned:
                owner = connection.execute(
                    select(identity_table.c.candidate_id).where(
                        and_(
                            identity_table.c.workspace_id == self.workspace_id,
                            identity_table.c.identity_type == identity_type,
                            identity_table.c.identity_value == identity_value,
                        )
                    )
                ).scalar_one_or_none()
                if owner is not None and int(owner) != int(candidate_id):
                    raise RepositoryConflict(
                        f"Candidate identity already belongs to candidate {int(owner)}"
                    )
            connection.execute(
                delete(identity_table).where(
                    and_(
                        identity_table.c.workspace_id == self.workspace_id,
                        identity_table.c.candidate_id == int(candidate_id),
                    )
                )
            )
            if cleaned:
                connection.execute(
                    insert(identity_table),
                    [
                        {
                            "workspace_id": self.workspace_id,
                            "identity_type": identity_type,
                            "identity_value": identity_value,
                            "candidate_id": int(candidate_id),
                            "created_at": created_at,
                        }
                        for identity_type, identity_value in sorted(cleaned)
                    ],
                )

    def dashboard_rows(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        jobs = _table("jobs")
        candidates = _table("candidates")
        with self.engine.connect() as connection:
            job_rows = connection.execute(
                select(
                    jobs.c.id,
                    jobs.c.title,
                    jobs.c.department,
                    jobs.c.location,
                    jobs.c.status,
                    jobs.c.created_at,
                )
                .where(jobs.c.workspace_id == self.workspace_id)
                .order_by(jobs.c.id.desc())
            ).mappings().all()
            candidate_rows = connection.execute(
                select(
                    candidates.c.id,
                    candidates.c.name,
                    candidates.c.email,
                    candidates.c.job_id,
                    candidates.c.stage,
                    candidates.c.ai_score,
                    candidates.c.rating,
                    candidates.c.source,
                    candidates.c.profile_details,
                    candidates.c.created_at,
                    candidates.c.updated_at,
                    jobs.c.title.label("job_title"),
                )
                .select_from(
                    candidates.outerjoin(
                        jobs,
                        and_(
                            jobs.c.id == candidates.c.job_id,
                            jobs.c.workspace_id == self.workspace_id,
                        ),
                    )
                )
                .where(candidates.c.workspace_id == self.workspace_id)
                .order_by(candidates.c.updated_at.desc(), candidates.c.id.desc())
            ).mappings().all()
            return [dict(row) for row in job_rows], [dict(row) for row in candidate_rows]

    def list_interviews(
        self,
        *,
        candidate_id: int | None = None,
        job_id: int | None = None,
        status: str = "",
    ) -> list[dict[str, Any]]:
        interviews = _table("interviews")
        candidates = _table("candidates")
        jobs = _table("jobs")
        stmt = (
            select(
                interviews,
                candidates.c.name.label("candidate_name"),
                candidates.c.email.label("candidate_email"),
                jobs.c.title.label("job_title"),
            )
            .select_from(
                interviews.join(
                    candidates,
                    and_(
                        candidates.c.id == interviews.c.candidate_id,
                        candidates.c.workspace_id == self.workspace_id,
                    ),
                ).outerjoin(
                    jobs,
                    and_(jobs.c.id == interviews.c.job_id, jobs.c.workspace_id == self.workspace_id),
                )
            )
            .where(interviews.c.workspace_id == self.workspace_id)
        )
        if candidate_id is not None:
            stmt = stmt.where(interviews.c.candidate_id == int(candidate_id))
        if job_id is not None:
            stmt = stmt.where(interviews.c.job_id == int(job_id))
        if str(status or "").strip():
            stmt = stmt.where(interviews.c.status == str(status).strip())
        stmt = stmt.order_by(interviews.c.scheduled_at.asc(), interviews.c.id.desc())
        with self.engine.connect() as connection:
            return [dict(row) for row in connection.execute(stmt).mappings().all()]

    def get_interview(self, interview_id: int) -> dict[str, Any] | None:
        rows = self.list_interviews()
        for row in rows:
            if int(row["id"]) == int(interview_id):
                return row
        return None
