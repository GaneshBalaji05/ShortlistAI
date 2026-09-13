from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from sqlalchemy import MetaData, Table, and_, delete, func, insert, select, update
from sqlalchemy.engine import Connection, Engine


TENANT_TABLES = {"jobs", "candidates", "notes", "activity_log", "interviews"}


@dataclass(frozen=True)
class WorkspaceRepository:
    """Small explicit repository boundary for new PostgreSQL-capable backend work.

    Existing runtime routes are not switched to this repository yet. New/migrated routes
    should use this boundary instead of regex SQL rewriting so workspace ownership is always
    visible in the query itself.
    """

    engine: Engine
    workspace_id: int

    def _table(self, connection: Connection, table_name: str) -> Table:
        if table_name not in TENANT_TABLES:
            raise ValueError(f"Unsupported tenant table: {table_name}")
        metadata = MetaData()
        return Table(table_name, metadata, autoload_with=connection)

    def list_rows(
        self,
        table_name: str,
        *,
        limit: int = 200,
        offset: int = 0,
        newest_first: bool = True,
    ) -> list[dict[str, Any]]:
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        if offset < 0:
            raise ValueError("offset must be zero or greater")
        with self.engine.connect() as connection:
            table = self._table(connection, table_name)
            stmt = select(table).where(table.c.workspace_id == self.workspace_id)
            if "id" in table.c:
                stmt = stmt.order_by(table.c.id.desc() if newest_first else table.c.id.asc())
            stmt = stmt.offset(offset).limit(limit)
            return [dict(row) for row in connection.execute(stmt).mappings().all()]

    def count_rows(self, table_name: str) -> int:
        with self.engine.connect() as connection:
            table = self._table(connection, table_name)
            stmt = select(func.count()).select_from(table).where(table.c.workspace_id == self.workspace_id)
            return int(connection.execute(stmt).scalar_one())

    def get_row(self, table_name: str, row_id: int) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            table = self._table(connection, table_name)
            stmt = select(table).where(
                and_(table.c.id == row_id, table.c.workspace_id == self.workspace_id)
            )
            row = connection.execute(stmt).mappings().first()
            return dict(row) if row else None

    def create_row(self, table_name: str, values: Mapping[str, Any]) -> int:
        payload = dict(values)
        supplied_workspace = payload.get("workspace_id")
        if supplied_workspace not in (None, self.workspace_id):
            raise ValueError("Cross-workspace insert rejected")
        payload["workspace_id"] = self.workspace_id
        with self.engine.begin() as connection:
            table = self._table(connection, table_name)
            stmt = insert(table).values(**payload).returning(table.c.id)
            return int(connection.execute(stmt).scalar_one())

    def update_row(self, table_name: str, row_id: int, values: Mapping[str, Any]) -> bool:
        payload = dict(values)
        if "workspace_id" in payload and payload["workspace_id"] != self.workspace_id:
            raise ValueError("Cross-workspace update rejected")
        payload.pop("workspace_id", None)
        if not payload:
            return False
        with self.engine.begin() as connection:
            table = self._table(connection, table_name)
            stmt = (
                update(table)
                .where(and_(table.c.id == row_id, table.c.workspace_id == self.workspace_id))
                .values(**payload)
            )
            return connection.execute(stmt).rowcount > 0

    def delete_row(self, table_name: str, row_id: int) -> bool:
        with self.engine.begin() as connection:
            table = self._table(connection, table_name)
            stmt = delete(table).where(
                and_(table.c.id == row_id, table.c.workspace_id == self.workspace_id)
            )
            return connection.execute(stmt).rowcount > 0
