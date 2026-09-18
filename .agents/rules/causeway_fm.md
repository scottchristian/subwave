---
trigger: always_on
description: Environment details for Causeway FM instance
---

# Causeway FM Context

This codebase is being used to host a personal radio station named **Causeway FM**.
Must try and keep cost's to $0 where possible, only suggest to spend $ on tokens when nessesary.

## LLM Model Stack
- **Primary Model:** `Free_Shit` (9router alias — currently resolves to a free Nvidia Nemotron reasoning model via OpenRouter)
- **Failover Model:** `gemini-2.5-flash` (via the `google` provider in Subwave)
- Agents **MUST** configure the station with `Free_Shit` as the primary model and `gemini-2.5-flash` as the backup. Do not change this without explicit user instruction.
- **Important**: `Free_Shit` is a reasoning model that occasionally wraps tool-call arguments in markdown fences (` ```json ... ``` `). A custom fix in `controller/src/llm/internal/provider/registry.ts` strips these fences in the `openAICompatibleFetch` response handler. Additionally, `Free_Shit` is on the skip-list for OpenAI-specific no-think injection (`chat_template_kwargs`, `thinking`, `reasoning_format`) to avoid 400 Bad Requests from the upstream router.

## Environment
- OS: Debian 13 container
- Platform: Proxmox server

## Network Architecture
- **VPS Proxy:** A cloud VPS at `ssh root@ghostmaster.online`.
- **Routing:** NGINX and Icecast on the VPS route `radio.ghostmaster.online` over native IPv6 directly to the Proxmox container (`[2404:e80:bef:0:be24:11ff:fe6c:b839]:7700`) to bypass Tailscale overhead.
- **Domain:** `radio.ghostmaster.online`
- **Security:** Let's Encrypt is configured on the VPS for HTTPS.

## URLs
- **Stream URL:** http://192.168.68.196:7700/stream.mp3
- **Now-Playing API (Current Track + Context):** http://192.168.68.196:7700/api/now-playing
- **State API (Queue + History + DJ Log):** http://192.168.68.196:7700/api/state

## SSH Access
Agents can access the container directly to adjust `.env` or other settings using:
```bash
ssh root@192.168.68.196
```
### Container Paths
- **Subwave `.env` (Boot settings):** `/root/subwave/.env`
- **Subwave `settings.json` (Live UI settings):** `/root/subwave/state/settings.json` (Check this file to see what LLM model, TTS voices, and station settings are currently applied!)
- **Navidrome:** `/root/navidrome/docker-compose.yml`

### Missed Requests Script
To generate a clean list of listener-requested songs that couldn't be fulfilled (so you know what to purchase and add to the library), run the following on the server:
```bash
/root/subwave/missed_requests.py
```
This parses the raw Subwave `requests.log` and isolates failed requests and "near-misses".

## MCP Configuration
If an agent needs to use the subwave MCP server for this deployment, the configuration is:

```json
{
  "mcpServers": {
    "subwave": {
      "type": "http",
      "url": "http://192.168.68.196:7700/api/mcp",
      "headers": {
        "Authorization": "Basic <base64 of user:pass>"
      }
    }
  }
}
```

## Available MCP Tools
Once configured, agents can use the following tools to interact with the station:
- **`subwave_health`**: Check if the station is up.
- **`subwave_now_playing`**: Check what's on-air right now.
- **`subwave_station_state`**: View the queue, history, and DJ booth log.
- **`subwave_schedule`**: View shows, personas, and the weekly grid.
- **`subwave_session`**: View the DJ's live session transcript.
- **`subwave_request_song`**: Ask the AI DJ to play a track.
- **`subwave_request_status`**: Poll an earlier request's outcome.
- **`subwave_search_library`**: Deterministic library search (admin).
- **`subwave_queue_track`**: Queue an exact track (admin).
- **`subwave_skip_track`**: Force-end the current track (admin).
- **`subwave_dj_announce`**: Put a spoken update on-air (admin).
- **`subwave_dj_segment`**: Fire a scripted voice segment (admin).
- **`subwave_list_skills`**: List the available skill catalogue (admin).
- **`subwave_run_skill`**: Run a named skill segment (admin).
- **`subwave_list_sfx`**: List the sound-effects library (admin).
- **`subwave_play_sfx`**: Fire a sound effect on-air (admin).

## Gemini API Notes
When configuring the `gemini-2.5-flash-preview-tts` model via the `google-genai` SDK:
- By default, the Gemini models apply strict safety filters. For the DJ personas to use harsh banter or mild roasts, all `HARM_CATEGORY_*` settings in `safety_settings` must be explicitly set to `BLOCK_NONE`.

## Custom Modifications
Because Subwave is frequently updated upstream, we have made the following custom codebase modifications to support advanced Gemini TTS features. If an upstream pull breaks them, they must be re-implemented:

- **Style Prompts (Python Bridge):** Added a `STYLE_MAP` inside `gemini_tts.py` that maps the `voice` string (e.g. `jax`) to specific instructions to sound like an Australian radio presenter with their specific persona traits. These instructions are injected as non-spoken bracketed text at the start of every request.
- **Markup Tags (Controller):** Modified `controller/src/llm/internal/prompts/system.ts` to instruct the AI DJ that it is allowed to use specific bracketed emotional tags (e.g. `[laughing]`, `[sigh]`, `[sarcasm]`) when generating its script if it is using the `remote` engine, so the Gemini model will render the paralinguistic audio.
- **Weather Hallucination Fix (Controller):** Modified `controller/src/llm/internal/prompts/system.ts` and `controller/src/llm/internal/prompts/banter.ts` to explicitly forbid the AI from mentioning, assuming, or inventing the current weather in regular links and banter, to prevent hallucinations like "enjoy the sunshine".
- **Banter Rules (Controller):** Modified `controller/src/llm/internal/prompts/banter.ts` to explicitly allow harshness, sarcasm, and occasional swearing during banter to fit the DJ personas.
- **Station Stats Skill (Telemetry Durability):** To provide accurate, durable tracking of station stats across container restarts, we migrated the telemetry storage to a `better-sqlite3` database (`state/telemetry.db`).
    - Added `controller/src/llm/internal/telemetry/db.ts` to manage the DB connection.
    - Modified `controller/src/llm/internal/telemetry/budget.ts` to log LLM tokens, TTS characters, and daily peak listener counts directly into the SQLite database instead of in-memory.
    - Modified `controller/src/broadcast/listeners.ts` to report new peak listener records to the DB.
    - Modified `controller/src/llm/internal/tools/station-services.ts` to read the durable peak from the DB. This allows the custom `station-stats` DJ skill to accurately calculate the station's total daily cost and peak listeners.
- **Station Stats AUD Conversion (State):** Modified `state/skills/station-stats/tool.mjs` to internally apply a 1.50x conversion multiplier and strip the "USD" label so the DJ naturally reads the value as AUD.
- **Safety Settings UI (Controller & Web):** Added `geminiSafety` toggles in the Web UI, which dynamically configures safety overrides in both the LLM (`prompts/system.ts`) and TTS (`gemini_tts.py`) engines instead of relying on hardcoded values.
- **Gemini Safety Bypass via OpenAI-Compatible Route:** When using the `openai-compatible` provider with a `gemini/` model (routed through 9router), the `geminiSafety` UI block has no effect because the Gemini-native `safetySettings` field is only used by the `google` provider path. To disable safety filters on this path, `controller/src/llm/internal/provider/registry.ts`'s `openAICompatibleFetch` now automatically injects `safe_prompt: false` into the request body for any model whose name starts with `gemini/`. This is 9router's supported mechanism for passing `BLOCK_NONE` through to the upstream Gemini API. **Important:** The `geminiSafety` UI toggles on the Settings page are NOT what controls filtering for this path — the injection in `registry.ts` is unconditional for `gemini/` models.
- **Proxy Support (Controller & TTS):** 
    - Modified `controller/src/llm/internal/provider/registry.ts` to pass `cfg.baseUrl` into the `createGoogleGenerativeAI` initialization, allowing Subwave's text generation (LLM) to route to 9router at `http://192.168.68.193:20128/v1beta` while retaining the `google` provider schema (critical for safety bypasses).
    - Modified `gemini_tts.py` to accept a `GEMINI_BASE_URL` environment variable for routing TTS generation through 9router.
    - Added a strict safeguard to `gemini_tts.py`: if `GEMINI_BASE_URL` is present and Google issues a `400 Bad Request` (usually a safety block during abrasive banter), the script immediately aborts the fallback loop instead of retrying. This prevents 9router from locking the TTS pool for 30 seconds due to cascading errors.
- **Agent Prompts UI Customization (Controller & Web):** 
    - Added a `Banter Rules` field (`banterPrompt`) to the Web UI to dynamically configure banter behavior instead of using hardcoded rules. Modified `controller/src/settings.ts` to bump its truncation limit to 10,000 characters.
    - Added a `Listener Activities` field (`listenerPrompt`) to the Web UI to dynamically guide the core DJ prompt on how to describe listeners during regular segments.
- **Multi-Speaker Banter & Inline Voice Tags:** 
    - `gemini_tts.py` has a custom `/speak-multi` endpoint using `SpeakMultiRequest` (an array of `SpeakLine` objects). It parses the array to build a script string and passes a `multi_speaker_voice_config` to Gemini to render all speakers at once.
    - `gemini_tts.py`'s standard `/speak` endpoint has been hot-patched to automatically parse `[voice:voicename]` tags (e.g. `[voice:zane]`) inside standard single-speaker requests. If a tag is found, it automatically splits the text and upgrades the request to use `SpeakMultiRequest` internally. This allows individual skills to inject custom voices into standard DJ links without needing full Banter support.
    - `controller/src/audio/remoteTts.ts` exposes `speakMulti()`.
    - `controller/src/audio/tts.ts` exposes `speakExchange()` to try and batch `remote` lines.
    - `controller/src/broadcast/queue.ts` modifies `announceExchange()` to attempt batching the exchange through `tts.speakExchange()`, airing the result as a single clip with a combined text payload while falling back to sequential rendering otherwise.
    - **Important**: NEVER remove or recommend removing the `/speak-multi` endpoint or the batching logic. Although it currently has styling inconsistencies with Gemini's multi-speaker model, the user explicitly wants to retain this batching architecture.
- **Spotify to Navidrome Playlist Sync:**
    - Modified `spotify_extract.py` to capture actual Spotify playlist structures, writing `playlists` and `playlist_tracks` tables into `spotify_library.db` along with Liked Songs. It checks for both `track` and `item` keys to handle undocumented API changes.
    - **Note on Playlists**: The Spotify API will return `403 Forbidden` for public playlists not owned by the user. To sync a third-party playlist, it must first be "cloned" into the user's library (e.g. copied to a new playlist created by the user).
    - Created `spotify_to_navidrome_playlists.py` which reads `spotify_library.db`, fuzzy matches tracks against the Navidrome library (via Subsonic API), and reconstructs the Spotify playlists as Navidrome playlists.
- **Navidrome Global Blocklist:**
    - Created `navidrome_filter.py` to handle station-wide track filtering. This script scans the local Navidrome library and generates a `Causeway-Blocked` playlist containing any tracks with banned words (e.g., "instrumental", "interlude", "skit", "intro") and artists that do not appear in the user's Spotify Liked Songs, preventing them from airing.
- **Tyrone the Grog Finder Skill (Multi-Store Price Tracker):**
    - A custom background scraper script `grog_scraper.py` runs daily at 10 AM via system cron on the Proxmox server (`192.168.68.196`). It fetches prices from Thirsty Camel (Midway Point) and BWS (Sorell Drive).
    - **Note on Liquorland/Coles, Cellarbrations & Dan Murphy's**: The scraper currently ignores Liquorland because their endpoint uses aggressive "ShieldSquare Captcha" protection, and ignores Cellarbrations and Dan Murphy's due to strict "Cloudflare" bot protection. While you can sometimes bypass these locally by copying cookies from a browser, these systems strictly tie the clearance cookies to the browser's IP address. If the container uses those cookies from a different IP, the request is immediately blocked. To support these stores in the future, the container would need to route traffic through a residential proxy or run a headless browser (like Playwright) to naturally execute the JS challenges.
    - It maintains an all-time maximum price and current price in `/root/subwave/state/bottle_shops.db` using SQLite constraints and a `cheapest_prices` view.
    - A custom Subwave DJ skill `grog-finder` in `state/skills/grog-finder/` reads the SQLite database using `better-sqlite3` and formats a specials announcement for the DJ "Tyrone" to read, finding the cheapest store for each item. The skill has a `3h` cooldown. If no items are on special, the skill returns `{ available: false }` to cleanly abort the segment without the DJ mentioning it.
    - **Skill Native Module Imports:** Because custom skills are dynamically loaded ES modules mounted at `/app/state/skills/`, they cannot natively resolve C++ extensions like `better-sqlite3` installed inside the container's `/app/node_modules/`. To import them inside a `tool.mjs` script, you must bypass standard module resolution using a custom `createRequire` context pointing to the container's root: `import { createRequire } from "module"; const require = createRequire("/app/src/index.js"); const Database = require('better-sqlite3');`
    - **Skill LLM Bypass (requiresData):** By default, if a skill provides data to the LLM, the system schema allows the LLM to choose to stand down (`air: false`) if it thinks the data is empty. Because `grog-finder` returns a complete, pre-written script instead of raw data, reasoning models like Nemotron will incorrectly deduce that no "data" was provided and stand down. To fix this, `tool.mjs` MUST include `export const requiresData = false;` at the top level. This bypasses the grounding check and forces the DJ schema to output text, preventing the model from aborting the script.
    - **Tyrone Voice (Inline Voice Tag):** The `grog-finder` skill uses `[voice:sadachbia]` at the start of the script to switch to Tyrone's voice via the `/speak` endpoint's inline voice tag upgrade path in `gemini_tts.py`. The voice `sadachbia` maps to the Gemini built-in voice `Sadachbia` in the `VOICE_MAP` and has a custom Tyrone persona style prompt in `STYLE_MAP`. Both `VOICE_MAP` and `STYLE_MAP` entries MUST exist in `gemini_tts.py` for Tyrone's segment to render correctly. A backup of the patched `gemini_tts.py` is kept at `custom_assets/gemini_tts.py` in this repository.
    - **Verbatim Script Passthrough (Controller):** Modified `controller/src/skills/_agent.ts` in both `runSimpleDirector` (autonomous tick) and `runCapability` (manual `/dj/skill` trigger) to short-circuit the LLM rewrite when a skill's `tool.mjs` returns `{ available: true, script: '...' }`. If this shape is detected, the script is passed directly to `queue.announce()` without any LLM call, so `[voice:]` tags and literal text (swearing, catchphrases) survive untouched to TTS. Any skill that wants verbatim passthrough must return `{ available: true, script: '<text>' }`. Skills that do NOT return a `script` field continue to use the normal LLM generation path.
- **Lidarr Auto-Requester Pipeline (`missed_requests_server.py`, `lidarr_sync_server.py`, `lidarr_watchdog.py`):**
    - **LLM Cleanup Routing:** `missed_requests_server.py` Phase 3 (LLM request cleanup) reads `GEMINI_BASE_URL` from `.env` and passes the API key in the `Authorization: Bearer` header, routing cleanly through 9router (OpenRouter) with the `gemini-3.6-flash` model.
    - **Generic Band Requests:** For requests like "some Foo Fighters", the pipeline sets the track to `Any` and triggers Lidarr to search for missing albums (`lidarr_album_id = ARTIST:{id}`). The watchdog then polls all tracks for the artist and plays the very first one that finishes downloading.
    - **Fuzzy Title Matching:** `lidarr_sync_server.py` uses `rapidfuzz` to loosely match iTunes metadata track titles against Lidarr's track titles to prevent infinite rejection loops on slight spelling differences.
    - **Watchdog IP Bypass:** `lidarr_watchdog.py` unconditionally injects the downloaded track into the station queue. The old logic that tried to query Icecast (`localhost:8000/admin/listclients`) to verify the listener's IP was removed because Icecast is isolated inside the Docker network.
## Deployments & Hot-Patching
Because the production radio station on the Proxmox server (`192.168.68.196`) runs pre-built Subwave Docker images from GitHub Container Registry (GHCR) and does **not** contain a local git repository, any custom code modifications made to the local repository must be hot-patched into the live containers.

### Updating Subwave to a New Release
> **READ THIS BEFORE UPDATING.** A full step-by-step update runbook (backup → git pull → conflict resolution → redeploy → verify) is maintained at:
> **`CAUSEWAY_UPDATE_RUNBOOK.md`** in the root of this repository.
> Any AI agent tasked with performing an update MUST read and follow that file. Do not attempt an update by hand without it.

To deploy custom changes (like the AI modifications above):
1. **Copy to Server:** Transfer the modified local files to the server via `scp` (e.g., `scp controller/src/audio/tts.ts root@192.168.68.196:/root/subwave/tts.ts`).
2. **Patch Container:** SSH into the server and use `docker cp` to inject the files directly into the running container (e.g., `docker cp /root/subwave/tts.ts sub-wave-controller:/app/src/audio/tts.ts`).
3. **Restart Service:** Restart the container to apply the changes (e.g., `docker compose restart controller`).

For the controller and web frontend, the repository includes two convenience scripts that handle the compile + copy + restart cycle automatically:
- `bash deploy_controller.sh` — builds the TypeScript controller and hot-patches it into the live `sub-wave-controller` container.
- `bash deploy_web.sh` — runs the Next.js production build and hot-patches it into the live `sub-wave-web` container.

**Important Note:** Because these are hot-patches inside the container filesystem, they will be **wiped out** the next time the station operator updates Subwave by pulling a new GHCR image. When that happens, the custom codebase modifications documented above must be re-implemented in the new codebase and hot-patched again.

### Custom Station Ident (Jingle) Recovery
The default Subwave station ident (`station_ident_default.wav`) on the live server has been overwritten with a custom, personality-driven AI jingle. A backup of this custom audio file is stored in this repository at `custom_assets/station_ident_default.wav`.

Because Subwave's backend explicitly protects the default ident and regenerates it if missing, an upstream update or a state wipe may accidentally restore the generic built-in jingle over our custom one. 

If this happens, agents must restore it by copying the backup directly over the live file on the server:
```bash
scp custom_assets/station_ident_default.wav root@192.168.68.196:/root/subwave/state/jingles/station_ident_default.wav
```
(No container restart is required for the jingle audio replacement to take effect).

- **9router / AI SDK Bug Fixes (Controller):** 
    - Modified `controller/src/llm/internal/provider/registry.ts` to implement a custom `openAICompatibleFetch` wrapper that forces `stream: false` to bypass a 9router bug where it always streams SSE responses (and appends a malformed `data: [DONE]`), causing `ai-sdk`'s JSON parser to crash with a 500.
    - Modified the same fetch wrapper to strip `thinking: {type: "disabled"}` and `chat_template_kwargs` for non-standard models (like `cf/` or `gemini/` or aliases like `free_shit`) because passing OpenAI-specific thinking schema arguments to them via 9router causes a 400 Bad Request.
    - Also modified `/settings/llm/probe-compat` in `controller/src/routes/settings/llm.ts` to use `openAICompatibleFetch` so the "Test Connection" button in the Web UI works successfully against models like `free_shit` without throwing an "Invalid JSON" parse error from the SSE streams.
    - Added an interceptor to stringify `function.arguments` if the model natively outputs it as a JSON object (as seen with Nemotron/Free_Shit via OpenRouter), bypassing a strict Zod schema crash in `ai-sdk` that manifests as an `Invalid JSON response`.
    - Added a robust prose-to-tool synthesiser for instances where reasoning models like `Free_Shit` ignore `tool_choice: "required"` and dump their JSON output directly into a markdown block in `msg.content`. The wrapper automatically parses the JSON out of the prose and synthesises a clean `tool_calls` structure for `ai-sdk`.
    - Modified `controller/src/llm/internal/prompts/system.ts` to explicitly instruct reasoning models to isolate their internal monologue within `<think>...</think>` tags. Because `ai-sdk`'s native reasoning support is disabled via the `openai-compatible` provider bypass, reasoning models like Nemotron were dumping their monologue directly into `msg.content`, causing it to be read aloud on air. This explicitly forces them to use tags so Subwave's existing `stripThinking` logic can safely remove it.
- **Banter Template Variables (Controller):** Modified `controller/src/llm/internal/prompts/banter.ts` to support dynamic `{host}`, `{guest}`, `{guests}`, and `{show}` tags within the `banterPrompt` field, replacing them with live context before sending to the LLM.
- **Request API Authentication:** Added `requireStationAuth` middleware to `POST /request` and `GET /request/:id` in `controller/src/routes/request.ts` to block unauthenticated song requests from bots. All API clients must now pass the station password via an `x-station-auth` header (or `Authorization: Bearer` / `?auth=` query param).
    - `web/lib/stationClient.ts` — updated `requestSong()` and `getRequestStatus()` to read the station token from `localStorage` and attach the `x-station-auth` header automatically.
    - `controller/src/mcp/client.ts` — updated the MCP `requestSong` / `requestStatus` calls to include `station: true` so the AI DJ's internal requests pass the header.
    - `lidarr_watchdog.py` — updated to include `"x-station-auth": "Midw@y!FM2026"` in the HTTP headers when submitting programmatic requests.
- **Midway Tavern Happy Hour Skill Time-Gate:** Added `state/skills/midway-tavern/tool.mjs` — a custom script that checks the current Hobart (`Australia/Hobart`) timezone and only allows the skill to fire on **Thursday, Friday, or Saturday between 2 PM and 6 PM** local time. Returns `{ available: false }` at all other times to prevent the Happy Hour announcement from triggering incorrectly. The `SKILL.md` prompt was updated to specify **$6 schooners** as the happy hour special. The old cron-only schedule (`cron: 45 15 * * 5,6`) was removed in favour of this runtime check.
- **Multi-Speaker Banter Queue Batching:** Modified `controller/src/broadcast/queue.ts` to have `announceExchange()` attempt to batch a full multi-speaker banter exchange through `tts.speakExchange()` as a single audio clip, falling back to sequential per-line rendering if the batch fails. **NEVER remove this batching logic** — the user explicitly wants to retain this architecture.