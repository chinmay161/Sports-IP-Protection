# app/api/alerts.py
import random
import uuid
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import verify_token
from app.core.config import get_settings
from app.db.session import get_db_session
from app.models.asset import Asset
from app.schemas.alert import AlertCreate, AlertResponse, AlertStatusUpdate, DMCARequest
from app.services.alert import (
    create_alert,
    generate_dmca_notice,
    get_alert,
    list_alerts,
    update_alert_status,
)
from app.services.events import CHANNEL_MATCH_CREATED, publish

router = APIRouter(
    prefix="/alerts",
    tags=["alerts"],
    dependencies=[Depends(verify_token)],
)


@router.post("", response_model=AlertResponse, status_code=status.HTTP_201_CREATED)
async def create_new_alert(
    data: AlertCreate,
    db: AsyncSession = Depends(get_db_session),
) -> AlertResponse:
    """Create a new infringement alert. Triggers AI scoring + email notification."""
    return await create_alert(db=db, data=data)


@router.get("", response_model=list[AlertResponse])
async def list_all_alerts(
    skip: int = 0,
    limit: int = 50,
    status: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
) -> list[AlertResponse]:
    """List all alerts. Filter by status or severity."""
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
    db: AsyncSession = Depends(get_db_session),
) -> AlertResponse:
    """Update alert status: open | acknowledged | dmca_initiated | resolved"""
    valid = {"open", "acknowledged", "dmca_initiated", "resolved"}
    if body.status not in valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status. Must be one of: {valid}",
        )
    alert = await update_alert_status(db=db, alert_id=str(alert_id), new_status=body.status)
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    return alert


@router.post("/{alert_id}/dmca", response_model=AlertResponse)
async def initiate_dmca(
    alert_id: UUID,
    body: DMCARequest,
    db: AsyncSession = Depends(get_db_session),
) -> AlertResponse:
    """One-click DMCA notice generation. Generates a formal takedown notice and marks alert."""
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
    return alert


# ---------------------------------------------------------------------------
# Dev-only simulator. Only exposed when AUTH_DISABLED=true.
# Creates a synthetic asset + alert in the DB and publishes a match.created
# event to Redis, exactly like the real matcher will do.
# ---------------------------------------------------------------------------

_SAMPLE_PLATFORMS = ["youtube", "tiktok", "telegram", "instagram", "twitter"]
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

    Disabled unless AUTH_DISABLED=true.
    """
    if not get_settings().auth_disabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not found",
        )

    # Ensure a dummy asset exists (create on first call, reuse afterwards).
    dummy_asset_id = "00000000-0000-0000-0000-0000000000a1"
    asset = await db.get(Asset, dummy_asset_id)
    if asset is None:
        asset = Asset(
            id=dummy_asset_id,
            title="Demo Match Highlight (Simulator)",
            description="Synthetic asset used by /alerts/_simulate.",
            status="ready",
            fingerprint_status="ready",
            watermark_status="ready",
            video_path="/dev/null",
        )
        db.add(asset)
        await db.commit()

    chosen_confidence = confidence if confidence is not None else round(random.uniform(0.55, 0.99), 3)
    chosen_platform = platform or random.choice(_SAMPLE_PLATFORMS)
    chosen_match_type = match_type or random.choice(_SAMPLE_MATCH_TYPES)

    fake_url = f"https://{chosen_platform}.example/watch/{uuid.uuid4().hex[:11]}"

    alert = await create_alert(
        db=db,
        data=AlertCreate(
            asset_id=UUID(dummy_asset_id),
            match_type=chosen_match_type,
            confidence=chosen_confidence,
            infringing_url=fake_url,
            platform=chosen_platform,
        ),
    )

    # Publish the minimal event payload. The subscriber will fetch the full
    # alert from the DB and broadcast to every connected WebSocket.
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