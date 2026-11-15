"""Opt-in local history of reconciled AIS observations, keyed by UTC second."""
from datetime import timedelta

from .model import NormalizedPosition, ProjectedPosition
from .reconcile import merge_position

HISTORY_RETENTION = timedelta(days=7)


def record_positions(conn, source_id, candidates):
    groups = {}
    for position in candidates:
        key = (position.mmsi, position.provider_bucket)
        groups.setdefault(key, []).append(position)
    if not groups:
        return

    rows = conn.execute('''SELECT h.*, ST_X(h.geom) AS lon, ST_Y(h.geom) AS lat
        FROM position_history h
        JOIN unnest(%s::text[], %s::bigint[]) AS keys(mmsi, bucket)
          ON h.mmsi=keys.mmsi AND h.provider_bucket=keys.bucket
        WHERE h.source_id=%s''', ([k[0] for k in groups], [k[1] for k in groups], source_id))
    current = {(r['mmsi'], r['provider_bucket']): ProjectedPosition(
        NormalizedPosition(**{field: r[field] for field in NormalizedPosition.__dataclass_fields__}),
        r['time_conflict']) for r in rows}

    changes = []
    for key, positions in groups.items():
        old = result = current.get(key)
        for position in positions:
            result = merge_position(result, position)
        if result != old:
            p = result.position
            changes.append((p.source_id, p.mmsi, p.lon, p.lat, p.provider_time, p.provider_bucket,
                            p.time_precision, p.received_at, p.transport, p.sog_kn, p.cog_deg,
                            p.heading_deg, p.fingerprint, result.time_conflict, p.clock_skew))
    if changes:
        with conn.cursor() as cursor:
            cursor.executemany('''INSERT INTO position_history
                (source_id,mmsi,geom,provider_time,provider_bucket,time_precision,received_at,
                 transport,sog_kn,cog_deg,heading_deg,fingerprint,time_conflict,clock_skew)
                VALUES (%s,%s,ST_SetSRID(ST_MakePoint(%s,%s),4326),%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (source_id, mmsi, provider_bucket) DO UPDATE SET
                  geom=excluded.geom, provider_time=excluded.provider_time,
                  time_precision=excluded.time_precision, received_at=excluded.received_at,
                  transport=excluded.transport, sog_kn=excluded.sog_kn, cog_deg=excluded.cog_deg,
                  heading_deg=excluded.heading_deg, fingerprint=excluded.fingerprint,
                  time_conflict=excluded.time_conflict, clock_skew=excluded.clock_skew''', changes)
