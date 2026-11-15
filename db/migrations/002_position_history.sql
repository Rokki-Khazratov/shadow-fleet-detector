CREATE TABLE position_history (
  LIKE latest_position INCLUDING CONSTRAINTS,
  PRIMARY KEY (source_id, mmsi, provider_bucket),
  FOREIGN KEY (source_id) REFERENCES source (source_id)
);
CREATE INDEX position_history_expiry_idx ON position_history (source_id, provider_time);
