from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import CurrentUser
from app.core.config import get_settings
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import DatabaseSession
from app.models.user import User
from app.schemas.auth import TokenResponse, UserLogin, UserRegister, UserResponse

router = APIRouter(prefix="/auth", tags=["authentication"])
settings = get_settings()


def normalized_email(email: str) -> str:
    return email.strip().lower()


def invalid_credentials_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid email or password.",
        headers={"WWW-Authenticate": "Bearer"},
    )


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a user",
)
def register_user(payload: UserRegister, session: DatabaseSession) -> User:
    user = User(
        email=normalized_email(str(payload.email)),
        password_hash=hash_password(payload.password.get_secret_value()),
    )
    session.add(user)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Unable to register with these credentials.",
        ) from error

    session.refresh(user)
    return user


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Log in",
)
def login_user(payload: UserLogin, session: DatabaseSession) -> TokenResponse:
    password = payload.password.get_secret_value()
    statement = select(User).where(User.email == normalized_email(str(payload.email)))
    user = session.scalar(statement)

    if user is None:
        hash_password(password)
        raise invalid_credentials_error()
    if not verify_password(password, user.password_hash):
        raise invalid_credentials_error()

    return TokenResponse(
        access_token=create_access_token(user.id),
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get the authenticated user",
)
def get_authenticated_user(current_user: CurrentUser) -> User:
    return current_user
