import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import DatabaseSession
from app.models.knowledge_base import KnowledgeBase
from app.schemas.knowledge_base import (
    KnowledgeBaseCreate,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdate,
)

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])


def find_knowledge_base(
    knowledge_base_id: uuid.UUID,
    session: Session,
) -> KnowledgeBase:
    knowledge_base = session.get(KnowledgeBase, knowledge_base_id)
    if knowledge_base is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge base not found.",
        )
    return knowledge_base


@router.post(
    "",
    response_model=KnowledgeBaseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a knowledge base",
)
def create_knowledge_base(
    payload: KnowledgeBaseCreate,
    session: DatabaseSession,
) -> KnowledgeBase:
    knowledge_base = KnowledgeBase(**payload.model_dump())
    session.add(knowledge_base)
    session.commit()
    session.refresh(knowledge_base)
    return knowledge_base


@router.get(
    "",
    response_model=list[KnowledgeBaseResponse],
    summary="List knowledge bases",
)
def list_knowledge_bases(
    session: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[KnowledgeBase]:
    statement = (
        select(KnowledgeBase)
        .order_by(KnowledgeBase.created_at, KnowledgeBase.id)
        .limit(limit)
        .offset(offset)
    )
    result = session.scalars(statement)
    return list(result)


@router.get(
    "/{knowledge_base_id}",
    response_model=KnowledgeBaseResponse,
    summary="Get a knowledge base",
)
def get_knowledge_base(
    knowledge_base_id: uuid.UUID,
    session: DatabaseSession,
) -> KnowledgeBase:
    return find_knowledge_base(knowledge_base_id, session)


@router.patch(
    "/{knowledge_base_id}",
    response_model=KnowledgeBaseResponse,
    summary="Update a knowledge base",
)
def update_knowledge_base(
    knowledge_base_id: uuid.UUID,
    payload: KnowledgeBaseUpdate,
    session: DatabaseSession,
) -> KnowledgeBase:
    knowledge_base = find_knowledge_base(knowledge_base_id, session)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(knowledge_base, field, value)

    session.commit()
    session.refresh(knowledge_base)
    return knowledge_base


@router.delete(
    "/{knowledge_base_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a knowledge base",
)
def delete_knowledge_base(
    knowledge_base_id: uuid.UUID,
    session: DatabaseSession,
) -> Response:
    knowledge_base = find_knowledge_base(knowledge_base_id, session)
    session.delete(knowledge_base)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
