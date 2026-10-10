# Integrated dashboard

Copy platform_dashboard.py and test_platform_dashboard.py beside operations_dashboard.py and compare_inventory.py. No extra Python packages. The new server defaults to port 8502, so the old 8501 server can remain stopped.

## Choose one project directory

Earlier commands used citi_bike_phase1, while the latest comparison ran from its parent Citi_Bike_Technical_Project. Use the directory containing the intended data/citibike.sqlite, data/operations.sqlite and data/raw/202509/JC-202509-citibike-tripdata.csv.zip. Do not merge or move databases blindly. Keep the collector, historical runner and dashboard in that same project directory, or explicitly point this dashboard at that directory using --root.

From that directory:

```powershell
python platform_dashboard.py --baseline-month 202509
python -m unittest test_platform_dashboard -v
```

Run the test in another terminal or before starting the server. Open http://127.0.0.1:8502. Keep the server terminal open. It prints both absolute database paths, which also appear at the bottom of the page. Paths are shown only for this locally bound development dashboard.

If the scripts are in a different directory, use an explicit root:

```powershell
python platform_dashboard.py --root "C:\Users\haoxu\Citi_Bike_Technical_Project\citi_bike_phase1" --baseline-month 202509
```

Only use that example root if it is your intended data directory. Missing database/schema/archive causes an explicit startup error; an empty database is never created.

## Page content

The existing inventory dashboard stays at the top: inventory cards, searchable stations with coordinates and operational status, freshness, selected-station time series and collection evidence. Scroll down for the new sections.

Historical demand + inventory: station, inventory, historical net outflow/hour, illustrative remaining-hour flow, sample days, attention indicator and mapping status. Search and attention filters are independent of the original station table. Click a comparison row to select that station for its inventory chart. No-threshold rows are hidden by the default attention filter; uncheck it to inspect all stations.

Recorded snapshots evaluates the comparison at the last saved successful poll, explicitly labeled a recorded example. Current operations evaluates it at the current time: stale, uncertain, unmapped or restricted records do not produce pressure signals. The original station freshness badges always indicate present-time age, even in recorded mode. A low_bikes_now label within recorded comparison describes the inventory at its recorded evaluation time, not availability now.

Historical analytics shows daily/hourly trips, weekday/weekend hourly averages per calendar day, top origins/destinations, rider and bike types, duration distribution, missing-station counts and average minutes. The historical month is a startup filter (--baseline-month), displayed on the page; no month dropdown is claimed. September 2025 should show 116017 local-start trips with your current phase 1 dataset. Top destinations filter by arrival date and can have a different total from start-date trips. The mean duration is descriptive and sensitive to long rides.

Historical profiles, baselines and charts are cached in memory at startup; operational data and combined indicators are read/evaluated every 10 seconds. Restart the server after historical batch changes. The page refresh does not collect source data or append database records. Each request uses read-only database connections. The historical cache avoids repeatedly scanning ZIPs every 10 seconds. No external JS/chart services are required.

## Acceptance

1. Check printed database paths against the directory used by poll_stations.py.
2. Open page: historical coverage should be September 2025 and total 116017; observe combined mapping counts.
3. Recorded mode should show a labeled example using the latest stored poll.
4. In a second terminal, run python poll_stations.py --cycles 3 --interval 60 from the same project directory.
5. Without manually reloading the browser, latest successful poll, collection evidence and inventory should update. Switch to Current operations for current comparison; individual sources may still be stale.
6. Stop collecting; after the freshness window, current indicators must become unavailable while history remains visible.
7. Run the three dashboard tests. They test month boundaries, zero-filled dates/hours, missing stations, calendar denominators, arrival-date behavior, category totals and no database creation on wrong paths.

Developer verification: tests and actual HTTP HTML/API passed against retained data (116017 September trips, 109 station comparisons, 89 supported mappings). Embedded JavaScript syntax was checked. Browser rendering and actual timer/UI interaction still require local acceptance; do not claim those have been visually verified here.

The operational indicator remains an unvalidated heuristic using old historical data, not a shortage probability. Its mapping, freshness, sample and quality exclusions are the phase 3 rules. Current source reads and historical cache do not form a cross-database atomic snapshot.

Part 5 remains: executable batch scheduling, architecture, recovery and final delivery instructions. No production deployment is needed for this local exercise.
