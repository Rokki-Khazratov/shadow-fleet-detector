CREATE EXTENSION IF NOT EXISTS postgis;
CREATE TABLE source (
  source_id text PRIMARY KEY, display_name text NOT NULL,
  attribution text NOT NULL, license_url text NOT NULL, policy_checked_at date NOT NULL
);
INSERT INTO source VALUES ('fintraffic', 'Fintraffic / Digitraffic',
  'Data: Fintraffic / Digitraffic, CC BY 4.0; normalized and filtered',
  'https://creativecommons.org/licenses/by/4.0/', '2026-11-14');
CREATE TABLE source_state (
  source_id text PRIMARY KEY REFERENCES source(source_id),
  epoch bigint NOT NULL CHECK (epoch >= 0),
  sync_state text NOT NULL CHECK (sync_state IN ('starting','syncing','live','degraded')),
  heartbeat_at timestamptz,
  last_snapshot_at timestamptz,
  last_mqtt_at timestamptz,
  error_code text
);
INSERT INTO source_state(source_id, epoch, sync_state) VALUES ('fintraffic', 0, 'starting');
CREATE TABLE latest_position (
  source_id text NOT NULL REFERENCES source(source_id),
  mmsi text NOT NULL CHECK (mmsi ~ '^[0-9]{9}$'),
  geom geometry(Point,4326) NOT NULL,
  provider_time timestamptz NOT NULL,
  provider_bucket bigint NOT NULL,
  time_precision text NOT NULL CHECK (time_precision IN ('second','millisecond')),
  received_at timestamptz NOT NULL,
  transport text NOT NULL CHECK (transport IN ('rest','mqtt')),
  sog_kn double precision,
  cog_deg double precision,
  heading_deg double precision,
  fingerprint bytea NOT NULL CHECK (octet_length(fingerprint)=32),
  time_conflict boolean NOT NULL,
  clock_skew boolean NOT NULL,
  PRIMARY KEY (source_id,mmsi),
  CHECK (provider_bucket = floor(extract(epoch FROM provider_time))::bigint),
  CHECK (NOT ST_IsEmpty(geom) AND ST_NDims(geom)=2 AND
         ST_X(geom) >= -180 AND ST_X(geom) < 180 AND
         ST_Y(geom) >= -90 AND ST_Y(geom) <= 90),
  CHECK (sog_kn IS NULL OR (sog_kn >= 0 AND sog_kn < 102.3 AND sog_kn < 'Infinity'::float8)),
  CHECK (cog_deg IS NULL OR (cog_deg >= 0 AND cog_deg < 360 AND cog_deg < 'Infinity'::float8)),
  CHECK (heading_deg IS NULL OR (heading_deg >= 0 AND heading_deg <= 359 AND heading_deg < 'Infinity'::float8 AND heading_deg = trunc(heading_deg)))
);
CREATE INDEX latest_position_geom_idx ON latest_position USING gist(geom);
CREATE INDEX latest_position_bucket_idx ON latest_position(provider_bucket);
