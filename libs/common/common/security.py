"""JWT (RS256) issuing and verification.

auth-service signs tokens with its private key and publishes the public key as JWKS.
The gateway and every service verify tokens locally with that public key (fetched once
and cached), so a token cannot be forged even if a service port is reached directly.
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.algorithms import RSAAlgorithm

from .errors import ForbiddenError, ServiceUnavailableError, UnauthorizedError

logger = logging.getLogger("common.security")

ISSUER = "ticketing-auth"
AUDIENCE = "ticketing"
ALGORITHM = "RS256"

ROLE_USER = "user"
ROLE_ADMIN = "admin"


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    role: str
    email: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN


def encode_token(
    private_key: Any,
    kid: str,
    *,
    subject: str,
    role: str,
    email: str | None,
    token_type: str = "access",
    ttl_seconds: int = 900,
) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": subject,
        "role": role,
        "email": email,
        "type": token_type,
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(seconds=ttl_seconds),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, private_key, algorithm=ALGORITHM, headers={"kid": kid})


def public_jwk(public_key: Any, kid: str) -> dict[str, Any]:
    jwk = json.loads(RSAAlgorithm.to_jwk(public_key))
    jwk.update({"kid": kid, "use": "sig", "alg": ALGORITHM})
    return jwk


class JWTVerifier:
    def __init__(
        self,
        jwks_url: str | None = None,
        *,
        static_keys: dict[str, Any] | None = None,
        http_timeout: float = 3.0,
        refresh_cooldown: float = 10.0,
    ) -> None:
        self.jwks_url = jwks_url
        self._keys: dict[str, Any] = dict(static_keys or {})
        self._lock = asyncio.Lock()
        self._last_fetch = 0.0
        self._timeout = http_timeout
        self._cooldown = refresh_cooldown

    async def _refresh_keys(self) -> None:
        if not self.jwks_url:
            return
        async with self._lock:
            if self._keys and time.monotonic() - self._last_fetch < self._cooldown:
                return
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(self.jwks_url)
                response.raise_for_status()
            keys = {jwk["kid"]: RSAAlgorithm.from_jwk(json.dumps(jwk)) for jwk in response.json()["keys"]}
            self._keys = keys
            self._last_fetch = time.monotonic()
            logger.info("JWKS refreshed", extra={"kids": list(keys)})

    async def verify(self, token: str) -> Principal:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise UnauthorizedError("Invalid token", code="invalid_token") from exc

        kid = header.get("kid")
        if kid not in self._keys:
            try:
                await self._refresh_keys()
            except Exception as exc:  # noqa: BLE001
                logger.error("Cannot fetch JWKS from auth-service", extra={"error": repr(exc)})
                raise ServiceUnavailableError("Authentication service is unavailable") from exc
        key = self._keys.get(kid)
        if key is None:
            raise UnauthorizedError("Invalid token", code="invalid_token")

        try:
            claims = jwt.decode(token, key, algorithms=[ALGORITHM], audience=AUDIENCE, issuer=ISSUER)
        except jwt.ExpiredSignatureError as exc:
            raise UnauthorizedError("Token has expired", code="token_expired") from exc
        except jwt.PyJWTError as exc:
            raise UnauthorizedError("Invalid token", code="invalid_token") from exc

        if claims.get("type") != "access":
            raise UnauthorizedError("Invalid token type", code="invalid_token")
        try:
            user_id = uuid.UUID(str(claims["sub"]))
        except (KeyError, ValueError) as exc:
            raise UnauthorizedError("Invalid token subject", code="invalid_token") from exc
        return Principal(user_id=user_id, role=str(claims.get("role", ROLE_USER)), email=claims.get("email"))


bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token from POST /api/auth/login")


async def get_current_user(
    request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise UnauthorizedError("Missing bearer token")
    verifier: JWTVerifier = request.app.state.verifier
    principal = await verifier.verify(credentials.credentials)
    request.state.principal = principal
    return principal


def require_role(*roles: str):
    async def dependency(user: Principal = Depends(get_current_user)) -> Principal:
        if user.role not in roles:
            raise ForbiddenError(f"Requires role: {', '.join(roles)}")
        return user

    return dependency


require_admin = require_role(ROLE_ADMIN)
