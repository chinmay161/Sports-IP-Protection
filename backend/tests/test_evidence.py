from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from app.core.auth import verify_token
from app.db.base import Base
from app.db.session import get_db_session
from app.main import app
from app.models.alert import Alert  # noqa: F401
from app.models.asset import Asset
from app.models.evidence import EvidencePackage as EvidencePackageModel
from app.models.match import Match, MatchNote, MatchSegment  # noqa: F401
from app.models.watermark import WatermarkRegistry  # noqa: F401
from app.services import evidence
from app.services.evidence import EvidenceError, EvidenceService

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'evidence.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield Session
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def client(session_factory):
    async def override_session():
        async with session_factory() as session:
            yield session

    async def override_token():
        return {"sub": "test"}

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[verify_token] = override_token
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.clear()


@pytest.fixture
def fake_storage(monkeypatch: pytest.MonkeyPatch):
    uploads: dict[str, bytes] = {}

    def upload_file(local_path, s3_key: str) -> None:
        uploads[s3_key] = Path(local_path).read_bytes()

    def download_file(s3_key: str, local_path) -> None:
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        Path(local_path).write_bytes(f"downloaded:{s3_key}".encode("utf-8"))

    def generate_presigned_url(s3_key: str, expires_in: int = 3600) -> str:
        return f"https://storage.test/{s3_key}?expires={expires_in}"

    monkeypatch.setattr(evidence.storage, "upload_file", upload_file)
    monkeypatch.setattr(evidence.storage, "download_file", download_file)
    monkeypatch.setattr(evidence.storage, "generate_presigned_url", generate_presigned_url)
    return uploads


@pytest.fixture
def fake_ffmpeg(monkeypatch: pytest.MonkeyPatch):
    def extract_thumbnail(match: Match, segment: MatchSegment, local_path: Path) -> None:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(b"fake-image")

    monkeypatch.setattr(evidence, "_extract_thumbnail", extract_thumbnail)


async def _asset(db: AsyncSession) -> Asset:
    asset = Asset(
        id=str(uuid4()),
        title="Premier League Final",
        description=None,
        status="ready",
        fingerprint_status="ready",
        watermark_status="ready",
        video_path="assets/original.mp4",
    )
    db.add(asset)
    await db.flush()
    return asset


async def _match(db: AsyncSession, asset_id: str, *, status: str = "dmca_sent") -> Match:
    match = Match(
        id=str(uuid4()),
        asset_id=asset_id,
        source_url="https://example.test/infringing.mp4",
        platform="web",
        confidence=0.93,
        match_type="fingerprint",
        severity="critical",
        duration_matched_ms=5000,
        status=status,
        detected_at=datetime(2026, 4, 24, 12, 0, tzinfo=UTC),
    )
    db.add(match)
    await db.flush()
    db.add_all(
        [
            MatchSegment(
                match_id=match.id,
                asset_start_ms=0,
                asset_end_ms=1000,
                source_start_ms=100,
                source_end_ms=1100,
                frame_run_length=12,
            ),
            MatchSegment(
                match_id=match.id,
                asset_start_ms=2000,
                asset_end_ms=3000,
                source_start_ms=5100,
                source_end_ms=6100,
                frame_run_length=8,
            ),
        ]
    )
    await db.flush()
    return match


async def test_generate_creates_pdf_hash_row_and_resolves_match(
    session_factory,
    fake_storage,
    fake_ffmpeg,
):
    async with session_factory() as db:
        asset = await _asset(db)
        match = await _match(db, asset.id)
        await db.commit()

        package = await EvidenceService().generate(match.id, db)

        assert package.pdf_s3_key.endswith("evidence.pdf")
        assert len(package.package_hash) == 64
        int(package.package_hash, 16)

        row = (
            await db.execute(
                select(EvidencePackageModel).where(EvidencePackageModel.match_id == match.id)
            )
        ).scalar_one()
        assert row.pdf_s3_key == package.pdf_s3_key
        assert row.package_hash == package.package_hash
        assert (await db.get(Match, match.id)).status == "resolved"
        assert fake_storage[package.pdf_s3_key].startswith(b"%PDF")


async def test_generate_rejects_non_dmca_sent_match(session_factory, fake_storage, fake_ffmpeg):
    async with session_factory() as db:
        asset = await _asset(db)
        match = await _match(db, asset.id, status="acknowledged")
        await db.commit()

        with pytest.raises(EvidenceError):
            await EvidenceService().generate(match.id, db)


async def test_manifest_contains_segments_and_thumbnail_hash(
    session_factory,
    fake_storage,
    fake_ffmpeg,
):
    async with session_factory() as db:
        asset = await _asset(db)
        match = await _match(db, asset.id)
        await db.commit()

        package = await EvidenceService().generate(match.id, db)
        manifest = json.loads(fake_storage[package.manifest_s3_key])

        assert len(manifest["segments"]) == 2
        assert manifest["segments"][0]["thumbnail_sha256"] == evidence.hashlib.sha256(b"fake-image").hexdigest()
        assert manifest["manifest_sha256"]


async def test_manifest_sha256_is_stable_with_fixed_timestamp(session_factory):
    async with session_factory() as db:
        asset = await _asset(db)
        match = await _match(db, asset.id)
        await db.commit()
        result = await db.execute(
            select(Match)
            .options(selectinload(Match.asset), selectinload(Match.segments))
            .where(Match.id == match.id)
        )
        loaded_match = result.scalar_one()

        fixed = datetime(2026, 4, 24, 13, 0, tzinfo=UTC)
        thumb = evidence._ThumbnailEntry(
            segment_id=loaded_match.segments[0].id,
            s3_key="thumb.jpg",
            local_path=Path("thumb.jpg"),
            sha256="a" * 64,
        )
        first = evidence._build_manifest(loaded_match, [thumb], generated_at=fixed)
        second = evidence._build_manifest(loaded_match, [thumb], generated_at=fixed)

        assert first["manifest_sha256"] == second["manifest_sha256"]


async def test_download_url_success_and_missing_failure(session_factory, fake_storage):
    async with session_factory() as db:
        asset = await _asset(db)
        match = await _match(db, asset.id)
        db.add(
            EvidencePackageModel(
                match_id=match.id,
                asset_id=asset.id,
                manifest_s3_key="evidence/pkg/manifest.json",
                pdf_s3_key="evidence/pkg/evidence.pdf",
                package_hash="b" * 64,
                thumbnail_count=0,
            )
        )
        await db.commit()

        payload = await EvidenceService().get_download_url(match.id, db)
        assert payload == {
            "download_url": "https://storage.test/evidence/pkg/evidence.pdf?expires=3600",
            "expires_in": 3600,
        }

        with pytest.raises(EvidenceError):
            await EvidenceService().get_download_url(str(uuid4()), db)


async def test_endpoint_202_while_generating(client, session_factory):
    async with session_factory() as db:
        asset = await _asset(db)
        match = await _match(db, asset.id, status="dmca_sent")
        await db.commit()

    response = await client.get(f"/detections/{match.id}/evidence")
    assert response.status_code == 202
    assert response.json() == {"status": "generating"}


async def test_endpoint_200_when_ready(client, session_factory, fake_storage):
    async with session_factory() as db:
        asset = await _asset(db)
        match = await _match(db, asset.id, status="resolved")
        db.add(
            EvidencePackageModel(
                match_id=match.id,
                asset_id=asset.id,
                manifest_s3_key="evidence/ready/manifest.json",
                pdf_s3_key="evidence/ready/evidence.pdf",
                package_hash="c" * 64,
                thumbnail_count=0,
            )
        )
        await db.commit()

    response = await client.get(f"/detections/{match.id}/evidence")
    assert response.status_code == 200
    assert response.json() == {
        "download_url": "https://storage.test/evidence/ready/evidence.pdf?expires=3600",
        "expires_in": 3600,
    }
