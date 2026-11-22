# JARVIS Overnight Research

Overnight research is a separate persistent workflow. It does not use Groq or any
language model during discovery and collection. Once the collection window ends,
the saved evidence is analyzed through the configured OmniRoute model only.

## Start and control

- `overnight research on <topic>` — start a background mission immediately.
- `overnight research on <topic> and give me the result at 5:30 AM` — set a local-time delivery target. JARVIS reserves the final part of the window for analysis and synthesis.
- `research status` — show mission phase, counters, progress, and errors.
- `list research missions` — list normal and overnight research jobs.
- `cancel research <mission-id>` — stop an active overnight mission while preserving evidence.
- `resume research <mission-id>` — resume a paused mission or retry analysis from saved batches.

The default collection window is eight hours. The report is written to
`data/research/overnight/<mission-id>/FINAL_REPORT.md`. Raw evidence is stored
incrementally in `evidence.jsonl`; completed OmniRoute batch analyses are saved
under `analysis/`. A failed analysis can therefore resume without repeating the
collection stage.

## Configuration

- `JARVIS_OVERNIGHT_RESEARCH_HOURS`: collection duration, 1–16 hours (default 8).
- `JARVIS_RESEARCH_LOCAL_PATHS`: optional path-separated list of additional local
  directories to scan. When set, it replaces the default local roots.
- Default local roots are the JARVIS repository and shared Android Documents and
  Download directories when available.

The collector scans text/code/document formats only, skips hidden and sensitive
directories, ignores symlinks and large files, and redacts common credential
patterns before evidence is persisted or sent for analysis. The Knowledge Hub is
queried separately. Do not add directories containing private messages, account
exports, credentials, or unrelated personal material to the configured roots.

## Resource and reliability behavior

- Collection is incremental and disk-backed; the complete corpus is never loaded
  into RAM for analysis. Evidence storage is capped at 512 MB per mission.
- Search-provider failures are isolated and recorded.
- Only public HTTPS pages on the standard port are fetched. Non-public addresses
  and redirects are rejected.
- Search results seed a depth-limited crawler; query variants target documentation,
  papers, GitHub implementations, benchmarks, and community discussions.
- Evidence records retain source IDs, URLs or local paths, provider, type, and
  collection timestamps.
- OmniRoute analysis is chunked, checkpointed, and retried up to three times.
  It never falls back to Groq.
- A JARVIS process restart automatically resumes an interrupted mission from its
  persisted evidence and completed analysis batches. It does not restart collection
  from zero. If the collection deadline has passed, it proceeds directly to analysis.
- Deadline-driven missions retain the original delivery target across restarts.
  If the device was offline at the target time, JARVIS completes the report as soon
  as it can after recovery; it cannot deliver while the device is powered off.
- Research evidence is appended incrementally and completed analysis batches are
  written atomically, so a process kill does not discard already completed work.

Android may suspend or terminate Termux during long idle periods. A process-level
recovery feature cannot launch itself after Android force-stops the Termux app or
while the device is powered off. To resume after a device reboot, Termux must be
started by the user or a separately installed and configured Termux:Boot app.
Android battery-optimization and background-execution policies can still affect
availability. No software can continue processing while the device is switched off.

The collector searches configured, reachable sources; it cannot guarantee
exhaustive coverage of the internet, private sites, paywalled material, or
unindexed documents.
