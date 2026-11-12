import os
from pathlib import Path

import psycopg
from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .control.routes import router as control_router
from .crm.landing import router as landing_router
from .crm.routes import router as crm_router
from .hermes.routes import internal_router
from .hermes.routes import router as hermes_router
from .sara.routes import router as sara_router
from .social.mcp_routes import router as social_mcp_router
from .social.routes import router as social_router
from .social.routes import webhook_router
from .voice.routes import router as voice_router

app = FastAPI(title="Jardines del Encanto API", docs_url=None, redoc_url=None, openapi_url=None)


app.include_router(crm_router)
app.include_router(control_router)
app.include_router(hermes_router)
app.include_router(sara_router)
app.include_router(voice_router)
app.include_router(internal_router)
app.include_router(landing_router)
app.include_router(social_router)
app.include_router(social_mcp_router)
app.include_router(webhook_router)


@app.middleware("http")
async def private_response_headers(request: Request, call_next):
    private_control = request.url.path.startswith(
        ("/crm/control/", "/crm/hermes/", "/internal/hermes/", "/crm/sara/", "/crm/voice/")
    )
    if private_control and request.method in ("POST", "PATCH", "DELETE"):
        # Bound bytes before JSON/Pydantic parsing, including chunked requests.
        large = request.url.path.startswith("/internal/hermes/") or (
            request.url.path.startswith("/crm/control/items")
            and not request.url.path.endswith("/run")
        )
        maximum = (
            768 * 1024
            if request.url.path in ("/crm/sara/attachments", "/crm/voice/attachments")
            else 65536
            if large
            else 16384
        )
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > maximum:
                return JSONResponse(
                    {"detail": "request_too_large"},
                    status_code=413,
                    headers={"Cache-Control": "no-store, private"},
                )
            chunks.append(chunk)
        request._body = b"".join(chunks)
    response = await call_next(request)
    if request.url.path.startswith(("/crm/", "/public/", "/internal/hermes/")):
        response.headers["Cache-Control"] = "no-store, private"
    return response


@app.exception_handler(RequestValidationError)
async def invalid_input(request, error):
    if request.url.path.startswith(("/crm/", "/public/", "/internal/hermes/")):
        return JSONResponse({"detail": "invalid_input"}, status_code=422)
    return await request_validation_exception_handler(request, error)


@app.exception_handler(psycopg.Error)
async def database_error(request, error):
    if isinstance(error, psycopg.errors.UniqueViolation):
        return JSONResponse({"detail": "phone_already_exists"}, status_code=409)
    return JSONResponse({"detail": "database_unavailable"}, status_code=503)


@app.get("/health/live")
def live():
    return {"status": "ok"}


@app.get("/health/ready")
def ready():
    try:
        if os.getenv("CRM_DATABASE_URL"):
            with psycopg.connect(os.environ["CRM_DATABASE_URL"], connect_timeout=3) as connection:
                connection.execute("SELECT 1 FROM crm.contacts LIMIT 1")
        else:
            password = Path(os.environ["DATABASE_PASSWORD_FILE"]).read_text().strip()
            with psycopg.connect(
                host="db", dbname="jardines", user="jardines", password=password, connect_timeout=3
            ) as connection:
                connection.execute("SELECT 1")
    except (OSError, KeyError, psycopg.Error):
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return {"status": "ok"}
