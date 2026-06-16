from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.config import get_settings


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Emit standard security response headers on every API response.

    Applied at the app layer so coverage is identical on both staging (Droplet)
    and prod (App Platform), regardless of any reverse-proxy header handling.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"

        # HSTS is production-only: asserting it pins the host to HTTPS, which would
        # break local dev served over plain HTTP. Staging is deliberately excluded
        # here — it already gets HSTS at the nginx edge (MYS-58), so an API-level
        # header would be redundant. (This is a narrower gate than the cookie
        # `secure` flag in auth.py, which is on for every non-development env.)
        if get_settings().environment == "production":
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"

        return response
