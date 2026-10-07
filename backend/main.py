"""Tech Migration AI backend — chat, comparison, conversion,
learning, RAG knowledge base, repository analysis, and automated migration."""
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.chat import router as chat_router
from api.compare import router as compare_router
from api.convert import router as convert_router
from api.knowledge import router as knowledge_router
from api.learn import router as learn_router
from api.migration import router as migration_router


def _allowed_origins() -> list[str]:
    origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
    # FRONTEND_URL: comma-separated extra origins (e.g. the Render frontend
    # URL). Bare hosts get an https:// scheme.
    for raw in os.environ.get("FRONTEND_URL", "").split(","):
        raw = raw.strip().rstrip("/")
        if not raw:
            continue
        if not raw.startswith(("http://", "https://")):
            raw = f"https://{raw}"
        if raw not in origins:
            origins.append(raw)
    return origins


def create_app() -> FastAPI:
    app = FastAPI(title="Tech Migration AI", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(chat_router, prefix="/api")
    app.include_router(compare_router, prefix="/api")
    app.include_router(convert_router, prefix="/api")
    app.include_router(learn_router, prefix="/api")
    app.include_router(knowledge_router, prefix="/api")
    app.include_router(migration_router, prefix="/api")

    @app.get("/")
    async def root():
        return {"service": "tech-migration-ai", "phase": 7, "status": "ok"}

    return app


app = create_app()
