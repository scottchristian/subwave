# Handle Artist-Only Song Requests

Currently, when a listener requests "some powderfinger", the `missed_requests_server.py` script strips the word "some" and searches iTunes for a **song** named "Powderfinger". This results in finding the song "Powderfinger" by Neil Young, rather than the band Powderfinger.

This plan details how to correctly detect and route artist-only requests so the station auto-downloads the band and seamlessly plays one of their top tracks.

## Proposed Changes

### 1. `missed_requests_server.py`

#### [MODIFY] `missed_requests_server.py`
We will update `get_itunes_metadata` to detect when a listener uses phrasing that indicates an artist rather than a specific track:

1. **Detection:** Check the raw text for patterns like `"some <name>"`, `"anything by <name>"`, or `"something by <name>"`.
2. **Artist Lookup:** If detected, search the iTunes API for `entity=musicArtist` to find the exact artist match (e.g., Powderfinger).
3. **Top Track Resolution:** Take the iTunes `artistId` and query the iTunes Lookup API for their most popular track (`entity=song&sort=popular&limit=1`).
4. **Transparent Hand-off:** Return this top track (e.g., "My Happiness" by "Powderfinger") back to the pipeline.

**Why this approach is elegant:**
Because we resolve the artist request into a specific, highly popular track by that artist *at the very beginning of the pipeline*, **zero changes** are needed in `lidarr_sync_server.py` or `lidarr_watchdog.py`. 
- Lidarr Sync will see "My Happiness", add Powderfinger to Lidarr, and monitor the "Odyssey Number Five" album.
- Once the file downloads, the Watchdog will announce: *"Someone asked for this song before, so we sent someone out to go and get it... Please play My Happiness by Powderfinger"*. This flows perfectly on air for a listener who simply asked for "some Powderfinger".

## Open Questions

> [!IMPORTANT]  
> If the user asks for "some Powderfinger", and we automatically pick their #1 track on iTunes to fulfill it, are you happy with the DJ introducing it as *"Please play [Top Track] by Powderfinger"* when the track finally downloads? 

## Verification Plan

### Automated Tests
- Test the Python iTunes lookup locally with a mock script to ensure "some powderfinger" correctly resolves to a Powderfinger track instead of Neil Young.

### Manual Verification
- Deploy the updated `missed_requests.py` script to the server.
- Monitor the `/root/subwave/state/logs/requests.log` to ensure artist-only requests correctly route through the new logic.