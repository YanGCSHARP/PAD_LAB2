"""Routing table and coarse-grained access policy of the gateway.

Fine-grained authorization (e.g. "a user may only read his own booking") is enforced by the
services themselves; the gateway rejects obviously unauthorized requests early.
"""

from fnmatch import fnmatchcase

from common.errors import ForbiddenError
from common.security import Principal

# path prefix -> upstream name
ROUTES: list[tuple[str, str]] = [
    ("/api/auth", "auth"),
    ("/api/users", "user"),
    ("/api/venues", "catalog"),
    ("/api/events", "catalog"),
    ("/api/bookings", "booking"),
    ("/api/payments", "payment"),
    ("/api/notifications", "notification"),
]

WRITE = {"POST", "PUT", "PATCH", "DELETE"}

PUBLIC_ROUTES: list[tuple[set[str], str]] = [
    ({"POST"}, "/api/auth/register"),
    ({"POST"}, "/api/auth/login"),
    ({"POST"}, "/api/auth/refresh"),
    ({"POST"}, "/api/auth/logout"),
    ({"GET"}, "/api/auth/.well-known/jwks.json"),
    ({"GET"}, "/api/events"),
    ({"GET"}, "/api/events/*"),
    ({"GET"}, "/api/venues"),
    ({"GET"}, "/api/venues/*"),
]

ADMIN_ROUTES: list[tuple[set[str], str]] = [
    (WRITE, "/api/events"),
    (WRITE, "/api/events/*"),
    (WRITE, "/api/venues"),
    (WRITE, "/api/venues/*"),
    ({"GET"}, "/api/users"),
    ({"PATCH"}, "/api/auth/users/*"),
]

LOGIN_PATHS = {"/api/auth/login", "/api/auth/register"}


def resolve_upstream(path: str) -> str | None:
    for prefix, name in ROUTES:
        if path == prefix or path.startswith(prefix + "/"):
            return name
    return None


def _matches(rules: list[tuple[set[str], str]], method: str, path: str) -> bool:
    path = path.rstrip("/") or "/"
    return any(method in methods and fnmatchcase(path, pattern) for methods, pattern in rules)


def is_public(method: str, path: str) -> bool:
    return method == "OPTIONS" or _matches(PUBLIC_ROUTES, method, path)


def check_access(method: str, path: str, principal: Principal | None) -> None:
    if _matches(ADMIN_ROUTES, method, path) and (principal is None or not principal.is_admin):
        raise ForbiddenError("Administrator role required")
