import asyncio
import logging
import math
import shutil
import time
from concurrent.futures import Executor
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any
from uuid import UUID, uuid4

from app.core.config import get_settings
from app.db.milvus import get_collection
from app.schemas.fingerprint import FingerprintMatch, FingerprintResult

try:
    import ffmpeg
except ImportError:  # pragma: no cover - exercised only when dependency is absent
    ffmpeg = None

try:
    import imagehash
except ImportError:  # pragma: no cover - exercised only when dependency is absent
    imagehash = None

try:
    import librosa
    import numpy as np
except ImportError:  # pragma: no cover - exercised only when dependency is absent
    librosa = None
    np = None

try:
    from PIL import Image
except ImportError:  # pragma: no cover - exercised only when dependency is absent
    Image = None


LOGGER = logging.getLogger(__name__)
FRAME_INTERVAL_MS = 1000
AUDIO_SAMPLE_RATE = 22050
AUDIO_WINDOW_MS = 371
AUDIO_WINDOW_SAMPLES = int(round(AUDIO_SAMPLE_RATE * (AUDIO_WINDOW_MS / 1000.0)))
AUDIO_HOP_SAMPLES = max(1, AUDIO_WINDOW_SAMPLES // 2)
AUDIO_HOP_MS = int(round((AUDIO_HOP_SAMPLES / AUDIO_SAMPLE_RATE) * 1000))
FRAME_RUN_THRESHOLD = 30
FRAME_FUSED_THRESHOLD = 15
AUDIO_RUN_THRESHOLD = 10


@dataclass(slots=True)
class FingerprintVector:
    timestamp_ms: int
    vector: bytes
    kind: str


@dataclass(slots=True)
class MatchPoint:
    candidate_ms: int
    stored_ms: int


@dataclass(slots=True)
class MatchRun:
    asset_id: str
    kind: str
    start_ms: int
    end_ms: int
    count: int
    density: float


class _TempWorkspace:
    def __init__(self, path: Path) -> None:
        self.path = path

    async def __aenter__(self) -> Path:
        self.path.mkdir(parents=True, exist_ok=True)
        return self.path

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: shutil.rmtree(self.path, ignore_errors=True))


class FingerprintService:
    def __init__(
        self,
        collection: Any | None = None,
        logger: logging.Logger | None = None,
        executor: Executor | None = None,
    ) -> None:
        self.settings = get_settings()
        self.collection = collection if collection is not None else get_collection()
        self.logger = logger if logger is not None else LOGGER
        self.executor = executor

    async def generate(self, video_path: str, asset_id: UUID) -> FingerprintResult:
        start_time = time.perf_counter()
        frame_vectors, audio_vectors, duration_ms = await self._extract_fingerprints(
            video_path=video_path,
            asset_key=str(asset_id),
        )
        await self._insert_fingerprints(asset_id=str(asset_id), frame_vectors=frame_vectors, audio_vectors=audio_vectors)
        elapsed = time.perf_counter() - start_time
        self.logger.info(
            "fingerprint_generated asset_id=%s frame_count=%s duration_ms=%s processing_seconds=%.3f",
            asset_id,
            len(frame_vectors),
            duration_ms,
            elapsed,
        )
        return FingerprintResult(
            asset_id=asset_id,
            frame_count=len(frame_vectors),
            audio_window_count=len(audio_vectors),
            duration_ms=duration_ms,
        )

    async def match(self, video_path: str, threshold: int = 10) -> list[FingerprintMatch]:
        frame_vectors, audio_vectors, _ = await self._extract_fingerprints(
            video_path=video_path,
            asset_key=f"candidate-{uuid4()}",
        )

        frame_hits = await self._search_vectors(frame_vectors, threshold=threshold)
        audio_hits = await self._search_vectors(audio_vectors, threshold=threshold)

        frame_runs = self._build_runs(
            matches_by_asset=frame_hits,
            kind="frame",
            expected_step_ms=FRAME_INTERVAL_MS,
            min_length=FRAME_FUSED_THRESHOLD,
        )
        audio_runs = self._build_runs(
            matches_by_asset=audio_hits,
            kind="audio",
            expected_step_ms=AUDIO_HOP_MS,
            min_length=AUDIO_RUN_THRESHOLD,
        )

        results: list[FingerprintMatch] = []
        for asset_id in sorted(set(frame_runs) | set(audio_runs)):
            asset_frame_runs = frame_runs.get(asset_id, [])
            asset_audio_runs = audio_runs.get(asset_id, [])

            strong_frame = self._select_best_run(asset_frame_runs, minimum=FRAME_RUN_THRESHOLD)
            if strong_frame is not None:
                results.append(
                    FingerprintMatch(
                        asset_id=UUID(asset_id),
                        confidence=self._confidence_from_runs(strong_frame, None, match_type="frame"),
                        start_ms=strong_frame.start_ms,
                        end_ms=strong_frame.end_ms,
                        match_type="frame",
                    )
                )
                continue

            fused_match = self._select_fused_run(asset_frame_runs, asset_audio_runs)
            if fused_match is None:
                continue

            frame_run, audio_run = fused_match
            start_ms = max(frame_run.start_ms, audio_run.start_ms)
            end_ms = min(frame_run.end_ms, audio_run.end_ms)
            results.append(
                FingerprintMatch(
                    asset_id=UUID(asset_id),
                    confidence=self._confidence_from_runs(frame_run, audio_run, match_type="fused"),
                    start_ms=max(0, start_ms),
                    end_ms=max(start_ms, end_ms),
                    match_type="fused",
                )
            )

        return sorted(results, key=lambda item: item.confidence, reverse=True)

    async def delete(self, asset_id: UUID) -> None:
        expression = f'asset_id == "{asset_id}"'
        await self._run_blocking(self.collection.delete, expression)
        await self._run_blocking(self.collection.flush)

    async def _extract_fingerprints(
        self,
        video_path: str,
        asset_key: str,
    ) -> tuple[list[FingerprintVector], list[FingerprintVector], int]:
        workspace = self.settings.temp_root / asset_key
        async with _TempWorkspace(workspace):
            frames_dir = workspace / "frames"
            audio_path = workspace / "audio.wav"
            frames_dir.mkdir(parents=True, exist_ok=True)
            duration_ms = await self._probe_duration_ms(video_path)
            frame_paths = await self._extract_frames(video_path, frames_dir)
            frame_vectors = await self._hash_frames(frame_paths)
            await self._extract_audio(video_path, audio_path)
            audio_vectors = await self._fingerprint_audio(audio_path)
            return frame_vectors, audio_vectors, duration_ms

    async def _probe_duration_ms(self, video_path: str) -> int:
        if ffmpeg is None:
            raise RuntimeError("ffmpeg-python is required for video fingerprinting")

        def _probe() -> int:
            metadata = ffmpeg.probe(video_path)
            duration_seconds = float(metadata["format"]["duration"])
            return max(0, int(round(duration_seconds * 1000)))

        return await self._run_blocking(_probe)

    async def _extract_frames(self, video_path: str, frames_dir: Path) -> list[Path]:
        if ffmpeg is None:
            raise RuntimeError("ffmpeg-python is required for video fingerprinting")

        output_pattern = frames_dir / "frame_%06d.jpg"

        def _run() -> list[Path]:
            (
                ffmpeg
                .input(video_path)
                .filter("fps", fps=1, round="down")
                .output(str(output_pattern), start_number=0, **{"qscale:v": 2, "vsync": "vfr"})
                .overwrite_output()
                .run(capture_stdout=True, capture_stderr=True)
            )
            return sorted(frames_dir.glob("frame_*.jpg"))

        return await self._run_blocking(_run)

    async def _hash_frames(self, frame_paths: list[Path]) -> list[FingerprintVector]:
        vectors: list[FingerprintVector] = []
        for index, frame_path in enumerate(frame_paths):
            vector = await self._run_blocking(self._hash_single_frame, frame_path)
            vectors.append(
                FingerprintVector(
                    timestamp_ms=index * FRAME_INTERVAL_MS,
                    vector=vector,
                    kind="frame",
                )
            )
        return vectors

    def _hash_single_frame(self, frame_path: Path) -> bytes:
        if imagehash is None or Image is None:
            raise RuntimeError("imagehash and Pillow are required for frame hashing")

        with Image.open(frame_path) as image:
            processed = image.convert("L").resize((32, 32))
            hash_value = imagehash.phash(processed, hash_size=8)
        return self._int_to_binary_vector(int(str(hash_value), 16), bits=64)

    async def _extract_audio(self, video_path: str, audio_path: Path) -> None:
        if ffmpeg is None:
            raise RuntimeError("ffmpeg-python is required for audio extraction")

        def _run() -> None:
            (
                ffmpeg
                .input(video_path)
                .output(
                    str(audio_path),
                    acodec="pcm_s16le",
                    ac=1,
                    ar=AUDIO_SAMPLE_RATE,
                )
                .overwrite_output()
                .run(capture_stdout=True, capture_stderr=True)
            )

        await self._run_blocking(_run)

    async def _fingerprint_audio(self, audio_path: Path) -> list[FingerprintVector]:
        return await self._run_blocking(self._fingerprint_audio_sync, audio_path)

    def _fingerprint_audio_sync(self, audio_path: Path) -> list[FingerprintVector]:
        if librosa is None or np is None:
            raise RuntimeError("librosa and numpy are required for audio fingerprinting")

        waveform, _ = librosa.load(str(audio_path), sr=AUDIO_SAMPLE_RATE, mono=True)
        if waveform.size == 0:
            return []

        fingerprints: list[FingerprintVector] = []
        for start in range(0, max(1, waveform.shape[0] - AUDIO_WINDOW_SAMPLES + 1), AUDIO_HOP_SAMPLES):
            window = waveform[start:start + AUDIO_WINDOW_SAMPLES]
            if window.shape[0] < AUDIO_WINDOW_SAMPLES:
                window = np.pad(window, (0, AUDIO_WINDOW_SAMPLES - window.shape[0]))

            vector = self._compute_audio_window_fingerprint(window)
            fingerprints.append(
                FingerprintVector(
                    timestamp_ms=int(round((start / AUDIO_SAMPLE_RATE) * 1000)),
                    vector=vector,
                    kind="audio",
                )
            )

        return fingerprints

    def _compute_audio_window_fingerprint(self, window: Any) -> bytes:
        assert librosa is not None
        assert np is not None

        mel = librosa.feature.melspectrogram(
            y=window,
            sr=AUDIO_SAMPLE_RATE,
            n_mels=96,
            n_fft=2048,
            hop_length=256,
            power=2.0,
        )
        mel_db = librosa.power_to_db(mel + 1e-9, ref=np.max)
        band_size = mel_db.shape[0] // 6
        fingerprint = 0
        energy_total = 0.0

        for band_index in range(6):
            band = mel_db[band_index * band_size:(band_index + 1) * band_size]
            collapsed = band.mean(axis=1)
            peak_index = int(np.argmax(collapsed)) & 0x0F
            fingerprint = (fingerprint << 4) | peak_index
            energy_total += float(np.max(collapsed))

        normalized_energy = max(0, min(255, int(round((energy_total / 6.0) + 80))))
        fingerprint = (fingerprint << 8) | normalized_energy
        return self._pad_audio_fingerprint(fingerprint.to_bytes(4, byteorder="big", signed=False))

    def _pad_audio_fingerprint(self, fingerprint: bytes) -> bytes:
        return fingerprint + (b"\x00" * (8 - len(fingerprint)))

    async def _insert_fingerprints(
        self,
        asset_id: str,
        frame_vectors: list[FingerprintVector],
        audio_vectors: list[FingerprintVector],
    ) -> None:
        entities = {
            "asset_id": [asset_id for _ in range(len(frame_vectors) + len(audio_vectors))],
            "timestamp_ms": [item.timestamp_ms for item in frame_vectors + audio_vectors],
            "type": [item.kind for item in frame_vectors + audio_vectors],
            "hash_vector": [item.vector for item in frame_vectors + audio_vectors],
        }
        if not entities["asset_id"]:
            return

        await self._run_blocking(self.collection.insert, entities)
        await self._run_blocking(self.collection.flush)

    async def _search_vectors(
        self,
        vectors: list[FingerprintVector],
        threshold: int,
    ) -> dict[str, list[MatchPoint]]:
        matches_by_asset: dict[str, list[MatchPoint]] = {}
        for vector in vectors:
            search_hits = await self._run_blocking(
                self.collection.search,
                data=[vector.vector],
                anns_field="hash_vector",
                param={"metric_type": "HAMMING", "params": {}},
                limit=10,
                expr=f'type == "{vector.kind}"',
                output_fields=["asset_id", "timestamp_ms"],
            )
            if not search_hits:
                continue

            for hit in search_hits[0]:
                distance = getattr(hit, "distance", None)
                if distance is None or distance > threshold:
                    continue
                entity = getattr(hit, "entity", None)
                asset_id = entity.get("asset_id") if entity is not None else hit.get("asset_id")
                timestamp_ms = entity.get("timestamp_ms") if entity is not None else hit.get("timestamp_ms")
                if asset_id is None or timestamp_ms is None:
                    continue
                matches_by_asset.setdefault(str(asset_id), []).append(
                    MatchPoint(candidate_ms=vector.timestamp_ms, stored_ms=int(timestamp_ms))
                )
        return matches_by_asset

    def _build_runs(
        self,
        matches_by_asset: dict[str, list[MatchPoint]],
        kind: str,
        expected_step_ms: int,
        min_length: int,
    ) -> dict[str, list[MatchRun]]:
        runs_by_asset: dict[str, list[MatchRun]] = {}
        for asset_id, points in matches_by_asset.items():
            runs = detect_consecutive_runs(
                asset_id=asset_id,
                kind=kind,
                points=points,
                expected_step_ms=expected_step_ms,
                tolerance_ms=max(80, expected_step_ms // 3),
                min_length=min_length,
            )
            if runs:
                runs_by_asset[asset_id] = runs
        return runs_by_asset

    def _select_best_run(self, runs: list[MatchRun], minimum: int) -> MatchRun | None:
        eligible = [run for run in runs if run.count >= minimum]
        if not eligible:
            return None
        return max(eligible, key=lambda run: (run.count, run.density, -(run.start_ms)))

    def _select_fused_run(
        self,
        frame_runs: list[MatchRun],
        audio_runs: list[MatchRun],
    ) -> tuple[MatchRun, MatchRun] | None:
        eligible_frames = [run for run in frame_runs if run.count >= FRAME_FUSED_THRESHOLD]
        eligible_audio = [run for run in audio_runs if run.count >= AUDIO_RUN_THRESHOLD]
        best_pair: tuple[MatchRun, MatchRun] | None = None
        best_score = -1.0
        for frame_run in eligible_frames:
            for audio_run in eligible_audio:
                overlap_start = max(frame_run.start_ms, audio_run.start_ms)
                overlap_end = min(frame_run.end_ms, audio_run.end_ms)
                if overlap_end < overlap_start:
                    continue
                overlap_ms = overlap_end - overlap_start
                score = frame_run.count + audio_run.count + (overlap_ms / 1000.0)
                if score > best_score:
                    best_pair = (frame_run, audio_run)
                    best_score = score
        return best_pair

    def _confidence_from_runs(
        self,
        frame_run: MatchRun,
        audio_run: MatchRun | None,
        match_type: str,
    ) -> float:
        frame_score = min(1.0, (frame_run.count / FRAME_RUN_THRESHOLD) * 0.7 + (frame_run.density * 0.2))
        if match_type == "frame" or audio_run is None:
            return round(min(1.0, 0.1 + frame_score), 4)

        audio_score = min(1.0, (audio_run.count / AUDIO_RUN_THRESHOLD) * 0.6 + (audio_run.density * 0.2))
        return round(min(1.0, 0.2 + (frame_score * 0.45) + (audio_score * 0.35)), 4)

    def _int_to_binary_vector(self, value: int, bits: int) -> bytes:
        byte_length = bits // 8
        return value.to_bytes(byte_length, byteorder="big", signed=False)

    async def _run_blocking(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, lambda: func(*args, **kwargs))


def detect_consecutive_runs(
    asset_id: str,
    kind: str,
    points: list[MatchPoint],
    expected_step_ms: int,
    tolerance_ms: int,
    min_length: int,
) -> list[MatchRun]:
    if not points:
        return []

    sorted_points = sorted(points, key=lambda item: (item.candidate_ms, item.stored_ms))
    deduped: list[MatchPoint] = []
    seen: set[tuple[int, int]] = set()
    for point in sorted_points:
        key = (point.candidate_ms, point.stored_ms)
        if key not in seen:
            seen.add(key)
            deduped.append(point)

    runs: list[MatchRun] = []
    current: list[MatchPoint] = [deduped[0]]
    for point in deduped[1:]:
        previous = current[-1]
        candidate_delta = point.candidate_ms - previous.candidate_ms
        stored_delta = point.stored_ms - previous.stored_ms
        candidate_ok = abs(candidate_delta - expected_step_ms) <= tolerance_ms
        stored_ok = abs(stored_delta - expected_step_ms) <= tolerance_ms
        monotonic_ok = point.candidate_ms > previous.candidate_ms and point.stored_ms > previous.stored_ms

        if candidate_ok and stored_ok and monotonic_ok:
            current.append(point)
            continue

        run = _run_from_points(asset_id=asset_id, kind=kind, points=current, expected_step_ms=expected_step_ms)
        if run.count >= min_length:
            runs.append(run)
        current = [point]

    final_run = _run_from_points(asset_id=asset_id, kind=kind, points=current, expected_step_ms=expected_step_ms)
    if final_run.count >= min_length:
        runs.append(final_run)
    return runs


def _run_from_points(asset_id: str, kind: str, points: list[MatchPoint], expected_step_ms: int) -> MatchRun:
    if not points:
        return MatchRun(asset_id=asset_id, kind=kind, start_ms=0, end_ms=0, count=0, density=0.0)

    if len(points) == 1:
        expected_span = expected_step_ms
    else:
        expected_span = max(expected_step_ms, points[-1].candidate_ms - points[0].candidate_ms + expected_step_ms)

    density = min(1.0, len(points) / max(1, math.ceil(expected_span / expected_step_ms)))
    return MatchRun(
        asset_id=asset_id,
        kind=kind,
        start_ms=points[0].candidate_ms,
        end_ms=points[-1].candidate_ms + expected_step_ms,
        count=len(points),
        density=round(density, 4),
    )
