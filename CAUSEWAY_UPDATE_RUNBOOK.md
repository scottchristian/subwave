# Causeway FM — Subwave Update Runbook

> **Purpose:** A repeatable step-by-step guide for any AI agent to safely update the Causeway FM Subwave installation to a new upstream release, while preserving all custom code modifications and skills.
>
> **Architecture summary:**
> - **Local machine (Mac):** `/Users/scott/GitHub/subwave` — the git working copy where all edits are made before deployment.
> - **Proxmox server (`192.168.68.196`):** Runs all Subwave Docker containers. Source of truth for live skills and state.
> - **VPS proxy (`ghostmaster.online`):** NGINX + Icecast proxy; does **not** need updating during a Subwave upgrade.

---

## Pre-Flight Checks

Before starting, verify the station is in a safe state.

```bash
# 1. Confirm the station is reachable
curl -s https://radio.ghostmaster.online/api/health

# 2. Check what version is currently running
ssh root@192.168.68.196 "docker ps --format 'table {{.Names}}\t{{.Image}}' | grep sub-wave"

# 3. Note the current SUBWAVE_VERSION in the server .env
ssh root@192.168.68.196 "grep SUBWAVE_VERSION /root/subwave/.env"
```

> **IMPORTANT:** Note the current version tag (e.g. `1.13.0`) before proceeding. You'll need it to confirm the update was successful.

---

## Step 1 — Sync Server Skills to Local

Pull the latest skill files from the live server to the local repo so the backup captures any skills that may have been edited directly on the server.

```bash
scp -r "root@192.168.68.196:/root/subwave/state/skills/" "/Users/scott/GitHub/subwave/state/"
```

---

## Step 2 — Create Backup

Create a timestamped backup of **all** custom files. Store one copy locally in `custom_assets/` and upload a second copy to the server.

### 2a — Local Backup

```bash
cd /Users/scott/GitHub/subwave

BACKUP_NAME="causeway_backup_$(date +%Y%m%d_%H%M%S).tar.gz"

tar -czf "custom_assets/${BACKUP_NAME}" \
  custom_assets/gemini_tts.py \
  custom_assets/gemini_tts_live.py \
  custom_assets/station_ident_default.wav \
  controller/src/audio/remoteTts.ts \
  controller/src/audio/tts.ts \
  controller/src/broadcast/listeners.ts \
  controller/src/llm/internal/prompts/banter.ts \
  controller/src/llm/internal/prompts/system.ts \
  controller/src/llm/internal/provider/registry.ts \
  controller/src/llm/internal/telemetry/budget.ts \
  controller/src/llm/internal/telemetry/db.ts \
  controller/src/llm/internal/tools/station-services.ts \
  controller/src/mcp/client.ts \
  controller/src/routes/request.ts \
  controller/src/skills/_agent.ts \
  web/lib/stationClient.ts \
  state/skills/ \
  lidarr_watchdog.py \
  lidarr_sync_server.py \
  missed_requests_server.py \
  navidrome_filter.py \
  grog_scraper.py \
  verify_station_mods.py \
  deploy_controller.sh \
  deploy_web.sh

echo "Local backup created: custom_assets/${BACKUP_NAME}"
```

### 2b — Upload Backup to Server

```bash
ssh root@192.168.68.196 "mkdir -p /root/subwave/backups"
scp "custom_assets/${BACKUP_NAME}" "root@192.168.68.196:/root/subwave/backups/"
echo "Server backup uploaded to: /root/subwave/backups/${BACKUP_NAME}"
```

---

## Step 3 — Stash Local Customisations & Pull Upstream

### 3a — Stash All Local Changes

```bash
cd /Users/scott/GitHub/subwave
git stash push --include-untracked -m "causeway-fm-customisations-$(date +%Y%m%d)"
git stash list
```

> **CAUTION:** If `git stash` reports "No local changes to save", stop and investigate. This means something has already been committed or lost.

### 3b — Pull Upstream Changes

```bash
cd /Users/scott/GitHub/subwave
git pull origin main
grep '"version"' controller/package.json
grep '"version"' web/package.json
```

### 3c — Reapply Our Custom Patches

```bash
cd /Users/scott/GitHub/subwave
git stash pop
```

> **WARNING: Merge conflicts are expected.** When you pop the stash, git may report merge conflicts on files that the upstream release also changed. For each conflict:
> 1. Open the file — conflicts look like `<<<<<<< Updated upstream` / `>>>>>>> Stashed changes`.
> 2. Carefully merge the content, keeping BOTH our custom changes AND any new upstream code.
> 3. Refer to the **Custom Modifications Reference** section at the bottom of this document for what each file is supposed to do.
> 4. After resolving a file, run `git add <file>` to mark it resolved.
>
> If a conflict is too complex, restore the file from the backup:
> ```bash
> tar -xzf "custom_assets/${BACKUP_NAME}" -C /tmp controller/src/audio/tts.ts
> cp /tmp/controller/src/audio/tts.ts controller/src/audio/tts.ts
> ```

---

## Step 4 — Rebuild & Deploy the Controller

```bash
cd /Users/scott/GitHub/subwave
bash deploy_controller.sh
```

Verify the controller came back healthy:
```bash
curl -s https://radio.ghostmaster.online/api/health
```

---

## Step 5 — Rebuild & Deploy the Web Frontend

```bash
cd /Users/scott/GitHub/subwave
bash deploy_web.sh
```

> **NOTE:** If the build fails with a TypeScript error, read the error output carefully. The upstream update may have changed a component interface. Refer to the Custom Modifications Reference section to identify which customised file is at fault and apply the minimal fix.

---

## Step 6 — Rebuild the Gemini TTS Service

### 6a — Update the Gemini TTS Script on the Server

```bash
scp /Users/scott/GitHub/subwave/custom_assets/gemini_tts.py root@192.168.68.196:/root/subwave/gemini-tts/gemini_tts.py
```

### 6b — Rebuild the Docker Image on the Server

```bash
ssh root@192.168.68.196 "cd /root/subwave/gemini-tts && docker build -t subwave-gemini-tts . && docker restart sub-wave-gemini-tts"
```

Verify TTS is healthy:
```bash
ssh root@192.168.68.196 "docker logs sub-wave-gemini-tts --tail 20"
```

---

## Step 7 — Sync Skills to Server

```bash
scp -r /Users/scott/GitHub/subwave/state/skills root@192.168.68.196:/root/subwave/state/

curl -s -X POST https://radio.ghostmaster.online/api/dj/skills/rescan \
  -H "Authorization: Bearer ddFn.VGLyGYmAuT6Dik9"
```

---

## Step 8 — Restore the Custom Station Ident

```bash
scp /Users/scott/GitHub/subwave/custom_assets/station_ident_default.wav \
  root@192.168.68.196:/root/subwave/state/jingles/station_ident_default.wav
```

---

## Step 9 — Restore Python Companion Scripts

```bash
scp /Users/scott/GitHub/subwave/lidarr_watchdog.py root@192.168.68.196:/root/subwave/lidarr_watchdog.py
scp /Users/scott/GitHub/subwave/lidarr_sync_server.py root@192.168.68.196:/root/subwave/lidarr_sync_server.py
scp /Users/scott/GitHub/subwave/missed_requests_server.py root@192.168.68.196:/root/subwave/missed_requests_server.py
scp /Users/scott/GitHub/subwave/navidrome_filter.py root@192.168.68.196:/root/subwave/navidrome_filter.py
scp /Users/scott/GitHub/subwave/grog_scraper.py root@192.168.68.196:/root/subwave/grog_scraper.py
```

---

## Step 10 — Post-Update Verification

```bash
# 1. Station health check
curl -s https://radio.ghostmaster.online/api/health

# 2. Confirm the new version is running
ssh root@192.168.68.196 "docker ps --format 'table {{.Names}}\t{{.Image}}' | grep sub-wave"

# 3. Test the request endpoint is still password-protected (should return an error)
curl -s -X POST https://radio.ghostmaster.online/api/request \
  -H "Content-Type: application/json" \
  -d '{"text": "test"}'
# Expected: {"error":"station password required ..."}

# 4. Test that an authenticated request passes through
curl -s -X POST https://radio.ghostmaster.online/api/request \
  -H "Content-Type: application/json" \
  -H "x-station-auth: Midw@y!FM2026" \
  -d '{"text": "test"}'
# Expected: any response OTHER than the "password required" error

# 5. Confirm now-playing is live
curl -s https://radio.ghostmaster.online/api/now-playing | head -c 200

# 6. Check controller logs for errors
ssh root@192.168.68.196 "docker logs sub-wave-controller --tail 50 2>&1 | grep -i error"

# 7. Run the Automated Custom Modification Tests
ssh root@192.168.68.196 "python3 /root/subwave/verify_station_mods.py"
```

---

## Custom Modifications Reference

Use this as the authoritative guide when resolving merge conflicts in Step 3c. Each entry describes what a customised file does and why, so a fresh agent understands the intent before editing it.

### controller/src/routes/request.ts
**What:** Added `requireStationAuth` middleware to `POST /request` and `GET /request/:id`.
**Why:** Prevents unauthenticated bots from spamming the song request endpoint and burning AI tokens.

### web/lib/stationClient.ts
**What:** `requestSong()` and `getRequestStatus()` attach the `x-station-auth` header from `localStorage` (the token the listener typed when they authenticated to the player).
**Why:** Allows authenticated listeners to submit requests through the web player without a separate prompt.

### controller/src/routes/dj.ts
**What:** Added `POST /dj/queue-with-intro` endpoint.
**Why:** Allows external scripts to queue a specific track with a custom, pre-written raw intro script that the DJ will read verbatim, rather than relying on the LLM to generate the link.

### controller/src/server.ts
**What:** Added `app.set('trust proxy', true);` and updated the budget logging to handle the new `seeded.tokens` schema from our SQLite telemetry upgrade.
**Why:** Required for accurate listener IPs via NGINX/Caddy, and ensures the boot logs don't crash when reading the SQLite budget object.

### controller/src/mcp/client.ts
**What:** Added `station: true` and the station auth header passthrough to MCP `requestSong` and `requestStatus` calls.
**Why:** AI agents using the MCP interface can still queue songs after the request endpoint was locked.

### controller/src/llm/internal/provider/registry.ts
**What:** Custom `openAICompatibleFetch` wrapper with several fixes applied to ALL openai-compatible provider calls:
- Forces `stream: false` to bypass a 9router SSE streaming bug.
- Strips `thinking` / `chat_template_kwargs` for non-standard model names (`cf/`, `gemini/`, `free_shit` aliases).
- Injects `safe_prompt: false` for any `gemini/` model (disables Gemini safety filters on the 9router path).
- Stringifies `function.arguments` if a model returns it as a JSON object instead of a string (Nemotron/OpenRouter quirk).
- Synthesises a `tool_calls` structure from markdown prose/JSON blocks for reasoning models that ignore `tool_choice: required`.
- Strips markdown fences (` ```json ... ``` `) from tool-call argument values.

### controller/src/llm/internal/prompts/system.ts
**What:**
- Forbids the DJ from mentioning, assuming, or inventing the current weather.
- Instructs reasoning models to put their internal monologue inside `<think>...</think>` tags so it is not spoken on air.
- Appends `banterPrompt` (from settings UI) and `listenerPrompt` (from settings UI) to the base system prompt.

### controller/src/llm/internal/prompts/banter.ts
**What:**
- Supports `{host}`, `{guest}`, `{guests}`, `{show}` dynamic tags in the `banterPrompt` field.
- Explicitly allows profanity, sarcasm, and harshness in the banter system prompt.
- Forbids weather hallucination in banter.

### controller/src/audio/tts.ts
**What:** Exposes `speakExchange()` which tries to batch a multi-speaker banter exchange into a single audio clip through the Gemini `/speak-multi` endpoint, falling back to sequential rendering on failure.

### controller/src/audio/remoteTts.ts
**What:** Exposes `speakMulti()` — the low-level HTTP call to the Gemini TTS `/speak-multi` endpoint with a `SpeakMultiRequest` payload (array of `{voice, text}` objects).

### controller/src/broadcast/listeners.ts
**What:** Reports new peak listener records to the SQLite telemetry database at `state/telemetry.db`.

### controller/src/llm/internal/telemetry/budget.ts
**What:** Logs LLM token usage and TTS character costs to the SQLite telemetry DB instead of in-memory only. Data survives container restarts.

### controller/src/llm/internal/telemetry/db.ts *(new file)*
**What:** Manages the `better-sqlite3` database connection for `state/telemetry.db`.

### controller/src/llm/internal/tools/station-services.ts
**What:** Reads the durable peak listener count from the SQLite telemetry DB for the `station-stats` skill.

### controller/src/skills/_agent.ts
**What:** Short-circuits the LLM rewrite step for any skill that returns `{ available: true, script: '...' }`. The script is passed directly to `queue.announce()` without modification. This preserves `[voice:name]` inline tags, swear words, and catchphrases that would otherwise be sanitised or rewritten by the LLM.

### custom_assets/gemini_tts.py (source of truth for the `subwave-gemini-tts` container)
**What:** Our completely custom Gemini TTS service. Key additions over the upstream version:
- `VOICE_MAP` — maps persona slug names (e.g. `jax`, `zane`, `tyrone`/`sadachbia`) to Gemini built-in voice names.
- `STYLE_MAP` — maps persona slugs to style-prompt instructions that shape how each character sounds.
- `/speak-multi` endpoint — accepts a JSON array of `{voice, text}` objects and renders them in a single Gemini multi-speaker request.
- Inline `[voice:name]` tag parser in the `/speak` endpoint — detects tags, splits the text, and upgrades the request to use `SpeakMultiRequest` automatically.
- `GEMINI_BASE_URL` environment variable — routes TTS generation through 9router instead of calling Google directly.
- 400 abort safeguard — immediately stops the retry loop if a `400 Bad Request` is received on the 9router path, preventing cascading lock-ups.

### state/skills/midway-tavern/tool.mjs *(new file)*
**What:** A time-gate script that checks the current Hobart (`Australia/Hobart`) timezone. Returns `{ available: false }` unless it is Thursday, Friday, or Saturday between 2 PM and 6 PM local time. Prevents the Happy Hour announcement from triggering at wrong times.
**Skill prompt note:** The `SKILL.md` prompt specifies **$6 schooners** as the happy hour special and the 4 PM–6 PM time window.

### state/skills/grog-finder/tool.mjs
**What:** Reads live bottle shop pricing from `state/bottle_shops.db` (populated daily by `grog_scraper.py`). Returns a pre-written verbatim DJ script using `[voice:sadachbia]` (Tyrone's voice). Must include `export const requiresData = false;` to prevent reasoning models from standing down when no raw "data" object is returned. The skill has a 3-hour cooldown and returns `{ available: false }` cleanly when no items are on special.

### state/skills/station-stats/tool.mjs
**What:** Reads cumulative LLM token spend, TTS character cost, and peak listener count from the SQLite telemetry DB. Applies a 1.50x AUD conversion multiplier to the cost figure before returning it (so the DJ reads it as AUD without being told to convert).

### missed_requests_server.py
**What:** Ingests unfulfilled requests from `requests.log`. Uses Gemini via `GEMINI_BASE_URL` on 9router (OpenRouter) to clean up messy conversational requests (e.g. stripping out swear words and banter before searching iTunes).
**Why:** Without this, messy requests fail iTunes lookup. Also handles "Any" band requests by mapping them generically rather than locking to a specific song.

### lidarr_sync_server.py
**What:** Syncs the cleaned iTunes requests to Lidarr. For generic band requests, it forces Lidarr to search for missing albums and logs the artist ID so the watchdog can monitor all of their tracks. Also uses `rapidfuzz` to loosely match iTunes titles to Lidarr titles to prevent infinite loops.

### lidarr_watchdog.py
**What:** Monitors Lidarr for newly downloaded tracks and submits them to the Subwave request queue. Must include the `x-station-auth: Midw@y!FM2026` header in all HTTP requests to `/api/request` since the endpoint was locked. Unconditionally pushes the downloaded track to the queue because Icecast's active-listener IP is isolated and cannot be reliably checked.

### controller/src/broadcast/queue.ts
**What:** Modified `announceExchange()` to attempt batching a multi-speaker banter exchange through `tts.speakExchange()`, airing the result as a single audio clip. Falls back to sequential per-line rendering if the batch fails.
**Why:** Reduces TTS latency and produces more natural-sounding multi-speaker banter.
**Important:** NEVER remove this batching logic. The user explicitly wants to retain this architecture even though Gemini's multi-speaker model occasionally has styling inconsistencies.

### controller/src/routes/settings/llm.ts
**What:** Modified the `/settings/llm/probe-compat` route (the "Test Connection" button in the Web UI) to use the custom `openAICompatibleFetch` wrapper instead of a raw fetch.
**Why:** Without this fix, testing the connection to `free_shit` or any 9router model in the Web UI throws an "Invalid JSON" parse error from the SSE stream response.

### controller/src/settings.ts & controller/src/settings/defaults.ts
**What:** Increased the truncation limit for the `banterPrompt` settings field to 10,000 characters in `settings.ts`. Added our custom default `banterPrompt`, `listenerPrompt`, and `geminiSafety` (harassment/hateSpeech blocks set to false) configurations to `defaults.ts`.
**Why:** The default limit was too short to fit detailed persona-specific banter rules, and we want our harsh banter rules to survive a settings reset.

### web/components/admin/settings/LlmSection.tsx, TtsSection.tsx, SettingsPanel.tsx, registry.ts, shared.tsx
**What:** Added the UI toggles for `geminiSafety` blocks and the textarea for `listenerPrompt` and `banterPrompt` to the Admin Settings dashboard.
**Why:** Allows the station operator to tune the DJ's behavior, safety limits, and listener assumptions on the fly without restarting the container.

### controller/src/broadcast/dj-agent/schemas.ts
**What:**
- Extended `requestSchema` `kind` enum from `['track', 'chat']` to `['track', 'chat', 'skill']`. Added optional `skill` field (the slug to trigger).
- Updated `requestSystem()` to conditionally inject:
  - The full `djBehaviour.requestChatPrompt` text (editable from UI) when `allowRequestShoutOuts` is true — this IS the complete instruction, not an append.
  - A list of enabled skill slugs when `allowRequestSkills` is true.
- Updated the `ack` field description to explicitly allow profanity, sarcasm and harshness.
**Why:** Enables the DJ Agent to respond to shout-outs/jokes directly and route skill requests to station capabilities.

### controller/src/broadcast/dj-agent.ts
**What:** Added a "Skill escape (C2)" block in `runRequestViaAgent` that returns `{ skill: slug }` to the caller when `kind === 'skill'`.
**Why:** Decouples the skill dispatch from the agent itself so the route can handle it synchronously.

### controller/src/routes/request.ts
**What:** Added a skill escape handler that calls `runCapability(slug)` when the agent returns a skill slug. The skill airs immediately (over the music, ducked), and its generated text is returned as the listener's ack.
**Why:** Allows listeners to trigger station skills (weather, grog prices, etc.) via a request.

### controller/src/schemas/settings.ts & controller/src/settings/defaults.ts & controller/src/settings.ts
**What:** Added three new `djBehaviour` settings:
- `allowRequestShoutOuts` (boolean, default `true`)
- `allowRequestSkills` (boolean, default `true`)
- `requestChatPrompt` (string, max 10000 chars, has a default shout-out/joke instruction)
- `requestTrackPrompt` (string, max 10000 chars, appended to music request system prompt)
**Where to edit:** Admin → Settings → DJ Behaviour → "Listener request chat" card.

### web/components/admin/settings/DjBehaviourSection.tsx & shared.tsx
**What:** Added the "Listener request chat" card with toggle for shout-outs, toggle for skills, and a full-height textarea for the request chat prompt and music request intro prompt.
**Why:** Operator-editable on the fly, no container restart needed.
