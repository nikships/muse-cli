# Protocol notes

How `muse` talks to the muse.ai personal gateway. Derived from the web app's
own client bundle and verified live. Internal APIs are unversioned and can
change without notice; if calls start failing, re-derive from a fresh bundle
(HAR capture + the `derive-client` workflow).

## Layers

```
muse CLI
  │  HTTPS (browser TLS fingerprint via curl-impersonated requests)
  ▼
muse.ai            cookies → POST /api/auth/check → access_token
                   POST /api/hatch/token {vmAddress, vmName} → hatch token
                   GET /api/session → assigned VM id (auto-discovered)
  │  wss://hatch.metaaivm.com/v1/noise?vm_id=..&auth_token=..
  │  Noise_XX_25519_AESGCM_SHA256, empty payloads both ways
  ▼
personal VM gateway
  │  protobuf envelopes (descriptors in desc0.bin / desc1.bin)
  │  request/response + newline-JSON event subscriptions
  ▼
chat / feed / goals / ideas / sessions / ...
```

## Details

- **Gateway host:** the shared `hatch.metaaivm.com`, not the per-VM hostname.
  Plain TLS to the per-VM host is reset at the edge; a Chrome fingerprint
  (curl_cffi `impersonate="chrome"`) is required.
- **Handshake:** standard Noise XX. This account negotiates standard mode
  (empty msg3). An attested/RV mode with SNP attestation and HMAC proofs
  exists in the client for other configurations.
- **Framing:** `NoiseTransportFrame{chunk_id(i64), chunk_index, total_chunks,
  payload}` protobuf → Noise transport encrypt → one WS binary frame each.
- **Request:** `ServiceRequest{service, payload =
  ServiceFrame{stream_id, request =
  ApplicationRequest{verb, path, headers, body, end_body}}}`. Stream ids start
  at 1. Services: daemon 0, sentinel 1, vault 2, authd 3.
- **Response:** `ServiceResponse{payload = ServiceFrame{... response =
  ApplicationResponse{status, headers, body, end_body}}}` plus `body_chunk`
  frames until `end_body`.
- **Subscriptions** (`chat.subscribe`, `chat.stream`, ...): same envelope, the
  server streams `application/x-ndjson` records in body chunks.
- **Method table:** `routes.json` (258 methods extracted from the web bundle).

## Server quirks learned from live errors

- `chat.history`: GET query params only; `transcript_mode` is rejected, omit
  it; `session_id` scopes to a side chat; `limit` works. History events use
  `event_name` (`message.user` / `message.assistant`), carry the text in both
  top-level and `payload.display_text`, and are the source of truth.
- Genuine assistant replies have an **empty `reply_to_message_id`**; proactive
  pushes (Telegram drafts, background task updates) are self-referential
  there. That is how `send` tells a reply apart from background chatter.
- Live `chat.subscribe` events use **different shapes** (`delta.text_append`
  with `message_seq` + text chunks, `delta.message_done` with the full
  transcript) and only cover main-chat traffic: threaded replies never arrive
  as live events, just a `sessions.updated` snippet. `send` therefore polls
  history instead of watching the stream. The `chat.stream` response stream
  itself carries only the send echo, then ends.
- `/api/session` can return 200 `{"status":"unavailable",
  "vm_resolution_issue":{"kind":"retryable"}}` while the VM restarts. The
  client raises a clean error (not KeyError); retry, or wake a known VM id
  via `MUSE_VM_ID=<id> muse-cli wake`.
- Concurrent `_read_frame` calls from two threads split frames and corrupt
  the stateful Noise decrypt (fatal BAD_DECRYPT). `Gateway` serializes
  receives with a lock as a backstop, but callers must still keep exactly
  one frame consumer at a time (`send` makes sequential unary calls only).
- `session.start`: `{method: "/api/session/start", params: {origin: "fresh",
  lifecycle: "persistent", title?}}`.
- `session.rename`: flat `{session_id, title}`. pin/unpin/archive/unarchive/
  delete: `{method: "/api/session/<op>", session_id}`.
- `api.idea-cards.execute`: `{ideaCardId, mode: "full"}` plus path param.
- POSTs to muse.ai need browser `Sec-Fetch-*` headers or they return 403.
- `auth export` must focus a muse.ai tab before reading cookies (the export
  follows the active tab) and must never overwrite a working jar without a
  `hatch_sess` in the new one.
