# Test Suite for Causeway FM Custom Modifications

We need a bulletproof way to verify that all of our custom codebase modifications are successfully re-implemented and functioning correctly after Subwave is updated to a new upstream release. 

Instead of brittle unit tests that require the TypeScript compiler, I propose building a comprehensive **Integration Test Script** (`verify_station_mods.py`) that runs directly against the live station APIs and services on the Proxmox server.

## User Review Required

Please review the proposed test coverage below. Are there any specific custom modifications you want to ensure are tested that I might have missed?

## Proposed Changes

I will create a new file: `verify_station_mods.py`. This script will contain a suite of automated checks.

### [NEW] `verify_station_mods.py`

This script will run the following checks:

**1. API Security & Routing (Controller)**
- Send an unauthenticated request to `POST /api/request` and assert it is correctly blocked with a 401/403 (verifies our custom `requireStationAuth` middleware).
- Send an authenticated request to `POST /api/request` with `x-station-auth` and assert it is accepted.
- Hit the `/settings/llm/probe-compat` endpoint with the `free_shit` 9router alias and assert it returns valid JSON (verifies the `openAICompatibleFetch` SSE streaming bug fix and `thinking` block bypass).

**2. Custom Gemini TTS (`gemini_tts.py`)**
- Send a standard `/speak` request containing the `[voice:sadachbia]` tag and assert the TTS engine automatically upgrades it to a multi-speaker response and successfully uses the `VOICE_MAP` overrides.
- Verify the TTS engine correctly routes through `GEMINI_BASE_URL` (9router) instead of hitting Google directly.

**3. Durable Telemetry & Skills (`better-sqlite3`)**
- Connect to `state/telemetry.db` and assert the `tokens` and `listeners` tables exist and are actively tracking data (verifies our custom SQLite telemetry migration for the `station-stats` skill).
- Connect to `state/bottle_shops.db` and verify the `grog-finder` schema is valid.

**4. Lidarr Auto-Requester Pipeline**
- Execute `missed_requests_server.py`, `lidarr_sync_server.py`, and `lidarr_watchdog.py` in a simulated "dry run" mode (or by checking their syntax and connectivity) to ensure they haven't been broken by python environment changes.
- Verify `lidarr_watchdog.py` unconditionally connects to the queue API (verifying the IP bypass fix).

## Verification Plan

Once the script is written:
1. I will deploy it to the Proxmox server.
2. I will execute the test suite against the *current* healthy station to establish a passing baseline.
3. I will attach the script to `CAUSEWAY_UPDATE_RUNBOOK.md` so it is officially part of the post-update verification process.