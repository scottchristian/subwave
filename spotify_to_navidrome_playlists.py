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
        'c': 'Spotify-Sync',
        'f': 'json'
    }

def normalize_string(s):
    if not s:
        return ""
    # Lowercase and remove all non-alphanumeric characters for fuzzy matching
    s = s.lower()
    return re.sub(r'[^a-z0-9]', '', s)

def main():
    print("=== Navidrome Playlist Sync ===")
    
    spotify_db_path = "/root/subwave/spotify_library.db"
    if not os.path.exists(spotify_db_path):
        print(f"Error: Database not found at {spotify_db_path}")
        sys.exit(1)

    # 1. Load Spotify Playlists and Tracks
    print("Loading Spotify playlists from database...")
    playlists = {}
    try:
        conn = sqlite3.connect(spotify_db_path)
        c = conn.cursor()
        
        c.execute("SELECT id, name FROM playlists")
        for row in c.fetchall():
            playlists[row[0]] = {
                'name': row[1],
                'tracks': []
            }
            
        c.execute('''
            SELECT pt.playlist_id, t.title, t.artist 
            FROM playlist_tracks pt
            JOIN tracks t ON pt.track_id = t.id
        ''')
        for row in c.fetchall():
            pid, title, artist = row
            if 'instrumental' in title.lower():
                continue
            if pid in playlists:
                playlists[pid]['tracks'].append({
                    'title': title,
                    'artist': artist,
                    'norm_title': normalize_string(title),
                    'norm_artist': normalize_string(artist.split(',')[0]) # Use first artist
                })
        conn.close()
    except Exception as e:
        print(f"Database error: {e}")
        sys.exit(1)

    print(f"Loaded {len(playlists)} playlists from Spotify.")

    # 2. Get Navidrome Credentials
    url = "http://localhost:4533/rest"
    user = "admin"
    password = "P@ssword11"
    auth_params = get_subsonic_auth(user, password)
    
    # 3. Fetch all tracks from Navidrome
    print("\nFetching tracks from Navidrome... (this may take a minute)")
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
            
    # Build a lookup table for Navidrome tracks
    navidrome_tracks = {}
    
    for i, artist in enumerate(navidrome_artists):
        if i > 0 and i % 50 == 0:
            print(f"Processed {i}/{len(navidrome_artists)} artists...")
            
        artist_id = artist['id']
        artist_name = artist['name']
        norm_artist = normalize_string(artist_name)
        
        a_resp = requests.get(f"{url}/getArtist", params={**auth_params, 'id': artist_id}).json()
        albums = a_resp.get('subsonic-response', {}).get('artist', {}).get('album', [])
        
        for album in albums:
            al_resp = requests.get(f"{url}/getAlbum", params={**auth_params, 'id': album['id']}).json()
            songs = al_resp.get('subsonic-response', {}).get('album', {}).get('song', [])
            
            for song in songs:
                title = song.get('title', '')
                # Strip remix stuff to find the base song
                base_title = re.split(r'(?i)\s*[\(\[-].*remix', title)[0].strip()
                base_title = re.sub(r'(?i)\s+remix\s*', '', base_title).strip()
                
                norm_title = normalize_string(base_title)
                
                # Create a match key: norm_artist + norm_title
                match_key = f"{norm_artist}::{norm_title}"
                
                # If multiple exist (e.g. albums vs singles), just keep the first one
                if match_key not in navidrome_tracks:
                    navidrome_tracks[match_key] = song['id']

    print(f"Indexed {len(navidrome_tracks)} unique track signatures in Navidrome.")

    # 4. Sync Playlists
    print("\nSyncing playlists to Navidrome...")
    
    # Get existing playlists to overwrite
    p_resp = requests.get(f"{url}/getPlaylists", params=auth_params).json()
    existing_playlists = p_resp.get('subsonic-response', {}).get('playlists', {}).get('playlist', [])
    existing_map = {p['name']: p['id'] for p in existing_playlists}
    
    for pid, playlist in playlists.items():
        name = playlist['name']
        tracks = playlist['tracks']
        
        if not tracks:
            continue
            
        print(f"\nProcessing playlist: {name} ({len(tracks)} tracks)")
        
        matched_ids = []
        for t in tracks:
            match_key = f"{t['norm_artist']}::{t['norm_title']}"
            if match_key in navidrome_tracks:
                matched_ids.append(navidrome_tracks[match_key])
                
        print(f" -> Matched {len(matched_ids)} out of {len(tracks)} tracks locally.")
        
        if not matched_ids:
            print(" -> Skipping empty playlist.")
            continue
            
        # Empty if exists, otherwise create
        if name in existing_map:
            print(" -> Emptying existing Navidrome playlist to preserve ID...")
            new_id = existing_map[name]
            pl_resp = requests.get(f"{url}/getPlaylist", params={**auth_params, 'id': new_id}).json()
            entries = pl_resp.get('subsonic-response', {}).get('playlist', {}).get('entry', [])
            
            if entries:
                indices = list(range(len(entries)-1, -1, -1))
                for i in range(0, len(indices), 50):
                    batch = indices[i:i+50]
                    update_params = auth_params.copy()
                    update_params['playlistId'] = new_id
                    update_params['songIndexToRemove'] = batch
                    requests.get(f"{url}/updatePlaylist", params=update_params)
        else:
            c_resp = requests.get(f"{url}/createPlaylist", params={**auth_params, 'name': name}).json()
            new_id = c_resp.get('subsonic-response', {}).get('playlist', {}).get('id')
            
            if not new_id:
                print(" -> Failed to create playlist!")
                continue
            
        # Add tracks in batches of 50
        batch_size = 50
        for i in range(0, len(matched_ids), batch_size):
            batch = matched_ids[i:i+batch_size]
            update_params = auth_params.copy()
            update_params['playlistId'] = new_id
            update_params['songIdToAdd'] = batch
            
            u_resp = requests.get(f"{url}/updatePlaylist", params=update_params).json()
            if u_resp.get('subsonic-response', {}).get('status') != 'ok':
                print(f" -> Warning: Failed to add batch {i} to playlist.")
                
        print(" -> Done!")

if __name__ == "__main__":
    main()
