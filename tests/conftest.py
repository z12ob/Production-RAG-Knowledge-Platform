import os
import secrets
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from pydantic import PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from alembic import command

PROJECT_ROOT = Path(__file__).parents[1]


class DatabaseTestSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="RAG_", extra="ignore")

    test_database_url: PostgresDsn = PostgresDsn(
        "postgresql+psycopg://rag_app:change-me@localhost:5432/rag_platform_test"
    )


TEST_DATABASE_URL = DatabaseTestSettings.model_validate({}).test_database_url.unicode_string()
TEST_UPLOAD_DIRECTORY = tempfile.TemporaryDirectory(prefix="rag-platform-tests-")
TEST_UPLOAD_ROOT = Path(TEST_UPLOAD_DIRECTORY.name)

database_name = make_url(TEST_DATABASE_URL).database
if database_name is None or not database_name.endswith("_test"):
    raise RuntimeError("RAG_TEST_DATABASE_URL must identify a database ending in '_test'.")

os.environ["RAG_DATABASE_URL"] = TEST_DATABASE_URL
os.environ["RAG_ENVIRONMENT"] = "test"
os.environ["RAG_JWT_SECRET"] = secrets.token_urlsafe(48)
os.environ["RAG_ACCESS_TOKEN_EXPIRE_MINUTES"] = "15"
os.environ["RAG_UPLOAD_DIR"] = str(TEST_UPLOAD_ROOT)
os.environ["RAG_MAX_UPLOAD_BYTES"] = "1024"

test_engine = create_engine(TEST_DATABASE_URL)


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Iterator[None]:
    alembic_config = Config(PROJECT_ROOT / "alembic.ini")
    command.upgrade(alembic_config, "head")
    yield
    test_engine.dispose()
    TEST_UPLOAD_DIRECTORY.cleanup()


@pytest.fixture(autouse=True)
def clean_database(migrated_database: None) -> None:
    with test_engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE documents, knowledge_bases, users CASCADE"))
    shutil.rmtree(TEST_UPLOAD_ROOT, ignore_errors=True)
    TEST_UPLOAD_ROOT.mkdir(parents=True)
