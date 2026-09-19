# Protect Request API with Password

This plan outlines how to add a dedicated password requirement to the song request API (`POST /request`), ensuring only the official web UI and your internal scripts can trigger requests (and spend LLM tokens). 

## User Review Required

> [!WARNING]
> **Frontend Hardcoding**: The web interface will need to know this password to send it automatically without asking the listener to type it. This means the password will be bundled into the web UI's source code (`NEXT_PUBLIC_REQUEST_PASSWORD`). While this will easily stop casual spam bots, a determined attacker could inspect the network traffic in their browser, find the password, and configure their bot to use it. Is this level of "security through obscurity" acceptable for your needs?

## Proposed Changes

---

### `controller` (Backend)

We will add a check to the `POST /request` endpoint to require a password if one is configured in `.env`.

#### [MODIFY] [request.ts](file:///Users/scott/GitHub/subwave/controller/src/routes/request.ts)
- Add a check at the top of the `POST /request` handler.
- Read `process.env.REQUEST_PASSWORD`.
- If set, verify that `req.headers['x-request-password']` matches. If not, reject with `401 Unauthorized`.

---

### `web` (Frontend)

We will modify the API client used by the web UI to automatically attach the password to request submissions.

#### [MODIFY] [stationClient.ts](file:///Users/scott/GitHub/subwave/web/lib/stationClient.ts)
- Update the `submitRequest` function to read `process.env.NEXT_PUBLIC_REQUEST_PASSWORD`.
- If set, append it to the `headers` object as `x-request-password` when calling `fetch`.

---

### Environment Configuration

#### [MODIFY] [.env.example](file:///Users/scott/GitHub/subwave/.env.example)
- Add `REQUEST_PASSWORD` and `NEXT_PUBLIC_REQUEST_PASSWORD` as documented examples.

## Verification Plan

### Automated Tests
- N/A - simple environment variable check.

### Manual Verification
1. I will apply these changes and rebuild the live server containers.
2. I will configure a secure password in your live `.env` file for both variables.
3. I will test the API directly via `curl` without the header to ensure it gets blocked.
4. I will test the API via `curl` with the header to ensure it works.
5. You can verify that the web UI still allows requests normally.
