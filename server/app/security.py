import hmac

from fastapi import Header, HTTPException, Query, status

from .config import get_settings


def _valid_token(value: str | None) -> bool:
    configured = get_settings().token
    return bool(value and configured and hmac.compare_digest(value, configured))


def require_token(authorization: str | None = Header(default=None)) -> None:
    candidate = ""
    if authorization and authorization.lower().startswith("bearer "):
        candidate = authorization[7:]
    if not _valid_token(candidate):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid NAS Link token")


def validate_websocket_token(token: str = Query(default="")) -> None:
    if not _valid_token(token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid NAS Link token")

