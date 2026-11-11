"""Public, consented contact capture; registration codes never reserve inventory."""

import secrets

import psycopg
from fastapi import APIRouter, HTTPException, Request
from pydantic import Field, StrictBool, ValidationError, field_validator
from starlette.concurrency import run_in_threadpool

from .database import connect
from .models import ContactInput, Input
from .security import digest, require_origin

router = APIRouter(prefix="/public")


class RegistrationInput(Input):
    name: str = Field(min_length=3, max_length=120)
    phone: str = Field(min_length=7, max_length=32)
    consent: StrictBool
    website: str = Field(default="", max_length=0)

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value):
        return ContactInput.normalize_phone(value)

    @field_validator("consent")
    @classmethod
    def require_consent(cls, value):
        if not value:
            raise ValueError("consent_required")
        return value


def throttle(phone):
    # Durable global + normalized-phone budgets; never trust forwarded IP headers.
    with connect() as db:
        db.execute("DELETE FROM crm.landing_limits WHERE window_start < now() - interval '1 day'")
        for key, maximum in (("global", 100), ("phone:" + digest(phone), 5)):
            attempts = db.execute(
                """INSERT INTO crm.landing_limits(key) VALUES (%s)
                   ON CONFLICT (key) DO UPDATE SET
                     attempts = CASE WHEN crm.landing_limits.window_start < now() - interval '10 minutes'
                       THEN 1 ELSE crm.landing_limits.attempts + 1 END,
                     window_start = CASE WHEN crm.landing_limits.window_start < now() - interval '10 minutes'
                       THEN now() ELSE crm.landing_limits.window_start END
                   RETURNING attempts""",
                (key,),
            ).fetchone()["attempts"]
            if attempts > maximum:
                db.commit()
                raise HTTPException(429, "capture_throttled", headers={"Retry-After": "600"})


def register(data):
    throttle(data.phone)
    with connect() as db:
        record = db.execute(
            """INSERT INTO crm.contacts(name, phone, source) VALUES (%s,%s,'web')
               ON CONFLICT (phone) DO NOTHING RETURNING id""",
            (data.name, data.phone),
        ).fetchone()
        if not record:
            record = db.execute(
                "SELECT id FROM crm.contacts WHERE phone=%s FOR UPDATE", (data.phone,)
            ).fetchone()
        if not record:
            # An administrator changed the phone concurrently; retry without partial writes.
            raise HTTPException(409, "capture_retry")
        contact_id = record["id"]
        db.execute(
            "INSERT INTO crm.deals(contact_id) VALUES (%s) ON CONFLICT (contact_id) DO NOTHING",
            (contact_id,),
        )
        existing = db.execute(
            "SELECT code FROM crm.landing_registrations WHERE contact_id=%s", (contact_id,)
        ).fetchone()
        if existing:
            return {"code": existing["code"]}
        for _ in range(3):
            try:
                # Savepoint permits retrying an improbable code collision without losing the lead.
                with db.transaction():
                    code = "JDE-" + secrets.token_hex(6).upper()
                    db.execute(
                        """INSERT INTO crm.landing_registrations(contact_id,code,consent_version)
                           VALUES (%s,%s,'landing-contact-v1')""",
                        (contact_id, code),
                    )
                return {"code": code}
            except psycopg.errors.UniqueViolation:
                continue
        raise HTTPException(503, "capture_unavailable")


@router.post("/registrations", status_code=201)
async def capture(request: Request):
    require_origin(request)
    if (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "application/json"
    ):
        raise HTTPException(415, "invalid_content_type")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 2048:
            raise HTTPException(413, "request_too_large")
        body.extend(chunk)
    try:
        data = RegistrationInput.model_validate_json(body)
    except ValidationError:
        raise HTTPException(422, "invalid_input") from None
    return await run_in_threadpool(register, data)
