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

def trigger_navidrome_scan():
    os.system("docker restart sub-wave-navidrome")



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

        print(f"File downloaded for {song_name}! Triggering scan...")
        trigger_navidrome_scan()

        print(f"Submitting request for {song_name} by {artist} to the station...")
        
        display_name = requester if (requester and requester.lower() != 'anon') else 'Someone'
        request_text = f"{display_name} asked for this song before, so we sent someone out to go and get it, and now we do, so this one goes out to you {display_name}. Please play {song_name} by {artist}"

        queue_resp = requests.post(
            "http://localhost:7700/api/request",
            headers={"Content-Type": "application/json", "X-Forwarded-For": req_ip or "127.0.0.1", "x-station-auth": "Midw@y!FM2026"},
            json={
                "text": request_text,
                "name": requester
            }
        )
        print("Queue response:", queue_resp.status_code, queue_resp.text)
        
        if queue_resp.status_code == 429:
            print("Rate limited or queued. Will try again next minute.")
            continue # Do not mark fulfilled so we can retry!

        c.execute("UPDATE missed_requests SET fulfilled = 1 WHERE id = ?", (req_id,))
        conn.commit()

if __name__ == "__main__":
    main()
