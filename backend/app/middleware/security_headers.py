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

        # HSTS is production-only: asserting it forces HTTPS for the host, which
        # would break local dev served over plain HTTP. Same gating idiom as the
        # refresh-cookie `secure` flag in app/api/routes/auth.py.
        if get_settings().environment == "production":
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"

        return response
