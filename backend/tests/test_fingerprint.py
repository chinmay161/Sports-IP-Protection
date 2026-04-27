import asyncio
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.services.fingerprint import (
    AUDIO_HOP_MS,
    FRAME_INTERVAL_MS,
    FingerprintService,
    FingerprintVector,
    MatchPoint,
    detect_consecutive_runs,
)


class FakeHit:
    def __init__(self, asset_id: str, timestamp_ms: int, distance: int) -> None:
        self.distance = distance
        self.entity = {"asset_id": asset_id, "timestamp_ms": timestamp_ms}


class FakeCollection:
    def __init__(self) -> None:
        self.insert_payloads: list[dict[str, list[object]]] = []
        self.search_requests: list[dict[str, object]] = []
        self.search_responses: list[list[list[FakeHit]]] = []
        self.deleted: list[str] = []
        self.flushed = 0

    def insert(self, payload: dict[str, list[object]]) -> None:
        self.insert_payloads.append(payload)

    def flush(self) -> None:
        self.flushed += 1

    def delete(self, expression: str) -> None:
        self.deleted.append(expression)

    def search(self, **kwargs):
        self.search_requests.append(kwargs)
        if self.search_responses:
            return self.search_responses.pop(0)
        return [[]]


def test_generate_returns_correct_frame_count(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    collection = FakeCollection()
    service = FingerprintService(collection=collection)
    asset_id = uuid4()

    async def fake_probe(_: str) -> int:
        return 3000

    async def fake_extract_frames(_: str, frames_dir: Path) -> list[Path]:
        paths = [frames_dir / f"frame_{index:06d}.jpg" for index in range(3)]
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"frame")
        return paths

    async def fake_hash_frames(frame_paths: list[Path]) -> list[FingerprintVector]:
        return [
            FingerprintVector(timestamp_ms=index * FRAME_INTERVAL_MS, vector=b"\x01" * 8, kind="frame")
            for index, _ in enumerate(frame_paths)
        ]

    async def fake_extract_audio(_: str, audio_path: Path) -> None:
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        audio_path.write_bytes(b"audio")

    async def fake_has_audio(_: str) -> bool:
        return True

    async def fake_fingerprint_audio(_: Path) -> list[FingerprintVector]:
        return []

    monkeypatch.setattr(service, "_probe_duration_ms", fake_probe)
    monkeypatch.setattr(service, "_extract_frames", fake_extract_frames)
    monkeypatch.setattr(service, "_hash_frames", fake_hash_frames)
    monkeypatch.setattr(service, "_has_audio_stream", fake_has_audio)
    monkeypatch.setattr(service, "_extract_audio", fake_extract_audio)
    monkeypatch.setattr(service, "_fingerprint_audio", fake_fingerprint_audio)
    service.settings.temp_root = tmp_path

    result = asyncio.run(service.generate(video_path="clip.mp4", asset_id=asset_id))

    assert result.frame_count == 3
    assert result.audio_window_count == 0
    assert result.duration_ms == 3000
    assert [row["asset_id"] for row in collection.insert_payloads[0]] == [str(asset_id)] * 3


def test_generate_skips_audio_for_video_without_audio_stream(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    collection = FakeCollection()
    service = FingerprintService(collection=collection)
    asset_id = uuid4()

    async def fake_probe(_: str) -> int:
        return 1000

    async def fake_extract_frames(_: str, frames_dir: Path) -> list[Path]:
        frame_path = frames_dir / "frame_000000.jpg"
        frame_path.parent.mkdir(parents=True, exist_ok=True)
        frame_path.write_bytes(b"frame")
        return [frame_path]

    async def fake_hash_frames(_: list[Path]) -> list[FingerprintVector]:
        return [FingerprintVector(timestamp_ms=0, vector=b"\x01" * 8, kind="frame")]

    async def fake_has_audio(_: str) -> bool:
        return False

    async def fail_extract_audio(_: str, audio_path: Path) -> None:
        raise AssertionError("audio extraction should be skipped")

    monkeypatch.setattr(service, "_probe_duration_ms", fake_probe)
    monkeypatch.setattr(service, "_extract_frames", fake_extract_frames)
    monkeypatch.setattr(service, "_hash_frames", fake_hash_frames)
    monkeypatch.setattr(service, "_has_audio_stream", fake_has_audio)
    monkeypatch.setattr(service, "_extract_audio", fail_extract_audio)
    service.settings.temp_root = tmp_path

    result = asyncio.run(service.generate(video_path="silent.mp4", asset_id=asset_id))

    assert result.frame_count == 1
    assert result.audio_window_count == 0
    assert collection.insert_payloads[0][0]["type"] == "frame"


def test_match_finds_reencoded_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    collection = FakeCollection()
    service = FingerprintService(collection=collection)
    asset_id = str(uuid4())

    frame_vectors = [
        FingerprintVector(timestamp_ms=index * FRAME_INTERVAL_MS, vector=bytes([index % 256]) * 8, kind="frame")
        for index in range(30)
    ]
    audio_vectors = [
        FingerprintVector(timestamp_ms=index * AUDIO_HOP_MS, vector=bytes([(index + 1) % 256]) * 8, kind="audio")
        for index in range(12)
    ]

    async def fake_extract(*, video_path: str, asset_key: str):
        assert video_path == "reencoded.mp4"
        assert asset_key.startswith("candidate-")
        return frame_vectors, audio_vectors, 30000

    monkeypatch.setattr(service, "_extract_fingerprints", fake_extract)
    collection.search_responses = [
        [[FakeHit(asset_id=asset_id, timestamp_ms=vector.timestamp_ms, distance=2)]]
        for vector in frame_vectors + audio_vectors
    ]

    matches = asyncio.run(service.match(video_path="reencoded.mp4"))

    assert matches
    assert matches[0].asset_id == UUID(asset_id)
    assert matches[0].confidence > 0.85


def test_match_ignores_short_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    collection = FakeCollection()
    service = FingerprintService(collection=collection)
    asset_id = str(uuid4())

    frame_vectors = [
        FingerprintVector(timestamp_ms=index * FRAME_INTERVAL_MS, vector=bytes([7]) * 8, kind="frame")
        for index in range(4)
    ]

    async def fake_extract(*, video_path: str, asset_key: str):
        assert video_path == "candidate.mp4"
        return frame_vectors, [], 20000

    monkeypatch.setattr(service, "_extract_fingerprints", fake_extract)
    collection.search_responses = [
        [[FakeHit(asset_id=asset_id, timestamp_ms=vector.timestamp_ms, distance=1)]]
        for vector in frame_vectors
    ]

    matches = asyncio.run(service.match(video_path="candidate.mp4"))

    assert matches == []


def test_match_accepts_short_dense_frame_run(monkeypatch: pytest.MonkeyPatch) -> None:
    collection = FakeCollection()
    service = FingerprintService(collection=collection)
    asset_id = str(uuid4())

    frame_vectors = [
        FingerprintVector(timestamp_ms=index * FRAME_INTERVAL_MS, vector=bytes([index]) * 8, kind="frame")
        for index in range(8)
    ]

    async def fake_extract(*, video_path: str, asset_key: str):
        assert video_path == "short.mp4"
        return frame_vectors, [], 8400

    monkeypatch.setattr(service, "_extract_fingerprints", fake_extract)
    collection.search_responses = [
        [[FakeHit(asset_id=asset_id, timestamp_ms=vector.timestamp_ms, distance=0)]]
        for vector in frame_vectors
    ]

    matches = asyncio.run(service.match(video_path="short.mp4"))

    assert matches
    assert matches[0].asset_id == UUID(asset_id)
    assert matches[0].confidence >= 0.7


def test_consecutive_run_detection() -> None:
    asset_id = str(uuid4())
    points = [MatchPoint(candidate_ms=index * 1000, stored_ms=index * 1000) for index in range(35)]
    points.insert(10, MatchPoint(candidate_ms=10000, stored_ms=10000))

    runs = detect_consecutive_runs(
        asset_id=asset_id,
        kind="frame",
        points=points,
        expected_step_ms=1000,
        tolerance_ms=120,
        min_length=30,
    )

    assert len(runs) == 1
    assert runs[0].count == 35
    assert runs[0].start_ms == 0
    assert runs[0].end_ms == 35000


def test_audio_padding_consistency() -> None:
    service = FingerprintService(collection=FakeCollection())

    padded = service._pad_audio_fingerprint(b"\x12\x34\x56\x78")

    assert padded == b"\x12\x34\x56\x78\x00\x00\x00\x00"


def test_milvus_search_requests_only_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    collection = FakeCollection()
    service = FingerprintService(collection=collection)
    asset_id = str(uuid4())
    vectors = [FingerprintVector(timestamp_ms=0, vector=b"\x01" * 8, kind="frame")]

    async def fake_extract(*, video_path: str, asset_key: str):
        assert video_path == "candidate.mp4"
        return vectors, [], 1000

    monkeypatch.setattr(service, "_extract_fingerprints", fake_extract)
    collection.search_responses = [[[FakeHit(asset_id=asset_id, timestamp_ms=0, distance=1)]]]

    asyncio.run(service.match(video_path="candidate.mp4"))

    assert collection.search_requests[0]["output_fields"] == ["asset_id", "timestamp_ms"]


def test_match_can_filter_search_by_asset_id(monkeypatch: pytest.MonkeyPatch) -> None:
    collection = FakeCollection()
    service = FingerprintService(collection=collection)
    asset_id = uuid4()
    vectors = [FingerprintVector(timestamp_ms=0, vector=b"\x01" * 8, kind="frame")]

    async def fake_extract(*, video_path: str, asset_key: str):
        return vectors, [], 1000

    monkeypatch.setattr(service, "_extract_fingerprints", fake_extract)

    asyncio.run(service.match(video_path="candidate.mp4", asset_ids=[asset_id]))

    assert f'asset_id == "{asset_id}"' in collection.search_requests[0]["expr"]


def test_search_vectors_keeps_best_hit_per_asset_per_vector() -> None:
    collection = FakeCollection()
    service = FingerprintService(collection=collection)
    asset_id = str(uuid4())
    vectors = [FingerprintVector(timestamp_ms=0, vector=b"\x01" * 8, kind="frame")]
    collection.search_responses = [
        [[
            FakeHit(asset_id=asset_id, timestamp_ms=1000, distance=5),
            FakeHit(asset_id=asset_id, timestamp_ms=0, distance=0),
        ]]
    ]

    hits = asyncio.run(service._search_vectors(vectors, threshold=10))

    assert hits[asset_id] == [MatchPoint(candidate_ms=0, stored_ms=0)]


def test_temp_directory_cleanup_on_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    collection = FakeCollection()
    service = FingerprintService(collection=collection)
    asset_id = uuid4()
    service.settings.temp_root = tmp_path

    async def fake_probe(_: str) -> int:
        return 1000

    async def fake_extract_frames(_: str, frames_dir: Path) -> list[Path]:
        frame_path = frames_dir / "frame_000000.jpg"
        frame_path.parent.mkdir(parents=True, exist_ok=True)
        frame_path.write_bytes(b"frame")
        return [frame_path]

    async def fake_hash_frames(_: list[Path]) -> list[FingerprintVector]:
        return [FingerprintVector(timestamp_ms=0, vector=b"\x01" * 8, kind="frame")]

    async def fake_extract_audio(_: str, audio_path: Path) -> None:
        audio_path.write_bytes(b"audio")

    async def fake_has_audio(_: str) -> bool:
        return True

    async def fake_fingerprint_audio(_: Path) -> list[FingerprintVector]:
        return []

    monkeypatch.setattr(service, "_probe_duration_ms", fake_probe)
    monkeypatch.setattr(service, "_extract_frames", fake_extract_frames)
    monkeypatch.setattr(service, "_hash_frames", fake_hash_frames)
    monkeypatch.setattr(service, "_has_audio_stream", fake_has_audio)
    monkeypatch.setattr(service, "_extract_audio", fake_extract_audio)
    monkeypatch.setattr(service, "_fingerprint_audio", fake_fingerprint_audio)

    asyncio.run(service.generate(video_path="clip.mp4", asset_id=asset_id))

    assert not (tmp_path / str(asset_id)).exists()


def test_temp_directory_cleanup_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    collection = FakeCollection()
    service = FingerprintService(collection=collection)
    asset_id = uuid4()
    service.settings.temp_root = tmp_path

    async def fake_probe(_: str) -> int:
        return 1000

    async def fake_extract_frames(_: str, frames_dir: Path) -> list[Path]:
        frame_path = frames_dir / "frame_000000.jpg"
        frame_path.parent.mkdir(parents=True, exist_ok=True)
        frame_path.write_bytes(b"frame")
        return [frame_path]

    async def fake_hash_frames(_: list[Path]) -> list[FingerprintVector]:
        raise RuntimeError("hash failure")

    monkeypatch.setattr(service, "_probe_duration_ms", fake_probe)
    monkeypatch.setattr(service, "_extract_frames", fake_extract_frames)
    monkeypatch.setattr(service, "_hash_frames", fake_hash_frames)

    with pytest.raises(RuntimeError, match="hash failure"):
        asyncio.run(service.generate(video_path="clip.mp4", asset_id=asset_id))

    assert not (tmp_path / str(asset_id)).exists()


class FakeSession:
    def __init__(self, asset) -> None:
        self.asset = asset
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def get(self, model, asset_id: str):
        assert model is not None
        if self.asset is None or self.asset.id != asset_id:
            return None
        return self.asset

    async def commit(self) -> None:
        self.commits += 1


def test_ingest_task_sets_asset_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    ingest_module = pytest.importorskip("app.workers.ingest_task")
    asset = type("AssetStub", (), {"id": str(uuid4()), "status": "pending", "video_path": "clip.mp4"})()
    session = FakeSession(asset)

    async def fake_generate(self, video_path: str, asset_id: UUID):
        assert video_path == "clip.mp4"
        assert str(asset_id) == asset.id
        return None

    monkeypatch.setattr("app.workers.ingest_task.SessionLocal", lambda: session)
    monkeypatch.setattr("app.workers.ingest_task.FingerprintService.generate", fake_generate)

    result = asyncio.run(ingest_module._ingest_asset_impl(asset_id=asset.id, video_path=asset.video_path))

    assert result == {"asset_id": asset.id, "status": "ready"}
    assert asset.status == "ready"
    assert session.commits >= 2


def test_ingest_task_sets_asset_failed_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    ingest_module = pytest.importorskip("app.workers.ingest_task")
    asset = type("AssetStub", (), {"id": str(uuid4()), "status": "pending", "video_path": "clip.mp4"})()
    session = FakeSession(asset)

    async def fake_generate(self, video_path: str, asset_id: UUID):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.workers.ingest_task.SessionLocal", lambda: session)
    monkeypatch.setattr("app.workers.ingest_task.FingerprintService.generate", fake_generate)

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(ingest_module._ingest_asset_impl(asset_id=asset.id, video_path=asset.video_path))

    assert asset.status == "failed"
    assert session.commits >= 2
