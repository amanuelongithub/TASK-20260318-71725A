from fastapi import FastAPI, HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from app.api.router import api_router
from app.core.config import settings
from app.core.logging import logger

if settings.environment == "prod":
    # Robust check for default or weak secrets
    insecure_markers = {"change-me", "REPLACE_WITH", "INSECURE", "DEV-SECRET", "DEV-AES"}
    is_secret_key_insecure = any(marker in settings.secret_key.upper() for marker in insecure_markers)
    is_aes_key_insecure = any(marker in settings.aes_key.upper() for marker in insecure_markers)
    
    if is_secret_key_insecure or is_aes_key_insecure or len(settings.secret_key) < 32:
        import sys
        logger.critical("FATAL: Cannot start in production with default, weak, or placeholder secrets.")
        logger.critical(f"SECRET_KEY status: {'INSECURE' if is_secret_key_insecure else 'OK'}")
        logger.critical(f"AES_KEY status: {'INSECURE' if is_aes_key_insecure else 'OK'}")
        sys.exit(1)

app = FastAPI(title=settings.app_name)

class HTTPSRedirectMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Universal HTTPS enforcement as required by compliance. 
        # Bypassable ONLY if ALLOW_PLAIN_HTTP is True AND we are NOT in production.
        is_prod = settings.environment.lower() == "prod"
        if not settings.allow_plain_http or is_prod:
            # Check for standard HTTPS header
            is_https = request.url.scheme == "https"
            
            # Check for proxy forwarding header (common in load balancers)
            forwarded_proto = request.headers.get("x-forwarded-proto")
            
            if not is_https and forwarded_proto != "https":
                 # If it's an API request, returning 403 Forbidden is safer than 301.
                 # Using JSONResponse directly because HTTPException in middleware 
                 # can sometimes bypass standard exception handlers.
                 from fastapi.responses import JSONResponse
                 return JSONResponse(
                     status_code=status.HTTP_403_FORBIDDEN, 
                     content={"detail": "HTTPS-only endpoint. Transmission must be encrypted (Production/Compliance requirement)."}
                 )
        return await call_next(request)


app.add_middleware(HTTPSRedirectMiddleware)

app.include_router(api_router, prefix="/api")

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

