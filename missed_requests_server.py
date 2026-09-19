#!/usr/bin/env python3
import json
import sys
import os
import urllib.request
import urllib.parse
import re
import sqlite3

LOG_FILE = "/root/subwave/state/logs/requests.log"
DB_FILE = "/root/subwave/state/missed_requests.db"

def get_itunes_metadata(query):
    # Check if the user is asking for an artist rather than a specific song
    artist_match = re.search(r'(?i)\b(?:some|anything by|something by|the band)\s+(.+)', query)
    
    if artist_match:
        # Extract just the artist name
        artist_query = re.sub(r'(?i)\b(i want to hear|play|the song|track)\b', '', artist_match.group(1)).strip()
        
        if artist_query:
            # 1. Search for the artist
            artist_url = f"https://itunes.apple.com/search?term={urllib.parse.quote(artist_query)}&entity=musicArtist&limit=1"
            try:
                req = urllib.request.Request(artist_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=3) as response:
                    data = json.loads(response.read().decode())
                    if data.get("results"):
                        artist_id = data["results"][0].get("artistId")
                        # Return a generic 'Any' track request for this artist
                        return {
                            "song_name": "Any",
                            "artist": data["results"][0].get("artistName"),
                            "album": "Any"
                        }
            except Exception as e:
                print(f"Artist lookup error for '{query}': {e}")

    # Fallback to standard song lookup
    clean_query = re.sub(r'(?i)\b(i want to hear|play|something by|anything by|some|the song|track)\b', '', query).strip()
    if not clean_query:
        return None
        
    url = f"https://itunes.apple.com/search?term={urllib.parse.quote(clean_query)}&entity=song&limit=1"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3) as response:
            data = json.loads(response.read().decode())
            if data.get("results"):
                res = data["results"][0]
                return {
                    "song_name": res.get("trackName"),
                    "artist": res.get("artistName"),
                    "album": res.get("collectionName")
                }
    except Exception:
        pass
    return None

def get_gemini_extraction(query, api_key, base_url="https://generativelanguage.googleapis.com"):
    # Strip any trailing slashes from base_url to ensure the path constructs correctly
    base_url = base_url.rstrip("/")
    url = f"{base_url}/v1beta/models/gemini-3.6-flash:generateContent?key={api_key}"
    
    prompt = f"""Extract the requested song and artist from the following conversational text.
If it is obviously an ad or not a real song request, return exactly the string "null".
If the user requests an artist or band in general but does not name a specific song, set "song" to "Any".
Important context: If the user says "play another live song" or "some live", they likely mean the rock band named "Live", not a live concert recording.
Text: "{query}"
Return ONLY a JSON object exactly like this: {{"song": "Song Name", "artist": "Artist Name"}} or the string "null"."""
    
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1}
    }
    
    try:
        # Pass the key in both query parameter and Authorization header for compatibility
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}'
        }
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            text = data['candidates'][0]['content']['parts'][0]['text']
            
            # Clean up markdown block if present
            text = text.strip()
            if text == "null":
                return None
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
                
            result = json.loads(text.strip())
            if result and isinstance(result, dict) and "song" in result and "artist" in result:
                return f"{result['song']} by {result['artist']}"
    except Exception as e:
        print(f"Gemini API Error: {e}")
    return None

def main():
    if not os.path.exists(LOG_FILE):
        print(f"Log file not found: {LOG_FILE}")
        return

    gemini_key = None
    gemini_base_url = "https://generativelanguage.googleapis.com"
    if os.path.exists("/root/subwave/.env"):
        with open("/root/subwave/.env", "r") as env_f:
            for eline in env_f:
                if eline.startswith("GEMINI_API_KEY="):
                    gemini_key = eline.strip().split("=", 1)[1]
                elif eline.startswith("GEMINI_BASE_URL="):
                    gemini_base_url = eline.strip().split("=", 1)[1]

    # Initialize SQLite database
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Unique constraint originally was (song_name, artist) which is too restrictive for unknowns.
    # We rely on datetime_requested being unique in memory checking now.
    c.execute('''
        CREATE TABLE IF NOT EXISTS missed_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            song_name TEXT,
            artist TEXT,
            album TEXT,
            datetime_requested TEXT,
            sent_to_lidarr BOOLEAN DEFAULT 0,
            raw_request_text TEXT,
            itunes_searched BOOLEAN DEFAULT 0,
            llm_searched BOOLEAN DEFAULT 0,
            ip TEXT,
            requester TEXT,
            lidarr_album_id TEXT,
            fulfilled BOOLEAN DEFAULT 0
        )
    ''')
    conn.commit()

    print("========================================")
    print("      MISSED / UNFULFILLED REQUESTS     ")
    print("========================================")
    
    # Phase 1: Parse logs & ingest raw requests
    negatives = ["couldn't find", "don't have", "no ", "out of luck", "bare", "didn't have", "none of"]
    
    c.execute("SELECT datetime_requested FROM missed_requests")
    existing_timestamps = {row[0] for row in c.fetchall()}

    ingested_count = 0
    with open(LOG_FILE, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
                time_str = req.get("t", "Unknown Time")
                if time_str in existing_timestamps:
                    continue # Skip already processed requests
                
                req_text = req.get("text", "")
                ack = (req.get("ack") or "").lower()
                played_artist = (req.get("track") or {}).get("artist", "").lower()
                
                req_ip = req.get("ip")
                req_name = req.get("requester")
                
                is_failed = req.get("status") == "failed"
                artist_miss = req.get("artistMiss")
                
                is_conversational_miss = False
                if req.get("status") == "resolved" and not artist_miss:
                    if any(n in ack for n in negatives) and played_artist and not any(part in req_text.lower() for part in played_artist.split()):
                        is_conversational_miss = True

                if is_failed or artist_miss or is_conversational_miss:
                    artist_to_save = artist_miss if artist_miss else "Unknown"
                    c.execute('''
                        INSERT OR IGNORE INTO missed_requests 
                        (song_name, artist, album, datetime_requested, sent_to_lidarr, raw_request_text, itunes_searched, llm_searched, ip, requester)
                        VALUES (?, ?, ?, ?, 0, ?, 0, 0, ?, ?)
                    ''', (req_text, artist_to_save, "Unknown", time_str, req_text, req_ip, req_name))
                    existing_timestamps.add(time_str)
                    ingested_count += 1
            except json.JSONDecodeError:
                pass
    
    conn.commit()
    if ingested_count > 0:
        print(f"Phase 1: Ingested {ingested_count} new missed requests.")
    
    # Phase 2: iTunes lookup
    c.execute("SELECT id, raw_request_text, artist FROM missed_requests WHERE itunes_searched = 0")
    itunes_pending = c.fetchall()
    
    if itunes_pending:
        print(f"Phase 2: Running iTunes lookup on {len(itunes_pending)} requests.")
    
    for rowid, req_text, artist_miss in itunes_pending:
        metadata = get_itunes_metadata(req_text)
        if metadata:
            try:
                c.execute('''
                    UPDATE missed_requests 
                    SET song_name = ?, artist = ?, album = ?, itunes_searched = 1
                    WHERE id = ?
                ''', (metadata['song_name'], metadata['artist'], metadata['album'], rowid))
                print(f"iTunes Match: {metadata['song_name']} by {metadata['artist']} (Album: {metadata['album']})")
            except sqlite3.IntegrityError:
                # This song is already in the DB from a previous request. Just delete this duplicate row.
                c.execute("DELETE FROM missed_requests WHERE id = ?", (rowid,))
        else:
            c.execute("UPDATE missed_requests SET itunes_searched = 1 WHERE id = ?", (rowid,))
    
    conn.commit()
    
    # Phase 3: LLM cleanup
    if gemini_key:
        c.execute("SELECT id, raw_request_text FROM missed_requests WHERE itunes_searched = 1 AND llm_searched = 0 AND album = 'Unknown'")
        llm_pending = c.fetchall()
        
        if llm_pending:
            print(f"Phase 3: Running Gemini cleanup on {len(llm_pending)} stubborn requests.")
            
        for rowid, req_text in llm_pending:
            print(f"Asking Gemini about: {req_text}")
            cleaned_query = get_gemini_extraction(req_text, gemini_key, gemini_base_url)
            if cleaned_query:
                print(f"Gemini extracted: {cleaned_query}")
                metadata = get_itunes_metadata(cleaned_query)
                if metadata:
                    try:
                        c.execute('''
                            UPDATE missed_requests 
                            SET song_name = ?, artist = ?, album = ?, llm_searched = 1
                            WHERE id = ?
                        ''', (metadata['song_name'], metadata['artist'], metadata['album'], rowid))
                        print(f"iTunes Match (Post-LLM): {metadata['song_name']} by {metadata['artist']} (Album: {metadata['album']})")
                    except sqlite3.IntegrityError:
                        c.execute("DELETE FROM missed_requests WHERE id = ?", (rowid,))
                    continue
            
            c.execute("UPDATE missed_requests SET llm_searched = 1 WHERE id = ?", (rowid,))
            
        conn.commit()
        
    print("========================================")

if __name__ == "__main__":
    main()
