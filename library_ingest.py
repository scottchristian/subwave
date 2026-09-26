import os
import glob
import time
import csv
import datetime
import requests
import hashlib
import string
import random
import re
import shutil
from mutagen import File

def cleanup_empty_dirs(source_dir):
    for dirpath, dirnames, filenames in os.walk(source_dir, topdown=False):
        if dirpath == source_dir:
            continue
        if not os.listdir(dirpath):
            try:
                os.rmdir(dirpath)
                print(f"Removed empty directory: {dirpath}")
            except Exception as e:
                print(f"Failed to remove directory {dirpath}: {e}")

def get_subsonic_auth(user, password):
    salt = ''.join(random.choices(string.ascii_letters + string.digits, k=6))
    token = hashlib.md5((password + salt).encode('utf-8')).hexdigest()
    return {
        'u': user,
        't': token,
        's': salt,
        'v': '1.16.1',
        'c': 'SubWave-Ingest',
        'f': 'json'
    }

def clean_filename(name):
    if not name:
        return "Unknown"
    return re.sub(r'[\\/:*?"<>|]', '-', str(name)).strip()

def get_track_id(artist, title, auth_params):
    url = "http://localhost:4533/rest/search3"
    query = f"{artist} {title}" if artist else title
    params = auth_params.copy()
    params['query'] = query
    params['songCount'] = 50
    
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get('subsonic-response', {}).get('status') != 'ok':
            return None
            
        songs = data.get('subsonic-response', {}).get('searchResult3', {}).get('song', [])
        
        artist_lower = str(artist).lower().strip() if artist else None
        title_lower = str(title).lower().strip()
        
        for song in songs:
            s_artist = song.get('artist', '').lower().strip()
            s_title = song.get('title', '').lower().strip()
            if artist_lower:
                if s_artist == artist_lower and s_title == title_lower:
                    return song['id']
            else:
                if s_title == title_lower:
                    return song['id']
    except Exception:
        pass
    return None

def trigger_scan(auth_params):
    print("Triggering Navidrome scan...")
    url = "http://localhost:4533/rest/startScan"
    try:
        requests.get(url, params=auth_params, timeout=10)
        # Give Navidrome a moment to process the newly moved files
        time.sleep(15)
    except Exception as e:
        print(f"Failed to trigger scan: {e}")

def process_m3u(m3u_path, source_dir):
    # Parse m3u and try to find artist/title for each track
    intents = []
    try:
        with open(m3u_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            
        for i, line in enumerate(lines):
            line = line.strip()
            if line and not line.startswith('#'):
                artist = None
                title = None
                
                # 1. Try EXTINF
                if i > 0 and lines[i-1].startswith('#EXTINF:'):
                    extinf = lines[i-1].strip()
                    if ',' in extinf:
                        meta = extinf.split(',', 1)[1]
                        if ' - ' in meta:
                            artist, title = meta.split(' - ', 1)
                        else:
                            title = meta
                            
                # 2. Try reading file tags directly if they exist
                if not artist or not title:
                    # M3U lines are relative to the m3u file location
                    rel_path = line.replace('\\', '/')
                    full_path = os.path.join(os.path.dirname(m3u_path), rel_path)
                    
                    if not os.path.exists(full_path):
                        # Fallback: maybe it's just in the same dir
                        base = os.path.basename(rel_path)
                        full_path = os.path.join(source_dir, base)
                        
                    if os.path.exists(full_path):
                        try:
                            audio = File(full_path, easy=True)
                            if audio:
                                artist = audio.get('artist', [artist])[0]
                                title = audio.get('title', [title])[0]
                        except:
                            pass
                            
                if not artist or not title:
                    # Fallback 3: extract title from filename if all else fails
                    filename = os.path.basename(line)
                    name_no_ext = os.path.splitext(filename)[0]
                    # Strip leading track numbers like '01 - '
                    cleaned_title = re.sub(r'^[0-9]+[\s-]*', '', name_no_ext).strip()
                    if cleaned_title:
                        title = cleaned_title
                        if not artist:
                            artist = None

                if title:
                    intents.append((artist.strip() if artist else None, title.strip()))
                else:
                    print(f"Warning: Could not determine Title for {line} in {m3u_path}")
    except Exception as e:
        print(f"Error reading {m3u_path}: {e}")
        
    return intents

def sync_playlist(playlist_name, intents, auth_params):
    url = "http://localhost:4533/rest"
    
    # Resolve IDs
    target_ids = []
    for artist, title in intents:
        tid = get_track_id(artist, title, auth_params)
        if tid:
            target_ids.append(tid)
        else:
            print(f"Could not find track in Navidrome for playlist: {artist} - {title}")
            
    if not target_ids and not intents:
        print(f"No valid tracks found for playlist {playlist_name}")
        return False
        
    # Get existing playlists
    p_resp = requests.get(f"{url}/getPlaylists", params=auth_params).json()
    playlists = p_resp.get('subsonic-response', {}).get('playlists', {}).get('playlist', [])
    
    playlist_id = None
    for p in playlists:
        if p['name'] == playlist_name:
            playlist_id = p['id']
            break
            
    if not playlist_id:
        print(f"Creating new playlist: {playlist_name}")
        c_resp = requests.get(f"{url}/createPlaylist", params={**auth_params, 'name': playlist_name}).json()
        playlist_id = c_resp.get('subsonic-response', {}).get('playlist', {}).get('id')
        if not playlist_id:
            print("Failed to create playlist")
            return False
            
        for i in range(0, len(target_ids), 50):
            batch = target_ids[i:i+50]
            params = auth_params.copy()
            params['playlistId'] = playlist_id
            params['songIdToAdd'] = batch
            requests.get(f"{url}/updatePlaylist", params=params)
        print(f"Added {len(target_ids)} tracks to new playlist.")
    else:
        print(f"Updating existing playlist via Delta: {playlist_name}")
        pl_resp = requests.get(f"{url}/getPlaylist", params={**auth_params, 'id': playlist_id}).json()
        entries = pl_resp.get('subsonic-response', {}).get('playlist', {}).get('entry', [])
        
        target_set = set(target_ids)
        
        # Remove extras (must remove by index)
        indices_to_remove = []
        for i, e in enumerate(entries):
            if e['id'] not in target_set:
                indices_to_remove.append(i)
                
        if indices_to_remove:
            indices_to_remove.sort(reverse=True)
            for i in range(0, len(indices_to_remove), 50):
                batch = indices_to_remove[i:i+50]
                params = auth_params.copy()
                params['playlistId'] = playlist_id
                params['songIndexToRemove'] = batch
                requests.get(f"{url}/updatePlaylist", params=params)
                
        # Add missing
        existing_set = {e['id'] for e in entries}
        to_add = []
        for tid in target_ids:
            if tid not in existing_set:
                to_add.append(tid)
                existing_set.add(tid) # Prevent duplicates if target_ids has dupes
                
        if to_add:
            for i in range(0, len(to_add), 50):
                batch = to_add[i:i+50]
                params = auth_params.copy()
                params['playlistId'] = playlist_id
                params['songIdToAdd'] = batch
                requests.get(f"{url}/updatePlaylist", params=params)
                
        print(f"Playlist updated: removed {len(indices_to_remove)}, added {len(to_add)}")
    
    is_complete = len(target_ids) == len(intents)
    if not is_complete:
        print(f"Playlist {playlist_name} is incomplete ({len(target_ids)}/{len(intents)} found). M3U will not be deleted.")
        
    return is_complete

def main():
    source_dir = "/VMHOST/General/Music"
    target_dir = "/VMHOST/Media/Music"
    log_file = os.path.join(source_dir, "ingest_log.csv")
    
    if not os.path.exists(source_dir):
        print(f"Source dir {source_dir} does not exist.")
        return
        
    auth_params = get_subsonic_auth("admin", "P@ssword11")
    now = time.time()
    
    # 1. Pre-parse M3U files
    m3u_files = glob.glob(os.path.join(source_dir, "*.m3u"))
    pending_playlists = {}
    for m3u in m3u_files:
        playlist_name = os.path.splitext(os.path.basename(m3u))[0]
        intents = process_m3u(m3u, source_dir)
        if intents:
            pending_playlists[m3u] = (playlist_name, intents)
    
    # 2. Process Audio Files
    extensions = ['**/*.mp3', '**/*.flac', '**/*.m4a']
    audio_files = []
    for ext in extensions:
        audio_files.extend(glob.glob(os.path.join(source_dir, ext), recursive=True))
        
    write_header = not os.path.exists(log_file)
    moved_any = False
    
    with open(log_file, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(['Timestamp', 'Action', 'Source File', 'Target/Match', 'Artist', 'Album', 'Title', 'TrackNumber'])
            
        for filepath in audio_files:
            mtime = os.path.getmtime(filepath)
            if now - mtime < 60:
                print(f"Skipping {filepath}, modified recently")
                continue
                
            try:
                audio = File(filepath, easy=True)
                if audio is None:
                    raise Exception("Mutagen could not read file format")
                
                artist = audio.get('artist', [None])[0]
                album = audio.get('album', [None])[0]
                title = audio.get('title', [None])[0]
                tracknumber = audio.get('tracknumber', [None])[0]
                
                if not artist or not title:
                    raise Exception("Missing Artist or Title in ID3 tags")
            except Exception as e:
                print(f"Error reading tags for {filepath}: {e}")
                writer.writerow([datetime.datetime.now().isoformat(), 'Error (Missing Tags)', os.path.basename(filepath), str(e), '', '', '', ''])
                continue
                
            track_id = get_track_id(artist, title, auth_params)
            if track_id:
                try:
                    os.remove(filepath)
                    print(f"Deleted duplicate: {filepath}")
                    writer.writerow([datetime.datetime.now().isoformat(), 'Deleted (Already in Navidrome)', os.path.basename(filepath), '', artist, album, title, tracknumber])
                except Exception as e:
                    print(f"Failed to delete {filepath}: {e}")
                continue
                
            c_artist = clean_filename(artist)
            c_album = clean_filename(album)
            c_title = clean_filename(title)
            
            ext = os.path.splitext(filepath)[1]
            if tracknumber:
                track_num = str(tracknumber).split('/')[0].zfill(2)
                filename = f"{track_num} - {c_title}{ext}"
            else:
                filename = f"{c_title}{ext}"
                
            target_folder = os.path.join(target_dir, c_artist, c_album)
            target_path = os.path.join(target_folder, filename)
            
            if os.path.exists(target_path):
                try:
                    os.remove(filepath)
                    print(f"Deleted duplicate (Exists on disk): {filepath}")
                    writer.writerow([datetime.datetime.now().isoformat(), 'Deleted (Exists on Disk)', os.path.basename(filepath), target_path, artist, album, title, tracknumber])
                except Exception as e:
                    print(f"Failed to delete {filepath}: {e}")
                continue
                
            try:
                os.makedirs(target_folder, exist_ok=True)
                shutil.move(filepath, target_path)
                moved_any = True
                print(f"Moved {filepath} -> {target_path}")
                writer.writerow([datetime.datetime.now().isoformat(), 'Moved', os.path.basename(filepath), target_path, artist, album, title, tracknumber])
            except Exception as e:
                print(f"Failed to move {filepath}: {e}")
                writer.writerow([datetime.datetime.now().isoformat(), 'Error (Move Failed)', os.path.basename(filepath), str(e), artist, album, title, tracknumber])

    # 3. Trigger Scan if needed
    if pending_playlists or moved_any:
        trigger_scan(auth_params)
        
    # 4. Sync Playlists
    for m3u_path, (playlist_name, intents) in pending_playlists.items():
        mtime = os.path.getmtime(m3u_path)
        if now - mtime < 60:
            print(f"Skipping {m3u_path}, modified recently")
            continue
            
        success = sync_playlist(playlist_name, intents, auth_params)
        if success:
            try:
                os.remove(m3u_path)
                print(f"Deleted {m3u_path} after successful sync")
                with open(log_file, 'a', newline='', encoding='utf-8') as f:
                    csv.writer(f).writerow([datetime.datetime.now().isoformat(), 'Playlist Synced', os.path.basename(m3u_path), playlist_name, '', '', '', ''])
            except Exception as e:
                print(f"Failed to delete {m3u_path}: {e}")

    # 5. Cleanup empty directories
    cleanup_empty_dirs(source_dir)

if __name__ == "__main__":
    main()
