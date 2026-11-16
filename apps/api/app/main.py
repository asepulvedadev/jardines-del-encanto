import os
from contextlib import asynccontextmanager
from pathlib import Path

import psycopg
from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .campaigns.routes import router as campaigns_router
from .control.routes import router as control_router
from .crm.landing import router as landing_router
from .crm.routes import router as crm_router
from .hermes.routes import internal_router
from .hermes.routes import router as hermes_router
from .images import delivery as image_delivery
from .images import worker as images_worker
from .images.routes import router as images_router
from .inbox.routes import router as inbox_router
from .retell.routes import router as retell_router
from .sara import simulations
from .sara.profile_routes import router as sara_profile_router
from .sara.routes import router as sara_router
from .social import lead_capture_worker, lead_notifications_worker, whatsapp_agent
from .social.mcp_routes import router as social_mcp_router
from .social.routes import router as social_router
from .social.routes import webhook_router
from .voice.routes import router as voice_router
from .workflows import worker as workflows_worker
from .workflows.routes import router as workflows_router


@asynccontextmanager
async def lifespan(app):
    lead_capture_worker.start()
    lead_notifications_worker.start()
    workflows_worker.start()
    whatsapp_agent.start()
    simulations.start()
    images_worker.start()
    image_delivery.start()
    try:
        yield
    finally:
        lead_capture_worker.stop()
        lead_notifications_worker.stop()
        workflows_worker.stop()
        whatsapp_agent.stop()
        simulations.stop()
        images_worker.stop()
        image_delivery.stop()


app = FastAPI(
    lifespan=lifespan,
    title="Jardines del Encanto API",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


app.include_router(crm_router)
app.include_router(campaigns_router)
app.include_router(inbox_router)
app.include_router(workflows_router)
app.include_router(control_router)
app.include_router(hermes_router)
app.include_router(sara_router)
app.include_router(sara_profile_router)
app.include_router(images_router)
app.include_router(voice_router)
app.include_router(retell_router)
app.include_router(internal_router)
app.include_router(landing_router)
app.include_router(social_router)
app.include_router(social_mcp_router)
app.include_router(webhook_router)
app.include_router(whatsapp_agent.router)


@app.middleware("http")
async def private_response_headers(request: Request, call_next):
    if request.url.path.startswith(("/crm/campaigns", "/crm/inbox")) and request.url.query:
        return JSONResponse(
            {"detail": "invalid_input"}, status_code=422,
            headers={"Cache-Control": "no-store, private"},
        )
    if request.url.path.startswith("/crm/workflows/") and request.url.query:
        return JSONResponse(
            {"detail": "invalid_input"},
            status_code=422,
            headers={"Cache-Control": "no-store, private"},
        )
    private_control = request.url.path.startswith(
        (
            "/crm/social/whatsapp-agent",
            "/crm/campaigns",
            "/crm/inbox/",
            "/crm/workflows/",
            "/crm/control/",
            "/crm/hermes/",
            "/internal/hermes/",
            "/crm/sara/",
            "/crm/images",
            "/crm/voice/",
            "/crm/retell/",
        )
    )
    if private_control and request.method in ("POST", "PATCH", "DELETE"):
        # Bound bytes before JSON/Pydantic parsing, including chunked requests.
        large = (
            request.url.path.startswith("/internal/hermes/")
            or (request.url.path.startswith("/crm/workflows/definitions"))
            or (
                request.url.path.startswith("/crm/control/items")
                and not request.url.path.endswith("/run")
            )
        )
        maximum = (
            768 * 1024
            if request.url.path in ("/crm/sara/attachments", "/crm/voice/attachments")
            else 65536
            if large or request.url.path.startswith("/crm/inbox/")
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
