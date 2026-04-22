# app/services/alert.py
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert
from app.models.asset import Asset
from app.schemas.alert import AlertCreate
from app.services.email import send_alert_email
from app.services.severity import compute_severity

logger = logging.getLogger(__name__)


async def create_alert(db: AsyncSession, data: AlertCreate) -> Alert:
    """Create an alert, score severity via AI, send email notification."""

    # Fetch asset title for context
    asset = await db.get(Asset, str(data.asset_id))
    asset_title = asset.title if asset else "Unknown Asset"

    # AI severity scoring
    score, label, reasoning = await compute_severity(
        match_type=data.match_type,
        confidence=data.confidence,
        infringing_url=data.infringing_url,
        platform=data.platform,
        asset_title=asset_title,
    )

    alert = Alert(
        id=str(uuid.uuid4()),
        asset_id=str(data.asset_id),
        match_type=data.match_type,
        confidence=data.confidence,
        infringing_url=data.infringing_url,
        platform=data.platform,
        severity_score=score,
        severity_label=label,
        ai_reasoning=reasoning,
        status="open",
        notified_email=False,
    )
    db.add(alert)
    await db.commit()
    await db.refresh(alert)

    # Send email notification in background (non-blocking)
    try:
        sent = send_alert_email(
            asset_title=asset_title,
            infringing_url=data.infringing_url,
            severity_label=label,
            confidence=data.confidence,
            match_type=data.match_type,
            platform=data.platform,
            ai_reasoning=reasoning,
            alert_id=alert.id,
        )
        if sent:
            alert.notified_email = True
            await db.commit()
    except Exception as exc:
        logger.warning("Email notification failed for alert %s: %s", alert.id, exc)

    return alert


async def list_alerts(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 50,
    status: str | None = None,
    severity: str | None = None,
) -> list[Alert]:
    query = select(Alert).order_by(Alert.created_at.desc())
    if status:
        query = query.where(Alert.status == status)
    if severity:
        query = query.where(Alert.severity_label == severity)
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_alert(db: AsyncSession, alert_id: str) -> Alert | None:
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    return result.scalar_one_or_none()


async def update_alert_status(
    db: AsyncSession, alert_id: str, new_status: str
) -> Alert | None:
    alert = await get_alert(db, alert_id)
    if alert is None:
        return None
    alert.status = new_status
    await db.commit()
    await db.refresh(alert)
    return alert


async def generate_dmca_notice(
    db: AsyncSession,
    alert_id: str,
    asset_owner: str,
    contact_email: str,
) -> Alert | None:
    alert = await get_alert(db, alert_id)
    if alert is None:
        return None

    asset = await db.get(Asset, alert.asset_id)
    asset_title = asset.title if asset else "Unknown Asset"

    notice = f"""DMCA TAKEDOWN NOTICE
====================
Date: {alert.created_at.strftime('%B %d, %Y')}

TO WHOM IT MAY CONCERN,

I, {asset_owner}, am the copyright owner of the media content titled:
"{asset_title}"

I have discovered that the following URL is hosting or distributing this 
content without authorization:

Infringing URL: {alert.infringing_url}
Platform: {alert.platform or "Unknown"}
Match Type: {alert.match_type}
Detection Confidence: {alert.confidence * 100:.1f}%

This content is protected under copyright law. I hereby request that you 
immediately remove or disable access to the infringing material.

I declare under penalty of perjury that I am the copyright owner or 
authorized to act on behalf of the copyright owner.

Contact: {contact_email}
Alert Reference ID: {alert.id}

Sincerely,
{asset_owner}
"""

    alert.dmca_notice = notice
    alert.status = "dmca_initiated"
    await db.commit()
    await db.refresh(alert)
    return alert