import sqlite3
import requests
import json
import os
import re

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
                if is_artist_req:
                    if t.get("hasFile", False):
                        song_name = t.get("title", "Unknown Track")
                        downloaded = True
                        break
                else:
                    t_title = t.get("title", "").lower()
                    if song_name.lower() in t_title or t_title in song_name.lower():
                        if t.get("hasFile", False):
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
