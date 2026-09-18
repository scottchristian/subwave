import spotipy
from spotipy.oauth2 import SpotifyOAuth
import sqlite3
import getpass
import sys
import os

# Override Spotipy's local server behavior to force manual URL pasting
class ManualSpotifyOAuth(SpotifyOAuth):
    def _get_auth_response_local_server(self, redirect_port):
        # Fall back to the manual prompt
        return self._get_auth_response_interactive(open_browser=True)

def main():
    print("=== Spotify Playlist Extractor (External HTTPS Callback) ===")
    print("Please provide your Spotify API credentials:")
    client_id = input("Client ID: ").strip()
    client_secret = getpass.getpass("Client Secret: ").strip()
    
    if not client_id or not client_secret:
        print("Error: Client ID and Secret are required!")
        sys.exit(1)
        
    print("\nAuthenticating with Spotify...")
    # Using an external HTTPS URL entirely bypasses Spotify's localhost blocking!
    redirect_uri = "https://google.com/callback"
    
    sp = spotipy.Spotify(auth_manager=ManualSpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope="playlist-read-private playlist-read-collaborative user-library-read"
    ))
    
    db_path = "spotify_library.db"
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS tracks (
            id TEXT PRIMARY KEY,
            title TEXT,
            artist TEXT,
            album TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS playlists (
            id TEXT PRIMARY KEY,
            name TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS playlist_tracks (
            playlist_id TEXT,
            track_id TEXT,
            UNIQUE(playlist_id, track_id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS liked_tracks (
            track_id TEXT PRIMARY KEY
        )
    ''')
    
    print("\nFetching playlists...")
    playlists = sp.current_user_playlists()
    
    track_count = 0
    artist_count = set()
    
    while playlists:
        for i, playlist in enumerate(playlists['items']):
            print(f"Processing playlist: {playlist['name']}")
            
            # Fetch tracks for this playlist
            try:
                c.execute('''
                    INSERT OR IGNORE INTO playlists (id, name)
                    VALUES (?, ?)
                ''', (playlist['id'], playlist['name']))
                
                results = sp.playlist_tracks(playlist['id'])
                tracks = results['items']
                while results['next']:
                    results = sp.next(results)
                    tracks.extend(results['items'])
                    
                if not tracks:
                    print(f"  -> Playlist '{playlist['name']}' returned 0 tracks from Spotify API.")
                    
                inserted_count = 0
                for item in tracks:
                    track = item.get('track') or item.get('item')
                    if not track:
                        if inserted_count == 0:
                            print(f"  -> DEBUG: missing track key! item keys: {list(item.keys())}")
                        continue
                    track_id = track.get('id')
                    title = track.get('name', 'Unknown')
                    
                    if 'instrumental' in title.lower():
                        continue
                    
                    if not track_id:
                        # For local files, generate a deterministic fallback ID
                        import hashlib
                        artist_str = ", ".join([a['name'] for a in track.get('artists', [])])
                        fallback_str = f"{title}_{artist_str}"
                        track_id = "local_" + hashlib.md5(fallback_str.encode()).hexdigest()
                        
                    album = track.get('album', {}).get('name', 'Unknown Album')
                    # Join multiple artists
                    artists = ", ".join([a.get('name', 'Unknown') for a in track.get('artists', [])])
                    
                    c.execute('''
                        INSERT OR IGNORE INTO tracks (id, title, artist, album)
                        VALUES (?, ?, ?, ?)
                    ''', (track_id, title, artists, album))
                    
                    c.execute('''
                        INSERT OR IGNORE INTO playlist_tracks (playlist_id, track_id)
                        VALUES (?, ?)
                    ''', (playlist['id'], track_id))
                    
                    inserted_count += 1
                    track_count += 1
                    for a in track['artists']:
                        artist_count.add(a['name'])
                        
                if inserted_count > 0:
                    print(f"  -> Extracted {inserted_count} tracks.")
                    # Force commit per playlist so we don't lose data
                    conn.commit()
            except spotipy.exceptions.SpotifyException as e:
                print(f"  -> Skipping playlist due to error: {e}")
                    
        if playlists['next']:
            playlists = sp.next(playlists)
        else:
            playlists = None
            
    # Also fetch saved tracks (Liked Songs)
    print("Processing Liked Songs...")
    results = sp.current_user_saved_tracks()
    while results:
        for item in results['items']:
            track = item['track']
            if not track or not track.get('id'):
                continue
                
            track_id = track['id']
            title = track['name']
            
            if 'instrumental' in title.lower():
                continue
                
            album = track['album']['name']
            artists = ", ".join([a['name'] for a in track['artists']])
            
            c.execute('''
                INSERT OR IGNORE INTO tracks (id, title, artist, album)
                VALUES (?, ?, ?, ?)
            ''', (track_id, title, artists, album))
            
            c.execute('''
                INSERT OR IGNORE INTO liked_tracks (track_id)
                VALUES (?)
            ''', (track_id,))
            
            track_count += 1
            for a in track['artists']:
                artist_count.add(a['name'])
                
        if results['next']:
            results = sp.next(results)
        else:
            break

    conn.commit()
    conn.close()
    
    print(f"\nDone! Extracted {track_count} tracks across {len(artist_count)} distinct artists.")
    print(f"Data saved to {os.path.abspath(db_path)}")

if __name__ == "__main__":
    main()
