"""Default-deny ASGI ingress-authentication middleware."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from http.cookies import CookieError, SimpleCookie
from typing import Any

from .models import AuthenticatedIdentity, AuthenticationMechanism, AuthenticationMode
from .policy import AuthenticationPolicy
from .session import OwnerSessionCodec, SessionVerificationError, VerifiedOwnerSession

ASGIScope = dict[str, Any]
ASGIMessage = dict[str, Any]
ASGIReceive = Callable[[], Awaitable[ASGIMessage]]
ASGISend = Callable[[ASGIMessage], Awaitable[None]]
ASGIApp = Callable[[ASGIScope, ASGIReceive, ASGISend], Awaitable[None]]

OWNER_SESSION_COOKIE = "assistantmd_owner_session"
OWNER_CSRF_COOKIE = "assistantmd_csrf"
CSRF_HEADER = "x-assistantmd-csrf"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class PublicRoute:
    """One deliberately unauthenticated method/path pair."""

    method: str
    path: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "method", self.method.upper())
        if not self.path.startswith("/"):
            raise ValueError("Public route paths must be absolute.")


DEFAULT_PUBLIC_ROUTES = frozenset(
    {
        PublicRoute("GET", "/api/health"),
        PublicRoute("HEAD", "/api/health"),
        PublicRoute("GET", "/auth/login"),
        PublicRoute("POST", "/auth/session"),
    }
)


class AuthenticationMiddleware:
    """Authenticate every HTTP/WebSocket scope before route resolution."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        policy: AuthenticationPolicy,
        public_routes: Iterable[PublicRoute] = DEFAULT_PUBLIC_ROUTES,
    ) -> None:
        self._app = app
        self._policy = policy
        self._public_routes = frozenset(public_routes)
        self._session_codec = (
            OwnerSessionCodec(policy)
            if policy.mode is AuthenticationMode.OWNER_TOKEN
            else None
        )

    async def __call__(
        self,
        scope: ASGIScope,
        receive: ASGIReceive,
        send: ASGISend,
    ) -> None:
        scope_type = scope.get("type")
        if scope_type not in {"http", "websocket"}:
            await self._app(scope, receive, send)
            return
        method = str(scope.get("method") or "GET").upper()
        path = str(scope.get("path") or "")
        if scope_type == "http" and PublicRoute(method, path) in self._public_routes:
            await self._app(scope, receive, send)
            return

        admission = self._authenticate(scope)
        if admission is None:
            await _reject(
                scope_type, send, status_code=401, detail="Authentication required."
            )
            return
        identity, owner_session = admission
        if (
            scope_type == "http"
            and method not in _SAFE_METHODS
            and identity.mechanism is AuthenticationMechanism.OWNER_SESSION
        ):
            if owner_session is None or not self._verify_csrf(scope, owner_session):
                await _reject(
                    scope_type,
                    send,
                    status_code=403,
                    detail="CSRF verification failed.",
                )
                return

        state = scope.setdefault("state", {})
        state["authenticated_identity"] = identity
        await self._app(scope, receive, send)

    def _authenticate(
        self, scope: ASGIScope
    ) -> tuple[AuthenticatedIdentity, VerifiedOwnerSession | None] | None:
        mode = self._policy.mode
        if mode is AuthenticationMode.DISABLED:
            identity = self._policy.authenticate_disabled()
            return (identity, None) if identity is not None else None
        peer_host = _peer_host(scope)
        if mode is AuthenticationMode.LOOPBACK:
            identity = self._policy.authenticate_loopback(peer_host)
            return (identity, None) if identity is not None else None
        if mode is AuthenticationMode.TRUSTED_PROXY:
            assertion = _single_header(
                scope,
                self._policy.proxy_assertion_header.lower().encode("ascii"),
            )
            identity = self._policy.authenticate_proxy(
                assertion=assertion,
                peer_host=peer_host,
            )
            return (identity, None) if identity is not None else None

        bearer = _bearer_token(scope)
        identity = self._policy.authenticate_owner_bearer(bearer)
        if identity is not None:
            return identity, None
        session = self._owner_session(scope)
        if session is None:
            return None
        return session.identity, session

    def _owner_session(self, scope: ASGIScope) -> VerifiedOwnerSession | None:
        if self._session_codec is None:
            return None
        cookie_header = _single_header(scope, b"cookie")
        if cookie_header is None:
            return None
        try:
            cookies = SimpleCookie()
            cookies.load(cookie_header)
        except CookieError:
            return None
        morsel = cookies.get(OWNER_SESSION_COOKIE)
        if morsel is None:
            return None
        try:
            return self._session_codec.verify(morsel.value)
        except SessionVerificationError:
            return None

    def _verify_csrf(
        self,
        scope: ASGIScope,
        session: VerifiedOwnerSession,
    ) -> bool:
        if self._session_codec is None:
            return False
        csrf_token = _single_header(scope, CSRF_HEADER.encode("ascii"))
        try:
            self._session_codec.verify_csrf(session, csrf_token)
        except SessionVerificationError:
            return False
        return True


def get_authenticated_identity(scope: ASGIScope) -> AuthenticatedIdentity | None:
    """Return the identity installed by ingress middleware, if present."""
    state = scope.get("state")
    if not isinstance(state, dict):
        return None
    identity = state.get("authenticated_identity")
    return identity if isinstance(identity, AuthenticatedIdentity) else None


def _single_header(scope: ASGIScope, lower_name: bytes) -> str | None:
    raw_headers = scope.get("headers")
    if not isinstance(raw_headers, list):
        return None
    matches: list[bytes] = []
    for raw_header in raw_headers:
        if not isinstance(raw_header, tuple) or len(raw_header) != 2:
            return None
        name, value = raw_header
        if not isinstance(name, bytes) or not isinstance(value, bytes):
            return None
        if name.lower() == lower_name:
            matches.append(value)
    if len(matches) != 1:
        return None
    try:
        return matches[0].decode("latin-1")
    except UnicodeDecodeError:
        return None


def _bearer_token(scope: ASGIScope) -> str | None:
    authorization = _single_header(scope, b"authorization")
    if authorization is None:
        return None
    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token or " " in token:
        return None
    return token


def _peer_host(scope: ASGIScope) -> str | None:
    client = scope.get("client")
    if not isinstance(client, tuple | list) or not client:
        return None
    host = client[0]
    return host if isinstance(host, str) else None


async def _reject(
    scope_type: str,
    send: ASGISend,
    *,
    status_code: int,
    detail: str,
) -> None:
    if scope_type == "websocket":
        await send({"type": "websocket.close", "code": 4401, "reason": detail})
        return
    body = json.dumps({"detail": detail}, separators=(",", ":")).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"cache-control", b"no-store"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
