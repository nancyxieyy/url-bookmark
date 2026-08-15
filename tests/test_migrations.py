import pytest
from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable
from sqlmodel import create_engine

import app.database as database_module
import app.migrations as migrations_module
from app.migrations import Migration, applied_versions, run_migrations
from app.models import ExtensionCredential


def sqlite_engine(tmp_path, name: str):
    return create_engine(f"sqlite:///{tmp_path / name}")


def test_empty_database_initializes_to_latest_schema(tmp_path, monkeypatch):
    engine = sqlite_engine(tmp_path, "empty.db")
    monkeypatch.setattr(database_module, "engine", engine)

    database_module.create_db_and_tables()

    tables = set(inspect(engine).get_table_names())
    assert {
        "bookmark",
        "tag",
        "bookmarktaglink",
        "extension_credential",
        "schema_migrations",
    }.issubset(tables)
    assert applied_versions(engine) == [1, 2, 3, 4]


def test_partial_legacy_database_upgrades_without_losing_rows(tmp_path, monkeypatch):
    engine = sqlite_engine(tmp_path, "legacy.db")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE bookmark ("
                "id INTEGER PRIMARY KEY, "
                "url VARCHAR(2048) NOT NULL, "
                "title VARCHAR(500) NOT NULL, "
                "markdown_content TEXT NOT NULL DEFAULT '', "
                "status VARCHAR(30) NOT NULL DEFAULT 'success'"
                ")"
            )
        )
        connection.execute(
            text(
                "INSERT INTO bookmark (id, url, title, markdown_content, status) "
                "VALUES (7, 'https://www.zhihu.com/question/7', 'Legacy item', '# old', 'success')"
            )
        )
    monkeypatch.setattr(database_module, "engine", engine)

    database_module.create_db_and_tables()

    columns = {item["name"] for item in inspect(engine).get_columns("bookmark")}
    assert {
        "notes",
        "platform",
        "created_at",
        "updated_at",
        "deleted_at",
        "is_draft",
        "capture_method",
    }.issubset(columns)
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT title, markdown_content, platform, created_at, capture_method "
                "FROM bookmark WHERE id = 7"
            )
        ).mappings().one()
    assert row["title"] == "Legacy item"
    assert row["markdown_content"] == "# old"
    assert row["platform"] == "知乎"
    assert row["created_at"] is not None
    assert row["capture_method"] == "server"
    assert applied_versions(engine) == [1, 2, 3, 4]


def test_migrations_are_idempotent(tmp_path, monkeypatch):
    engine = sqlite_engine(tmp_path, "idempotent.db")
    monkeypatch.setattr(database_module, "engine", engine)
    database_module.create_db_and_tables()

    first = applied_versions(engine)
    database_module.create_db_and_tables()

    assert first == [1, 2, 3, 4]
    assert applied_versions(engine) == first


def test_failed_migration_does_not_advance_version(tmp_path, monkeypatch):
    engine = sqlite_engine(tmp_path, "failure.db")

    def first(connection):
        connection.execute(text("CREATE TABLE migration_probe (id INTEGER PRIMARY KEY)"))

    def failing(connection):
        connection.execute(text("INSERT INTO migration_probe (id) VALUES (1)"))
        raise RuntimeError("intentional migration failure")

    monkeypatch.setattr(
        migrations_module,
        "MIGRATIONS",
        (
            Migration(1, "first", first),
            Migration(2, "failing", failing),
        ),
    )

    with pytest.raises(RuntimeError, match="intentional migration failure"):
        run_migrations(engine)

    assert applied_versions(engine) == [1]
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM migration_probe")).scalar_one() == 0


def test_new_migration_table_compiles_for_postgresql():
    ddl = str(
        CreateTable(ExtensionCredential.__table__).compile(
            dialect=postgresql.dialect()
        )
    )

    assert "extension_credential" in ddl
    assert "token_hash" in ddl
    assert "TIMESTAMP" in ddl
