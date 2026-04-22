# app/api/alerts.py
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import verify_token
from app.db.session import get_db_session
from app.schemas.alert import AlertCreate, AlertResponse, AlertStatusUpdate, DMCARequest
from app.services.alert import (
    create_alert,
    generate_dmca_notice,
    get_alert,
    list_alerts,
    update_alert_status,
)

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
