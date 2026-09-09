---
trigger: always_on
description: Environment details for Causeway FM instance
---

# Causeway FM Context

This codebase is being used to host a personal radio station named **Causeway FM**.
Must try and keep cost's to $0 where possible, only suggest to spend $ on tokens when nessesary.

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
- **Agent Prompts UI Customization (Controller & Web):** 
    - Added a `Banter Rules` field (`banterPrompt`) to the Web UI to dynamically configure banter behavior instead of using hardcoded rules. Modified `controller/src/settings.ts` to bump its truncation limit to 10,000 characters.
    - Added a `Listener Activities` field (`listenerPrompt`) to the Web UI to dynamically guide the core DJ prompt on how to describe listeners during regular segments.
- **Multi-Speaker Banter:** 
    - `gemini_tts.py` has a custom `/speak-multi` endpoint using `SpeakMultiRequest` (an array of `SpeakLine` objects). It parses the array to build a script string and passes a `multi_speaker_voice_config` to Gemini to render all speakers at once.
    - `controller/src/audio/remoteTts.ts` exposes `speakMulti()`.
    - `controller/src/audio/tts.ts` exposes `speakExchange()` to try and batch `remote` lines.
    - `controller/src/broadcast/queue.ts` modifies `announceExchange()` to attempt batching the exchange through `tts.speakExchange()`, airing the result as a single clip with a combined text payload while falling back to sequential rendering otherwise.

## Deployments & Hot-Patching
Because the production radio station on the Proxmox server (`192.168.68.196`) runs pre-built Subwave Docker images from GitHub Container Registry (GHCR) and does **not** contain a local git repository, any custom code modifications made to the local repository must be hot-patched into the live containers.

To deploy custom changes (like the AI modifications above):
1. **Copy to Server:** Transfer the modified local files to the server via `scp` (e.g., `scp controller/src/audio/tts.ts root@192.168.68.196:/root/subwave/tts.ts`).
2. **Patch Container:** SSH into the server and use `docker cp` to inject the files directly into the running container (e.g., `docker cp /root/subwave/tts.ts sub-wave-controller:/app/src/audio/tts.ts`).
3. **Restart Service:** Restart the container to apply the changes (e.g., `docker compose restart controller`).

**Important Note:** Because these are hot-patches inside the container filesystem, they will be **wiped out** the next time the station operator updates Subwave by pulling a new GHCR image. When that happens, the custom codebase modifications documented above must be re-implemented in the new codebase and hot-patched again.

### Custom Station Ident (Jingle) Recovery
The default Subwave station ident (`station_ident_default.wav`) on the live server has been overwritten with a custom, personality-driven AI jingle. A backup of this custom audio file is stored in this repository at `custom_assets/station_ident_default.wav`.

Because Subwave's backend explicitly protects the default ident and regenerates it if missing, an upstream update or a state wipe may accidentally restore the generic built-in jingle over our custom one. 

If this happens, agents must restore it by copying the backup directly over the live file on the server:
```bash
scp custom_assets/station_ident_default.wav root@192.168.68.196:/root/subwave/state/jingles/station_ident_default.wav
```
(No container restart is required for the jingle audio replacement to take effect).