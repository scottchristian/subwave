---
trigger: always_on
description: Environment details for Causeway FM instance
---

# Causeway FM Context

This codebase is being used to host a personal radio station named **Causeway FM**.
Must try and keep cost's to $0 where possible, only suggest to spend $ on tokens when nessesary.

## LLM Model Stack
- **Primary Model:** `gemini/gemini-3.5-flash-lite` (via 9router at `http://192.168.68.193:20128/v1`, key = `.env GEMINI_API_KEY`). Set 2026-09-26 by operator instruction — do NOT switch back to `Free_Shit` without explicit operator approval (see incident 2026-09-26 below).
- **Failover Model:** `gemini-2.5-flash` (via the `google` provider in Subwave, key = `GOOGLE_GENERATIVE_AI_API_KEY` in `state/secrets.env`).
- `Free_Shit` (9router alias, free Nvidia Nemotron) is PARKED, not primary. It still throws `Invalid JSON response` on structured calls (Station ID, picker) even with the fence-strip/prose-synthesis fixes in `registry.ts`.
- **Important**: `Free_Shit` occasionally wraps tool-call arguments in markdown fences (` ```json ... ``` `). A custom fix in `controller/src/llm/internal/provider/registry.ts` strips these fences in the `openAICompatibleFetch` response handler. Additionally, `Free_Shit` is on the skip-list for OpenAI-specific no-think injection (`chat_template_kwargs`, `thinking`, `reasoning_format`) to avoid 400 Bad Requests from the upstream router. `gemini/*` models are NOT on that skip-list — but `gemini/gemini-3.8-flash` DOES 400 with `Thinking level MINIMAL is not supported`, so never set it primary. `gemini-3.5-flash-lite` accepts the full param set (verified 2026-09-26).

## TTS Configuration
- **Primary TTS Engine:** The station uses a custom Gemini TTS container running `gemini-2.5-flash-preview-tts` as its primary text-to-speech engine for all personas.
- **Engine Setting:** Agents **MUST** ensure that the TTS engine for announcements and skills uses the `remote` engine (which routes to `gemini_tts.py` at `http://192.168.68.196:5001`). Do NOT change the station's TTS engine to OpenAI, Piper, or ElevenLabs unless explicitly instructed.
- **Skill Overrides:** Custom skills that output a `[voice:Persona]` tag rely on the `remote` engine handling to correctly route and style the voice (e.g. `grog-finder` using `[voice:Tyrone]`).

## Environment
- OS: Debian 13 container
- Platform: Proxmox server

## Network Architecture
- **VPS Proxy:** A cloud VPS at `ssh root@ghostmaster.online`.
  - Hosts `https://causewayfm.com` (the listener-facing Next.js frontend).
  - Hosts `https://radio.ghostmaster.online` (the backend API / Icecast stream router).
- **Routing:** NGINX and Icecast on the VPS route `radio.ghostmaster.online` over native IPv6 directly to the Proxmox container (`[2404:e80:bef:0:be24:11ff:fe6c:b839]:7700`) to bypass Tailscale overhead.
  - **Important:** The VPS cannot directly access the local `192.168.68.196` LAN address. The Next.js app (`causewayfm.com`) must communicate with the backend using the public `radio.ghostmaster.online` address (or the IPv6 proxy tunnel).
- **Domain:** `radio.ghostmaster.online`
- **Security:** Let's Encrypt is configured on the VPS for HTTPS.

## URLs
- **Stream URL:** http://192.168.68.196:7700/stream.mp3
  - *Note:* When proxying this stream for authorized listeners through Next.js on the VPS, you must pass Icecast Basic Auth (`Authorization: Basic <base64 of listener:password>`) using the station password, because `listenerAuth` is enabled.
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
        "Authorization": "Basic YWRtaW46TWlkd0B5IUZNMjAyNg==",
        "x-station-auth": "Midw@y!FM2026"
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
- **`subwave_similar_tracks`**: Find similar sounding tracks using CLAP embeddings.
- **`subwave_queue_track`**: Queue an exact track (admin).
- **`subwave_queue_block`**: Queue a whole album or artist block (admin).
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
Because Subwave is frequently updated upstream, we have made extensive custom codebase modifications to support advanced Gemini TTS features, multi-store scraping, and playlist syncing. 

**IMPORTANT:** Do not list the modifications here. For a comprehensive, up-to-date list of all custom modifications and what they do, you **MUST** read the `Custom Modifications Reference` section at the bottom of the update runbook:
`[CAUSEWAY_UPDATE_RUNBOOK.md](file:///Users/scott/GitHub/subwave/CAUSEWAY_UPDATE_RUNBOOK.md)`
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
- **Request Chat Routing (Shout-Outs, Jokes & Skills):** Extended the DJ Agent request path to handle non-music requests directly.
    - **Schema (`controller/src/broadcast/dj-agent/schemas.ts`):** The `requestSchema` `kind` enum now includes `'skill'`. A new optional `skill` field carries the skill slug. The `requestSystem()` prompt now conditionally injects:
        - The operator-editable **"Request Chat Prompt"** (`djBehaviour.requestChatPrompt`) as the complete instruction for shout-outs and jokes — not appended to a hardcoded rule, so it can be replaced entirely from the UI.
        - A list of enabled skill slugs so the model can route explicit requests like "what's the weather?" to `kind: "skill"`.
    - **DJ Agent (`controller/src/broadcast/dj-agent.ts`):** Added a "Skill escape (C2)" block that returns `{ skill: slug }` to the caller when the agent outputs `kind: 'skill'`.
    - **Route (`controller/src/routes/request.ts`):** The skill escape is handled by calling `runCapability(slug)`, which airs the skill immediately over the music (ducked). The generated text is returned to the listener as the request acknowledgment.
    - **Settings (backend + UI):** Three new `djBehaviour` settings control this feature:
        - `allowRequestShoutOuts` (boolean, default `true`) — enables shout-outs and jokes in request acks.
        - `allowRequestSkills` (boolean, default `true`) — enables listener-triggered skills via requests.
        - `requestChatPrompt` (string, max 10000 chars) — the **complete** instruction the DJ receives for chat (shout-out/joke) requests, editable live from **Settings → DJ Behaviour → Listener Request Chat**. The default is a snarky-but-friendly shout-out instruction allowing profanity.
    - **Agent ack swearing:** Also updated the `ack` field description in `requestSchema` and the agent schema to explicitly allow profanity and sarcasm in acknowledgments when the listener's tone warrants it.


## Common Errors & Troubleshooting

### Silent DJs / 2026-09-26 — NEVER restore a backup export over live settings blind
Symptoms: music played fine, zero presenter speech; settings save 400'd `unknown settings keys: pauseTalkMinSeconds, djBehaviour`.
Two stacked faults, both traced to a backup restore plus a stale prod image:
1. The restored `state/settings.json` carried redacted `"set"` sentinels as LITERAL provider keys (`llm.keys["openai-compatible"] = "set"`). Controller sent `Bearer set` → 9router 401 on every LLM call → no scripts, music only. (`getRedacted()` masks keys as `'set'`; replaying that export through `update()` destroys credentials.)
2. Prod ran GHCR image 1.13.0 while repo is 1.16.0: old patch registry rejected new settings keys (the 400), old `registry.ts` lacked `stream: false` + fence fixes (Invalid JSON on 9router SSE).
Fix applied: real keys rewritten into `llm.keys` (`openai-compatible` from `.env GEMINI_API_KEY`, `google` from `secrets.env GOOGLE_GENERATIVE_AI_API_KEY`), fallback set to `google/gemini-2.5-flash`, primary set to `gemini/gemini-3.5-flash-lite`, then `bash deploy_controller.sh` hot-patch + restart. Verified: fresh `voice-playing.json`, zero `[error]` lines. Rollback copy: `state/settings.json.pre-silent-fix.bak` on server.
Regression guards:
- After ANY settings restore, check `llm.keys` holds real key material (lengths, never the literal `"set"`), then `docker restart sub-wave-controller` and confirm no `Unauthorized`/`INVALID_ARGUMENT` in logs.
- Keep prod controller hot-patched from this repo (`deploy_controller.sh`); a GHCR pull wipes it and re-opens both faults. Long-term fix is an image bump to 1.16+.

### Icecast Admin 429 (Too Many Failed Attempts)
If the main web dashboard reports: `can’t reach Icecast admin: /listeners/connections failed (429): too many failed attempts, try again later`, this means a client or script has hit the API with invalid credentials too many times, triggering the controller's `MAX_AUTH_FAILURES` IP lockout in `controller/src/middleware/auth.ts`.
**Fix:** The lockout is stored in-memory. SSH into the Proxmox server and restart the controller to clear the block:
```bash
ssh root@192.168.68.196 'docker restart sub-wave-controller'
```