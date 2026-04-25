from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.match import Match
from app.schemas.propagation import (
    GraphEdge,
    GraphMeta,
    GraphNode,
    PropagationGraph,
    PropagationSummary,
    PropagationTimeline,
    TimelineBucket,
)

BUCKET_SIZE_MS = 3_600_000
UNKNOWN_DELTA_MS = 172_800_000


class PropagationError(Exception):
    pass


def _sort_nodes(nodes: list[GraphNode]) -> list[GraphNode]:
    return sorted(nodes, key=lambda node: (node.detected_at, node.id))


def _delta_ms(source: GraphNode, target: GraphNode) -> int:
    return int((target.detected_at - source.detected_at).total_seconds() * 1000)


def _infer_edges(nodes: list[GraphNode]) -> list[GraphEdge]:
    sorted_nodes = _sort_nodes(nodes)
    edges: list[GraphEdge] = []

    for index, target in enumerate(sorted_nodes[1:], start=1):
        earlier_nodes = [
            node for node in sorted_nodes[:index] if node.detected_at < target.detected_at
        ]
        if not earlier_nodes:
            continue

        different_platform = [
            node for node in earlier_nodes if node.platform != target.platform
        ]
        if different_platform:
            source = max(different_platform, key=lambda node: (node.detected_at, node.id))
            relation = "repost"
        else:
            source = max(earlier_nodes, key=lambda node: (node.detected_at, node.id))
            relation = "mirror"

        delta_ms = _delta_ms(source, target)
        if delta_ms > UNKNOWN_DELTA_MS:
            relation = "unknown"

        edges.append(
            GraphEdge(
                id=str(uuid5(NAMESPACE_URL, f"{source.id}-{target.id}")),
                source=source.id,
                target=target.id,
                relation=relation,
                delta_ms=delta_ms,
            )
        )

    return edges


def _assign_node_types(nodes: list[GraphNode]) -> list[GraphNode]:
    sorted_nodes = _sort_nodes(nodes)
    edges_by_target = {edge.target: edge for edge in _infer_edges(sorted_nodes)}
    typed_nodes: list[GraphNode] = []

    for index, node in enumerate(sorted_nodes):
        if index == 0:
            node_type = "origin"
        else:
            edge = edges_by_target.get(node.id)
            node_type = edge.relation if edge and edge.relation in {"repost", "mirror"} else "unknown"
        typed_nodes.append(node.model_copy(update={"type": node_type}))

    return typed_nodes


def _build_timeline(nodes: list[GraphNode], bucket_ms: int = BUCKET_SIZE_MS) -> PropagationTimeline:
    sorted_nodes = _sort_nodes(nodes)
    if not sorted_nodes:
        raise PropagationError("Cannot build propagation timeline without nodes")

    t0 = sorted_nodes[0].detected_at
    if len(sorted_nodes) == 1:
        return PropagationTimeline(
            match_id=UUID(sorted_nodes[0].id),
            bucket_size_ms=bucket_ms,
            buckets=[
                TimelineBucket(
                    bucket_start=t0,
                    new_nodes=1,
                    cumulative_nodes=1,
                    cumulative_views=sorted_nodes[0].view_count or 0,
                )
            ],
            peak_bucket=t0,
            velocity_index=0.0,
        )

    t_end = sorted_nodes[-1].detected_at
    bucket_delta = timedelta(milliseconds=bucket_ms)
    buckets: list[TimelineBucket] = []
    cumulative_nodes = 0
    cumulative_views = 0
    peak_bucket = t0
    peak_new_nodes = -1
    bucket_start = t0

    while bucket_start <= t_end:
        bucket_end = bucket_start + bucket_delta
        bucket_nodes = [
            node for node in sorted_nodes if bucket_start <= node.detected_at < bucket_end
        ]
        new_nodes = len(bucket_nodes)
        cumulative_nodes += new_nodes
        cumulative_views += sum(node.view_count or 0 for node in bucket_nodes)

        if new_nodes > peak_new_nodes:
            peak_new_nodes = new_nodes
            peak_bucket = bucket_start

        buckets.append(
            TimelineBucket(
                bucket_start=bucket_start,
                new_nodes=new_nodes,
                cumulative_nodes=cumulative_nodes,
                cumulative_views=cumulative_views,
            )
        )
        bucket_start = bucket_end

    return PropagationTimeline(
        match_id=UUID(sorted_nodes[0].id),
        bucket_size_ms=bucket_ms,
        buckets=buckets,
        peak_bucket=peak_bucket,
        velocity_index=float(peak_new_nodes),
    )


def _node_from_match(match: Match) -> GraphNode:
    return GraphNode(
        id=str(match.id),
        type="origin",
        platform=match.platform,
        channel=match.source_channel,
        url=match.source_url,
        view_count=match.view_count,
        confidence=match.confidence,
        severity=match.severity,
        geo_country=match.geo_country,
        detected_at=match.detected_at,
        status=match.status,
    )


async def _qualifying_matches_for_asset(asset_id: str, db: AsyncSession) -> list[Match]:
    result = await db.execute(
        select(Match)
        .where(Match.asset_id == asset_id)
        .where(Match.confidence >= 0.5)
        .order_by(Match.detected_at.asc(), Match.id.asc())
    )
    return list(result.scalars().all())


async def get_graph(match_id: UUID, db: AsyncSession) -> PropagationGraph:
    anchor = await db.get(Match, str(match_id))
    if anchor is None:
        raise PropagationError(f"Match {match_id} not found")

    matches = await _qualifying_matches_for_asset(anchor.asset_id, db)
    if not matches:
        raise PropagationError(f"Match {match_id} not found")

    nodes = [_node_from_match(match) for match in matches]
    edges = _infer_edges(nodes)
    typed_nodes = _assign_node_types(nodes)

    meta = GraphMeta(
        node_count=len(nodes),
        edge_count=len(edges),
        platform_spread=dict(Counter(node.platform for node in nodes)),
        first_detected_at=nodes[0].detected_at,
        spread_duration_ms=int(
            (nodes[-1].detected_at - nodes[0].detected_at).total_seconds() * 1000
        ),
        origin_country=nodes[0].geo_country,
    )

    return PropagationGraph(
        match_id=match_id,
        generated_at=datetime.now(UTC),
        nodes=typed_nodes,
        edges=edges,
        meta=meta,
    )


async def get_timeline(match_id: UUID, db: AsyncSession) -> PropagationTimeline:
    anchor = await db.get(Match, str(match_id))
    if anchor is None:
        raise PropagationError(f"Match {match_id} not found")

    matches = await _qualifying_matches_for_asset(anchor.asset_id, db)
    if not matches:
        raise PropagationError(f"Match {match_id} not found")

    timeline = _build_timeline([_node_from_match(match) for match in matches])
    return timeline.model_copy(update={"match_id": match_id})


async def get_summary(asset_id: UUID, db: AsyncSession) -> PropagationSummary:
    asset_id_str = str(asset_id)
    result = await db.execute(
        select(
            func.count(Match.id).label("total"),
            func.coalesce(func.sum(Match.view_count), 0).label("total_views"),
            func.min(Match.detected_at).label("first_detected"),
            func.group_concat(distinct(Match.platform)).label("platforms"),
            func.count(distinct(Match.geo_country)).label("countries"),
        )
        .where(Match.asset_id == asset_id_str)
        .where(Match.confidence >= 0.5)
    )
    row = result.one()
    if int(row.total or 0) == 0:
        raise PropagationError(f"Asset {asset_id} not found")

    earliest_result = await db.execute(
        select(Match.id, Match.detected_at, Match.platform)
        .where(Match.asset_id == asset_id_str)
        .where(Match.confidence >= 0.5)
        .order_by(Match.detected_at.asc(), Match.id.asc())
        .limit(2)
    )
    earliest = list(earliest_result.all())
    fastest_repost_ms = (
        int((earliest[1].detected_at - earliest[0].detected_at).total_seconds() * 1000)
        if len(earliest) >= 2
        else None
    )
    origin_platform = earliest[0].platform if earliest else None
    peak_velocity_index = 0.0
    if earliest:
        peak_velocity_index = (
            await get_timeline(UUID(str(earliest[0].id)), db)
        ).velocity_index

    platforms = sorted(row.platforms.split(",")) if row.platforms else []
    return PropagationSummary(
        asset_id=asset_id,
        total_infringing_copies=int(row.total or 0),
        total_estimated_views=int(row.total_views or 0),
        platforms_reached=platforms,
        countries_reached=int(row.countries or 0),
        fastest_repost_ms=fastest_repost_ms,
        origin_platform=origin_platform,
        peak_velocity_index=peak_velocity_index,
    )
