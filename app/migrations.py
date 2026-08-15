from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import Connection, Engine, inspect, text

from app.services.platforms import platform_for_url


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    apply: Callable[[Connection], None]


def _table_names(connection: Connection) -> set[str]:
    return set(inspect(connection).get_table_names())


def _column_names(connection: Connection, table_name: str) -> set[str]:
    if table_name not in _table_names(connection):
        return set()
    return {
        column["name"] for column in inspect(connection).get_columns(table_name)
    }


def _add_missing_column(
    connection: Connection,
    table_name: str,
    column_name: str,
    definition: str,
) -> None:
    if column_name in _column_names(connection, table_name):
        return
    connection.execute(
        text(f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" {definition}')
    )


def migration_001_bookmark_baseline(connection: Connection) -> None:
    """Bring pre-versioned Bookmark tables up to the current baseline."""
    if "bookmark" not in _table_names(connection):
        return

    _add_missing_column(
        connection, "bookmark", "markdown_content", "TEXT NOT NULL DEFAULT ''"
    )
    _add_missing_column(
        connection,
        "bookmark",
        "status",
        "VARCHAR(30) NOT NULL DEFAULT 'success'",
    )
    _add_missing_column(
        connection, "bookmark", "error_message", "VARCHAR(1000) NULL"
    )
    _add_missing_column(connection, "bookmark", "notes", "TEXT NOT NULL DEFAULT ''")
    _add_missing_column(
        connection,
        "bookmark",
        "platform",
        "VARCHAR(50) NOT NULL DEFAULT '其他'",
    )
    _add_missing_column(
        connection,
        "bookmark",
        "created_at",
        "TIMESTAMP NOT NULL DEFAULT '1970-01-01 00:00:00'",
    )
    _add_missing_column(
        connection,
        "bookmark",
        "updated_at",
        "TIMESTAMP NOT NULL DEFAULT '1970-01-01 00:00:00'",
    )
    _add_missing_column(connection, "bookmark", "deleted_at", "TIMESTAMP NULL")
    _add_missing_column(
        connection,
        "bookmark",
        "is_draft",
        "BOOLEAN NOT NULL DEFAULT FALSE",
    )

    now = datetime.now(timezone.utc)
    connection.execute(
        text(
            "UPDATE bookmark SET created_at = :now "
            "WHERE created_at IS NULL OR created_at = '1970-01-01 00:00:00'"
        ),
        {"now": now},
    )
    connection.execute(
        text(
            "UPDATE bookmark SET updated_at = :now "
            "WHERE updated_at IS NULL OR updated_at = '1970-01-01 00:00:00'"
        ),
        {"now": now},
    )


def migration_002_platform_backfill_and_indexes(connection: Connection) -> None:
    """Backfill source platforms and ensure indexes missing from old databases."""
    if "bookmark" not in _table_names(connection):
        return

    columns = _column_names(connection, "bookmark")
    if {"id", "url", "platform"}.issubset(columns):
        rows = connection.execute(
            text(
                "SELECT id, url, platform FROM bookmark "
                "WHERE platform IS NULL OR platform = '' OR platform = '其他'"
            )
        ).mappings()
        for row in rows:
            connection.execute(
                text("UPDATE bookmark SET platform = :platform WHERE id = :id"),
                {"platform": platform_for_url(row["url"]), "id": row["id"]},
            )

    index_columns = {
        "ix_bookmark_url": "url",
        "ix_bookmark_title": "title",
        "ix_bookmark_status": "status",
        "ix_bookmark_platform": "platform",
        "ix_bookmark_deleted_at": "deleted_at",
        "ix_bookmark_is_draft": "is_draft",
    }
    columns = _column_names(connection, "bookmark")
    for index_name, column_name in index_columns.items():
        if column_name in columns:
            connection.execute(
                text(
                    f'CREATE INDEX IF NOT EXISTS "{index_name}" '
                    f'ON "bookmark" ("{column_name}")'
                )
            )


def migration_003_extension_credential(connection: Connection) -> None:
    """Create the single-user extension credential store."""
    from app.models import ExtensionCredential

    ExtensionCredential.__table__.create(bind=connection, checkfirst=True)


def migration_004_browser_capture_fields(connection: Connection) -> None:
    """Record whether content came from the server or the browser."""
    if "bookmark" not in _table_names(connection):
        return
    _add_missing_column(
        connection,
        "bookmark",
        "capture_method",
        "VARCHAR(20) NOT NULL DEFAULT 'server'",
    )
    connection.execute(
        text(
            "UPDATE bookmark SET capture_method = 'server' "
            "WHERE capture_method IS NULL OR capture_method = ''"
        )
    )
    connection.execute(
        text(
            'CREATE INDEX IF NOT EXISTS "ix_bookmark_capture_method" '
            'ON "bookmark" ("capture_method")'
        )
    )


MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "bookmark_baseline", migration_001_bookmark_baseline),
    Migration(
        2,
        "platform_backfill_and_indexes",
        migration_002_platform_backfill_and_indexes,
    ),
    Migration(3, "extension_credential", migration_003_extension_credential),
    Migration(4, "browser_capture_fields", migration_004_browser_capture_fields),
)

LATEST_SCHEMA_VERSION = MIGRATIONS[-1].version


def _ensure_migration_table(connection: Connection) -> None:
    connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, "
            "name VARCHAR(255) NOT NULL, "
            "applied_at TIMESTAMP NOT NULL"
            ")"
        )
    )


def applied_versions(engine: Engine) -> list[int]:
    with engine.begin() as connection:
        _ensure_migration_table(connection)
        return list(
            connection.execute(
                text("SELECT version FROM schema_migrations ORDER BY version")
            ).scalars()
        )


def run_migrations(engine: Engine) -> int:
    """Run each pending migration atomically and return the current version."""
    with engine.begin() as connection:
        _ensure_migration_table(connection)

    for migration in MIGRATIONS:
        with engine.begin() as connection:
            already_applied = connection.execute(
                text(
                    "SELECT 1 FROM schema_migrations WHERE version = :version"
                ),
                {"version": migration.version},
            ).first()
            if already_applied:
                continue
            migration.apply(connection)
            connection.execute(
                text(
                    "INSERT INTO schema_migrations (version, name, applied_at) "
                    "VALUES (:version, :name, :applied_at)"
                ),
                {
                    "version": migration.version,
                    "name": migration.name,
                    "applied_at": datetime.now(timezone.utc),
                },
            )

    versions = applied_versions(engine)
    return versions[-1] if versions else 0
