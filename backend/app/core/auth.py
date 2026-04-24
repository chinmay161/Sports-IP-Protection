# app/core/auth.py
import os
from typing import Annotated

import httpx
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.core.config import get_settings

load_dotenv()

AUTH0_DOMAIN = os.getenv("AUTH0_DOMAIN", "")
AUTH0_AUDIENCE = os.getenv("AUTH0_AUDIENCE", "")
ALGORITHMS = ["RS256"]

# auto_error=False so we can manually decide — otherwise FastAPI 403s on missing header
# even when AUTH_DISABLED is true.
bearer_scheme = HTTPBearer(auto_error=False)

_DEV_USER = {
    "sub": "dev|local",
    "email": "dev@local",
    "name": "Local Dev User",
    "scope": "read:alerts write:alerts",
}


async def _get_jwks() -> dict:
    if not AUTH0_DOMAIN:
        raise RuntimeError("AUTH0_DOMAIN is not set in .env")
    url = f"https://{AUTH0_DOMAIN}/.well-known/jwks.json"
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()


async def verify_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> dict:
    # Dev shortcut: skip Auth0 entirely.
    if get_settings().auth_disabled:
        return dict(_DEV_USER)

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        raise credentials_exception

    token = credentials.credentials
    try:
        jwks = await _get_jwks()
        unverified_header = jwt.get_unverified_header(token)
        rsa_key = {}
        for key in jwks["keys"]:
            if key["kid"] == unverified_header["kid"]:
                rsa_key = {
                    "kty": key["kty"],
                    "kid": key["kid"],
                    "use": key["use"],
                    "n":   key["n"],
                    "e":   key["e"],
                }
                break
        if not rsa_key:
            raise credentials_exception
        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=ALGORITHMS,
            audience=AUTH0_AUDIENCE,
            issuer=f"https://{AUTH0_DOMAIN}/",
        )
        return payload
    except JWTError:
        raise credentials_exception