"""Read-only local API for the current AIS projection."""
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable, Literal

import psycopg
from fastapi import FastAPI, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from pydantic import BaseModel

from .history import HISTORY_RETENTION

@dataclass(frozen=True)
class Settings:
    database_url: str


class SourceAttribution(BaseModel):
    id: str
    attribution: str
    license_url: str


class SourceInfo(SourceAttribution):
    sync_state: Literal["starting", "syncing", "live", "degraded"]
    last_mqtt_at: datetime | None
    last_snapshot_at: datetime | None


class Observation(BaseModel):
    source_id: str
    mmsi: str
    lon: float
    lat: float
    provider_time: datetime
    time_precision: Literal["second", "millisecond"]
    transport: Literal["rest", "mqtt"]
    received_at: datetime
    time_conflict: bool
    clock_skew: bool
    sog_kn: float | None
    cog_deg: float | None
    heading_deg: float | None


class Position(Observation):
    age_seconds: float
    stale: bool


class ObservationHistory(BaseModel):
    source: SourceAttribution
    mmsi: str
    items: list[Observation]
    truncated: bool


class PositionPage(BaseModel):
    as_of: datetime
    source: SourceInfo
    items: list[Position]
    truncated: bool


class PositionDetail(BaseModel):
    as_of: datetime
    source: SourceInfo
    item: Position


class ErrorInfo(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorInfo


def _error(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def _bbox(values):
    try:
        west, south, east, north = (float(value) for value in values)
    except (TypeError, ValueError):
        raise ValueError("Four finite bbox coordinates are required") from None
    if (not all(map(math.isfinite, (west, south, east, north))) or
        not (-180 <= west <= 180 and -180 <= east <= 180 and
             -90 <= south < north <= 90) or west == east or (west == 180 and east == -180)):
        raise ValueError("Invalid bbox")
    return west, south, east, north


def _source(conn, source_id, as_of):
    source = conn.execute("""SELECT s.source_id AS id, s.attribution, s.license_url,
        COALESCE(st.sync_state,'starting') AS sync_state, st.heartbeat_at,
        st.last_mqtt_at, st.last_snapshot_at
        FROM source s LEFT JOIN source_state st USING (source_id) WHERE s.source_id=%s""",
        (source_id,)).fetchone()
    if source is None:
        return None
    heartbeat = source.pop("heartbeat_at")
    stale_heartbeat = heartbeat is not None and heartbeat < as_of - timedelta(seconds=15)
    missing_heartbeat = heartbeat is None and source["sync_state"] in ('syncing', 'live')
    stale_live_push = source["sync_state"] == "live" and (
        source["last_mqtt_at"] is None or source["last_mqtt_at"] < as_of - timedelta(seconds=60))
    if stale_heartbeat or missing_heartbeat or stale_live_push:
        source["sync_state"] = "degraded"
    return source


def _item(row, as_of):
    age = max(0.0, (as_of - row["provider_time"]).total_seconds())
    row["age_seconds"] = age
    row["stale"] = age > 300
    return row


_COLUMNS = """source_id, mmsi, ST_X(geom) AS lon, ST_Y(geom) AS lat,
    provider_time, time_precision, transport, received_at, time_conflict, clock_skew,
    sog_kn, cog_deg, heading_deg"""
_UTC_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?(Z|\+00:00)")


def _history_window(from_, to):
    if not from_ or not to or not all(_UTC_TIMESTAMP.fullmatch(s) for s in (from_, to)):
        raise ValueError("from and to must be UTC timestamps")
    start, end = map(datetime.fromisoformat, (from_, to))
    if not timedelta(0) < end - start <= HISTORY_RETENTION:
        raise ValueError("History window must be positive and at most seven days")
    return start, end


def create_app(settings: Settings, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> FastAPI:
    app = FastAPI(title="Shadow Fleet Detector API", version="0.2.0")

    @app.middleware("http")
    async def no_store(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    def connect():
        conn = psycopg.connect(settings.database_url, connect_timeout=3, row_factory=dict_row)
        try:
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            conn.execute("SET LOCAL statement_timeout = '5s'")
        except BaseException:
            conn.close()
            raise
        return conn

    @app.get("/v1/positions", response_model=PositionPage,
             responses={400: {"model": ErrorResponse}, 503: {"model": ErrorResponse}})
    def positions(west: str | None = Query(None), south: str | None = Query(None),
                  east: str | None = Query(None), north: str | None = Query(None)):
        try:
            w, s, e, n = _bbox((west, south, east, north))
        except ValueError as exc:
            return _error("invalid_bbox", str(exc), 400)
        as_of = clock()
        try:
            with connect() as conn:
                source = _source(conn, "fintraffic", as_of)
                if source is None:
                    return _error("database_unavailable", "Source configuration unavailable", 503)
                if w < e:
                    # +180 is the same meridian as canonical -180.
                    spatial = "(geom && ST_MakeEnvelope(%s,%s,%s,%s,4326) OR (%s = 180 AND ST_X(geom) = -180 AND ST_Y(geom) BETWEEN %s AND %s))"
                    params = (w, s, e, n, e, s, n)
                else:
                    spatial = "(geom && ST_MakeEnvelope(%s,%s,180,%s,4326) OR geom && ST_MakeEnvelope(-180,%s,%s,%s,4326))"
                    params = (w, s, n, s, e, n)
                rows = conn.execute(f"""SELECT {_COLUMNS} FROM latest_position
                    WHERE source_id=%s AND provider_time >= %s AND {spatial}
                    ORDER BY provider_bucket DESC, source_id ASC, mmsi ASC LIMIT 2001""",
                    ("fintraffic", as_of - timedelta(hours=24), *params)).fetchall()
                payload = {"as_of": as_of, "source": source,
                           "items": [_item(row, as_of) for row in rows[:2000]],
                           "truncated": len(rows) > 2000}
                return JSONResponse(content=jsonable_encoder(payload))
        except psycopg.Error:
            return _error("database_unavailable", "Database unavailable", 503)

    @app.get("/v1/positions/{source_id}/{mmsi}", response_model=PositionDetail,
             responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse},
                        503: {"model": ErrorResponse}})
    def position(source_id: str, mmsi: str):
        if not re.fullmatch(r"[0-9]{9}", mmsi):
            return _error("invalid_mmsi", "MMSI must contain nine digits", 400)
        as_of = clock()
        try:
            with connect() as conn:
                source = _source(conn, source_id, as_of)
                row = conn.execute(f"""SELECT {_COLUMNS} FROM latest_position
                    WHERE source_id=%s AND mmsi=%s AND provider_time >= %s""",
                    (source_id, mmsi, as_of - timedelta(hours=24))).fetchone()
                if source is None or row is None:
                    return _error("not_found", "Position not found", 404)
                return JSONResponse(content=jsonable_encoder(
                    {"as_of": as_of, "source": source, "item": _item(row, as_of)}))
        except psycopg.Error:
            return _error("database_unavailable", "Database unavailable", 503)

    @app.get("/v1/history/{source_id}/{mmsi}", response_model=ObservationHistory,
             responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse},
                        503: {"model": ErrorResponse}})
    def history(source_id: str, mmsi: str, from_: str | None = Query(None, alias="from"),
                to: str | None = Query(None), limit: str = Query("1000")):
        if not re.fullmatch(r"[0-9]{9}", mmsi):
            return _error("invalid_mmsi", "MMSI must contain nine digits", 400)
        try:
            start, end = _history_window(from_, to)
        except ValueError:
            return _error("invalid_window", "Use UTC from/to and a positive window of up to seven days", 400)
        if not re.fullmatch(r"[0-9]{1,4}", limit) or not 1 <= (cap := int(limit)) <= 1000:
            return _error("invalid_limit", "Limit must be between 1 and 1000", 400)

        cutoff = max(start, clock() - HISTORY_RETENTION)
        try:
            with connect() as conn:
                source = conn.execute("SELECT source_id AS id, attribution, license_url FROM source WHERE source_id=%s",
                                      (source_id,)).fetchone()
                if source is None:
                    return _error("not_found", "Source not found", 404)
                rows = conn.execute(f"""SELECT {_COLUMNS} FROM position_history
                    WHERE source_id=%s AND mmsi=%s AND provider_bucket >= %s AND provider_bucket < %s
                      AND provider_time >= %s AND provider_time < %s
                    ORDER BY provider_bucket LIMIT %s""",
                    (source_id, mmsi, math.floor(cutoff.timestamp()), math.ceil(end.timestamp()), cutoff, end, cap + 1)).fetchall()
                return {"source": source, "mmsi": mmsi, "items": rows[:cap], "truncated": len(rows) > cap}
        except psycopg.Error:
            return _error("database_unavailable", "Database unavailable", 503)

    return app
