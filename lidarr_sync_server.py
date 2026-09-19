import sqlite3
import requests
import argparse
import sys
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def title_match(a, b):
    """Fuzzy title match: checks if one is contained in the other after lowercasing and stripping punctuation."""
    import re
    def clean(s): return re.sub(r'[^a-z0-9 ]', '', s.lower()).strip()
    ca, cb = clean(a), clean(b)
    return ca == cb or ca in cb or cb in ca


def get_artist_id(api_url, api_key, artist_name):
    """Search for an artist and return their ID. If not found, return None."""
    endpoint = f"{api_url}/api/v1/artist"
    params = {'name': artist_name}
    headers = {'X-Api-Key': api_key}

    try:
        response = requests.get(endpoint, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()

        # Search for an exact match in the results
        for artist in data:
            if artist.get('artistName', '').lower() == artist_name.lower():
                return artist.get('id')
    except Exception as e:
        logger.error(f"Error searching for artist {artist_name}: {e}")

    return None

def add_artist(api_url, api_key, artist_name):
    """Add a new artist to Lidarr."""
    endpoint = f"{api_url}/api/v1/artist"
    headers = {'X-Api-Key': api_key, 'Content-Type': 'application/json'}
    
    # Needs a metadata search first to get the foreignArtistId
    search_endpoint = f"{api_url}/api/v1/search"
    search_params = {'term': artist_name}
    try:
        s_resp = requests.get(search_endpoint, params=search_params, headers=headers)
        s_resp.raise_for_status()
        s_data = s_resp.json()
        if not s_data:
            return None
        # Grab the first artist result
        for res in s_data:
            if res.get('artist') and res['artist'].get('artistName', '').lower() == artist_name.lower():
                artist_meta = res['artist']
                artist_meta['monitored'] = True
                artist_meta['qualityProfileId'] = 1
                artist_meta['metadataProfileId'] = 1
                artist_meta['rootFolderPath'] = "/VMHOST/Media/Music"
                artist_meta['addOptions'] = {'searchForMissingAlbums': True}
                
                response = requests.post(endpoint, json=artist_meta, headers=headers)
                response.raise_for_status()
                data = response.json()
                return data.get('id')
    except Exception as e:
        logger.error(f"Error adding artist {artist_name}: {e}")
        return None

def get_album_id(api_url, api_key, artist_id, album_name):
    """Check if an album is already in Lidarr for the given artist (fuzzy title match)."""
    endpoint = f"{api_url}/api/v1/album"
    params = {'artistId': artist_id}
    headers = {'X-Api-Key': api_key}
    try:
        response = requests.get(endpoint, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()
        for album in data:
            if title_match(album.get('title', ''), album_name):
                return album.get('id')
    except Exception as e:
        logger.error(f"Error searching for album {album_name}: {e}")
    return None

def add_album(api_url, api_key, artist_id, album_name):
    """Add an album to a specific artist in Lidarr using foreignAlbumId from search."""
    endpoint = f"{api_url}/api/v1/album"
    headers = {'X-Api-Key': api_key, 'Content-Type': 'application/json'}

    search_endpoint = f"{api_url}/api/v1/search"
    search_params = {'term': album_name}

    try:
        s_resp = requests.get(search_endpoint, params=search_params, headers=headers)
        s_resp.raise_for_status()
        s_data = s_resp.json()
        if not s_data:
            return None

        # Find the best match by fuzzy title, preferring same artist
        best = None
        for res in s_data:
            if not res.get('album'):
                continue
            candidate = res['album']
            if title_match(candidate.get('title', ''), album_name):
                # Prefer same artistId if possible
                if candidate.get('artistId') == artist_id:
                    best = candidate
                    break
                if best is None:
                    best = candidate

        if not best:
            logger.warning(f"No Lidarr search result matched album '{album_name}'")
            return None

        # Lidarr v1 POST /album requires the full album object from the search result,
        # not just the foreignAlbumId. Use the raw result from the search response.
        best_raw = None
        for res in s_data:
            if not res.get('album'):
                continue
            candidate = res['album']
            if title_match(candidate.get('title', ''), album_name):
                if candidate.get('artistId') == artist_id:
                    best_raw = res['album']
                    break
                if best_raw is None:
                    best_raw = res['album']

        if not best_raw:
            return None

        best_raw['monitored'] = True
        best_raw['anyReleaseOk'] = True
        best_raw['addOptions'] = {'searchForNewAlbum': True}

        response = requests.post(endpoint, json=best_raw, headers=headers)
        if response.status_code in (200, 201):
            data = response.json()
            logger.info(f"Successfully added album '{best_raw.get('title')}' for artistId={artist_id}")
            return data.get('id')
        else:
            # 400 often means it already exists — try to fetch it
            logger.warning(f"POST /album returned {response.status_code}: {response.text[:200]}")
            return get_album_id(api_url, api_key, artist_id, album_name)
    except Exception as e:
        logger.error(f"Error adding album {album_name}: {e}")
    return None



def sync_requests(db_path, api_url, api_key):
    """Read pending requests from SQLite and send them to Lidarr."""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT id, song_name, artist, album FROM missed_requests WHERE sent_to_lidarr = 0")
        rows = cursor.fetchall()

        if not rows:
            logger.info("No pending requests found in the database.")
            return

        logger.info(f"Found {len(rows)} pending requests.")

        for row in rows:
            rowid, song_name, artist_name, album_name = row
            logger.info(f"Processing: {song_name} by {artist_name} (Album: {album_name})")

            # Ignore non-songs (e.g. ads or things that didn't match iTunes)
            if album_name == "Unknown":
                logger.info(f"Skipping {song_name} - Not identified as a real song/album (Likely an ad or unresolvable). Marking sent.")
                cursor.execute("UPDATE missed_requests SET sent_to_lidarr = 1 WHERE id = ?", (rowid,))
                conn.commit()
                continue

            if not artist_name:
                logger.warning(f"Row {rowid} missing artist name. Skipping.")
                continue

            # 1. Get or Create Artist
            artist_id = get_artist_id(api_url, api_key, artist_name)
            if not artist_id:
                logger.info(f"Artist {artist_name} not found. Adding...")
                artist_id = add_artist(api_url, api_key, artist_name)

            if not artist_id:
                logger.error(f"Could not resolve Artist ID for {artist_name}. Skipping album and marking as sent.")
                cursor.execute("UPDATE missed_requests SET sent_to_lidarr = 1 WHERE id = ?", (rowid,))
                conn.commit()
                continue

            if album_name == "Any":
                logger.info(f"Generic artist request for {artist_name}. Artist added, marking as sent with ARTIST:{artist_id}.")
                cursor.execute("UPDATE missed_requests SET sent_to_lidarr = 1, lidarr_album_id = ? WHERE id = ?", (f"ARTIST:{artist_id}", rowid,))
                conn.commit()
                continue

            # 2. Check if already queued
            album_id = get_album_id(api_url, api_key, artist_id, album_name)
            if album_id:
                logger.info(f"Album {album_name} is already in Lidarr. Marking as sent.")
                cursor.execute("UPDATE missed_requests SET sent_to_lidarr = 1, lidarr_album_id = ? WHERE id = ?", (album_id, rowid,))
                conn.commit()
                continue

            # 3. Add Album
            if album_name:
                album_id = add_album(api_url, api_key, artist_id, album_name)
                if album_id:
                    cursor.execute("UPDATE missed_requests SET sent_to_lidarr = 1, lidarr_album_id = ? WHERE id = ?", (album_id, rowid,))
                    conn.commit()
                    logger.info(f"Request {rowid} ({song_name}) queued in Lidarr album {album_id}.")
                else:
                    # Could not add album — mark as sent and fallback to monitoring the artist's tracks
                    logger.warning(f"Could not add album '{album_name}' to Lidarr for row {rowid}. Falling back to artist monitor.")
                    cursor.execute("UPDATE missed_requests SET sent_to_lidarr = 1, lidarr_album_id = ? WHERE id = ?", (f"ARTIST:{artist_id}", rowid,))
                    conn.commit()
            else:
                logger.warning(f"Row {rowid} missing album name. Artist added, but no album to request.")
                cursor.execute("UPDATE missed_requests SET sent_to_lidarr = 1 WHERE id = ?", (rowid,))
                conn.commit()


    except sqlite3.Error as e:
        logger.error(f"SQLite error: {e}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync music requests from SQLite to Lidarr")
    parser.add_argument("db_path", help="Path to the SQLite database file")
    parser.add_argument("--api-key", required=True, help="Lidarr API Key")
    parser.add_argument("--url", required=True, help="Lidarr Base URL")

    args = parser.parse_args()

    sync_requests(args.db_path, args.url, args.api_key)
