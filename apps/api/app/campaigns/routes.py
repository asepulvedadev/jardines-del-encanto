"""Authenticated drafts and explicit review; never message delivery or scheduling."""

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

from ..crm.database import connect
from ..crm.models import Input
from ..crm.routes import Admin
from ..social import config
from . import models, reviews, service


class ReviewMediaLogFilter(logging.Filter):
    """Never persist bearer capability paths in the default HTTP access log."""

    def filter(self, record):
        return "/campaigns/review-media/" not in record.getMessage()


logging.getLogger("uvicorn.access").addFilter(ReviewMediaLogFilter())
router = APIRouter(prefix="/crm/campaigns")


@router.get("")
def listing(admin: Admin):
    with connect() as db:
        return service.listing(db)


@router.post("", status_code=201)
def create(data: models.Create, admin: Admin):
    with connect() as db:
        return service.create(db, data, admin)


@router.get("/media/{asset_id}")
def media(asset_id: str, admin: Admin):
    if asset_id not in models.ASSETS:
        raise HTTPException(404, "not_found")
    return FileResponse(
        service.ROOT / "assets" / f"{asset_id}.png",
        media_type="image/png",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.patch("/{slug}")
def update(slug: str, data: models.Update, admin: Admin):
    if not 1 <= len(slug) <= 80 or any(
        char not in "abcdefghijklmnopqrstuvwxyz0123456789-" for char in slug
    ):
        raise HTTPException(404, "not_found")
    with connect() as db:
        return service.update(db, slug, data, admin)


@router.get("/review-accounts")
def review_accounts(admin: Admin):
    return {"items": reviews.accounts(config.required())}


@router.post("/{slug}/review-preview")
def review_preview(slug: str, data: models.ReviewPreview, admin: Admin):
    return reviews.preview(slug, data)


@router.get("/{slug}/reviews")
def review_history(slug: str, admin: Admin):
    return reviews.history(slug)


@router.post("/{slug}/reviews", status_code=201)
def review_submit(slug: str, data: models.ReviewSubmit, admin: Admin):
    return reviews.submit(slug, data, admin)


@router.post("/{slug}/reviews/{identifier}/refresh")
def review_refresh(slug: str, identifier: UUID, data: Input, admin: Admin):
    return reviews.refresh(slug, identifier)


@router.get("/review-media/{identifier}/{token}")
def review_media(identifier: UUID, token: str):
    # Short-lived, one-image capability for the vendor, not a public asset library.
    return Response(
        reviews.media(identifier, token),
        media_type="image/png",
        headers={
            "Cache-Control": "no-store, private",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        },
    )
