import os
import secrets
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlparse

import pytest
from alembic.config import Config
from pydantic import PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict
from redis import Redis
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from alembic import command

PROJECT_ROOT = Path(__file__).parents[1]


class DatabaseTestSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="RAG_", extra="ignore")

    test_database_url: PostgresDsn = PostgresDsn(
        "postgresql+psycopg://rag_app:change-me@localhost:5432/rag_platform_test"
    )
    redis_url: RedisDsn
    test_redis_url: RedisDsn


test_settings = DatabaseTestSettings.model_validate({})
TEST_DATABASE_URL = test_settings.test_database_url.unicode_string()
DEVELOPMENT_REDIS_URL = test_settings.redis_url.unicode_string()
TEST_REDIS_URL = test_settings.test_redis_url.unicode_string()
TEST_UPLOAD_DIRECTORY = tempfile.TemporaryDirectory(prefix="rag-platform-tests-")
TEST_UPLOAD_ROOT = Path(TEST_UPLOAD_DIRECTORY.name)

database_name = make_url(TEST_DATABASE_URL).database
if database_name is None or not database_name.endswith("_test"):
    raise RuntimeError("RAG_TEST_DATABASE_URL must identify a database ending in '_test'.")

test_redis_database = urlparse(TEST_REDIS_URL).path.lstrip("/")
if TEST_REDIS_URL == DEVELOPMENT_REDIS_URL or not test_redis_database.isdigit():
    raise RuntimeError("RAG_TEST_REDIS_URL must use a separate logical Redis database.")
if int(test_redis_database) == 0:
    raise RuntimeError("RAG_TEST_REDIS_URL must not use Redis database 0.")

os.environ["RAG_DATABASE_URL"] = TEST_DATABASE_URL
os.environ["RAG_ENVIRONMENT"] = "test"
os.environ["RAG_JWT_SECRET"] = secrets.token_urlsafe(48)
os.environ["RAG_ACCESS_TOKEN_EXPIRE_MINUTES"] = "15"
os.environ["RAG_UPLOAD_DIR"] = str(TEST_UPLOAD_ROOT)
os.environ["RAG_MAX_UPLOAD_BYTES"] = "1024"
os.environ["RAG_REDIS_URL"] = TEST_REDIS_URL

test_engine = create_engine(TEST_DATABASE_URL)
test_redis = Redis.from_url(TEST_REDIS_URL)


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Iterator[None]:
    if test_redis.ping() is not True:
        raise RuntimeError("The Redis-compatible test broker did not respond to PING.")
    test_redis.flushdb()
    alembic_config = Config(PROJECT_ROOT / "alembic.ini")
    command.upgrade(alembic_config, "head")
    yield
    test_engine.dispose()
    test_redis.flushdb()
    test_redis.close()
    TEST_UPLOAD_DIRECTORY.cleanup()


@pytest.fixture(autouse=True)
def clean_database(migrated_database: None) -> None:
    with test_engine.begin() as connection:
        connection.execute(
            text("TRUNCATE TABLE ingestion_jobs, documents, knowledge_bases, users CASCADE")
        )
    test_redis.flushdb()
    shutil.rmtree(TEST_UPLOAD_ROOT, ignore_errors=True)
    TEST_UPLOAD_ROOT.mkdir(parents=True)
