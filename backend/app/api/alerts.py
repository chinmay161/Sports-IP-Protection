# app/api/alerts.py
import random
import uuid
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.dmca import DraftDmcaResponse
from app.services.gemini import GeminiRateLimited, draft_dmca_notice

from app.core.auth import verify_token
from app.core.config import get_settings
from app.db.session import get_db_session
from app.models.asset import Asset
from app.schemas.alert import (
    AlertCreate,
    AlertResponse,
    AlertStatusUpdate,
    CaseUpdate,
    CommentCreate,
    CommentResponse,
    DMCARequest,
)
from app.services.alert import (
    create_alert,
    generate_dmca_notice,
    get_alert,
    list_alerts,
    update_alert_status,
)
from app.services.case import (
    VALID_PRIORITIES,
    add_comment,
    list_comments,
    update_case_fields,
)
from app.services.events import (
    CHANNEL_ALERT_UPDATED,
    CHANNEL_MATCH_CREATED,
    publish,
)

router = APIRouter(
    prefix="/alerts",
    tags=["alerts"],
    dependencies=[Depends(verify_token)],
)


# ---------------------------------------------------------------------------
# Alert CRUD
# ---------------------------------------------------------------------------

@router.post("", response_model=AlertResponse, status_code=status.HTTP_201_CREATED)
async def create_new_alert(
    data: AlertCreate,
    db: AsyncSession = Depends(get_db_session),
) -> AlertResponse:
    return await create_alert(db=db, data=data)


@router.get("", response_model=list[AlertResponse])
async def list_all_alerts(
    skip: int = 0,
    limit: int = 50,
    status: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
) -> list[AlertResponse]:
    return await list_alerts(db=db, skip=skip, limit=limit, status=status, severity=severity)


@router.get("/{alert_id}", response_model=AlertResponse)
async def get_single_alert(
    alert_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> AlertResponse:
    alert = await get_alert(db=db, alert_id=str(alert_id))
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    return alert


@router.patch("/{alert_id}/status", response_model=AlertResponse)
async def update_status(
    alert_id: UUID,
    body: AlertStatusUpdate,
    current_user: dict = Depends(verify_token),
    db: AsyncSession = Depends(get_db_session),
) -> AlertResponse:
    """Update alert status. Logs a system comment and fires alert.updated event."""
    valid = {"open", "acknowledged", "dmca_initiated", "resolved"}
    if body.status not in valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status. Must be one of: {valid}",
        )
    actor = current_user.get("email") or current_user.get("sub") or "system"
    result = await update_alert_status(
        db=db, alert_id=str(alert_id), new_status=body.status, actor=actor
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    alert, _system_comment = result
    await publish(CHANNEL_ALERT_UPDATED, {"alert_id": alert.id})
    return alert


@router.post("/{alert_id}/dmca", response_model=AlertResponse)
async def initiate_dmca(
    alert_id: UUID,
    body: DMCARequest,
    db: AsyncSession = Depends(get_db_session),
) -> AlertResponse:
    alert = await get_alert(db=db, alert_id=str(alert_id))
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    if alert.status == "resolved":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot initiate DMCA on a resolved alert",
        )
    alert = await generate_dmca_notice(
        db=db,
        alert_id=str(alert_id),
        asset_owner=body.asset_owner,
        contact_email=body.contact_email,
    )
    await publish(CHANNEL_ALERT_UPDATED, {"alert_id": alert.id})
    return alert


@router.post("/{alert_id}/draft-dmca", response_model=DraftDmcaResponse)
async def draft_dmca_for_alert(
    alert_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> DraftDmcaResponse:
    """Generate an AI-drafted DMCA notice for review. Does not send."""
    alert = await get_alert(db=db, alert_id=str(alert_id))
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")

    asset = await db.get(Asset, alert.asset_id) if alert.asset_id else None

    try:
        result = await draft_dmca_notice(
            platform=alert.platform,
            source_url=alert.infringing_url,
            detected_at=alert.created_at,
            severity=alert.severity_label,
            confidence=alert.confidence,
            match_type=alert.match_type,
            asset_title=asset.title if asset else "Protected Asset",
            asset_description=asset.description if asset else None,
        )
    except GeminiRateLimited:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Gemini rate limit reached, try again in a moment",
        )

    return DraftDmcaResponse(**result)

# ---------------------------------------------------------------------------
# Case management — assignment, priority, due date
# ---------------------------------------------------------------------------

@router.patch("/{alert_id}/case", response_model=AlertResponse)
async def patch_case(
    alert_id: UUID,
    body: CaseUpdate,
    current_user: dict = Depends(verify_token),
    db: AsyncSession = Depends(get_db_session),
) -> AlertResponse:
    """Partial update of case fields: assigned_to, priority, due_date.

    To explicitly null a field, send it as null in JSON. To leave untouched,
    omit it. (Note: both map to Python None in Pydantic, so we use the
    `__fields_set__` introspection to distinguish.)
    """
    alert = await get_alert(db=db, alert_id=str(alert_id))
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")

    if body.priority is not None and body.priority not in VALID_PRIORITIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid priority. Must be one of: {VALID_PRIORITIES}",
        )

    actor = current_user.get("email") or current_user.get("sub") or "system"
    sent_fields = body.model_fields_set  # fields the client actually sent

    try:
        alert, _comments = await update_case_fields(
            db=db,
            alert=alert,
            actor=actor,
            assigned_to=body.assigned_to,
            priority=body.priority,
            due_date=body.due_date,
            clear_assigned=("assigned_to" in sent_fields and body.assigned_to is None),
            clear_due_date=("due_date" in sent_fields and body.due_date is None),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    await publish(CHANNEL_ALERT_UPDATED, {"alert_id": alert.id})
    return alert


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------

@router.get("/{alert_id}/comments", response_model=list[CommentResponse])
async def get_comments(
    alert_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> list[CommentResponse]:
    alert = await get_alert(db=db, alert_id=str(alert_id))
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    return await list_comments(db=db, alert_id=str(alert_id))


@router.post(
    "/{alert_id}/comments",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_comment(
    alert_id: UUID,
    body: CommentCreate,
    db: AsyncSession = Depends(get_db_session),
) -> CommentResponse:
    alert = await get_alert(db=db, alert_id=str(alert_id))
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    comment = await add_comment(
        db=db,
        alert_id=str(alert_id),
        author=body.author,
        body=body.body,
        kind="user",
    )
    # Publish alert.updated so any open dashboard can refresh its comment thread.
    await publish(CHANNEL_ALERT_UPDATED, {"alert_id": str(alert_id)})
    return comment


# ---------------------------------------------------------------------------
# Dev-only simulator (unchanged)
# ---------------------------------------------------------------------------

# Realistic-looking infringement URLs for each platform. The 'web' bucket
# uses a typo-squatted Sky Sports clone we built specifically for the demo.
_SAMPLE_INFRINGEMENT_URLS = {
    "web": [
        "https://sky-sp0rts-replays.netlify.app/match/ucl-final-2026",
        "https://sky-sp0rts-replays.netlify.app/highlights/champions-league",
        "https://sky-sp0rts-replays.netlify.app/replays/match-ucl-2026-04",
    ],
    "youtube": [
        "https://www.youtube.com/watch?v=ucl_final_pirate",
        "https://www.youtube.com/shorts/replay_2026_04",
    ],
    "tiktok": [
        "https://www.tiktok.com/@sportsleaks/video/7234567890",
        "https://www.tiktok.com/@matchhighlights/video/7234567891",
    ],
    "telegram": [
        "https://t.me/sportsreplays/12847",
        "https://t.me/footballhd/12848",
    ],
    "instagram": [
        "https://www.instagram.com/reel/CxYz123abc/",
    ],
}

_SAMPLE_PLATFORMS = list(_SAMPLE_INFRINGEMENT_URLS.keys())
_SAMPLE_MATCH_TYPES = ["fingerprint", "watermark", "both"]


@router.post(
    "/_simulate",
    response_model=AlertResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=True,
)
async def simulate_alert(
    db: AsyncSession = Depends(get_db_session),
    confidence: float | None = Query(
        default=None,
        ge=0.0,
        le=1.0,
        description="Override confidence. Random 0.55-0.99 if omitted.",
    ),
    platform: str | None = Query(default=None, description="Override platform."),
    match_type: str | None = Query(default=None, description="fingerprint | watermark | both"),
) -> AlertResponse:
    """Dev-only: create a synthetic alert and fire a match.created event.

    For the demo we pre-create a richer protected asset (Champions League
    highlights, sourced from Pexels stock footage) and generate alerts with
    realistic-looking infringement URLs — including our own typo-squatted
    Sky Sports clone (sky-sp0rts-replays.netlify.app) as a 'web' platform
    target.
    """
    if not get_settings().auth_disabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not found",
        )

    dummy_asset_id = "00000000-0000-0000-0000-0000000000a1"
    asset = await db.get(Asset, dummy_asset_id)
    if asset is None:
        asset = Asset(
            id=dummy_asset_id,
            title="UEFA Champions League Final — Highlights",
            description=(
                "Stock-footage rights asset used for piracy detection demo. "
                "Source: Pexels (Usman Abdulrasheed Gambo). "
                "Fingerprinted via perceptual hashing, watermarked via DCT."
            ),
            status="ready",
            fingerprint_status="ready",
            watermark_status="ready",
            source_url="https://www.pexels.com/video/aerial-view-of-youth-soccer-match-on-green-field-31370176/",
            video_path="/dev/null",
        )
        db.add(asset)
        await db.commit()

    chosen_confidence = confidence if confidence is not None else round(random.uniform(0.78, 0.97), 3)
    chosen_platform = platform or random.choice(_SAMPLE_PLATFORMS)
    chosen_match_type = match_type or random.choice(_SAMPLE_MATCH_TYPES)

    # Pick a realistic URL for the chosen platform; fall back to a synthetic
    # one if the platform isn't in our sample set.
    url_pool = _SAMPLE_INFRINGEMENT_URLS.get(chosen_platform)
    if url_pool:
        infringing_url = random.choice(url_pool)
    else:
        infringing_url = f"https://{chosen_platform}.example/watch/{uuid.uuid4().hex[:11]}"

    alert = await create_alert(
        db=db,
        data=AlertCreate(
            asset_id=UUID(dummy_asset_id),
            match_type=chosen_match_type,
            confidence=chosen_confidence,
            infringing_url=infringing_url,
            platform=chosen_platform,
        ),
    )

    await publish(
        CHANNEL_MATCH_CREATED,
        {
            "alert_id": alert.id,
            "asset_id": alert.asset_id,
            "severity": alert.severity_label,
            "platform": alert.platform,
            "confidence": alert.confidence,
            "detected_at": alert.created_at.isoformat() if alert.created_at else None,
        },
    )

    return alert