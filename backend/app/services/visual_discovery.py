import asyncio
import io
import logging
import pickle
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from uuid import UUID, uuid4

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.visual import CrawlWatchlist, VisualAssetFrame, VisualCandidate
from app.services.crawler import CandidateVideo
from app.services.geoip import country_for_url

try:
    import ffmpeg
except ImportError:  # pragma: no cover
    ffmpeg = None

try:
    import imagehash
except ImportError:  # pragma: no cover
    imagehash = None

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

try:
    import clip
    import torch
except ImportError:  # pragma: no cover
    clip = None
    torch = None


LOGGER = logging.getLogger(__name__)
FRAME_LIMIT = 12
MAX_IMAGE_BYTES = 5 * 1024 * 1024
USER_AGENT = "sports-ip-protection-visual-crawler/1.0"


@dataclass(slots=True)
class ExtractedVisualLink:
    image_url: str
    source_url: str
    page_url: str
    platform: str


@dataclass(slots=True)
class ScoredCandidate:
    source_url: str
    page_url: str
    platform: str
    thumbnail_url: str
    phash_distance: int | None
    clip_score: float | None
    visual_score: float


class VisualLinkParser(HTMLParser):
    def __init__(self, page_url: str) -> None:
        super().__init__()
        self.page_url = page_url
        self.links: list[ExtractedVisualLink] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key.lower(): value for key, value in attrs if value}
        if tag == "meta":
            name = (attr.get("property") or attr.get("name") or "").lower()
            if name in {"og:image", "twitter:image"}:
                self._append(attr.get("content"), self.page_url)
            elif name in {"og:video", "twitter:player"}:
                self._append(attr.get("content"), attr.get("content"))
            return
        if tag == "img":
            self._append(attr.get("src") or attr.get("data-src"), self.page_url)
            return
        if tag == "video":
            self._append(attr.get("poster"), attr.get("src") or self.page_url)
            return
        if tag == "source":
            self._append(attr.get("src"), attr.get("src"))
            return
        if tag == "a":
            href = attr.get("href")
            if href and _looks_like_media_url(href):
                self._append(href, href)

    def _append(self, image_url: str | None, source_url: str | None) -> None:
        if not image_url:
            return
        absolute_image = urljoin(self.page_url, image_url)
        absolute_source = urljoin(self.page_url, source_url or self.page_url)
        self.links.append(
            ExtractedVisualLink(
                image_url=absolute_image,
                source_url=absolute_source,
                page_url=self.page_url,
                platform=_platform_for_url(absolute_source),
            )
        )


class ClipEmbedder:
    _model: Any | None = None
    _preprocess: Any | None = None
    _disabled_logged = False
    _load_failed = False

    def available(self) -> bool:
        if clip is None or torch is None or Image is None:
            if not self._disabled_logged:
                LOGGER.info("clip_unavailable using_phash_only=true")
                self._disabled_logged = True
            return False
        return True

    def embed(self, image: Any) -> bytes | None:
        if self._load_failed or not self.available():
            return None
        try:
            if self._model is None or self._preprocess is None:
                cache_root = get_settings().temp_root / "clip_cache"
                cache_root.mkdir(parents=True, exist_ok=True)
                self._model, self._preprocess = clip.load(
                    "ViT-B/32",
                    device="cpu",
                    download_root=str(cache_root),
                )
                self._model.eval()
            with torch.no_grad():
                tensor = self._preprocess(image).unsqueeze(0)
                embedding = self._model.encode_image(tensor)
                embedding = embedding / embedding.norm(dim=-1, keepdim=True)
            return pickle.dumps(embedding.cpu().numpy()[0].astype("float32"))
        except Exception as exc:
            LOGGER.warning("clip_embedding_disabled error=%s", exc)
            self._load_failed = True
            return None


class VisualDiscoveryService:
    def __init__(
        self,
        session: AsyncSession,
        client: httpx.AsyncClient | None = None,
        clip_embedder: ClipEmbedder | None = None,
    ) -> None:
        self.session = session
        self.settings = get_settings()
        self.client = client
        self.clip_embedder = clip_embedder or ClipEmbedder()

    async def index_asset(self, asset_id: UUID, video_path: str) -> int:
        if ffmpeg is None or imagehash is None or Image is None:
            raise RuntimeError("ffmpeg-python, ImageHash, and Pillow are required for visual discovery")

        workspace = self.settings.temp_root / "visual_frames" / str(asset_id)
        frames_dir = workspace / f"frames_{uuid4()}"
        frames_dir.mkdir(parents=True, exist_ok=True)
        frame_paths = await self._extract_asset_frames(video_path, frames_dir)

        await self.session.execute(delete(VisualAssetFrame).where(VisualAssetFrame.asset_id == str(asset_id)))
        count = 0
        for index, frame_path in enumerate(frame_paths):
            with Image.open(frame_path) as image:
                prepared = image.convert("RGB")
                phash = _phash_image(prepared)
                clip_vector = self.clip_embedder.embed(prepared)
            self.session.add(
                VisualAssetFrame(
                    asset_id=str(asset_id),
                    timestamp_ms=index * 5000,
                    frame_path=str(frame_path),
                    phash=phash,
                    clip_vector=clip_vector,
                )
            )
            count += 1
        await self.session.commit()
        return count

    async def discover(
        self,
        asset_id: UUID,
        query: str,
        max_candidates: int | None = None,
    ) -> list[CandidateVideo]:
        max_candidates = max_candidates or self.settings.visual_crawl_max_candidates
        asset_frames = await self._asset_frames(asset_id)
        if not asset_frames:
            return []

        page_urls = await self._seed_page_urls(query)
        visual_links = await self._extract_visual_links(page_urls)
        scored = await self._score_links(asset_id, asset_frames, visual_links)
        best = _dedupe_scored(scored)[:max_candidates]
        await self._store_candidates(asset_id, best)
        return [
            CandidateVideo(
                source_url=item.source_url,
                platform=item.platform,
                channel=urlparse(item.source_url).netloc or None,
                view_count=None,
                duration_ms=None,
                geo_country=country_for_url(item.source_url),
                thumbnail_url=item.thumbnail_url,
                uploaded_at=None,
            )
            for item in best
        ]

    async def _asset_frames(self, asset_id: UUID) -> list[VisualAssetFrame]:
        result = await self.session.execute(
            select(VisualAssetFrame).where(VisualAssetFrame.asset_id == str(asset_id))
        )
        return list(result.scalars().all())

    async def _extract_asset_frames(self, video_path: str, frames_dir: Path) -> list[Path]:
        output_pattern = frames_dir / "frame_%06d.jpg"

        def _run() -> list[Path]:
            (
                ffmpeg
                .input(video_path)
                .filter("fps", fps="1/5", round="down")
                .output(str(output_pattern), vframes=FRAME_LIMIT, start_number=0, **{"qscale:v": 2})
                .overwrite_output()
                .run(capture_stdout=True, capture_stderr=True)
            )
            return sorted(frames_dir.glob("frame_*.jpg"))

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _run)

    async def _seed_page_urls(self, query: str) -> list[str]:
        urls: list[str] = []
        urls.extend(await self._watchlist_urls())
        if query:
            try:
                from app.services.crawler import _duckduckgo_search

                urls.extend(await _duckduckgo_search(f"sports replay video {query}", self.settings.visual_crawl_max_pages))
            except Exception as exc:
                LOGGER.info("visual_search_seed_failed error=%s", exc)
        return _dedupe_urls(urls)[: self.settings.visual_crawl_max_pages]

    async def _watchlist_urls(self) -> list[str]:
        result = await self.session.execute(select(CrawlWatchlist).where(CrawlWatchlist.enabled == True))  # noqa: E712
        urls = [item.root_url for item in result.scalars().all()]
        env_urls = self.settings.crawler_watchlist_urls
        if env_urls:
            urls.extend(url.strip() for url in env_urls.split(",") if url.strip())
        return urls

    async def _extract_visual_links(self, page_urls: list[str]) -> list[ExtractedVisualLink]:
        links: list[ExtractedVisualLink] = []
        client = self.client
        owns_client = client is None
        if client is None:
            client = httpx.AsyncClient(
                timeout=15.0,
                follow_redirects=True,
                headers={"User-Agent": USER_AGENT},
            )
        try:
            for page_url in page_urls:
                if len(links) >= self.settings.visual_crawl_max_images:
                    break
                try:
                    response = await client.get(page_url)
                    response.raise_for_status()
                except Exception:
                    continue
                content_type = response.headers.get("content-type", "").lower()
                if content_type.startswith("image/"):
                    links.append(
                        ExtractedVisualLink(
                            image_url=page_url,
                            source_url=page_url,
                            page_url=page_url,
                            platform=_platform_for_url(page_url),
                        )
                    )
                    continue
                if "html" not in content_type:
                    continue
                parser = VisualLinkParser(page_url)
                parser.feed(response.text[:1_000_000])
                links.extend(parser.links)
            return _dedupe_links(links)[: self.settings.visual_crawl_max_images]
        finally:
            if owns_client:
                await client.aclose()

    async def _score_links(
        self,
        asset_id: UUID,
        asset_frames: list[VisualAssetFrame],
        links: list[ExtractedVisualLink],
    ) -> list[ScoredCandidate]:
        scored: list[ScoredCandidate] = []
        client = self.client
        owns_client = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=15.0, follow_redirects=True, headers={"User-Agent": USER_AGENT})
        try:
            for link in links:
                try:
                    image = await self._download_image(client, link.image_url)
                except Exception:
                    continue
                phash = _phash_image(image)
                distance = min(_hamming_hex(phash, frame.phash) for frame in asset_frames)
                if distance > self.settings.visual_phash_threshold:
                    continue
                clip_score = self._clip_score(image, asset_frames)
                visual_score = _visual_score(distance, self.settings.visual_phash_threshold, clip_score)
                scored.append(
                    ScoredCandidate(
                        source_url=link.source_url,
                        page_url=link.page_url,
                        platform=link.platform,
                        thumbnail_url=link.image_url,
                        phash_distance=distance,
                        clip_score=clip_score,
                        visual_score=visual_score,
                    )
                )
        finally:
            if owns_client:
                await client.aclose()
        return sorted(scored, key=lambda item: item.visual_score, reverse=True)

    async def _download_image(self, client: httpx.AsyncClient, url: str) -> Any:
        response = await client.get(url)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        if "image/" not in content_type and not _looks_like_image_url(url):
            raise ValueError("not an image response")
        if len(response.content) > MAX_IMAGE_BYTES:
            raise ValueError("image too large")
        with Image.open(io.BytesIO(response.content)) as image:
            return image.convert("RGB")

    def _clip_score(self, image: Any, asset_frames: list[VisualAssetFrame]) -> float | None:
        vector_bytes = self.clip_embedder.embed(image)
        if vector_bytes is None:
            return None
        candidate = pickle.loads(vector_bytes)
        scores: list[float] = []
        for frame in asset_frames:
            if frame.clip_vector is None:
                continue
            asset_vector = pickle.loads(frame.clip_vector)
            scores.append(float(candidate.dot(asset_vector)))
        if not scores:
            return None
        return max(scores)

    async def _store_candidates(self, asset_id: UUID, candidates: list[ScoredCandidate]) -> None:
        for item in candidates:
            self.session.add(
                VisualCandidate(
                    asset_id=str(asset_id),
                    source_url=item.source_url,
                    page_url=item.page_url,
                    platform=item.platform,
                    thumbnail_url=item.thumbnail_url,
                    phash_distance=item.phash_distance,
                    clip_score=item.clip_score,
                    visual_score=item.visual_score,
                )
            )
        await self.session.commit()


def _phash_image(image: Any) -> str:
    if imagehash is None or Image is None:
        raise RuntimeError("ImageHash and Pillow are required for visual discovery")
    return str(imagehash.phash(image.convert("L").resize((32, 32)), hash_size=8))


def _hamming_hex(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()


def _visual_score(distance: int, threshold: int, clip_score: float | None) -> float:
    phash_score = max(0.0, 1.0 - (distance / max(1, threshold)))
    if clip_score is None:
        return round(phash_score, 4)
    normalized_clip = max(0.0, min(1.0, (clip_score + 1.0) / 2.0))
    return round((phash_score * 0.65) + (normalized_clip * 0.35), 4)


def _looks_like_image_url(url: str) -> bool:
    return Path(urlparse(url).path.lower()).suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _looks_like_media_url(url: str) -> bool:
    return Path(urlparse(url).path.lower()).suffix in {
        ".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".mov", ".m4v", ".webm", ".mkv"
    }


def _platform_for_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "youtube." in host or "youtu.be" in host:
        return "youtube"
    if "tiktok." in host:
        return "tiktok"
    if "t.me" in host or "telegram." in host:
        return "telegram"
    return "web"


def _dedupe_urls(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for url in urls:
        if url in seen or not url.startswith(("http://", "https://")):
            continue
        seen.add(url)
        output.append(url)
    return output


def _dedupe_links(links: list[ExtractedVisualLink]) -> list[ExtractedVisualLink]:
    seen: set[tuple[str, str]] = set()
    output: list[ExtractedVisualLink] = []
    for link in links:
        key = (link.source_url, link.image_url)
        if key in seen:
            continue
        seen.add(key)
        output.append(link)
    return output


def _dedupe_scored(candidates: list[ScoredCandidate]) -> list[ScoredCandidate]:
    best: dict[str, ScoredCandidate] = {}
    for candidate in candidates:
        current = best.get(candidate.source_url)
        if current is None or candidate.visual_score > current.visual_score:
            best[candidate.source_url] = candidate
    return sorted(best.values(), key=lambda item: item.visual_score, reverse=True)
