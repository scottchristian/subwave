# Causeway FM - Web Player Architecture & Setup Guide

This document details the architecture, setup, and custom implementation details of the `causewayfm.com` Next.js frontend. This serves as a reference manual for repairing, rebuilding, or maintaining the site.

## Development Rules

**CRITICAL RULE: Element IDs**
Everything in our web player needs its own `id` element reference. This is required so that the operator can better direct AI agents to make specific changes or target specific sections of the layout. (e.g., `id="btn-play-radio"`, `id="section-now-playing"`). Never create interactive UI elements without assigning them a descriptive `id`.

## Architecture Overview

**Core Stack:**
- **Framework:** Next.js (App Router)
- **Database:** SQLite (managed via Prisma ORM)
- **Authentication:** NextAuth.js (Google OAuth & Magic Link Email)
- **Styling:** Vanilla CSS (`globals.css`) with modern features (View Transitions, CSS variables)
- **Deployment:** PM2 on a Debian VPS (`ghostmaster.online`) with NGINX routing.

**Network Flow:**
The web application runs on a VPS and communicates with a separate Proxmox container hosting the core Subwave backend and Icecast stream.
- **Frontend URL:** `https://causewayfm.com` (Served by Next.js on port 3000 via PM2, proxied by NGINX)
- **Backend URL:** `http://[2404:e80:bef:0:be24:11ff:fe6c:b839]:7700` (Proxmox container running Caddy, Controller, and Icecast)

## Key Features & Implementations

### 1. Authentication (NextAuth & Prisma)
The site requires users to be authenticated and explicitly approved by an admin before they can listen to the stream.
- **Providers:** Google OAuth (Email provider is not configured).
- **Database Schema (`prisma/schema.prisma`):**
  - Uses standard NextAuth models (`User`, `Account`, `Session`, `VerificationToken`).
  - Extends `User` with `isApproved` (default `false`), `isAdmin` (default `false`), `hideLikeName` (default `false`) and `nickname` (admin-set display override).
  - Custom models: `StreamSession` (logging listening time), `Donation` (tracking BMAC contributions), `Setting` (key-value store — station/server/auth config), `SongRequest`, `SongLike` (favorites + cached `title`/`artist`/`album` for history display), `SongLinkCache` (resolved Spotify/Apple URLs by `subsonic_id`) and `PushSubscription` (admin Web Push endpoints).
- **Approval Gate:** The player page shows Pending / Access-denied states. Pending clients poll `/api/me` every 10s and flip in automatically on approval; deleted accounts get an explicit denied screen.

### 2. Audio Stream Proxy & Master-Relay Architecture
To minimize upstream bandwidth, Causeway FM utilizes a **1-to-Many Master-Relay Architecture**:
- The VPS runs a local Icecast server (`radio.ghostmaster.online:8000`) configured as a **Relay**. It maintains exactly 1 connection to the master Icecast server on the Proxmox backend (`[2404:e80:bef:0:be24:11ff:fe6c:b839]:7700`).
- The Next.js frontend proxy (`/api/stream`) connects exclusively to the *local* VPS Icecast relay (`http://127.0.0.1:8000/stream.mp3`), distributing the stream to an unlimited number of listeners using the VPS's bandwidth.
- The Subwave DJ Brain (Controller) on the Proxmox backend has `ICECAST_ADMIN_URL` configured to poll the VPS Icecast relay (`http://ghostmaster.online:8000`). This ensures the DJ dashboard displays the correct number of listeners and their true IPs, completely bypassing the local Proxmox listener count.

- **Proxy Logic (`app/api/stream/route.ts`):** 
  - Validates the user's NextAuth session and `isApproved` status.
  - Retrieves the `stationPassword` from the Prisma `Setting` table.
  - Fetches the local VPS Icecast stream (`SUBWAVE_STREAM_URL=http://127.0.0.1:8000/stream.mp3`).
- **Safari Compatibility Quirk (CRITICAL):**
  - Icecast KH limits concurrent connections for basic authenticated users (`Account already in use` error). 
  - Safari's `<audio>` element sends rapid `Range` requests to probe the stream before fully connecting, which triggers Icecast's concurrent connection limit when using standard `Authorization: Basic` headers.
  - **The Fix (Backend - Connection Management):** The proxy passes the station password securely as a query parameter (`?auth=password`). It also strictly monitors the `req.signal.aborted` state and `abort` events from Next.js to immediately terminate the upstream `fetch` connection when Safari closes a probe request, preventing ghost connections.
  - **The Fix (Backend - Header Passthrough):** Next.js strips HTTP response headers by default. To prevent Safari from treating the stream as a static MP3 file (which causes duplicate connections), the proxy explicitly copies all `icy-*` headers (e.g., `icy-metaint`) from the Icecast response and sends them to the client. It also forwards the client's `X-Forwarded-For` IP to Icecast so the DJ dashboard shows the real listener IP instead of the proxy's IP.
- **Frontend Player (`app/page.tsx`):**
  - Uses a cache-buster (`/api/stream?t=Date.now()`) to prevent Safari from serving dead chunks from the disk cache.
  - Explicitly uses `preload="none"` and avoids calling `audio.load()` to prevent Safari from aggressively pre-establishing multiple TCP connections before the user clicks Play.
  - **Auto-Reconnect (Mobile Safari Limitations):** iOS WebKit strictly enforces user-gesture requirements for `audio.play()`. If the stream drops (e.g., VPS deployment or cell tower switch), the `error`/`ended` event attempts an immediate synchronous `audio.play()` to retain the gesture unlock. If iOS rejects this with a `NotAllowedError`, the player must gracefully fall back to a paused state, requiring the user to physically click play again. We avoid putting the reconnect inside a `setTimeout` loop because iOS explicitly blocks async auto-play.
  - **Station "Wake Up" State (Mobile Safari Limitations):** When playback begins on endless live streams, iOS Safari sometimes fails to fire the standard `playing` event. To reliably detect playback and dismiss the "Waking up..." UI overlay, the player binds `playing`/`canplay`/`loadeddata`/`timeupdate` plus a 500ms poll (`!paused && readyState >= 2`) as backstop. `waiting` only counts pre-roll (Safari fires it on healthy live edges), `stalled` is ignored unless actually paused, and the whole binding runs on the approved-player flag — binding on first mount misses the `<audio>` node (it renders after session resolves) and sticks the button forever.
  - **On-air controls (`section-player-controls`):** `Skip track` shows for every approved listener and fires while solo (server re-checks headcount at fire time; admins bypass); with company it sits disabled explaining why. Post-skip it cools down `bufferSeconds + 15s` to match the delayed art commit. `Never play` (track/album/artist menu → Subwave never-play blocklist) is admin-only. Both hide while the radio isn't running.
  - **Art overlay (`btn-art-toggle`):** hover reveals a play/stop disc over the cover (desktop); touch shows it whenever paused. Tap toggles. Art goes grayscale while hibernating, color on play.
  - **Liked overlay:** Liked Songs opens as a modal so `<audio>` stays mounted; navigating routes would kill sound.
  - **Now playing:** title · artist · album · year, Spotify/Apple links + heart on one row. Countdown (`song-countdown`) shows only while playing and clamps at -0:00 through the delayed promotion instead of vanishing.

### 3. Buy Me A Coffee (BMAC) Webhook (`/api/webhooks/bmac`)
The application listens for webhook events from Buy Me A Coffee to track listener donations.
- **Webhook Endpoint:** Receives `supporter_email`, `amount`, `currency`, and `support_note`.
- **Security:** Requires a secret token match (`BMAC_WEBHOOK_SECRET`).
- **Logic:** Maps the supporter's email to a registered NextAuth user (if they exist) and inserts a `Donation` record into the database.

### 4. Admin Dashboard (`/admin`)
An admin-only interface for managing users and station settings.
- **Security:** Validates that the session user has `isAdmin: true` in the database.
- **Features:**
  - Users: full roster (not just pending — zero-play accounts included) with Approve / Revoke (back to pending, never yourself) / Remove (donations kept, attribution nulled), plus per-user nickname override (blank clears).
  - Push alerts: Push card shows device count + "Enable on this device" (Web Push via `/sw.js`, VAPID keys in server env); every new signup fires `events.createUser` → push to all admin devices. iOS needs the installed homescreen app + granted permission.
  - Pending logins poll `/api/me` every 10s: approved flips in automatically, deleted accounts get an explicit access-denied screen.
  - **Support Button** card: `donate_url` + `donate_text` (listener-facing support button).
  - **Sub/Wave Server** card: `subwaveApiUrl` + `subwaveAdminUser`/`subwaveAdminPass` + `stationPassword`. All proxy routes (`/api/request`, `/api/stream` password, `/api/admin/skip`, `/api/admin/block-track`) read these live from the DB with server-env fallback — no restart. Save also calls `POST /api/admin/server/sync`, which rewrites the local Icecast relay's master `<server>`/`<port>`/`<password>` in `/etc/icecast2/icecast.xml` (backed up, only on change), reloads Icecast, and proves `/stream.mp3` answers 200. Without this, changing address/password would strand the 1-to-many relay on the old master and kill the stream.
  - **Google Sign-In** card: `googleClientId`/`googleClientSecret`/`adminEmail`. Mirrored into the server `.env.local` (backed up) and the station auto-restarts (~2s, listeners reconnect) because NextAuth reads provider creds once at boot. `NEXTAUTH_SECRET` stays env-only. Changing admin email promotes future matching sign-ins; it does not demote the previous admin.
  - View donation history and per-user stats (rolling 24h / 7d / 30d / all-time listening + song likes, via `/api/admin/stats`).
    - **Stats honesty rules:** windows key off session `startTime`; closed sessions use `durationSec` (capped 24h); open sessions count elapsed only if started within the last hour — older open rows are restart-orphans whose close hook never ran (140+ on a 4-user station) and count 0. Time is the **union** of intervals per user: every Play logs ~2 rows (Safari probe-double), so naive sums double-count; overlapping rows merge.

### 5. UI & View Transitions
The frontend is designed with a premium, seamless aesthetic using vanilla CSS and the native View Transitions API.
- **State Polling:** The player polls backend `now-playing`, `schedule` and `state` every 5 seconds.
- **Transitions:** `document.startViewTransition()` morphs art/track details on real lineup changes only — identical re-polls apply silently (snapshotting identical DOM flashes white).
- **Delay Buffer:** Holds the whole state commit for `stream.bufferSeconds` so art flips when audio flips. The hold keys on the now-playing id, but the backend queue runs ahead (handed-over `sent` items): polls that see the queue past the display stash instead of committing, or up-next art flips a track early. Commits always apply the freshest fetch.
- **Styling (`globals.css`):** Glassmorphism, dynamic gradients, `view-transition-name` properties (`album-art`, `track-title`, `track-artist`). Play button color-transitions on hover in both idle and playing states; submit text is white-on-red.
- **Song Likes:** Heart button (`/api/likes`) with global counter + avatar stack (name-hiders render Anonymous). Likes store title/artist/album at tap time for history display.

### 6. Direct Platform Link Resolver & Caching
Rather than opening generic search queries on Spotify and Apple Music, the web player asynchronously resolves the exact track URLs in the background.
- **Resolution (`/api/links`):** Takes `trackId` + `title`/`artist` + optional `album`/`year`. Spotify walks `track/artist/album/year` → drop album → drop year (title/artist trusted, album/year often wrong). Apple walks title+artist+album with collection verification → track+artist verified → top hit.
- **Request Anything:** The request card ("Request Something") takes songs, genres, shout-outs — not just tracks.
- **Prisma Caching (`SongLinkCache`):** Because Subsonic/Navidrome is largely read-only for track metadata, the resolved URLs are stored indefinitely in the Causeway FM SQLite database (`causewayfm.db`) mapped by the `subsonic_id`.
- **Dynamic UI Update:** If the database has the URLs cached, or once the external APIs resolve them, the frontend dynamically replaces the generic search `href` in the Spotify and Apple Music buttons with the direct links.

### 7. Liked Songs & Host Mirror

- **History (`/likes` + player overlay):** Own likes newest-first with cover (via backend `/api/cover`, logo fallback), per-row Spotify/Apple links and Unlike. Pre-metadata rows show cover + id until re-liked.
- **Name hiding:** `hideLikeName` renders the user as Anonymous in public like lists (counts and own-heart state unaffected).
- **Host mirror:** Every heart also fires the Subwave listener `POST /like` (never the operator heart — operator curation outranks listener signal), with the real client IP forwarded for their rate limiter. Fallback `"Artist - Title"` ids stay local; host misses never fail the local like.

### 8. Push Notifications (admin)
Admin devices subscribe via the Push card (Web Push through `/sw.js`, VAPID keys in server env — iOS needs the installed homescreen app). Every new signup fires `events.createUser` → push to all admin devices, opening `/admin` on tap. Gone endpoints (410/404) self-prune.

## Environment Variables
The `.env.local` file must contain the following keys for the app to function:
```env
# NextAuth
NEXTAUTH_URL="https://causewayfm.com"
NEXTAUTH_SECRET="<generate_with_openssl_rand_base64_32>"

# OAuth (Google only — no Email provider configured)
GOOGLE_CLIENT_ID="<google_oauth_client_id>"
GOOGLE_CLIENT_SECRET="<google_oauth_client_secret>"

# Stream proxy pulls the LOCAL relay (1-to-many). Never point this at the
# backend directly — every listener would open their own upstream connection.
SUBWAVE_STREAM_URL="http://127.0.0.1:8000/stream.mp3"

# Subwave Backend Routing (API calls: requests, skip/block, server sync)
# Must use the IPv6 tunnel address for direct Proxmox access
SUBWAVE_API_URL="http://[2404:e80:bef:0:be24:11ff:fe6c:b839]:7700/api"

# Web Push (admin alerts; generated once via `npx web-push generate-vapid-keys`)
VAPID_PUBLIC_KEY="<vapid_public>"
VAPID_PRIVATE_KEY="<vapid_private>"
VAPID_SUBJECT="mailto:<admin_email>"

# Webhooks
BMAC_WEBHOOK_SECRET="<bmac_secret>"

# Spotify API
SPOTIFY_CLIENT_ID="<spotify_client_id>"
SPOTIFY_CLIENT_SECRET="<spotify_client_secret>"
```

## Deployment & Recovery

**File Locations on VPS:**
- App Directory: `/var/www/causewayfm`
- SQLite Database: `/var/www/causewayfm/data/causewayfm.db`
- PM2 Process Name: `causewayfm`

**Deploying (`deploy_causeway_fm_web.sh` at repo root):**
- Aborts when anyone is listening (checked via public now-playing count); `--force`/`-f` overrides. Unreachable backend also aborts unless forced.
- Syncs everything except `node_modules`, `.next`, `data/` and `.env.local` (live secrets file — UI-saved OAuth/admin/Subwave creds must never be clobbered), then `npm install` + `prisma generate` + `prisma db push` + build + `pm2 restart`.
- Schema changes ship as `prisma/migrations/` + `prisma migrate deploy` (run before the code deploy).

**Manual restart (emergencies only):**
```bash
cd /var/www/causewayfm
npm run build
pm2 restart causewayfm
```
Only restart after `ls .next/BUILD_ID` exists — a failed build wipes `.next` and restarting then crash-loops the station.

**Viewing Logs:**
```bash
pm2 logs causewayfm
```

**Common Troubleshooting:**
- **"Upstream Error 403" on Stream:** Check that the `stationPassword` in the Admin Dashboard exactly matches the live station password on the Subwave backend.
- **Prisma Errors / Missing Data:** Ensure the `data/causewayfm.db` SQLite file has read/write permissions for the user running the PM2 process. Run `npx prisma db push` if the schema is out of sync.
- **Stream works in Chrome but not Safari:** Verify that `crossOrigin="anonymous"` is NOT set on the `<audio>` tag, as Safari strictly enforces CORS on proxied media streams, rejecting them.
