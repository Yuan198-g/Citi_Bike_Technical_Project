-- Daily and hourly demand (New York local time).
SELECT * FROM trips_daily ORDER BY local_date;
SELECT local_hour, COUNT(*) AS trips FROM fact_trip GROUP BY local_hour ORDER BY local_hour;
SELECT start_station_id, COUNT(*) AS departures FROM fact_trip
WHERE start_station_id IS NOT NULL GROUP BY start_station_id ORDER BY departures DESC LIMIT 10;
SELECT * FROM station_arrivals_hourly ORDER BY local_date, local_hour;
SELECT rider_type, COUNT(*) AS trips FROM fact_trip GROUP BY rider_type;
SELECT bike_type, COUNT(*) AS trips FROM fact_trip GROUP BY bike_type;
SELECT is_weekend, COUNT(*) AS trips FROM fact_trip GROUP BY is_weekend;
SELECT COUNT(*) AS trips, AVG(duration_seconds)/60 AS mean_minutes FROM fact_trip;
SELECT * FROM processed_files;
SELECT reason, COUNT(*) AS records FROM rejected_records GROUP BY reason;


SELECT rider_type, COUNT(*) AS trips
FROM fact_trip
WHERE local_date BETWEEN '2025-09-01' AND '2025-09-30'
GROUP BY rider_type
ORDER BY trips DESC;


SELECT bike_type, COUNT(*) AS trips
FROM fact_trip
WHERE local_date BETWEEN '2025-09-01' AND '2025-09-30'
GROUP BY bike_type
ORDER BY trips DESC;


WITH durations AS (
    SELECT
        CASE
            WHEN duration_seconds < 300 THEN '1. Under 5 min'
            WHEN duration_seconds < 900 THEN '2. 5–15 min'
            WHEN duration_seconds < 1800 THEN '3. 15–30 min'
            WHEN duration_seconds < 3600 THEN '4. 30–60 min'
            ELSE '5. 60+ min'
        END AS duration_group
    FROM fact_trip
    WHERE local_date BETWEEN '2025-09-01' AND '2025-09-30'
)
SELECT duration_group, COUNT(*) AS trips
FROM durations
GROUP BY duration_group
ORDER BY duration_group;