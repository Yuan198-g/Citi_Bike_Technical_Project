# Citi Bike Operations and Analytics

A local dashboard for historical trip analysis and station inventory monitoring. It uses public Citi Bike monthly trip files and GBFS 2.3 station feeds for Jersey City / Hoboken.

## 1. Understand the two data sources

| Data | Default period | Used for | How to update |
|---|---|---|---|
| Historical trips | August and September 2025; September is selected for analysis | Historical analytics and the demand baseline | Run historical processing for the required month |
| Station snapshots | The time you run the collector | Bikes, docks, operational status and inventory history | Run `poll_stations.py` |

Live collection does **not** change Historical analytics. The dashboard's `--baseline-month` selects both the historical charts and the historical demand used in the inventory comparison. It is not hard-coded to September, but the selected month's data and baseline must already exist.

The inventory comparison is a rule-based reference, not a validated shortage prediction. Using 2025 demand with 2026 inventory has year/season limitations.

## 2. Set up and run for the first time

Use Python 3.10 or newer. Keep all project scripts and `workflow.json` in the same directory as the intended `data` folder. Run commands from that project directory.

```powershell
python -m pip install -r requirements.txt
python workflow.py batch
python poll_stations.py --cycles 3 --interval 60
python workflow.py check
python platform_dashboard.py --baseline-month 202509
```

Open http://127.0.0.1:8502. Keep the dashboard terminal open; closing it stops the page service. The collector finishes after three cycles. The final check should end with `FINAL CHECKS PASSED`.

Already have data? Keep your existing `data` folder. You do not need to run the historical batch again just to open the page. Check the database paths printed at dashboard startup: a parent project folder and its nested `citi_bike_phase1` folder are different data roots.

## 3. Daily use: open the page and collect inventory

Terminal 1:

```powershell
python platform_dashboard.py --baseline-month 202509
```

Terminal 2, from the same project directory:

```powershell
python poll_stations.py --cycles 3 --interval 60
```

For continuous collection until you press Ctrl+C:

```powershell
python poll_stations.py --cycles 0 --interval 60
```

The page reads the database every 10 seconds. The collector retrieves source data about every 60 seconds, or longer when feed TTL requires it. Reading the page does not append database records; collecting does. Stop continuous collection when the demo ends because raw files and snapshots accumulate.

- **Recorded snapshots:** retained inventory and a demand comparison evaluated at the last successful poll. It is not current availability. Source-age badges still show present-time age.
- **Current operations:** fresh operating stations contribute to current totals. Old, restricted or unreliable records cannot produce current pressure signals.
- **Latest successful poll:** when collection last succeeded. **Page data refresh:** when the browser last read the database. Only the second can change while collection is stopped.
- **Attention / unavailable only:** hides `no_threshold_trigger` rows. Uncheck it to see all comparison rows, including JC009 if no threshold was triggered.

Historical charts and baselines are cached at dashboard startup. After changing historical data, stop the dashboard with Ctrl+C and restart it. Live inventory does not require a restart.

## 4. Add July and use it as the baseline

First download, process and build the July 2025 baseline:

```powershell
python run_phase1.py --months 202507 --analysis-month 202507
```

This adds July while retaining existing August/September trips. Reports are saved in `data/reports/202507/`.

Stop the running dashboard with Ctrl+C, then start it with July selected:

```powershell
python platform_dashboard.py --baseline-month 202507
```

Historical analytics now shows July, and the inventory comparison uses July weekday/hour demand. Inventory still comes from the live collector. To return to September, restart with `--baseline-month 202509`.

Changing only the dashboard parameter is enough **if that month's data and baseline have already been prepared**. Otherwise run the historical command first. Use six digits without spaces: `202507` means July 2025. A month not yet published by the source cannot be downloaded; the program does not generate it.

A one-time July import does not change `workflow.json`. To make batch scheduling and final checks use July too, change its `months` and `analysis_month` as explained below.

## 5. Main files

| File | Purpose | When to use |
|---|---|---|
| `run_phase1.py` | Download selected historical months, ingest trips, build a baseline, validate and export reports | Add a month or refresh historical reports |
| `pipeline.py` | Historical download, cleaning, deduplication and database logic | Called by the historical runner; usually no direct use |
| `poll_stations.py` | Retrieve GBFS information/status and save inventory snapshots | Get fresh inventory |
| `platform_dashboard.py` | Integrated inventory, demand comparison and historical page | Main dashboard entry point |
| `operations_dashboard.py` | Original inventory-only page and shared page code | Keep it: the integrated dashboard imports it; normally use `platform_dashboard.py` |
| `compare_inventory.py` | Check station mappings and export demand/inventory comparisons | View or share CSV results without the page; also imported by the dashboard |
| `workflow.py` | Batch execution, daily batch scheduling and final checks | Use `batch`, `schedule` or `check` |
| `workflow.json` | Historical months, analysis month, schedule and batch retry settings | Edit batch defaults |
| `test_*.py` | Small synthetic tests for transformations, failures and workflow behavior | Run through `workflow.py check`; test data is separate from business data |
| `requirements.txt` | Windows timezone dependency | Initial installation |
| `TECHNICAL_DESIGN.md` | Architecture, model, rules, assumptions and recovery | Technical review |
| `EVIDENCE.md` | Existing verification notes and submission evidence guidance | Prepare submission |

## 6. Parameters you can change

### Historical processing and the dashboard

| Command | Parameter | Meaning |
|---|---|---|
| `run_phase1.py` | `--months 202507 202508` | Historical files to ingest; old accepted trips remain |
| `run_phase1.py` | `--analysis-month 202507` | Month whose baseline and reports are generated; this month is also downloaded/ingested if necessary |
| `platform_dashboard.py` | `--baseline-month 202507` | Select historical charts and demand baseline |
| `platform_dashboard.py` | `--port 8503` | Change page port if 8502 is occupied; open the matching URL |
| `platform_dashboard.py` | `--root "C:\path\to\project"` | Read databases/raw inputs from an explicit project directory |
| `compare_inventory.py` | `--baseline-month 202507` | Select the exported comparison's historical baseline |
| `compare_inventory.py` | `--recorded` | Evaluate at the last stored poll; omit to evaluate current freshness |
| `compare_inventory.py` | `--root "C:\path\to\project"` | Select the project data directory |

`run_phase1.py` and `poll_stations.py` use the directory containing their scripts as the data root. They do not accept `--root`. Keep them beside the intended `data` folder instead of assuming that changing the terminal directory changes their storage location.

### Live collection

| Parameter | Default | Meaning |
|---|---:|---|
| `--cycles` | 3 | Number of polls; 0 continues until Ctrl+C |
| `--interval` | 60 | Requested seconds between polls; minimum 30; source TTL may increase it |
| `--stale-after` | 300 | Source freshness threshold in seconds; minimum 30 |
| `--low-bikes` | 3 | Flag a station when available bikes are at or below this value |
| `--low-docks` | 3 | Flag a station when available docks are at or below this value |

Example with different thresholds:

```powershell
python poll_stations.py --cycles 3 --interval 60 --stale-after 300 --low-bikes 5 --low-docks 5
```

Thresholds are saved with new snapshots; this command does not rewrite old records. The dashboard's 10-second read interval is fixed in the current code and has no command-line parameter.

### Batch configuration

Default `workflow.json`:

```json
{
  "months": ["202508", "202509"],
  "analysis_month": "202509",
  "daily_at_utc": "02:00",
  "batch_attempts": 3,
  "retry_seconds": 10
}
```

For July analysis while keeping all three months configured, change `months` to `["202507", "202508", "202509"]` and `analysis_month` to `"202507"`. The analysis month must be in the configured months list. `batch_attempts` accepts 1–5; `retry_seconds` accepts 0–60. Dashboard parameters are independent of this configuration: start the page with the month you want to display.

## 7. Scheduling: optional for normal viewing

```powershell
python workflow.py schedule
```

This schedules **historical batch processing only**. It does not collect live inventory or restart the dashboard. With fixed data and unchanged code, rerunning usually produces the same historical results.

`daily_at_utc` uses UTC, not the browser's display timezone. Keep the scheduler terminal and computer running. If started after today's configured time, it runs once if today has not already been attempted. It does not catch up all missed days or automatically discover new months. Restart it after editing configuration.

Logs are in `data/logs/`; the last scheduled attempt is in `data/scheduler_state.json`. Failed/interrupted days are not automatically repeated after restart. Inspect the log and retry manually with:

```powershell
python workflow.py batch
```

No Windows service is installed. For ordinary live dashboard use, run only the dashboard and collector.

## 8. Reports, checks and common problems

```powershell
python workflow.py check
```

This runs 20 tests, 16 historical checks, 6 operational checks, a recorded comparison export and integrated serving calculations. It uses `workflow.json`'s analysis month. It does not collect/download and does not visually test the browser. Correctly labeled stale data and retained quality warnings can coexist with a passing report.

| Output | Location |
|---|---|
| Historical CSVs, baseline, coverage summary | `data/reports/YYYYMM/` |
| Historical check details | `data/reports/YYYYMM/validation.json` |
| Mapping and inventory comparison CSVs | `data/reports/phase3/YYYYMM/recorded/` or `current/` |
| Complete acceptance report | `data/reports/final_acceptance.json` |
| Latest collector summary at capture time | `data/reports/live/collection_summary.json` |
| Batch retry/error logs | `data/logs/` |
| Historical / operational databases | `data/citibike.sqlite` / `data/operations.sqlite` |
| Original inputs | `data/raw/` and `data/raw_live/` |

CSV files can be opened in Excel; JSON/log files can be opened in a text editor. Reports are files, not new DBeaver tables. Scheduled batches update historical reports/checks; only `workflow.py check` generates the complete acceptance report.

| Problem | What to do |
|---|---|
| Script not found | Enter the folder containing the script |
| Database/raw ZIP missing | Check the printed data paths; prepare the historical month and collect inventory first |
| Baseline missing for a month | Run `run_phase1.py` with that `--analysis-month` |
| Current totals are empty / all stations stale | Run the collector; page refresh alone does not fetch inventory |
| Historical charts did not change | Restart the dashboard with the intended `--baseline-month` |
| Port already in use | Stop the old server or choose another `--port` |
| Windows database lock | Close interfering editors and use one writer per database |

For submission, include code/configuration, documentation, your final acceptance report and your own page screenshots. The default `.gitignore` excludes `data/`; copy selected evidence into an `evidence/` folder if uploading to GitHub. Preserve local raw data and databases. See technical design for limitations and recovery details.

Official sources: [Citi Bike System Data](https://citibikenyc.com/system-data) and [GBFS reference](https://gbfs.org/documentation/reference/).
