"""Single-writer projection of normalized observations in PostgreSQL."""
from dataclasses import dataclass
from contextlib import ExitStack
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Sequence

import psycopg
from psycopg.rows import dict_row

from .history import HISTORY_RETENTION, record_positions
from .model import NormalizedPosition, ProjectedPosition
from .reconcile import merge_position

MIGRATIONS = Path(__file__).resolve().parents[2] / "db" / "migrations"


@dataclass(frozen=True)
class SourceStateUpdate:
    sync_state: str
    heartbeat_at: datetime | None
    last_snapshot_at: datetime | None
    last_mqtt_at: datetime | None
    error_code: str | None


@dataclass(frozen=True)
class BatchStats:
    inserted: int = 0
    updated: int = 0
    ignored: int = 0
    conflicted: int = 0


def migrate(dsn: str) -> None:
    with psycopg.connect(dsn) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('sfd_migrations', 0))")
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, "
                     "applied_at timestamptz NOT NULL DEFAULT now(), checksum text NOT NULL)")
        for path in sorted(MIGRATIONS.glob("*.sql")):
            body = path.read_bytes()
            checksum = sha256(body).hexdigest()
            row = conn.execute("SELECT checksum FROM schema_migrations WHERE version = %s",
                               (path.name,)).fetchone()
            if row:
                if row[0] != checksum:
                    raise RuntimeError(f"migration checksum mismatch: {path.name}")
                continue
            conn.execute(body.decode())
            conn.execute("INSERT INTO schema_migrations(version, checksum) VALUES (%s, %s)",
                         (path.name, checksum))


class WriterSession:
    def __init__(self, conn, source_id: str, epoch: int, *, record_history: bool = False):
        self.conn, self.source_id, self.epoch = conn, source_id, epoch
        self.record_history = record_history

    @classmethod
    def open(cls, dsn: str, source_id: str, *, record_history: bool = False):
        conn = psycopg.connect(dsn, row_factory=dict_row, connect_timeout=3)
        try:
            conn.execute("SET statement_timeout = '5s'")
            conn.execute("SET transaction_timeout = '15s'")
            locked = conn.execute("SELECT pg_try_advisory_lock(hashtextextended(%s, 0)) AS ok",
                                  ("sfd_writer:" + source_id,)).fetchone()["ok"]
            if not locked:
                raise RuntimeError("writer_already_running")
            row = conn.execute("UPDATE source_state SET epoch = epoch + 1, sync_state = 'starting', heartbeat_at = now() "
                               "WHERE source_id = %s RETURNING epoch", (source_id,)).fetchone()
            if row is None:
                raise ValueError("unknown source")
            conn.commit()
            return cls(conn, source_id, row["epoch"], record_history=record_history)
        except BaseException:
            conn.close()
            raise

    def close(self):
        self.conn.close()

    def mark_degraded(self, *, now: datetime, error_code: str) -> None:
        with self.conn.transaction():
            row = self.conn.execute(
                "UPDATE source_state SET sync_state='degraded', heartbeat_at=%s, error_code=%s "
                "WHERE source_id=%s AND epoch=%s RETURNING epoch",
                (now, error_code, self.source_id, self.epoch)).fetchone()
            if row is None:
                raise RuntimeError('stale_epoch')

    def apply_batch(self, candidates: Sequence[NormalizedPosition], *, epoch: int,
                    state: SourceStateUpdate, now: datetime, commit_guard=None) -> BatchStats:
        if epoch != self.epoch:
            raise RuntimeError("stale_epoch")
        merged = {}
        history = []
        cutoff = now - timedelta(hours=24)
        for p in candidates:
            if p.source_id != self.source_id:
                raise ValueError("source mismatch")
            if p.provider_time < cutoff:
                continue
            if self.record_history:
                history.append(p)
            merged[p.mmsi] = merge_position(merged.get(p.mmsi), p)
        inserted = updated = ignored = conflicted = 0
        with ExitStack() as stack:
            guard_held = False
            stack.callback(lambda: commit_guard.release_commit() if guard_held else None)
            stack.enter_context(self.conn.transaction())
            row = self.conn.execute("SELECT epoch FROM source_state WHERE source_id=%s FOR UPDATE",
                                    (self.source_id,)).fetchone()
            if row is None or row["epoch"] != epoch:
                raise RuntimeError("stale_epoch")
            rows = self.conn.execute(
                "SELECT *, ST_X(geom) AS lon, ST_Y(geom) AS lat FROM latest_position "
                "WHERE source_id=%s AND mmsi = ANY(%s)",
                (self.source_id, list(merged))).fetchall()
            existing = {r["mmsi"]: r for r in rows}
            for mmsi, incoming in merged.items():
                r = existing.get(mmsi)
                if r:
                    old = NormalizedPosition(**{k: r[k] for k in NormalizedPosition.__dataclass_fields__})
                    current = ProjectedPosition(old, r["time_conflict"])
                    result = merge_position(current, incoming.position)
                    if incoming.time_conflict and result.position.provider_bucket == incoming.position.provider_bucket:
                        result = ProjectedPosition(result.position, True)
                    if result == current:
                        ignored += 1
                        continue
                    updated += 1
                else:
                    result = incoming
                    inserted += 1
                conflicted += int(result.time_conflict)
                p = result.position
                self.conn.execute("""INSERT INTO latest_position
                    (source_id,mmsi,geom,provider_time,provider_bucket,time_precision,received_at,
                     transport,sog_kn,cog_deg,heading_deg,fingerprint,time_conflict,clock_skew)
                    VALUES (%s,%s,ST_SetSRID(ST_MakePoint(%s,%s),4326),%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (source_id,mmsi) DO UPDATE SET geom=excluded.geom,
                    provider_time=excluded.provider_time,provider_bucket=excluded.provider_bucket,
                    time_precision=excluded.time_precision,received_at=excluded.received_at,
                    transport=excluded.transport,sog_kn=excluded.sog_kn,cog_deg=excluded.cog_deg,
                    heading_deg=excluded.heading_deg,fingerprint=excluded.fingerprint,
                    time_conflict=excluded.time_conflict,clock_skew=excluded.clock_skew""",
                    (p.source_id,p.mmsi,p.lon,p.lat,p.provider_time,p.provider_bucket,p.time_precision,
                     p.received_at,p.transport,p.sog_kn,p.cog_deg,p.heading_deg,p.fingerprint,
                     result.time_conflict,p.clock_skew))
            if history:
                record_positions(self.conn, self.source_id, history)
            self.conn.execute("UPDATE source_state SET sync_state=%s,heartbeat_at=%s,last_snapshot_at=%s,"
                              "last_mqtt_at=%s,error_code=%s WHERE source_id=%s",
                              (state.sync_state,state.heartbeat_at,state.last_snapshot_at,
                               state.last_mqtt_at,state.error_code,self.source_id))
            if commit_guard is not None:
                commit_guard.acquire_commit()
                guard_held = True
        return BatchStats(inserted, updated, ignored, conflicted)

    def prune(self, *, now: datetime, max_rows: int = 1000) -> int:
        if max_rows <= 0:
            raise ValueError("max_rows must be positive")
        with self.conn.transaction():
            row = self.conn.execute("SELECT epoch FROM source_state WHERE source_id=%s FOR UPDATE",
                                    (self.source_id,)).fetchone()
            if row is None or row["epoch"] != self.epoch:
                raise RuntimeError("stale_epoch")
            rows = self.conn.execute("""DELETE FROM latest_position WHERE (source_id,mmsi) IN
                (SELECT source_id,mmsi FROM latest_position WHERE source_id=%s AND provider_time < %s
                 ORDER BY provider_time LIMIT %s) RETURNING mmsi""",
                (self.source_id, now - timedelta(hours=24), max_rows)).fetchall()
            return len(rows)

    def prune_history(self, *, now: datetime, max_rows: int = 10_000) -> int:
        if not 1 <= max_rows <= 10_000:
            raise ValueError("history prune batch must be between 1 and 10000")
        with self.conn.transaction():
            row = self.conn.execute("SELECT epoch FROM source_state WHERE source_id=%s FOR UPDATE",
                                    (self.source_id,)).fetchone()
            if row is None or row["epoch"] != self.epoch:
                raise RuntimeError("stale_epoch")
            result = self.conn.execute("""DELETE FROM position_history WHERE (source_id,mmsi,provider_bucket) IN
                (SELECT source_id,mmsi,provider_bucket FROM position_history
                 WHERE source_id=%s AND provider_time < %s
                 ORDER BY provider_time, mmsi, provider_bucket LIMIT %s)""",
                (self.source_id, now - HISTORY_RETENTION, max_rows))
            return result.rowcount
