export interface Position {
  source_id: string;
  mmsi: string;
  lon: number;
  lat: number;
  provider_time: string;
  received_at: string;
  transport: 'rest' | 'mqtt';
  age_seconds: number;
  stale: boolean;
  time_conflict: boolean;
  clock_skew: boolean;
  sog_kn: number | null;
  cog_deg: number | null;
  heading_deg: number | null;
}

export interface Source {
  id: string;
  attribution: string;
  license_url: string;
  sync_state: 'starting' | 'syncing' | 'live' | 'degraded';
  last_mqtt_at: string | null;
  last_snapshot_at: string | null;
}

export interface Page {as_of: string; source: Source; items: Position[]; truncated: boolean}
export interface Detail {as_of: string; source: Source; item: Position}
