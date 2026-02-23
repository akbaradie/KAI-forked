from uvicorn import run

from app.server import FastAPI
from app.server.config import Settings

settings = Settings()
server = FastAPI(settings)
app = server.app()


if __name__ == "__main__":
    run(
        app="app.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.APP_ENABLE_HOT_RELOAD,
        # Keep SSE / streaming connections alive for up to 5 minutes.
        # The session/query/stream endpoint can take 60-150 s for SQL
        # generation + LLM analysis, so the default 5-second keepalive
        # caused "Truncated response body" errors.
        timeout_keep_alive=300,
    )
