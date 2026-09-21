import hmac

from fastapi import Header, HTTPException, status

from .config import get_settings


def _valid_token(value: str | None) -> bool:
    configured = get_settings().token
    return bool(value and configured and hmac.compare_digest(value, configured))


def _bearer_token(authorization: str | None) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def require_token(authorization: str | None = Header(default=None)) -> None:
    candidate = _bearer_token(authorization)
    if not _valid_token(candidate):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid NAS Link token")


def valid_websocket_token(authorization: str | None) -> bool:
    """WebSocket credentials must stay out of access-log URLs."""
    return _valid_token(_bearer_token(authorization))
