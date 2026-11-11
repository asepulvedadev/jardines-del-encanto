import os

import psycopg
from fastapi import HTTPException
from psycopg.rows import dict_row


def connect():
    url = os.getenv("CRM_DATABASE_URL")
    if not url:
        raise HTTPException(503, "crm_not_configured")
    return psycopg.connect(
        url,
        row_factory=dict_row,
        connect_timeout=3,
        options="-c statement_timeout=5000 -c lock_timeout=3000",
    )
