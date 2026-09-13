from pathlib import Path


def main() -> None:
    text = Path("POSTGRES_MIGRATION_RUNBOOK.md").read_text(encoding="utf-8")
    required = [
        "production remains on SQLite",
        "alembic upgrade head",
        "--apply",
        "Rollback",
        "workspace_id",
        "DATABASE_URL",
    ]
    lowered = text.lower()
    for phrase in required:
        assert phrase.lower() in lowered, f"Migration runbook missing safety instruction: {phrase}"
    print("PostgreSQL migration runbook safety contract OK")


if __name__ == "__main__":
    main()
