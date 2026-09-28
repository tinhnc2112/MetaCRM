# Realtime behavior after M8

`backend/app/api/ws.py` accepts a desktop subscriber at
`/api/v1/ws?page_id=<owned-page-id>` only when it supplies both `metacrm`
and `bearer.<access JWT>` WebSocket subprotocols. The server resolves the
active user and Page on the backend; a requested raw channel or URL token is
rejected. Page A notifications cannot be subscribed to through Page B access.
Webhook persistence commits before `new_message` is broadcast.

The Electron Messenger inbox already has an in-memory access token and the
selected Page ID, so it uses the authenticated socket for Page-scoped
invalidation. On opening a socket it refetches conversations and selected
messages; notifications invalidate affected API queries. Independently, active
conversation/message queries refetch every 30 seconds and on normal query
mount/focus. This catches missed notifications or a disconnected socket while
that screen is open. A fresh screen load also fetches from the API. Polling
pauses when React Query has no active screen/query; it is not a background
message-delivery guarantee.

The MV3 extension has neither an authenticated staff session nor Page context.
Its popup/side panel therefore report only the public HTTP liveness result
from `/api/v1/system/health`. “Reachable” means the backend responded to this
probe; it does not imply MySQL readiness, authorization, Page selection or a
Messenger stream. “Check again” repeats this request after an outage. The
extension opens no WebSocket, stores no session token and does not promise
Messenger updates or authenticated refetch. It can only show a public health
status until a separate secure staff/Page connection workflow is designed.

The API/database remains authoritative. `ConnectionManager` is process-local:
with multiple backend workers or a missed broadcast, a WebSocket client can
miss invalidation events; no multi-worker fan-out or durable event delivery is
implemented. Use API refetch after reconnect and polling for current state.
