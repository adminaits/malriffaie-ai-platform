from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from app.config import get_settings
from app.routers.public import router as public_router
from app.routers.admin import router as admin_router
from app.routers.auth import router as auth_router
from app.auth import ensure_default_admin
from app.routers.integrations import router as integrations_router

settings = get_settings()
app = FastAPI(title=settings.app_name)

@app.on_event("startup")
def startup_bootstrap():
    ensure_default_admin()

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(public_router)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(integrations_router)
