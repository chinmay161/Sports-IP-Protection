import asyncio
from pathlib import Path
from app.services.crawler import CrawlerService

async def main():
    service = CrawlerService(mode='real')
    url = "https://www.pexels.com/video/aerial-view-of-youth-soccer-match-on-green-field-31370176/"
    dest_dir = Path("/tmp/sports-ip-test")
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        print(f"Downloading {url} ...")
        path = await service.download_clip(url, dest_dir)
        print(f"Downloaded to {path}")
    except Exception as e:
        print(f"Failed to download: {e}")

if __name__ == "__main__":
    asyncio.run(main())
