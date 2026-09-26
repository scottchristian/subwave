import sqlite3
import requests
import json
import os
import re
import difflib

def is_fuzzy_match(title1, title2, threshold=0.8):
    if not title1 or not title2:
        return False
    def clean(s): return re.sub(r'[^a-z0-9 ]', '', str(s).lower()).strip()
    c1, c2 = clean(title1), clean(title2)
    if c1 == c2 or c1 in c2 or c2 in c1:
        return True
    return difflib.SequenceMatcher(None, c1, c2).ratio() >= threshold

LIDARR_URL = "http://192.168.68.191:8686"
LIDARR_API_KEY = "3aa1ec1352f841cd9ba28646a901a37d"

# Navidrome (same box): trigger a library scan via the Subsonic API instead of
# restarting the container — a restart risks interrupting a track mid-fetch,
# the scan does not.
NAVIDROME_URL = "http://localhost:4533/rest"
NAVIDROME_USER = "admin"
NAVIDROME_PASS = "P@ssword11"

STATION_URL = "http://localhost:7700/api"
STATION_AUTH = "Midw@y!FM2026"

import hashlib
import random as _random
import string as _string
import time


def _navidrome_auth():
    salt = "".join(_random.choice(_string.ascii_letters) for _ in range(8))
    token = hashlib.md5((NAVIDROME_PASS + salt).encode()).hexdigest()
    return {"u": NAVIDROME_USER, "t": token, "s": salt, "v": "1.16.1", "c": "lidarr-watchdog", "f": "json"}


def trigger_navidrome_scan(timeout_sec=180):
    """Start a Navidrome quick scan and wait until it finishes. Returns True
    when the library is fresh — the re-request must not fire before this, or
    it resolves against a stale index and burns the retry as fulfilled."""
    try:
        requests.get(f"{NAVIDROME_URL}/startScan.view", params=_navidrome_auth(), timeout=15)
    except Exception as e:
        print("Navidrome startScan failed:", e)
        return False
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            r = requests.get(f"{NAVIDROME_URL}/getScanStatus.view", params=_navidrome_auth(), timeout=15).json()
            status = r.get("subsonic-response", {}).get("scanStatus", {})
            if not status.get("scanning", False):
                print("Navidrome scan complete.")
                return True
        except Exception as e:
            print("Navidrome scan poll error:", e)
        time.sleep(5)
    print("Navidrome scan timed out — proceeding anyway.")
    return False



def await_match(request_id, song_name, artist, timeout_sec=120):
    """Poll GET /request/:id until resolved, then confirm the picked track is
    actually ours: artist must fuzzy-match (any request), and a specific song
    title must fuzzy-match too. Returns False on timeout, failure, or filler —
    the row stays open and the next cron minute retries."""
    specific = str(song_name or "").lower() not in ["any", "unknown", ""]
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            r = requests.get(
                f"{STATION_URL}/request/{request_id}",
                headers={"x-station-auth": STATION_AUTH},
                timeout=15,
            )
            if r.status_code != 200:
                time.sleep(5)
                continue
            body = r.json()
            if body.get("status") == "pending":
                time.sleep(5)
                continue
            if not body.get("success") or not body.get("track"):
                print(f"Request {request_id[:8]} ended without a track: {body.get('message')}")
                return False
            track = body["track"]
            if not is_fuzzy_match(artist, track.get("artist", "")):
                print(f"Request {request_id[:8]} matched {track.get('title')} by {track.get('artist')} — not ours.")
                return False
            if specific and not is_fuzzy_match(song_name, track.get("title", "")):
                print(f"Request {request_id[:8]} matched {track.get('title')} — title miss.")
                return False
            print(f"Request {request_id[:8]} matched {track.get('title')} by {track.get('artist')}.")
            return True
        except Exception as e:
            print("Match poll error:", e)
            time.sleep(5)
    print(f"Request {request_id[:8]} still pending after {timeout_sec}s — leaving open.")
    return False


def already_queued(artist, song_name):
    """True when the station's upcoming queue already holds this artist (any
    song) — or this exact song. Stops double rows (e.g. an 'Any' row plus a
    named-song row for the same band) and impatient re-requests from stacking
    the same band twice in a row."""
    try:
        r = requests.get(f"{STATION_URL}/state", timeout=15)
        if r.status_code != 200:
            return False
        upcoming = r.json().get("upcoming", [])
    except Exception as e:
        print("Queue check error:", e)
        return False
    specific = str(song_name or "").lower() not in ["any", "unknown", ""]
    for item in upcoming:
        track = item.get("track", {}) or {}
        if is_fuzzy_match(artist, track.get("artist", "")):
            if not specific or is_fuzzy_match(song_name, track.get("title", "")):
                print(f"Already queued: {track.get('title')} by {track.get('artist')} — skipping re-request.")
                return True
            # Same artist, different song already queued: one band appearance
            # is enough; the extra row is served by what's already coming.
            print(f"Same artist already queued: {track.get('title')} by {track.get('artist')} — skipping re-request.")
            return True
    return False


def main():
    conn = sqlite3.connect("/root/subwave/state/missed_requests.db")
    c = conn.cursor()
    c.execute("SELECT id, song_name, artist, ip, requester, lidarr_album_id FROM missed_requests WHERE sent_to_lidarr = 1 AND fulfilled = 0 AND lidarr_album_id IS NOT NULL")
    rows = c.fetchall()

    if not rows:
        return

    for row in rows:
        req_id, song_name, artist, req_ip, requester, album_id = row
        print(f"Checking {song_name} by {artist} (Album {album_id})")

        try:
            is_artist_req = album_id.startswith("ARTIST:")
            
            if is_artist_req:
                actual_artist_id = album_id.split(":")[1]
                resp = requests.get(f"{LIDARR_URL}/api/v1/track?artistId={actual_artist_id}", headers={"X-Api-Key": LIDARR_API_KEY})
            else:
                resp = requests.get(f"{LIDARR_URL}/api/v1/track?albumId={album_id}", headers={"X-Api-Key": LIDARR_API_KEY})
                
            if resp.status_code != 200:
                continue
                
            tracks = resp.json()
            downloaded = False
            for t in tracks:
                t_title = t.get("title", "")
                
                # If they requested a generic band (Any song), grab the first downloaded one
                if str(song_name).lower() in ["any", "unknown", ""]:
                    if t.get("hasFile", False):
                        song_name = t_title
                        downloaded = True
                        break
                # Otherwise, it's a specific song request, so we MUST match the title
                elif is_fuzzy_match(song_name, t_title):
                    if t.get("hasFile", False):
                        song_name = t_title
                        downloaded = True
                        break
            
            if not downloaded:
                continue
        except Exception as e:
            print("Lidarr check error:", e)
            continue

        # Coalesce: another row (or an impatient re-request) may already have
        # queued this artist. One band appearance per download wave — mark this
        # row served instead of stacking the queue.
        if already_queued(artist, song_name):
            c.execute("UPDATE missed_requests SET fulfilled = 1 WHERE id = ?", (req_id,))
            conn.commit()
            continue

        print(f"File downloaded for {song_name}! Triggering scan...")
        trigger_navidrome_scan()

        print(f"Submitting request for {song_name} by {artist} to the station...")

        display_name = requester if (requester and requester.lower() != 'anon') else 'Someone'
        request_text = f"{display_name} asked for this song before, so we sent someone out to go and get it, and now we do, so this one goes out to you {display_name}. Please play {song_name} by {artist}"

        queue_resp = requests.post(
            f"{STATION_URL}/request",
            headers={"Content-Type": "application/json", "X-Forwarded-For": req_ip or "127.0.0.1", "x-station-auth": STATION_AUTH},
            json={
                "text": request_text,
                "name": requester
            }
        )
        print("Queue response:", queue_resp.status_code, queue_resp.text)

        if queue_resp.status_code == 429:
            print("Rate limited or queued. Will try again next minute.")
            continue # Do not mark fulfilled so we can retry!

        # Verify the station actually matched OUR song before marking fulfilled.
        # A re-request that resolves to filler (artistMiss) must stay open so
        # the next minute retries — otherwise the download never airs.
        try:
            req_id = queue_resp.json().get("requestId")
        except Exception:
            req_id = None
        if req_id and await_match(req_id, song_name, artist):
            c.execute("UPDATE missed_requests SET fulfilled = 1 WHERE id = ?", (req_id,))
            conn.commit()
        elif req_id:
            print(f"Station did not match {song_name} by {artist} yet — leaving open for retry.")

if __name__ == "__main__":
    main()
