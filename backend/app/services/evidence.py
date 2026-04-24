from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    Image,
    LongTable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from PIL import Image as PILImage
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import storage
from app.models.evidence import EvidencePackage as EvidencePackageModel
from app.models.match import Match, MatchSegment


class EvidenceError(Exception):
    """Permanent evidence generation failure."""


class EvidenceTransientError(EvidenceError):
    """Retryable evidence generation failure."""


@dataclass(slots=True)
class EvidencePackage:
    match_id: str
    pdf_s3_key: str
    manifest_s3_key: str
    package_hash: str
    thumbnail_count: int


@dataclass(slots=True)
class _ThumbnailEntry:
    segment_id: str
    s3_key: str
    local_path: Path
    sha256: str


SEVERITY_COLORS = {
    "low": colors.HexColor("#2E7D32"),
    "medium": colors.HexColor("#F9A825"),
    "high": colors.HexColor("#EF6C00"),
    "critical": colors.HexColor("#C62828"),
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extract_thumbnail(match: Match, segment: MatchSegment, local_path: Path) -> None:
    midpoint_seconds = ((segment.source_start_ms + segment.source_end_ms) / 2) / 1000
    local_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                f"{midpoint_seconds:.3f}",
                "-i",
                match.source_url,
                "-frames:v",
                "1",
                str(local_path),
            ],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise EvidenceTransientError(f"Failed to extract thumbnail for segment {segment.id}") from exc


def _build_manifest(
    match: Match,
    thumbnails: list[_ThumbnailEntry],
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    thumbnail_by_segment = {entry.segment_id: entry for entry in thumbnails}
    manifest: dict[str, Any] = {
        "match_id": match.id,
        "asset_id": match.asset_id,
        "asset_title": match.asset.title if match.asset else "",
        "rights_owner": match.asset.title if match.asset else "",
        "source_url": match.source_url,
        "platform": match.platform,
        "severity": match.severity,
        "confidence": match.confidence,
        "match_type": match.match_type,
        "status": match.status,
        "detected_at": match.detected_at.isoformat() if match.detected_at else None,
        "generated_at": generated_at.isoformat(),
        "original_asset_s3_key": match.asset.video_path if match.asset else None,
        "segments": [],
    }
    for segment in sorted(match.segments, key=lambda item: item.source_start_ms):
        thumbnail = thumbnail_by_segment.get(segment.id)
        manifest["segments"].append(
            {
                "id": segment.id,
                "asset_start_ms": segment.asset_start_ms,
                "asset_end_ms": segment.asset_end_ms,
                "source_start_ms": segment.source_start_ms,
                "source_end_ms": segment.source_end_ms,
                "frame_run_length": segment.frame_run_length,
                "audio_confidence": segment.audio_confidence,
                "thumbnail_s3_key": thumbnail.s3_key if thumbnail else segment.thumbnail_s3_key,
                "thumbnail_sha256": thumbnail.sha256 if thumbnail else None,
            }
        )
    pre_hash = json.dumps(manifest, indent=2).encode("utf-8")
    manifest["manifest_sha256"] = hashlib.sha256(pre_hash).hexdigest()
    return manifest


def _write_manifest(path: Path, manifest: dict[str, Any]) -> str:
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return str(manifest["manifest_sha256"])


class _PageCountCanvas(Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict[str, Any]] = []

    def showPage(self) -> None:
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        page_count = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            _draw_header_footer(self, page_count)
            super().showPage()
        super().save()


def _draw_header_footer(canvas, page_count: int) -> None:
    width, height = A4
    canvas.saveState()
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawString(2 * cm, height - 1.3 * cm, "Sports IP Protection Evidence Package")
    canvas.setFont("Helvetica", 9)
    canvas.drawRightString(
        width - 2 * cm,
        1.2 * cm,
        f"Page {canvas.getPageNumber()} of {page_count}",
    )
    canvas.restoreState()


def _thumbnail_flowable(path: Path):
    try:
        with PILImage.open(path) as image:
            image.verify()
        return Image(str(path), width=5.2 * cm, height=3.0 * cm, kind="proportional")
    except Exception:
        table = Table(
            [[Paragraph("Thumbnail unavailable", ParagraphStyle("placeholder", alignment=TA_CENTER))]],
            colWidths=[5.2 * cm],
            rowHeights=[3.0 * cm],
        )
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EEEEEE")),
                    ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#666666")),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#BBBBBB")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ]
            )
        )
        return table


def _write_pdf(path: Path, match: Match, thumbnails: list[_ThumbnailEntry], manifest: dict[str, Any]) -> None:
    styles = getSampleStyleSheet()
    story: list[Any] = []
    title_style = ParagraphStyle(
        "EvidenceTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=18,
        spaceAfter=14,
    )
    badge_style = ParagraphStyle(
        "Badge",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        textColor=colors.white,
        alignment=TA_CENTER,
    )

    story.append(Paragraph("Copyright Evidence Package", title_style))
    story.append(Paragraph(f"Match ID: <font name='Courier'>{match.id}</font>", styles["Normal"]))
    story.append(Spacer(1, 0.35 * cm))

    severity_color = SEVERITY_COLORS.get(match.severity, colors.HexColor("#555555"))
    badge = Table(
        [[Paragraph(match.severity.upper(), badge_style)]],
        colWidths=[3.2 * cm],
        rowHeights=[0.7 * cm],
    )
    badge.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), severity_color),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.append(badge)
    story.append(Spacer(1, 0.45 * cm))

    summary = [
        ["Asset", match.asset.title if match.asset else ""],
        ["Rights owner", match.asset.title if match.asset else ""],
        ["Original asset S3 key", match.asset.video_path if match.asset else ""],
        ["Source URL", match.source_url],
        ["Platform", match.platform],
        ["Confidence", f"{match.confidence:.3f}"],
        ["Package manifest SHA-256", manifest["manifest_sha256"]],
    ]
    table = LongTable(summary, colWidths=[4.0 * cm, 12.0 * cm])
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CCCCCC")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(table)
    story.append(PageBreak())

    story.append(Paragraph("Matched Segments", styles["Heading1"]))
    thumbnail_by_segment = {entry.segment_id: entry for entry in thumbnails}
    for segment in sorted(match.segments, key=lambda item: item.source_start_ms):
        thumb = thumbnail_by_segment.get(segment.id)
        rows = [
            ["Segment ID", segment.id],
            ["Asset range", f"{segment.asset_start_ms}ms - {segment.asset_end_ms}ms"],
            ["Source range", f"{segment.source_start_ms}ms - {segment.source_end_ms}ms"],
            ["Frame run length", str(segment.frame_run_length)],
            ["Thumbnail SHA-256", thumb.sha256 if thumb else ""],
        ]
        meta = LongTable(rows, colWidths=[3.0 * cm, 7.0 * cm])
        meta.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#DDDDDD")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        story.append(
            Table(
                [[meta, _thumbnail_flowable(thumb.local_path) if thumb else _thumbnail_flowable(Path(""))]],
                colWidths=[10.5 * cm, 5.5 * cm],
            )
        )
        story.append(Spacer(1, 0.45 * cm))

    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )
    doc.build(story, canvasmaker=_PageCountCanvas)


class EvidenceService:
    async def generate(self, match_id: str, db: AsyncSession) -> EvidencePackage:
        existing = await db.execute(
            select(EvidencePackageModel).where(EvidencePackageModel.match_id == match_id)
        )
        if existing.scalar_one_or_none() is not None:
            raise EvidenceError(f"Evidence package already exists for match {match_id}")

        work_dir = Path(f"/tmp/sports-ip/evidence_{match_id}")
        try:
            work_dir.mkdir(parents=True, exist_ok=True)
            result = await db.execute(
                select(Match)
                .options(selectinload(Match.segments), selectinload(Match.asset))
                .where(Match.id == match_id)
            )
            match = result.scalar_one_or_none()
            if match is None:
                raise EvidenceError(f"Match {match_id} not found")
            if match.status != "dmca_sent":
                raise EvidenceError(f"Match {match_id} is not dmca_sent")

            thumbnails = await self._prepare_thumbnails(match, work_dir)
            manifest = _build_manifest(match, thumbnails)
            manifest_path = work_dir / "manifest.json"
            manifest_sha256 = _write_manifest(manifest_path, manifest)
            pdf_path = work_dir / "evidence.pdf"
            _write_pdf(pdf_path, match, thumbnails, manifest)
            pdf_sha256 = _sha256_file(pdf_path)
            package_hash = hashlib.sha256(
                manifest_sha256.encode("utf-8") + pdf_sha256.encode("utf-8")
            ).hexdigest()

            manifest_key = f"evidence/{match_id}/manifest.json"
            pdf_key = f"evidence/{match_id}/evidence.pdf"
            try:
                storage.upload_file(manifest_path, manifest_key)
                storage.upload_file(pdf_path, pdf_key)
            except Exception as exc:
                raise EvidenceError(f"Failed to upload evidence package for match {match_id}") from exc

            package_row = EvidencePackageModel(
                match_id=match.id,
                asset_id=match.asset_id,
                manifest_s3_key=manifest_key,
                pdf_s3_key=pdf_key,
                package_hash=package_hash,
                thumbnail_count=len(thumbnails),
            )
            match.status = "resolved"
            match.resolved_at = datetime.now(UTC)
            db.add(package_row)
            try:
                await db.commit()
            except IntegrityError as exc:
                await db.rollback()
                raise EvidenceError(f"Evidence package already exists for match {match_id}") from exc

            return EvidencePackage(
                match_id=match.id,
                pdf_s3_key=pdf_key,
                manifest_s3_key=manifest_key,
                package_hash=package_hash,
                thumbnail_count=len(thumbnails),
            )
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    async def _prepare_thumbnails(self, match: Match, work_dir: Path) -> list[_ThumbnailEntry]:
        thumbnails: list[_ThumbnailEntry] = []
        thumb_dir = work_dir / "thumbnails"
        for segment in sorted(match.segments, key=lambda item: item.source_start_ms):
            local_path = thumb_dir / f"{segment.id}.jpg"
            if segment.thumbnail_s3_key:
                try:
                    storage.download_file(segment.thumbnail_s3_key, local_path)
                except Exception as exc:
                    raise EvidenceError(f"Failed to download thumbnail for segment {segment.id}") from exc
                s3_key = segment.thumbnail_s3_key
            else:
                _extract_thumbnail(match, segment, local_path)
                s3_key = f"thumbnails/{match.id}/{segment.id}.jpg"
                try:
                    storage.upload_file(local_path, s3_key)
                except Exception as exc:
                    raise EvidenceError(f"Failed to upload thumbnail for segment {segment.id}") from exc
                segment.thumbnail_s3_key = s3_key
            thumbnails.append(
                _ThumbnailEntry(
                    segment_id=segment.id,
                    s3_key=s3_key,
                    local_path=local_path,
                    sha256=_sha256_file(local_path),
                )
            )
        return thumbnails

    async def get_download_url(
        self,
        match_id: str,
        db: AsyncSession,
        expires_in: int = 3600,
    ) -> dict[str, str | int]:
        result = await db.execute(
            select(EvidencePackageModel).where(EvidencePackageModel.match_id == match_id)
        )
        package = result.scalar_one_or_none()
        if package is None:
            raise EvidenceError(f"Evidence package not found for match {match_id}")
        try:
            return {
                "download_url": storage.generate_presigned_url(package.pdf_s3_key, expires_in),
                "expires_in": expires_in,
            }
        except Exception as exc:
            raise EvidenceError(f"Failed to generate download URL for match {match_id}") from exc


async def generate(match_id: str, db: AsyncSession) -> EvidencePackage:
    return await EvidenceService().generate(match_id, db)


async def get_download_url(
    match_id: str,
    db: AsyncSession,
    expires_in: int = 3600,
) -> dict[str, str | int]:
    return await EvidenceService().get_download_url(match_id, db, expires_in)
