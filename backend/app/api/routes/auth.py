from fastapi import APIRouter, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import AppSettings, CurrentUser, DbSession
from app.core.errors import AuthenticationError, ConflictError
from app.models import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserOut
from app.security.auth import create_access_token, hash_password, verify_password
from app.security.rate_limit import RateLimiter
from app.services.endpoint_service import record_audit

router = APIRouter(prefix="/auth", tags=["auth"])


def _limit(request: Request, key: str) -> None:
    limiter: RateLimiter = request.app.state.auth_limiter
    limiter.hit(f"{key}:{request.client.host if request.client else '?'}")


def _token(user: User, settings: AppSettings) -> TokenResponse:
    token = create_access_token(
        user.id, settings.jwt_secret, settings.jwt_algorithm, settings.access_token_expire_minutes
    )
    return TokenResponse(access_token=token, expires_in=settings.access_token_expire_minutes * 60)


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest, request: Request, db: DbSession, settings: AppSettings
) -> TokenResponse:
    """Create an account and return an access token."""
    _limit(request, "register")
    email = payload.email.lower()
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise ConflictError("An account with this email already exists")
    user = User(email=email, password_hash=hash_password(payload.password))
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:  # concurrent registration with the same email
        db.rollback()
        raise ConflictError("An account with this email already exists") from exc
    record_audit(db, user.id, "user.registered")
    db.commit()
    return _token(user, settings)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: DbSession, settings: AppSettings) -> TokenResponse:
    """Exchange email + password for a JWT access token."""
    email = payload.email.lower()
    _limit(request, f"login:{email}")
    user = db.scalar(select(User).where(User.email == email))
    if not verify_password(payload.password, user.password_hash if user else None) or user is None:
        raise AuthenticationError("Invalid email or password")
    return _token(user, settings)


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> User:
    return user
