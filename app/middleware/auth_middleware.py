"""
Auth Middleware
==============
Her istekte cookie kontrol eder.
Korumalı sayfalara login olmadan erişimi engeller.
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse
from app.auth import decode_token

# Bu path'ler login gerektirmez
PUBLIC_PATHS = {
    "/auth/login",
    "/auth/logout",
    "/favicon.ico",
    "/static",
}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Public path ise geç
        if any(path.startswith(p) for p in PUBLIC_PATHS):
            return await call_next(request)

        # Mobil API endpoint'leri api_key ile çalışır
        if path.startswith("/sistem/api/"):
            return await call_next(request)

        # Token kontrolü
        token = request.cookies.get("tw_token")
        if not token or not decode_token(token):
            return RedirectResponse("/auth/login", status_code=302)

        return await call_next(request)
