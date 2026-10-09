-- Open data/operations.sqlite in DBeaver. Source dates and ingestion dates are UTC.
SELECT observed_at,outcome,effective_interval FROM live_polls ORDER BY observed_at DESC;
SELECT COUNT(*) AS snapshot_rows,COUNT(DISTINCT batch_id) AS distinct_batches,
       COUNT(DISTINCT station_id) AS stations FROM station_snapshots;

-- All stations, including stale/restricted ones: never hide freshness.
SELECT short_name,name,bikes_available,docks_available,capacity,
       is_operational,is_stale,station_age_seconds,feed_age_seconds,
       present_in_latest_poll,source_regressed,utilization,warnings
FROM station_latest ORDER BY short_name;

-- Stations currently requiring attention. This is NOT historical demand risk yet.
SELECT short_name,name,bikes_available,docks_available,low_bike,low_dock
FROM station_latest
WHERE is_stale=0 AND (low_bike=1 OR low_dock=1)
ORDER BY bikes_available,short_name;

-- JC009 time series. Delta is net available-bike inventory change, not ride counts.
SELECT observed_at,source_reported_at,bikes_available,docks_available,
       net_bike_inventory_change
FROM station_inventory_changes WHERE short_name='JC009' ORDER BY observed_at;

-- Restriction and freshness checks.
SELECT short_name,name,is_installed,is_renting,is_returning,is_stale
FROM station_latest WHERE is_operational=0 OR is_stale=1 ORDER BY short_name;
SELECT reason,COUNT(*) AS rows FROM live_quarantine GROUP BY reason;

-- Basic reconciliation: quarantined and missing statuses are explicit.
SELECT COUNT(*) AS duplicate_keys FROM (
 SELECT batch_id,station_id,COUNT(*) AS n FROM station_snapshots
 GROUP BY batch_id,station_id HAVING COUNT(*)>1
);
