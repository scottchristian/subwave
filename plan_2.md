# Protect Request API with Station Auth

This plan updates the approach based on your feedback. Instead of hardcoding a separate password, we will use Subwave's existing `requireStationAuth` middleware on the request API. 

This means:
1. When `listenerAuth` (station password) is enabled, the request endpoints (`POST /request` and `GET /request/:id`) will **fail closed** (reject) unless they receive the station password.
2. The web interface *already* asks the listener for this password to unlock the player. We will just configure the web interface to pass that exact same password token to the request API when a listener submits a song.
3. If someone just hits the API directly (like the bot), they will be rejected because they haven't authenticated.
4. Internal scripts can simply pass the station password in the `x-station-auth` header to submit requests.

## User Review Required

> [!NOTE]
> **Same Password**: This means the password required to submit a request will be identical to the station stream password. This aligns perfectly with your requirement that "If someone has authed into the web interface than they know the password to access it, and can request things." 

## Proposed Changes

---

### `controller` (Backend)

We will import and apply `requireStationAuth` to the listener request routes.

#### [MODIFY] [request.ts](file:///Users/scott/GitHub/subwave/controller/src/routes/request.ts)
- Import `requireStationAuth` from `../middleware/station-auth.js`.
- Add `requireStationAuth` as the first middleware to `router.post('/request', ...)`
- Add `requireStationAuth` as the first middleware to `router.get('/request/:id', ...)`

---

### `web` (Frontend)

We will modify the API client used by the web UI to automatically attach the station auth token it already stores.

#### [MODIFY] [stationClient.ts](file:///Users/scott/GitHub/subwave/web/lib/stationClient.ts)
- Inside `submitRequest` and `requestStatus`, we will dynamically import and call `getStationAuthToken()`.
- We will attach this token to the `x-station-auth` header when making the fetch calls to the backend.
- (If the station is public, the token will be empty and `requireStationAuth` will naturally allow the request, exactly as it does for the stream).

## Verification Plan

### Manual Verification
1. I will apply these changes and rebuild the controller and web containers.
2. I will test the API directly via `curl` without the header to ensure it returns `401 Unauthorized`.
3. I will test the API via `curl` with the `x-station-auth` header to ensure it succeeds.
4. You can verify that the web UI (once unlocked with the station password) still allows you to request songs perfectly.
