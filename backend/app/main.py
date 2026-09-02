import asyncio
import logging
import sys
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

if sys.platform == "win32":
    # asyncpg is not fully compatible with Windows' default ProactorEventLoop -
    # pool_pre_ping connection checks (db.py) intermittently crash with
    # "AttributeError: 'NoneType' object has no attribute 'send'" when a pooled
    # connection is reused. SelectorEventLoop doesn't have this issue and is
    # otherwise equivalent for a plain TCP-based ASGI app like this one.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.logging_config import configure_logging

configure_logging()

from app.routers import admin, auth, catalog, chat, expert, payments, queries  # noqa: E402

logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Metallurgical Consultation API starting up")
    yield
    logger.info("Metallurgical Consultation API shutting down")


app = FastAPI(title="Metallurgical Consultation API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "%s %s -> %d (%.1fms)",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


app.include_router(auth.router)
app.include_router(catalog.router)
app.include_router(queries.router)
app.include_router(payments.router)
app.include_router(expert.router)
app.include_router(admin.router)
app.include_router(chat.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
