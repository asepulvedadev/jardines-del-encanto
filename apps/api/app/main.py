import os
from pathlib import Path

import psycopg
from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="Jardines del Encanto API", docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/health/live")
def live():
    return {"status": "ok"}


@app.get("/health/ready")
def ready():
    try:
        password = Path(os.environ["DATABASE_PASSWORD_FILE"]).read_text().strip()
        with psycopg.connect(
            host="db", dbname="jardines", user="jardines", password=password, connect_timeout=3
        ) as connection:
            connection.execute("SELECT 1")
    except (OSError, KeyError, psycopg.Error):
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return {"status": "ok"}
