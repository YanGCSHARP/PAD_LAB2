import uuid

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from common.db import get_session
from common.errors import AUTH_RESPONSES, PUBLIC_RESPONSES, ErrorResponse
from common.security import Principal, get_current_user, require_admin

from .schemas import JWKS, LoginRequest, RefreshRequest, RegisterRequest, RoleUpdate, TokenResponse, UserOut
from .service import AuthService

router = APIRouter(prefix="/api/auth", tags=["auth"])


def get_service(request: Request, session: AsyncSession = Depends(get_session)) -> AuthService:
    return AuthService(session, request.app.state.settings, request.app.state.signer)


@router.post(
    "/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    responses={**PUBLIC_RESPONSES, 409: {"model": ErrorResponse, "description": "Email already registered"}},
)
async def register(data: RegisterRequest, service: AuthService = Depends(get_service)) -> UserOut:
    return UserOut.model_validate(await service.register(data))


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Exchange email/password for an access + refresh token pair",
    responses={**PUBLIC_RESPONSES, 401: {"model": ErrorResponse}},
)
async def login(data: LoginRequest, service: AuthService = Depends(get_service)) -> TokenResponse:
    return await service.login(data.email, data.password)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Rotate a refresh token and get a new token pair",
    responses={**PUBLIC_RESPONSES, 401: {"model": ErrorResponse}},
)
async def refresh(data: RefreshRequest, service: AuthService = Depends(get_service)) -> TokenResponse:
    return await service.refresh(data.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Revoke a refresh token", responses=PUBLIC_RESPONSES)
async def logout(data: RefreshRequest, service: AuthService = Depends(get_service)) -> Response:
    await service.logout(data.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserOut, summary="Current user account", responses=AUTH_RESPONSES)
async def me(user: Principal = Depends(get_current_user), service: AuthService = Depends(get_service)) -> UserOut:
    return UserOut.model_validate(await service.get_user(user.user_id))


@router.patch(
    "/users/{user_id}/role",
    response_model=UserOut,
    summary="Change user role (admin only)",
    responses={**AUTH_RESPONSES, 404: {"model": ErrorResponse}},
)
async def change_role(
    user_id: uuid.UUID,
    data: RoleUpdate,
    _: Principal = Depends(require_admin),
    service: AuthService = Depends(get_service),
) -> UserOut:
    return UserOut.model_validate(await service.change_role(user_id, data.role))


@router.get("/.well-known/jwks.json", response_model=JWKS, summary="Public keys for verifying access tokens (JWKS)")
async def jwks(request: Request) -> dict:
    return request.app.state.signer.jwks()
