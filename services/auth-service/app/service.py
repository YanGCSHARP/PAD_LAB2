import logging
import secrets
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from common.db import Database, ensure_aware, utcnow
from common.errors import ConflictError, ForbiddenError, NotFoundError, UnauthorizedError
from common.outbox import add_outbox_event

from .config import Settings
from .crypto import TokenSigner, hash_password, hash_token, verify_password
from .models import OutboxEvent, RefreshToken, User
from .schemas import RegisterRequest, TokenResponse

logger = logging.getLogger(__name__)


def user_event(user: User) -> dict:
    return {"user_id": str(user.id), "email": user.email, "full_name": user.full_name, "role": user.role}


class AuthService:
    def __init__(self, session: AsyncSession, settings: Settings, signer: TokenSigner) -> None:
        self.session = session
        self.settings = settings
        self.signer = signer

    async def register(self, data: RegisterRequest, role: str = "user") -> User:
        email = data.email.lower()
        if await self.session.scalar(select(User.id).where(User.email == email)):
            raise ConflictError("User with this email already exists", code="email_taken")

        password_hash = await run_in_threadpool(hash_password, data.password, self.settings.bcrypt_rounds)
        user = User(id=uuid.uuid4(), email=email, full_name=data.full_name, password_hash=password_hash, role=role,
                    is_active=True, created_at=utcnow())
        self.session.add(user)
        # The event is stored in the same transaction as the user (transactional outbox).
        add_outbox_event(self.session, OutboxEvent, "user.registered", user_event(user))
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError("User with this email already exists", code="email_taken") from exc
        logger.info("User registered", extra={"user_id": str(user.id), "role": role})
        return user

    async def login(self, email: str, password: str) -> TokenResponse:
        user = await self.session.scalar(select(User).where(User.email == email.strip().lower()))
        valid = user is not None and await run_in_threadpool(verify_password, password, user.password_hash)
        if not valid:
            logger.info("Failed login attempt")
            raise UnauthorizedError("Invalid email or password", code="invalid_credentials")
        assert user is not None
        if not user.is_active:
            raise ForbiddenError("Account is disabled", code="account_disabled")
        logger.info("User logged in", extra={"user_id": str(user.id)})
        return await self._issue_tokens(user)

    async def refresh(self, raw_token: str) -> TokenResponse:
        stored = await self.session.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_token)).with_for_update()
        )
        if stored is None or stored.revoked_at is not None or ensure_aware(stored.expires_at) <= utcnow():
            raise UnauthorizedError("Refresh token is invalid or expired", code="invalid_refresh_token")
        stored.revoked_at = utcnow()  # rotation: every refresh token is single-use
        user = await self.session.get(User, stored.user_id)
        if user is None or not user.is_active:
            raise UnauthorizedError("User is not active", code="invalid_refresh_token")
        return await self._issue_tokens(user)

    async def logout(self, raw_token: str) -> None:
        stored = await self.session.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_token)))
        if stored is not None and stored.revoked_at is None:
            stored.revoked_at = utcnow()
            await self.session.commit()

    async def get_user(self, user_id: uuid.UUID) -> User:
        user = await self.session.get(User, user_id)
        if user is None:
            raise NotFoundError("User not found")
        return user

    async def change_role(self, user_id: uuid.UUID, role: str) -> User:
        user = await self.get_user(user_id)
        if user.role != role:
            user.role = role
            add_outbox_event(self.session, OutboxEvent, "user.role_changed", user_event(user))
            await self.session.commit()
            logger.info("User role changed", extra={"user_id": str(user.id), "role": role})
        return user

    async def _issue_tokens(self, user: User) -> TokenResponse:
        access = self.signer.access_token(
            user_id=str(user.id), role=user.role, email=user.email, ttl_seconds=self.settings.access_token_ttl_seconds
        )
        raw_refresh = secrets.token_urlsafe(48)
        self.session.add(
            RefreshToken(
                id=uuid.uuid4(),
                user_id=user.id,
                token_hash=hash_token(raw_refresh),
                expires_at=utcnow() + timedelta(seconds=self.settings.refresh_token_ttl_seconds),
                created_at=utcnow(),
            )
        )
        await self.session.commit()
        return TokenResponse(access_token=access, refresh_token=raw_refresh, expires_in=self.settings.access_token_ttl_seconds)


async def ensure_admin(db: Database, settings: Settings, signer: TokenSigner) -> None:
    if settings.admin_password is None:
        return
    async with db.sessionmaker() as session:
        if await session.scalar(select(User.id).where(User.email == settings.admin_email.lower())):
            return
        # model_construct skips the password-strength validator: the admin password comes from trusted config.
        data = RegisterRequest.model_construct(
            email=settings.admin_email, password=settings.admin_password.get_secret_value(), full_name=settings.admin_full_name
        )
        try:
            await AuthService(session, settings, signer).register(data, role="admin")
            logger.info("Bootstrap admin created", extra={"email": settings.admin_email})
        except ConflictError:
            pass
