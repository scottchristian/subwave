import sqlite3
import requests
import hashlib
import string
import random
import sys
import os
import re

def get_subsonic_auth(user, password):
    salt = ''.join(random.choices(string.ascii_letters + string.digits, k=6))
    token = hashlib.md5((password + salt).encode('utf-8')).hexdigest()
    return {
        'u': user,
        't': token,
        's': salt,
        'v': '1.16.1',
        'c': 'SubWave-Blocklist',
        'f': 'json'
    }

def main():
    print("=== Navidrome Blocklist Generator ===")
    
    # 1. Load Spotify Artists
    spotify_db_path = "/root/subwave/spotify_library.db"
    liked_artists = set()
    try:
        conn = sqlite3.connect(spotify_db_path)
        c = conn.cursor()
        c.execute('''
            SELECT DISTINCT t.artist 
            FROM tracks t
            JOIN liked_tracks lt ON t.id = lt.track_id
        ''')
        for row in c.fetchall():
            if row[0]:
                for a in row[0].split(','):
                    cleaned = a.strip().lower()
                    if cleaned:
                        liked_artists.add(cleaned)
        conn.close()
        print(f"Loaded {len(liked_artists)} distinct normalized artists from Spotify.")
    except Exception as e:
        print(f"Failed to read {spotify_db_path}: {e}")
        if "no such table: liked_tracks" in str(e):
            print("\nCRITICAL: The 'liked_tracks' table is missing from your spotify_library.db!")
            print("Please pull the latest spotify_extract.py from your workspace and re-run it locally,")
            print("then scp the new spotify_library.db to the server before running this filter script again.")
        sys.exit(1)

    # 1.5 Load Missed Requests Whitelist
    missed_requests_db = "/root/subwave/state/missed_requests.db"
    whitelisted_requests = set()
    if os.path.exists(missed_requests_db):
        try:
            conn = sqlite3.connect(missed_requests_db)
            c = conn.cursor()
            c.execute("SELECT artist, song_name, album FROM missed_requests")
            for row in c.fetchall():
                art = row[0].strip().lower()
                song = row[1].strip().lower()
                alb = row[2].strip().lower() if row[2] else 'unknown'
                whitelisted_requests.add((art, song, alb))
            conn.close()
            print(f"Loaded {len(whitelisted_requests)} whitelisted requests.")
        except Exception as e:
            print(f"Failed to read missed requests: {e}")

    def is_whitelisted(artist_name, album_name, song_title):
        art_lower = artist_name.lower().strip()
        alb_lower = album_name.lower().strip()
        song_lower = song_title.lower().strip()
        for req_art, req_song, req_alb in whitelisted_requests:
            if (req_art in art_lower or art_lower in req_art):
                if req_alb != 'unknown' and (req_alb in alb_lower or alb_lower in req_alb):
                    return True
                if (req_song in song_lower or song_lower in req_song):
                    return True
        return False
        
    # 2. Get Navidrome Credentials
    url = "http://localhost:4533/rest"
    user = "admin"
    password = "P@ssword11"
    auth_params = get_subsonic_auth(user, password)
    
    # 3. Fetch all artists from Navidrome
    print("\nConnecting to Navidrome to fetch artists...")
    resp = requests.get(f"{url}/getArtists", params=auth_params)
    if resp.status_code != 200:
        print(f"HTTP Error connecting to Navidrome: {resp.status_code}")
        sys.exit(1)
        
    data = resp.json().get('subsonic-response', {})
    if data.get('status') == 'failed':
        print(f"Auth failed: {data.get('error', {}).get('message')}")
        sys.exit(1)
        
    navidrome_artists = []
    indexes = data.get('artists', {}).get('index', [])
    for index in indexes:
        for artist in index.get('artist', []):
            navidrome_artists.append(artist)
            
    print(f"Found {len(navidrome_artists)} artists in Navidrome.")
    
    # We will gather all tracks first for global remix deduplication
    print("\nFetching tracks for all artists to build library state... (this may take a few minutes)")
    all_tracks = []
    bad_words = ["interlude", "intro", "skit", "instrumental"]
    
    for i, artist in enumerate(navidrome_artists):
        if i % 10 == 0:
            print(f"Processing artist {i}/{len(navidrome_artists)}...")
            
        artist_id = artist['id']
        artist_name = artist['name']
        artist_lower = artist_name.lower().strip()
        is_blocked_artist = artist_lower not in liked_artists
        
        a_resp = requests.get(f"{url}/getArtist", params={**auth_params, 'id': artist_id}).json()
        albums = a_resp.get('subsonic-response', {}).get('artist', {}).get('album', [])
        
        for album in albums:
            al_resp = requests.get(f"{url}/getAlbum", params={**auth_params, 'id': album['id']}).json()
            songs = al_resp.get('subsonic-response', {}).get('album', {}).get('song', [])
            
            album_name = album.get('name', album.get('title', ''))
            
            for song in songs:
                title_lower = song.get('title', '').lower()
                
                song['artist_name'] = artist_name
                song['album_name'] = album_name
                song['album_whitelisted'] = is_whitelisted(artist_name, album_name, title_lower)
                song['is_blocked_artist'] = is_blocked_artist
                
                song['is_bad_song'] = any(w in title_lower for w in bad_words)
                
                # Deduplication properties
                song['is_remix'] = "remix" in title_lower
                # Strip out everything after the start of a remix tag (e.g. "(Another Artist Remix)")
                base_title = re.split(r'(?i)\s*[\(\[-].*remix', title_lower)[0].strip()
                # Fallback if it's just "remix" without brackets
                base_title = re.sub(r'(?i)\s+remix\s*', '', base_title).strip()
                song['base_title'] = base_title
                
                all_tracks.append(song)
                
    # Phase 2: Group by base_title to find remixes globally
    from collections import defaultdict
    songs_by_base_title = defaultdict(list)
    for track in all_tracks:
        songs_by_base_title[track['base_title']].append(track)
        
    global_remixes_to_block = set()
    for base_title, tracks in songs_by_base_title.items():
        if len(tracks) > 1:
            # Check if there is an "original" (non-remix) version of this song
            has_original = any(not t['is_remix'] for t in tracks)
            if has_original:
                for t in tracks:
                    if t['is_remix']:
                        global_remixes_to_block.add(t['id'])
                        
    # Phase 3: Build the final blocklist
    tracks_to_block = []
    for track in all_tracks:
        if track['album_whitelisted']:
            continue # Never block whitelisted albums
            
        block_it = False
        if track['is_blocked_artist']:
            block_it = True
        elif track['is_bad_song']:
            block_it = True
        elif track['id'] in global_remixes_to_block:
            block_it = True
            
        if block_it:
            tracks_to_block.append(track['id'])

    print(f"\nTotal library tracks: {len(all_tracks)}")
    print(f"Identified {len(tracks_to_block)} tracks to BLOCK.")
    
    if len(tracks_to_block) == 0:
        print("No tracks found to block.")
        sys.exit(0)
        
    # Create or update playlist
    playlist_name = "Causeway-Blocked"
    print(f"\nCreating/updating playlist: {playlist_name}")
    
    p_resp = requests.get(f"{url}/getPlaylists", params=auth_params).json()
    playlists = p_resp.get('subsonic-response', {}).get('playlists', {}).get('playlist', [])
    
    playlist_id = None
    for p in playlists:
        if p['name'] == playlist_name:
            playlist_id = p['id']
            break
            
    if playlist_id:
        print(" -> Emptying existing playlist to preserve its ID...")
        pl_resp = requests.get(f"{url}/getPlaylist", params={**auth_params, 'id': playlist_id}).json()
        entries = pl_resp.get('subsonic-response', {}).get('playlist', {}).get('entry', [])
        
        if entries:
            indices = list(range(len(entries)-1, -1, -1))
            for i in range(0, len(indices), 50):
                batch = indices[i:i+50]
                update_params = auth_params.copy()
                update_params['playlistId'] = playlist_id
                update_params['songIndexToRemove'] = batch
                requests.get(f"{url}/updatePlaylist", params=update_params)
    else:
        c_resp = requests.get(f"{url}/createPlaylist", params={**auth_params, 'name': playlist_name}).json()
        playlist_id = c_resp.get('subsonic-response', {}).get('playlist', {}).get('id')
        
        if not playlist_id:
            print("Failed to create playlist!")
            sys.exit(1)
        
    batch_size = 50
    for i in range(0, len(tracks_to_block), batch_size):
        batch = tracks_to_block[i:i+batch_size]
        update_params = auth_params.copy()
        update_params['playlistId'] = playlist_id
        update_params['songIdToAdd'] = batch
        
        u_resp = requests.get(f"{url}/updatePlaylist", params=update_params).json()
        if u_resp.get('subsonic-response', {}).get('status') != 'ok':
            print(f"Warning: Failed to add batch {i} to playlist.")
            
    print(f"\nDone! Playlist '{playlist_name}' has been created with {len(tracks_to_block)} tracks.")

if __name__ == "__main__":
    main()
