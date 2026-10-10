# Phase 3: Historical demand and inventory

Copy compare_inventory.py and test_compare_inventory.py into the existing citi_bike_phase1 folder. Python standard library only. Leave the existing databases and scripts in place. tzdata must remain installed on Windows.

## Run a recorded example first

```powershell
python compare_inventory.py --baseline-month 202509 --recorded
python -m unittest test_compare_inventory -v
```

Recorded mode compares the latest saved inventory to the historical baseline for the weekday/hour of the last successful poll, in America/New_York. It does not download or replay anything, and is never labeled current. It evaluates report/feed age relative to that recorded poll. Old missing stations, regressed sources and source reports already stale at that poll remain excluded.

Output: data/reports/phase3/202509/recorded/

- station_mapping.csv: one row per retained live station, source UUID/numeric identifier, proposed historical short_name, names, location evidence, distance and mapping status.
- historical_unmatched.csv: historical baseline stations without a supported live mapping, including renamed/unresolved stations.
- inventory_demand_comparison.csv: one row per live station, inventory, matching weekday/hour baseline and attention indicator.
- summary.json: timing, counts, settings/limitations and output directory.

These are files in your project folder, not new DBeaver tables. Open CSVs in Excel or a text editor. Excel supports the UTF-8 BOM used here. Each run replaces the same mode's derived report files, rather than appending inventory or trips. Export is not an automatic schedule; rerun after collection when you want a new report. Phase 4 will connect comparison to the page. The existing dashboard has not changed.

## Compare current data

```powershell
python poll_stations.py --cycles 1 --interval 60
python compare_inventory.py --baseline-month 202509
```

Output uses a separate current/ folder. If sources are older than the saved freshness threshold (normally 300 seconds), no inventory pressure signal is produced. Successful polling alone does not guarantee fresh station reports.

## Mapping rules

The live GBFS station_id differs from historical JC/HB identifiers. Candidate join is GBFS short_name = historical station_id. Accept a candidate for this exercise only if the live short_name is unique, the baseline includes it, historical ZIP has at least 5 valid location observations, median historical location is within 150 meters of the live location, and the dominant historical name matches after case/punctuation normalization. These thresholds are documented exercise choices, not externally validated standards. A supported mapping is evidence, not proof of identity over time.

Location/name evidence is scanned from the selected original ZIP (both endpoints), because phase 1 did not keep it in fact_trip. Malformed/out-of-region coordinates are ignored for mapping evidence. Raw evidence includes source records independently of whether their rides were accepted: it does not add those records to the trip baseline. Median locations can hide relocation/multiple locations. Name changes can create false negatives. Do not automatically force unmatched candidates into a join. Inspect station_mapping.csv before extending the mapping rules.

The local verification sample had 109 live stations: 89 supported, 19 absent from the September baseline, and 1 name mismatch. There were 148 historical stations without a supported live mapping. Your current data may differ. Unmatched historical stations are not automatically assumed closed; new/renamed stations and source coverage can differ.

## Baseline and comparison definition

Baseline month: September 2025. Per-station weekday (Monday=0) and hour, based on New York local departure times and local arrival times. The phase 1 view divides totals by the number of calendar occurrences of that weekday, including days with zero trips. September has 4 or 5 days per weekday. Stations are assumed eligible for the entire month. Missing station identifiers cannot contribute to that station's flows.

Historical net outflow = mean departures - mean arrivals.

Illustrative remaining-hour net outflow = historical hourly net outflow × remaining fraction of the current New York hour. At 08:30, 14/hour becomes 7 for the remaining half hour. This assumes uniform demand inside the hour, without weather, holidays, variance, operator rebalancing, or season/year adjustment. Using September 2025 against October 2026 is an unvalidated historical comparison. It is not a stockout forecast or a probability.

Signal evaluation order:

1. Unsupported mapping / missing baseline: do not calculate pressure.
2. Missing in latest valid poll, regressed report, stale/future report or feed: stale_or_unreliable_source.
3. Not installed/renting/returning: not_fully_operational.
4. Any retained quality warning: quality_warning_review.
5. Fewer than 4 sample days: insufficient_baseline_days.
6. Available bikes ≤ saved low-bike threshold (normally 3): low_bikes_now.
7. Available docks ≤ saved low-dock threshold: low_docks_now.
8. Positive remaining-hour net outflow ≥ available bikes: historical_outflow_pressure.
9. Negative remaining-hour net outflow magnitude ≥ available docks: historical_inflow_pressure.
10. Otherwise: no_threshold_trigger. This does not mean no shortage risk.

One primary attention label is exported per row; the existing dashboard separately shows bike/dock flags. For supported rows, the historical baseline remains visible even if the current condition prevents a pressure calculation. Excluded rows have a blank illustrative flow, not zero. Do not rank unavailable signals as safe stations.

## Reliability and scope

Inputs are opened read-only. Each database uses its own read transaction and explicit connection close. No all-database atomic snapshot is claimed; avoid refreshing the historical baseline while exporting. Raw source ZIP is treated as immutable. There are no input writes, network downloads or extra dependencies in the comparison script.

The four tests check mapping ambiguity/location/name, remaining-hour direction, stale/regressed/quality suppression, restricted stations and small samples. Local integration was run against retained historical and live data in both modes. Current mode correctly suppressed stale data. Tests do not establish predictive accuracy.

Part 3 core implementation is ready for local acceptance when the export and tests succeed and you inspect mapping counts. Part 4 still needs the integrated attention indicator and historical charts. Part 5 still needs executable scheduling and final architecture/recovery documentation; several quality tests already exist.
