from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.routers import auth, dashboard, sync, xlri_credentials
from app.services.scheduler import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="XLRI Schedule Sync", lifespan=lifespan)

# Transient session used only by Authlib to store OAuth state/nonce during the
# redirect round-trip -- NOT the app's own login session (see app/services/session.py).
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    same_site="lax",
    https_only=settings.base_url.startswith("https"),
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth.router)
app.include_router(xlri_credentials.router)
app.include_router(sync.router)
app.include_router(dashboard.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
