import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, JsonValue, SecretStr

RegistrationPassword = Annotated[SecretStr, Field(min_length=12, max_length=128)]
LoginPassword = Annotated[SecretStr, Field(min_length=1, max_length=128)]
AUTH_EXAMPLE: dict[str, JsonValue] = {
    "email": "swagger.user@example.com",
    "password": "a-long-local-demo-password",
}


class UserRegister(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [AUTH_EXAMPLE]},
    )

    email: EmailStr
    password: RegistrationPassword


class UserLogin(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [AUTH_EXAMPLE]},
    )

    email: EmailStr
    password: LoginPassword


class UserResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: uuid.UUID
    email: str
    created_at: datetime


class TokenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
