# JARVIS Overnight Research

Overnight research is a separate persistent workflow. It does not use Groq or any
language model during discovery and collection. Once the collection window ends,
the saved evidence is analyzed through the configured OmniRoute model only.

## Start and control

- `overnight research on <topic>` — start a background mission immediately.
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
  into RAM for analysis.
- Search-provider failures are isolated and recorded.
- Only public HTTPS pages on the standard port are fetched. Non-public addresses
  and redirects are rejected.
- Search results seed a depth-limited crawler; query variants target documentation,
  papers, GitHub implementations, benchmarks, and community discussions.
- Evidence records retain source IDs, URLs or local paths, provider, type, and
  collection timestamps.
- OmniRoute analysis is chunked, checkpointed, and retried up to three times.
  It never falls back to Groq.
- A JARVIS/Termux process restart marks an interrupted mission as paused. Resume it
  explicitly after startup; the workflow does not silently replay or restart work.

Android may suspend or terminate Termux during long idle periods. Keep JARVIS
running overnight for uninterrupted collection. If Android terminates it, the
saved corpus and completed analysis batches remain available for explicit resume.

The collector searches configured, reachable sources; it cannot guarantee
exhaustive coverage of the internet, private sites, paywalled material, or
unindexed documents.
