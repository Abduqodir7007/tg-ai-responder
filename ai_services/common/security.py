import hmac
import os

from fastapi import Header, HTTPException, status


def verify_internal_token(x_internal_token: str = Header(default="")) -> None:
    expected = os.environ.get("INTERNAL_SERVICE_TOKEN", "")
    if not expected or not hmac.compare_digest(x_internal_token.encode(), expected.encode()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid internal token")
