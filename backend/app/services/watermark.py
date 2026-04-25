import asyncio
import base64
import hashlib
import hmac
import logging
import shutil
import subprocess
from collections import Counter
from concurrent.futures import Executor, ThreadPoolExecutor
from pathlib import Path
from types import TracebackType
from typing import Any
from uuid import UUID, uuid4

import numpy as np
from PIL import Image
from scipy.fft import dctn, idctn
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.watermark import WatermarkRegistry
from app.schemas.watermark import WatermarkDetection, WatermarkResult

try:
    import ffmpeg
except ImportError:  # pragma: no cover - exercised only when dependency is absent
    ffmpeg = None


LOGGER = logging.getLogger(__name__)
BIT_COUNT = 32
SPREAD_POSITIONS = 16
BLOCK_SIZE = 8
CANONICAL_SIZE = 256
DEFAULT_ALPHA = 8
PSNR_MIN_DB = 38.0
EMBED_SELF_CHECK_CONFIDENCE = 0.85
EMBED_MAX_ATTEMPTS = 4
TEMP_ROOT = Path("/tmp/sports-ip")


class WatermarkError(Exception):
    pass


class PSNRTooLowError(WatermarkError):
    pass


class ExtractionFailedError(WatermarkError):
    pass


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


class WatermarkService:
    def __init__(
        self,
        session_factory: Any = SessionLocal,
        logger: logging.Logger | None = None,
        executor: Executor | None = None,
    ) -> None:
        self.settings = get_settings()
        self.session_factory = session_factory
        self.logger = logger if logger is not None else LOGGER
        self.executor = executor if executor is not None else ThreadPoolExecutor(max_workers=2)

    @staticmethod
    def embed(frame: np.ndarray, payload: int, key: bytes, alpha: int = DEFAULT_ALPHA) -> np.ndarray:
        _validate_frame(frame)
        _validate_payload(payload)
        _validate_key(key)
        _validate_alpha(alpha)

        original = frame.astype(np.uint8, copy=False)
        image = Image.fromarray(original, mode="RGB").convert("YCbCr")
        y, cb, cr = image.split()
        y_array = np.asarray(y, dtype=np.float32)
        working_y = y_array.copy()
        best_frame: np.ndarray | None = None
        best_payload: int | None = None
        best_confidence = -1.0
        best_psnr = 0.0
        for _ in range(EMBED_MAX_ATTEMPTS):
            canonical = _resize_luma(working_y, (CANONICAL_SIZE, CANONICAL_SIZE))
            watermarked_canonical = _embed_luma(canonical, payload=payload, key=key, alpha=alpha)
            delta = watermarked_canonical - canonical
            resized_delta = _resize_float(delta, y_array.shape[::-1])
            y_watermarked = np.clip(working_y + resized_delta, 0, 255).astype(np.uint8)

            merged = Image.merge("YCbCr", (Image.fromarray(y_watermarked, mode="L"), cb, cr))
            candidate = np.asarray(merged.convert("RGB"), dtype=np.uint8)
            psnr = calculate_psnr(original, candidate)
            if psnr < PSNR_MIN_DB:
                raise PSNRTooLowError(f"Watermark PSNR {psnr:.2f} dB is below {PSNR_MIN_DB:.2f} dB")

            recovered, confidence = WatermarkService.extract(candidate, key)
            if confidence > best_confidence:
                best_frame = candidate
                best_payload = recovered
                best_confidence = confidence
                best_psnr = psnr
            if recovered == payload and confidence >= EMBED_SELF_CHECK_CONFIDENCE:
                return candidate

            roundtripped = Image.fromarray(candidate, mode="RGB").convert("YCbCr")
            working_y = np.asarray(roundtripped.split()[0], dtype=np.float32)

        if best_frame is not None and best_payload == payload and best_confidence >= EMBED_SELF_CHECK_CONFIDENCE:
            return best_frame
        raise ExtractionFailedError(
            f"Watermark self-check failed after embedding; best confidence={best_confidence:.3f}, psnr={best_psnr:.2f}"
        )

    @staticmethod
    def extract(frame: np.ndarray, key: bytes) -> tuple[int, float]:
        _validate_frame(frame)
        _validate_key(key)

        image = Image.fromarray(frame.astype(np.uint8, copy=False), mode="RGB").convert("YCbCr")
        y, _, _ = image.split()
        y_array = np.asarray(y, dtype=np.float32)
        canonical = _resize_luma(y_array, (CANONICAL_SIZE, CANONICAL_SIZE))
        return _extract_luma(canonical, key=key, alpha=DEFAULT_ALPHA)

    async def embed_video(
        self,
        video_path: str,
        asset_id: UUID,
        payload: int,
        key: bytes,
        alpha: int = DEFAULT_ALPHA,
    ) -> WatermarkResult:
        workspace_path = TEMP_ROOT / str(asset_id)
        psnr_values: list[float] = []
        async with _TempWorkspace(workspace_path) as workspace:
            output_path = workspace / "watermarked.mp4"
            keyframe_dir = workspace / "keyframes"
            watermarked_dir = workspace / "watermarked_frames"
            keyframe_dir.mkdir(parents=True, exist_ok=True)
            watermarked_dir.mkdir(parents=True, exist_ok=True)
            timestamps = await self._extract_keyframe_timestamps(video_path)
            frame_paths = await self._extract_keyframes(video_path, timestamps, keyframe_dir)

            for index, frame_path in enumerate(frame_paths):
                frame = await self._run_blocking(_read_rgb_frame, frame_path)
                watermarked = await self._run_blocking(self.embed, frame, payload, key, alpha)
                psnr_values.append(calculate_psnr(frame, watermarked))
                await self._run_blocking(_write_rgb_frame, watermarked_dir / f"frame_{index:06d}.png", watermarked)

            await self._render_watermarked_video(video_path, watermarked_dir, timestamps, output_path)
            s3_key = f"watermarked/{asset_id}/video.mp4"
            await self._upload_to_s3(output_path, s3_key)
            psnr_mean = float(np.mean(psnr_values)) if psnr_values else 0.0
            await self._register_watermark(
                asset_id=asset_id,
                payload=payload,
                alpha=alpha,
                keyframe_count=len(frame_paths),
                psnr_mean=psnr_mean,
            )
            self.logger.info("watermark_generated asset_id=%s keyframe_count=%s", asset_id, len(frame_paths))
            return WatermarkResult(
                asset_id=asset_id,
                payload=payload,
                keyframe_count=len(frame_paths),
                s3_key=s3_key,
                psnr_mean=psnr_mean,
            )

    async def detect_from_url(self, url: str, key: bytes) -> WatermarkDetection | None:
        detection_id = uuid4()
        workspace_path = TEMP_ROOT / f"detect_{detection_id}"
        async with _TempWorkspace(workspace_path) as workspace:
            clip_path = workspace / "clip.mp4"
            frames_dir = workspace / "frames"
            frames_dir.mkdir(parents=True, exist_ok=True)
            await self._download_clip(url, clip_path)
            frame_paths = await self._extract_detection_frames(clip_path, frames_dir, limit=10)

            pairs: list[tuple[int, float]] = []
            for frame_path in frame_paths:
                frame = await self._run_blocking(_read_rgb_frame, frame_path)
                payload, confidence = await self._run_blocking(self.extract, frame, key)
                if confidence >= 0.6:
                    pairs.append((payload, confidence))

            if not pairs:
                return None

            counts = Counter(payload for payload, _ in pairs)
            payload, frames_agreed = counts.most_common(1)[0]
            agreed_confidences = [confidence for candidate, confidence in pairs if candidate == payload]
            mean_confidence = float(np.mean(agreed_confidences)) if agreed_confidences else 0.0
            if frames_agreed < 3 or mean_confidence < 0.65:
                return None

            asset_id = await self._lookup_asset_id(payload)
            return WatermarkDetection(
                payload=payload,
                asset_id=asset_id,
                confidence=mean_confidence,
                frames_agreed=frames_agreed,
            )

    async def _register_watermark(
        self,
        asset_id: UUID,
        payload: int,
        alpha: int,
        keyframe_count: int,
        psnr_mean: float,
    ) -> None:
        async with self.session_factory() as session:
            existing = await session.execute(
                select(WatermarkRegistry).where(WatermarkRegistry.asset_id == str(asset_id))
            )
            registry = existing.scalar_one_or_none()
            if registry is None:
                registry = WatermarkRegistry(asset_id=str(asset_id))
                session.add(registry)
            registry.payload = payload
            registry.alpha = alpha
            registry.keyframe_count = keyframe_count
            registry.psnr_mean = psnr_mean
            await session.commit()

    async def _lookup_asset_id(self, payload: int) -> UUID | None:
        async with self.session_factory() as session:
            return await lookup_asset_id_by_payload(session, payload)

    async def _extract_keyframe_timestamps(self, video_path: str) -> list[float]:
        if ffmpeg is None:
            raise WatermarkError("ffmpeg-python is required for video watermarking")

        def _probe() -> list[float]:
            command = [
                "ffprobe",
                "-select_streams",
                "v",
                "-show_frames",
                "-show_entries",
                "frame=pkt_pts_time,best_effort_timestamp_time,pict_type",
                "-of",
                "csv=p=0",
                video_path,
            ]
            result = subprocess.run(command, check=True, capture_output=True, text=True)
            timestamps: list[float] = []
            for line in result.stdout.splitlines():
                parts = [part for part in line.split(",") if part]
                if not parts or parts[-1] != "I":
                    continue
                for value in parts[:-1]:
                    try:
                        timestamps.append(float(value))
                        break
                    except ValueError:
                        continue
            return timestamps

        return await self._run_blocking(_probe)

    async def _extract_keyframes(self, video_path: str, timestamps: list[float], output_dir: Path) -> list[Path]:
        paths: list[Path] = []
        for index, timestamp in enumerate(timestamps):
            output_path = output_dir / f"frame_{index:06d}.png"
            await self._extract_frame_at(video_path, timestamp, output_path)
            paths.append(output_path)
        return paths

    async def _extract_frame_at(self, video_path: str | Path, timestamp: float, output_path: Path) -> None:
        if ffmpeg is None:
            raise WatermarkError("ffmpeg-python is required for video watermarking")

        def _run() -> None:
            (
                ffmpeg.input(str(video_path), ss=max(0.0, timestamp))
                .output(str(output_path), vframes=1, format="image2", vcodec="png")
                .overwrite_output()
                .run(capture_stdout=True, capture_stderr=True)
            )

        await self._run_blocking(_run)

    async def _render_watermarked_video(
        self,
        video_path: str,
        watermarked_dir: Path,
        timestamps: list[float],
        output_path: Path,
    ) -> None:
        frame_paths = sorted(watermarked_dir.glob("frame_*.png"))
        if not frame_paths:
            await self._run_blocking(lambda: shutil.copyfile(video_path, output_path))
            return

        def _run() -> None:
            command = ["ffmpeg", "-y", "-i", video_path]
            for frame_path in frame_paths:
                command.extend(["-loop", "1", "-i", str(frame_path)])

            previous = "0:v"
            filters: list[str] = []
            for index, timestamp in enumerate(timestamps[: len(frame_paths)], start=1):
                output_label = f"v{index}"
                filters.append(
                    f"[{previous}][{index}:v]overlay=enable='between(t,{timestamp:.6f},{timestamp + 0.050:.6f})'[{output_label}]"
                )
                previous = output_label

            command.extend(
                [
                    "-filter_complex",
                    ";".join(filters),
                    "-map",
                    f"[{previous}]",
                    "-map",
                    "0:a?",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "copy",
                    str(output_path),
                ]
            )
            subprocess.run(command, check=True, capture_output=True)

        await self._run_blocking(_run)

    async def _upload_to_s3(self, local_path: Path, s3_key: str) -> None:
        await self._run_blocking(storage.upload_file, local_path, s3_key)

    async def _download_clip(self, url: str, output_path: Path) -> None:
        if ffmpeg is None:
            raise WatermarkError("ffmpeg-python is required for video watermarking")

        def _run() -> None:
            (
                ffmpeg.input(url, t=60)
                .output(str(output_path), c="copy")
                .overwrite_output()
                .run(capture_stdout=True, capture_stderr=True)
            )

        await self._run_blocking(_run)

    async def _extract_detection_frames(self, clip_path: Path, frames_dir: Path, limit: int = 10) -> list[Path]:
        timestamps = await self._extract_keyframe_timestamps(str(clip_path))
        if len(timestamps) > limit:
            indices = np.linspace(0, len(timestamps) - 1, num=limit, dtype=int)
            timestamps = [timestamps[int(index)] for index in indices]
        return await self._extract_keyframes(str(clip_path), timestamps, frames_dir)

    async def _run_blocking(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, lambda: func(*args, **kwargs))


async def lookup_asset_id_by_payload(session: AsyncSession, payload: int) -> UUID | None:
    result = await session.execute(select(WatermarkRegistry).where(WatermarkRegistry.payload == payload))
    registry = result.scalar_one_or_none()
    if registry is None:
        return None
    return UUID(registry.asset_id)


def decode_watermark_key(value: str) -> bytes:
    return base64.b64decode(value, validate=True)


def calculate_psnr(original: np.ndarray, candidate: np.ndarray) -> float:
    mse = float(np.mean((original.astype(np.float64) - candidate.astype(np.float64)) ** 2))
    if mse == 0.0:
        return float("inf")
    return float(20 * np.log10(255.0 / np.sqrt(mse)))


def _embed_luma(luma: np.ndarray, payload: int, key: bytes, alpha: int) -> np.ndarray:
    blocks = _split_blocks(luma)
    coefficients = dctn(blocks, axes=(-2, -1), norm="ortho")
    available = coefficients.shape[0]
    for bit_index in range(BIT_COUNT):
        bit = (payload >> (BIT_COUNT - 1 - bit_index)) & 1
        for block_index, row, column in _positions_for_bit(key, bit_index, available):
            coefficients[block_index, row, column] = _force_parity(coefficients[block_index, row, column], bit, alpha)
    watermarked = idctn(coefficients, axes=(-2, -1), norm="ortho")
    return _merge_blocks(watermarked, luma.shape)


def _extract_luma(luma: np.ndarray, key: bytes, alpha: int) -> tuple[int, float]:
    blocks = _split_blocks(luma)
    if blocks.shape[0] == 0:
        raise ExtractionFailedError("Frame is too small for watermark extraction")
    coefficients = dctn(blocks, axes=(-2, -1), norm="ortho")
    payload = 0
    confidences: list[float] = []
    for bit_index in range(BIT_COUNT):
        votes = [
            int(round(float(coefficients[block_index, row, column]) / alpha)) & 1
            for block_index, row, column in _positions_for_bit(key, bit_index, coefficients.shape[0])
        ]
        ones = sum(votes)
        zeros = len(votes) - ones
        bit = 1 if ones > zeros else 0
        payload = (payload << 1) | bit
        majority_fraction = max(ones, zeros) / len(votes)
        confidences.append(max(0.0, (majority_fraction - 0.5) * 2.0))
    return payload, float(np.mean(confidences))


def _positions_for_bit(key: bytes, bit_index: int, block_count: int) -> list[tuple[int, int, int]]:
    if block_count <= 0:
        raise ExtractionFailedError("No DCT blocks available")
    digest = hmac.new(key, bit_index.to_bytes(2, "big"), hashlib.sha256).digest()
    seed = int.from_bytes(digest[:8], "big", signed=False)
    rng = np.random.default_rng(seed)
    zigzag_positions = _mid_frequency_positions()
    chosen: set[tuple[int, int, int]] = set()
    attempts = 0
    max_unique = block_count * len(zigzag_positions)
    target = min(SPREAD_POSITIONS, max_unique)
    while len(chosen) < target:
        attempts += 1
        if attempts > SPREAD_POSITIONS * 100:
            break
        block_index = int(rng.integers(0, block_count))
        row, column = zigzag_positions[int(rng.integers(0, len(zigzag_positions)))]
        chosen.add((block_index, row, column))
    return list(chosen)


def _mid_frequency_positions() -> list[tuple[int, int]]:
    positions = _zigzag_positions(BLOCK_SIZE)
    return positions[10:27]


def _zigzag_positions(size: int) -> list[tuple[int, int]]:
    positions: list[tuple[int, int]] = []
    for diagonal in range(2 * size - 1):
        if diagonal % 2 == 0:
            row_range = range(min(diagonal, size - 1), max(-1, diagonal - size), -1)
        else:
            row_range = range(max(0, diagonal - size + 1), min(diagonal, size - 1) + 1)
        for row in row_range:
            column = diagonal - row
            if 0 <= column < size:
                positions.append((row, column))
    return positions


def _force_parity(value: float, bit: int, alpha: int) -> float:
    quotient = int(round(float(value) / alpha))
    if quotient & 1 != bit:
        lower = quotient - 1
        upper = quotient + 1
        quotient = lower if abs((lower * alpha) - value) <= abs((upper * alpha) - value) else upper
    return float(quotient * alpha)


def _split_blocks(luma: np.ndarray) -> np.ndarray:
    height = (luma.shape[0] // BLOCK_SIZE) * BLOCK_SIZE
    width = (luma.shape[1] // BLOCK_SIZE) * BLOCK_SIZE
    cropped = luma[:height, :width]
    return cropped.reshape(height // BLOCK_SIZE, BLOCK_SIZE, width // BLOCK_SIZE, BLOCK_SIZE).swapaxes(1, 2).reshape(
        -1,
        BLOCK_SIZE,
        BLOCK_SIZE,
    )


def _merge_blocks(blocks: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    height = (shape[0] // BLOCK_SIZE) * BLOCK_SIZE
    width = (shape[1] // BLOCK_SIZE) * BLOCK_SIZE
    merged = blocks.reshape(height // BLOCK_SIZE, width // BLOCK_SIZE, BLOCK_SIZE, BLOCK_SIZE).swapaxes(1, 2).reshape(
        height,
        width,
    )
    output = np.zeros(shape, dtype=np.float32)
    output[:height, :width] = merged
    return output


def _resize_luma(luma: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    image = Image.fromarray(np.clip(luma, 0, 255).astype(np.uint8), mode="L")
    return np.asarray(image.resize(size, Image.Resampling.LANCZOS), dtype=np.float32)


def _resize_float(values: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    image = Image.fromarray(values.astype(np.float32), mode="F")
    return np.asarray(image.resize(size, Image.Resampling.BICUBIC), dtype=np.float32)


def _read_rgb_frame(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image.convert("RGB"), dtype=np.uint8)


def _write_rgb_frame(path: Path, frame: np.ndarray) -> None:
    Image.fromarray(frame.astype(np.uint8, copy=False), mode="RGB").save(path)


def _validate_frame(frame: np.ndarray) -> None:
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise WatermarkError("Frame must be an RGB ndarray with shape HxWx3")
    if frame.shape[0] < BLOCK_SIZE or frame.shape[1] < BLOCK_SIZE:
        raise WatermarkError("Frame must be at least 8x8 pixels")


def _validate_payload(payload: int) -> None:
    if payload < 0 or payload > 0xFFFFFFFF:
        raise WatermarkError("Payload must be a 32-bit unsigned integer")


def _validate_key(key: bytes) -> None:
    if not key:
        raise WatermarkError("Watermark key must not be empty")


def _validate_alpha(alpha: int) -> None:
    if alpha <= 0:
        raise WatermarkError("Alpha must be positive")
