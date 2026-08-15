import os
from pathlib import Path

from sqlalchemy import URL
from sqlmodel import Session, SQLModel, create_engine


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)


def normalize_database_url(database_url: str) -> str:
    """Use psycopg 3 for standard Postgres URLs supplied by hosting providers."""
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def get_database_url() -> str | URL:
    """Build a safe Postgres URL when the password is supplied separately."""
    supabase_password = os.getenv("SUPABASE_DB_PASSWORD")
    supabase_host = os.getenv("SUPABASE_DB_HOST")
    supabase_user = os.getenv("SUPABASE_DB_USER")

    if supabase_password and supabase_host and supabase_user:
        return URL.create(
            "postgresql+psycopg",
            username=supabase_user,
            password=supabase_password,
            host=supabase_host,
            port=int(os.getenv("SUPABASE_DB_PORT", "5432")),
            database=os.getenv("SUPABASE_DB_NAME", "postgres"),
            query={"sslmode": "require"},
        )

    return normalize_database_url(
        os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'bookmarks.db'}")
    )


DATABASE_URL = get_database_url()
engine_options: dict = {"pool_pre_ping": True}
if isinstance(DATABASE_URL, str) and DATABASE_URL.startswith("sqlite:"):
    engine_options["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **engine_options)


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
