"""Tech Migration AI backend — Phase 3: FastAPI + Ollama chat, comparison, conversion."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.chat import router as chat_router
from api.compare import router as compare_router
from api.convert import router as convert_router


def create_app() -> FastAPI:
    app = FastAPI(title="Tech Migration AI", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(chat_router, prefix="/api")
    app.include_router(compare_router, prefix="/api")
    app.include_router(convert_router, prefix="/api")

    @app.get("/")
    async def root():
        return {"service": "tech-migration-ai", "phase": 3, "status": "ok"}

    return app


app = create_app()
