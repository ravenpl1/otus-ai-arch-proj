"""Authentication & Authorization — OIDC JWT validation.

Reads Bearer tokens issued by any OIDC-compliant Identity Provider
(Authelia, Keycloak, Auth0, Dex, etc.), validates JWT signature via
JWKS endpoint, extracts user identity and maps IdP groups to
application roles for RBAC.
"""

from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (from environment)
# ---------------------------------------------------------------------------

OIDC_ISSUER_URL: str = os.getenv("OIDC_ISSUER_URL", "http://192.168.1.50:9091")
OIDC_CLIENT_ID: str = os.getenv("OIDC_CLIENT_ID", "fastapi-swagger")
OIDC_CLIENT_SECRET: str = os.getenv("OIDC_CLIENT_SECRET", "")
OIDC_ISSUER: str = os.getenv("OIDC_ISSUER", OIDC_ISSUER_URL)

# ---------------------------------------------------------------------------
# Group -> Role mapping
# ---------------------------------------------------------------------------

_GROUP_ROLE_PRIORITY: List[str] = ["users", "finance", "data_stewards", "admin"]
_GROUP_TO_ROLE: Dict[str, str] = {
    "users": "USER",
    "finance": "FINANCE",
    "data_stewards": "DATA_STEWARD",
    "admin": "ADMIN",
}


def _map_groups_to_role(groups: List[str]) -> str:
    """Map IdP groups list to the highest-privilege application role."""
    if not groups:
        return "USER"

    best_role = "USER"
    best_priority = 0

    for group in groups:
        g = group.strip().lower()
        if g in _GROUP_TO_ROLE and g in _GROUP_ROLE_PRIORITY:
            priority = _GROUP_ROLE_PRIORITY.index(g)
            if priority >= best_priority:
                best_priority = priority
                best_role = _GROUP_TO_ROLE[g]

    return best_role


# ---------------------------------------------------------------------------
# JWKS client (lazy singleton)
# ---------------------------------------------------------------------------

_jwks_client = None


def _get_jwks_client():
    global _jwks_client
    if _jwks_client is None:
        # Authelia 4.38 uses /jwks.json (not /.well-known/jwks.json)
        jwks_url = f"{OIDC_ISSUER_URL}/jwks.json"
        _jwks_client = jwt.PyJWKClient(jwks_url, cache_keys=True)
    return _jwks_client


def _userinfo_token(token: str) -> Dict:
    """Get user info from OIDC userinfo endpoint using Bearer token.

    This is a reliable alternative to introspection, supported by Authelia 4.38+.
    Returns user claims including groups, preferred_username, sub, etc.
    """
    import httpx as _httpx

    userinfo_url = f"{OIDC_ISSUER_URL}/api/oidc/userinfo"
    headers = {
        "Authorization": f"Bearer {token}",
    }

    try:
        with _httpx.Client() as client:
            logger.info("Getting userinfo from %s", userinfo_url)
            logger.info("Token preview: %s...", token[:30])
            resp = client.get(userinfo_url, headers=headers, timeout=10.0)
            logger.info("Userinfo response: status=%d body=%s", resp.status_code, resp.text[:500])

            if resp.status_code == 401:
                raise HTTPException(status_code=401, detail="Token is not valid (userinfo)")

            resp.raise_for_status()
            result = resp.json()
            return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Userinfo request failed: %s", e)
        raise HTTPException(status_code=401, detail="Token verification failed (userinfo)")


def verify_token(token: str) -> Dict:
    """Verify JWT token issued by OIDC provider and return claims.

    Tries JWT validation first (for signed tokens), falls back to
    introspection (for opaque tokens from Authelia).
    """
    logger.info("verify_token: token has %d dots, preview: %s...", token.count("."), token[:30])

    # Try JWT decode first (only if token looks like JWT: 3 parts separated by dots)
    if token.count(".") == 2:
        try:
            jwks_client = _get_jwks_client()
            signing_key = jwks_client.get_signing_key_from_jwt(token)

            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["ES256", "RS256", "HS256"],
                issuer=OIDC_ISSUER,
                audience=OIDC_CLIENT_ID,
                options={
                    "verify_exp": True,
                    "verify_aud": True,
                    "verify_iss": True,
                },
            )
            return payload

        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token has expired")
        except jwt.InvalidAudienceError:
            raise HTTPException(status_code=401, detail="Invalid token audience")
        except jwt.InvalidIssuerError:
            raise HTTPException(status_code=401, detail="Invalid token issuer")
        except jwt.InvalidSignatureError:
            raise HTTPException(status_code=401, detail="Invalid token signature")
        except jwt.DecodeError:
            logger.info("Token is not a valid JWT (decode error), trying introspection...")
        except Exception as e:
            logger.warning("JWT verification error: %s", e)

    # Fallback: userinfo endpoint (for opaque tokens or when JWT validation fails)
    return _userinfo_token(token)


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

_bearer_scheme = HTTPBearer(auto_error=False)


class AuthenticatedUser:
    """Represents an authenticated user with their roles."""

    def __init__(self, username: str, groups: List[str], role: str, claims: Dict):
        self.username = username
        self.groups = groups
        self.role = role
        self.claims = claims

    @property
    def restricted_fields(self) -> set:
        """Return set of financial fields the user cannot see."""
        from domain.entities import get_restricted_fields
        return get_restricted_fields(self.role)

    def __repr__(self):
        return f"AuthenticatedUser(username={self.username!r}, role={self.role!r})"


async def get_optional_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> Optional[AuthenticatedUser]:
    """Extract user from Bearer token if present, otherwise return None."""
    if credentials is None:
        # Fallback: X-Remote-User header (forward-auth proxy mode, e.g. Traefik + Authelia)
        remote_user = request.headers.get("X-Remote-User")
        if remote_user:
            remote_groups = request.headers.get("X-Remote-Groups", "").split(",")
            groups = [g.strip() for g in remote_groups if g.strip()]
            role = _map_groups_to_role(groups)
            return AuthenticatedUser(
                username=remote_user,
                groups=groups,
                role=role,
                claims={"sub": remote_user, "groups": groups},
            )
        return None

    # Verify JWT Bearer token
    claims = verify_token(credentials.credentials)
    username = claims.get("preferred_username", claims.get("sub", "unknown"))
    groups = claims.get("groups", [])
    if isinstance(groups, str):
        groups = [groups]

    role = _map_groups_to_role(groups)

    return AuthenticatedUser(
        username=username,
        groups=groups,
        role=role,
        claims=claims,
    )


async def get_current_user(
    user: Optional[AuthenticatedUser] = Depends(get_optional_user),
) -> AuthenticatedUser:
    """Require authenticated user. Raises 401 if not authenticated."""
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Provide Bearer token.",
        )
    return user


def require_role(*allowed_roles: str):
    """FastAPI dependency factory that checks user has one of the allowed roles.

    Usage:
        @router.post("/ingest")
        async def ingest(user = Depends(require_role("DATA_STEWARD", "ADMIN"))):
            ...
    """

    async def _check_role(
        user: AuthenticatedUser = Depends(get_current_user),
    ) -> AuthenticatedUser:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"Access denied. Required: {allowed_roles}, your role: {user.role}",
            )
        return user

    return _check_role
