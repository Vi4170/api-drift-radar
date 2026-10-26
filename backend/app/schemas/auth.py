import uuid
from datetime import datetime

from pydantic import EmailStr, Field

from app.schemas.common import ORMModel, StrictModel


class RegisterRequest(StrictModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)


class LoginRequest(StrictModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(ORMModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth2 token type, not a secret
    expires_in: int


class UserOut(ORMModel):
    id: uuid.UUID
    email: str
    created_at: datetime
