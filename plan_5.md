# Generic Band Request Support

Currently, if someone asks for a band, we resolve it to their absolute #1 most popular song on iTunes and force Lidarr to wait for that specific album to download. As we just saw, Lidarr might download a different album first, causing the watchdog to wait endlessly. 

This plan details how we will restructure the pipeline to natively support "Any Track" requests, playing the very first song that successfully downloads for that artist.

## Proposed Changes

### 1. `missed_requests_server.py`
#### [MODIFY] `missed_requests_server.py`
Instead of resolving an artist request to a specific top track on iTunes, we will simply set `song_name = "Any"` and `album = "Any"`, keeping the resolved artist name.

### 2. `lidarr_sync_server.py`
#### [MODIFY] `lidarr_sync_server.py`
- We will update the script to recognize `album == "Any"`.
- It will add the artist to Lidarr. Crucially, we will modify the Lidarr `add_artist` payload to include `addOptions: { searchForMissingAlbums: True }` so Lidarr is explicitly commanded to search the internet for the artist's discography.
- To avoid complex database migrations, we will save the `artist_id` into the existing `lidarr_album_id` database column using a prefix (e.g. `ARTIST:110`).

### 3. `lidarr_watchdog.py`
#### [MODIFY] `lidarr_watchdog.py`
- When the watchdog reads a request from the database, it will check if the ID starts with `ARTIST:`.
- If it does, instead of querying Lidarr for a specific album, it will query Lidarr for **all tracks** by that artist (`/api/v1/track?artistId=...`).
- It will scan the list and pick the first track that reports `hasFile: True`. 
- It will seamlessly swap `"Any"` out for this actual track title, and push it to the station: *"Please play My Happiness by Powderfinger"*.

## Open Questions

None. This approach perfectly aligns with your request and makes the system far more dynamic and robust.

## Verification Plan
1. Send a mock `"Play me some Foo Fighters"` request through the pipeline.
2. Verify Lidarr Sync adds the artist and triggers an album search.
3. Verify the Watchdog detects the first downloaded track and queues it.