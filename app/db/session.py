import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

engine = create_engine(
    settings.database_url.unicode_string(),
    connect_args={"connect_timeout": settings.database_connect_timeout_seconds},
    pool_pre_ping=True,
)
session_factory = sessionmaker(engine, expire_on_commit=False)


def get_db_session() -> Iterator[Session]:
    with session_factory() as session:
        try:
            yield session
        except IntegrityError as error:
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The requested change conflicts with a database constraint.",
            ) from error
        except SQLAlchemyError as error:
            session.rollback()
            logger.exception("Database operation failed")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The database is temporarily unavailable.",
            ) from error
        except Exception:
            session.rollback()
            raise


DatabaseSession = Annotated[Session, Depends(get_db_session)]


@contextmanager
def worker_session_scope() -> Iterator[Session]:
    with session_factory() as session:
        try:
            yield session
        except Exception:
            session.rollback()
            raise
