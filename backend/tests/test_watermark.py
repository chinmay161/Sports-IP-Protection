import asyncio
import base64
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

import numpy as np
import pytest
from PIL import Image

from app.services.watermark import WatermarkService, calculate_psnr, lookup_asset_id_by_payload


KEY_A = b"watermark-key-a" * 3
KEY_B = b"watermark-key-b" * 3


def _random_frame(width: int = 512, height: int = 512) -> np.ndarray:
    rng = np.random.default_rng(12345)
    return rng.integers(0, 256, size=(height, width, 3), dtype=np.uint8)


def test_embed_extract_roundtrip() -> None:
    frame = _random_frame()

    watermarked = WatermarkService.embed(frame, payload=0xDEADBEEF, key=KEY_A)
    payload, confidence = WatermarkService.extract(watermarked, key=KEY_A)

    assert payload == 0xDEADBEEF
    assert confidence >= 0.95


def test_psnr_above_threshold() -> None:
    rng = np.random.default_rng(222)
    frame = rng.integers(0, 256, size=(1080, 1920, 3), dtype=np.uint8)

    watermarked = WatermarkService.embed(frame, payload=42, key=KEY_A, alpha=8)

    assert calculate_psnr(frame, watermarked) >= 38.0


def test_survives_jpeg_compression() -> None:
    frame = _random_frame()
    watermarked = WatermarkService.embed(frame, payload=0x1234ABCD, key=KEY_A)
    buffer = BytesIO()
    Image.fromarray(watermarked).save(buffer, format="JPEG", quality=75)
    buffer.seek(0)
    compressed = np.asarray(Image.open(buffer).convert("RGB"), dtype=np.uint8)

    payload, confidence = WatermarkService.extract(compressed, key=KEY_A)

    assert payload == 0x1234ABCD
    assert confidence >= 0.7


def test_survives_50pct_resize() -> None:
    frame = _random_frame()
    watermarked = WatermarkService.embed(frame, payload=0xFACECAFE, key=KEY_A)
    resized = Image.fromarray(watermarked).resize((256, 256), Image.Resampling.LANCZOS)

    payload, confidence = WatermarkService.extract(np.asarray(resized.convert("RGB"), dtype=np.uint8), key=KEY_A)

    assert payload == 0xFACECAFE
    assert confidence >= 0.7


def test_wrong_key_returns_noise() -> None:
    frame = _random_frame()
    watermarked = WatermarkService.embed(frame, payload=0xDEADBEEF, key=KEY_A)

    _, confidence = WatermarkService.extract(watermarked, key=KEY_B)

    assert confidence < 0.55


class FakeDetectionService(WatermarkService):
    def __init__(self, pairs: list[tuple[int, float]], asset_id: UUID | None = None) -> None:
        self.pairs = pairs
        self.lookup_payloads: list[int] = []
        self.asset_id = asset_id
        super().__init__()

    async def _download_clip(self, url: str, output_path: Path) -> None:
        assert url == "https://example.test/leak.mp4"

    async def _extract_detection_frames(self, clip_path: Path, frames_dir: Path, limit: int = 10) -> list[Path]:
        return [frames_dir / f"frame_{index}.png" for index in range(len(self.pairs))]

    async def _lookup_asset_id(self, payload: int) -> UUID | None:
        self.lookup_payloads.append(payload)
        return self.asset_id

    async def _run_blocking(self, func, *args, **kwargs):
        if getattr(func, "__name__", "") == "_read_rgb_frame":
            return np.zeros((256, 256, 3), dtype=np.uint8)
        return func(*args, **kwargs)

    def extract(self, frame: np.ndarray, key: bytes) -> tuple[int, float]:
        return self.pairs.pop(0)


def test_low_confidence_frames_discarded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.watermark.TEMP_ROOT", tmp_path)
    asset_id = uuid4()
    pairs = [(42, 0.9), (42, 0.8), (42, 0.7), (42, 0.66), (99, 0.4), (99, 0.5), (99, 0.55), (99, 0.2)]
    service = FakeDetectionService(pairs=pairs, asset_id=asset_id)

    detection = asyncio.run(service.detect_from_url("https://example.test/leak.mp4", KEY_A))

    assert detection is not None
    assert detection.payload == 42
    assert detection.frames_agreed == 4
    assert service.lookup_payloads == [42]


def test_majority_vote_resolves_correct_payload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.watermark.TEMP_ROOT", tmp_path)
    asset_id = uuid4()
    pairs = [(42, 0.8)] * 5 + [(99, 0.9)] * 2
    service = FakeDetectionService(pairs=pairs, asset_id=asset_id)

    detection = asyncio.run(service.detect_from_url("https://example.test/leak.mp4", KEY_A))

    assert detection is not None
    assert detection.payload == 42
    assert detection.asset_id == asset_id


class FakeScalarResult:
    def __init__(self, item) -> None:
        self.item = item

    def scalar_one_or_none(self):
        return self.item


class FakeRegistry:
    def __init__(self, asset_id: str) -> None:
        self.asset_id = asset_id


class FakeSession:
    def __init__(self, item) -> None:
        self.item = item

    async def execute(self, statement):
        assert statement is not None
        return FakeScalarResult(self.item)


def test_registry_lookup_returns_asset_id() -> None:
    asset_id = uuid4()

    result = asyncio.run(lookup_asset_id_by_payload(FakeSession(FakeRegistry(str(asset_id))), 42))

    assert result == asset_id


def test_registry_lookup_returns_none_when_missing() -> None:
    result = asyncio.run(lookup_asset_id_by_payload(FakeSession(None), 42))

    assert result is None


def test_watermark_worker_status_transitions(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = pytest.importorskip("app.workers.watermark_task")
    asset_id = str(uuid4())
    asset = type(
        "AssetStub",
        (),
        {
            "id": asset_id,
            "status": "pending",
            "fingerprint_status": "ready",
            "watermark_status": "pending",
            "video_path": "clip.mp4",
        },
    )()

    class Session:
        commits = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def get(self, model, requested_id: str):
            assert requested_id == asset_id
            return asset

        async def commit(self) -> None:
            self.commits += 1

    async def fake_embed_video(self, video_path: str, asset_id: UUID, payload: int, key: bytes, alpha: int):
        assert video_path == "clip.mp4"
        assert payload == 7
        assert alpha == 8

    monkeypatch.setenv("WATERMARK_SECRET_KEY", base64.b64encode(KEY_A).decode("ascii"))
    worker.get_settings.cache_clear()
    monkeypatch.setattr(worker, "SessionLocal", lambda: Session())
    monkeypatch.setattr(worker.WatermarkService, "embed_video", fake_embed_video)

    result = asyncio.run(worker._watermark_asset_impl(asset_id=asset_id, payload=7, alpha=8))

    assert result == {"asset_id": asset_id, "status": "ready"}
    assert asset.watermark_status == "ready"
    assert asset.status == "ready"
