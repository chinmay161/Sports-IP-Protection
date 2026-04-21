import asyncio
from functools import lru_cache

from app.core.config import get_settings

try:
    from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility
except ImportError:  # pragma: no cover - exercised only when dependency is absent
    Collection = None
    CollectionSchema = None
    DataType = None
    FieldSchema = None
    connections = None
    utility = None


settings = get_settings()
HASH_VECTOR_INDEX_PARAMS = {"index_type": "BIN_FLAT", "metric_type": "HAMMING", "params": {}}


def _connect() -> None:
    if connections is None:
        raise RuntimeError("pymilvus is required for Milvus operations")

    kwargs: dict[str, str] = {"alias": "default", "uri": settings.milvus_uri}
    if settings.milvus_token:
        kwargs["token"] = settings.milvus_token

    connections.connect(**kwargs)


@lru_cache(maxsize=1)
def get_collection():
    if Collection is None:
        raise RuntimeError("pymilvus is required for Milvus operations")

    _connect()
    return Collection(settings.milvus_collection_name)


def _ensure_collection_sync() -> None:
    if Collection is None or CollectionSchema is None or FieldSchema is None or DataType is None or utility is None:
        raise RuntimeError("pymilvus is required for Milvus operations")

    _connect()
    if not utility.has_collection(settings.milvus_collection_name):
        schema = CollectionSchema(
            fields=[
                FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
                FieldSchema(name="asset_id", dtype=DataType.VARCHAR, max_length=36),
                FieldSchema(name="timestamp_ms", dtype=DataType.INT64),
                FieldSchema(name="type", dtype=DataType.VARCHAR, max_length=8),
                FieldSchema(name="hash_vector", dtype=DataType.BINARY_VECTOR, dim=64),
            ],
            description="Perceptual video and audio fingerprints",
        )
        collection = Collection(name=settings.milvus_collection_name, schema=schema)
    else:
        collection = Collection(settings.milvus_collection_name)

    if not collection.has_index(index_name="hash_vector"):
        collection.create_index(
            field_name="hash_vector",
            index_params=HASH_VECTOR_INDEX_PARAMS,
            index_name="hash_vector",
        )

    collection.load()


async def ensure_collection() -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _ensure_collection_sync)
