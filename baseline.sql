CREATE VIEW IF NOT EXISTS station_hourly_baseline_202509 AS
WITH RECURSIVE
calendar(local_date) AS (
    SELECT '2025-09-01'
    UNION ALL
    SELECT date(local_date, '+1 day')
    FROM calendar
    WHERE local_date < '2025-09-30'
),
hour_list(local_hour) AS (
    SELECT 0
    UNION ALL
    SELECT local_hour + 1
    FROM hour_list
    WHERE local_hour < 23
),
weekday_counts AS (
    SELECT
        (CAST(strftime('%w', local_date) AS INTEGER) + 6) % 7 AS weekday,
        COUNT(*) AS sample_days
    FROM calendar
    GROUP BY weekday
),
flow_records AS (
    SELECT
        station_id,
        local_date,
        local_hour,
        trips AS departures,
        0 AS arrivals
    FROM station_departures_hourly
    WHERE local_date BETWEEN '2025-09-01' AND '2025-09-30'
    UNION ALL
    SELECT
        station_id,
        local_date,
        local_hour,
        0 AS departures,
        trips AS arrivals
    FROM station_arrivals_hourly
    WHERE local_date BETWEEN '2025-09-01' AND '2025-09-30'
),
station_list AS (
    SELECT DISTINCT station_id
    FROM flow_records
),
flow_totals AS (
    SELECT
        station_id,
        (CAST(strftime('%w', local_date) AS INTEGER) + 6) % 7 AS weekday,
        local_hour,
        SUM(departures) AS total_departures,
        SUM(arrivals) AS total_arrivals
    FROM flow_records
    GROUP BY station_id, weekday, local_hour
)
SELECT
    s.station_id,
    w.weekday,
    h.local_hour,
    w.sample_days,
    ROUND(
        COALESCE(f.total_departures, 0) * 1.0 / w.sample_days,
        2
    ) AS avg_departures,
    ROUND(
        COALESCE(f.total_arrivals, 0) * 1.0 / w.sample_days,
        2
    ) AS avg_arrivals,
    ROUND(
        (COALESCE(f.total_departures, 0) -
         COALESCE(f.total_arrivals, 0)) * 1.0 / w.sample_days,
        2
    ) AS avg_net_outflow
FROM station_list AS s
CROSS JOIN weekday_counts AS w
CROSS JOIN hour_list AS h
LEFT JOIN flow_totals AS f
    ON f.station_id = s.station_id
    AND f.weekday = w.weekday
    AND f.local_hour = h.local_hour;