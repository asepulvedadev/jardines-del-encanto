"""Separate read-only Ads credential and fixed GET routes; Inbox writes stay separate."""

import json
import os
import re
import stat
from urllib.parse import urlencode

from fastapi import HTTPException

from ..inbox import provider
from ..inbox.models import Execute, validate
from . import config
from .transport import https_connection

PROFILE = "6ae35794a3d08c217a343392"
FACEBOOK = "6af6692c45ef03d5f9965518"
ADS = "6afb351878449c760a51a501"
TIKTOK = "6afb3215050792ec90fe0f6a"
PAGE = "735902652941803"
AD_ACCOUNT = "act_1384537249280275"


def ads_credentials():
    folder = config.directory()
    if folder.is_symlink() or stat.S_IMODE(folder.stat().st_mode) != 0o700:
        raise ValueError("moderation_credentials_invalid")
    fd = os.open(folder / "ads-engagement-readonly.json", os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as file:
        info = os.fstat(file.fileno())
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError("moderation_credentials_invalid")
        raw = file.read(16385)
        if len(raw) > 16384:
            raise ValueError("moderation_credentials_invalid")
        data = json.loads(raw)
    if (
        data.get("profile_id") != PROFILE
        or data.get("account_id") != ADS
        or data.get("permission") != "read_only"
        or set(data.get("groups", [])) != {"ads", "accounts", "engagement"}
        or not isinstance(data.get("api_key"), str)
        or not data["api_key"]
    ):
        raise ValueError("moderation_credentials_invalid")
    return data


def ads_get(credentials, ad_id, cursor=None, detail=False):
    if not re.fullmatch(r"[a-f0-9]{24}", ad_id):
        raise ValueError("moderation_source_invalid")
    path = "/api/v1/ads/" + ad_id
    query = {"accountId": ADS} if detail else {"placement": "facebook", "limit": 50}
    if not detail:
        path += "/comments"
        if cursor:
            query["cursor"] = cursor
    conn = https_connection("zernio.com", timeout=12)
    try:
        conn.request(
            "GET",
            path + "?" + urlencode(query),
            headers={
                "Authorization": "Bearer " + credentials["api_key"],
                "Accept": "application/json",
            },
        )
        response = conn.getresponse()
        if response.status != 200:
            raise HTTPException(409, "moderation_ads_read_failed")
        raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("moderation_response_large")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise TypeError("moderation_response_invalid")
        return provider.scrub(data, credentials)
    finally:
        conn.close()


def inbox(credentials, source, operation, *, comment=None, message=None, cursor=None, key=None):
    if source["account_id"] not in (FACEBOOK, TIKTOK):
        raise ValueError("moderation_account_invalid")
    path = {"postId": source["post_id"]}
    body, query = {}, {}
    if operation == "getInboxPostComments":
        query = {"limit": 50}
        if cursor:
            query["cursor"] = cursor
        if comment:
            query["commentId"] = comment
    elif operation in ("hideInboxComment", "sendPrivateReplyToComment"):
        path["commentId"] = comment
        if message:
            body["message"] = message
    elif operation == "replyToInboxPost":
        body = {"commentId": comment, "message": message}
    else:
        raise ValueError("moderation_operation_invalid")
    if not all(isinstance(v, str) and 1 <= len(v) <= 200 for v in path.values()):
        raise ValueError("moderation_identity_invalid")
    spec, args = validate(
        Execute(
            operation=operation, account_id=source["account_id"], path=path, query=query, body=body
        ),
        credentials,
    )
    return provider.request(credentials, spec, args, key=key)
