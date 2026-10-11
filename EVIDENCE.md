# Verification evidence

## User-reported local runs

Historical August file: 108441 raw, 108399 inserted, 42 rejected. September: 116071 raw, 116033 inserted, 38 rejected. No duplicates or conflicts were reported for those first runs. Database total 224432. Safe reruns returned already_processed with unchanged total. September local-start analysis: 116017, with 450 missing destinations. Monthly baseline: 39816 rows (237 × 7 × 24). The user reported PHASE 1 CHECKS PASSED.

Live GBFS 2.3 collection on October 9, 2026: first three polls at 18:18:03, 18:19:04 and 18:20:05 UTC, 109 snapshots each, total 327. The first-to-last span was about 122 seconds, not hours of continuous monitoring. Another three at 22:13:30, 22:14:30 and 22:15:31 UTC increased the total to 654 and successful poll count to 6. No quarantine was reported for those cycles.

The user later reported an integrated-page latest successful poll at October 10, 11:46:18 America/Chicago and page refresh at 12:02:24. All 109 records were stale at that later time, while Recorded totals remained visible. The user confirmed the source poll updated on the page; complete October 10 snapshot counts were not supplied, so they are not invented here. User pasted inventory/demand rows and confirmed the integrated page was accessible. No screenshot is fabricated or included.

User phase 3 export: 109 live stations, 89 mappings supported by ID/name/location, 19 with no historical baseline station, 1 name mismatch, and 148 historical stations without supported live mappings. JC009 at October 9 18:15 New York had 14 bikes and 9 docks, net historical outflow −2.25/hour, reference remaining-hour flow −1.67, and no_threshold_trigger. This is a recorded example, not current inventory.

## Developer verification

Final package: 20 unit tests pass, including 3 workflow tests. Complete acceptance command was exercised against copied retained databases; its local report is generated in data/reports/final_acceptance.json. The bundle does not include these input databases or substitute them for the user's more recent data.

Earlier HTTP HTML/API integration verified 116017 September trips, 109 comparison rows, 89 supported mappings and suppression of current signals for stale data. Embedded JS syntax was checked. Developer browser rendering was not verified in the execution environment; local page display/update evidence is user-reported. The scheduler's due/state/released-lock logic is unit tested; actual Windows background service installation is not performed and is not part of the implementation.

## Submission evidence to include

Run workflow.py check on the chosen user data directory and include its final_acceptance.json. Save page screenshots of historical coverage, the comparison table, live polling before/after, and stale classification. Save relevant live collector output or polling summaries. Exclude synthetic test fixtures from business evidence. The report validates processing behavior, not shortage prediction accuracy.
