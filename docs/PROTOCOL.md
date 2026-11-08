# Protocol notes

How `muse-cli` talks to the muse.ai personal gateway. Derived from the web
app's own client bundle and verified live. Internal APIs are unversioned and
can change without notice; if calls start failing, re-derive from a fresh
bundle (for example a HAR capture of the web app).

## Layers

```
muse-cli
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
  A reply larger than one Noise message (65535 bytes) is split across several
  frames that share a `chunk_id` (`total_chunks > 1`, `chunk_index` 0-based).
  Only the concatenated payloads parse as a `ServiceResponse`; parsing a single
  chunk fails with `DecodeError: Wire format was corrupt`. Frames of different
  `chunk_id`s can interleave, so `Gateway._read_frame()` buffers per id.
  (`egress.approvals` returns ~123 KB and hit this.)
- **Request:** `ServiceRequest{service, payload =
  ServiceFrame{stream_id, request =
  ApplicationRequest{verb, path, headers, body, end_body}}}`. Stream ids start
  at 1. Services: daemon 0, sentinel 1, vault 2, authd 3, ssh_access 4,
  yolk 5.
- **Response:** `ServiceResponse{payload = ServiceFrame{... response =
  ApplicationResponse{status, headers, body, end_body}}}` plus `body_chunk`
  frames until `end_body`.
- **Subscriptions** (`chat.subscribe`, `chat.stream`, ...): same envelope, the
  server streams `application/x-ndjson` records in body chunks.
- **Method table:** `routes.json` (402 methods extracted from the web bundle
  by `scripts/extract_routes.py`).

## Server quirks learned from live errors

- `chat.history`: GET query params only; `transcript_mode` is rejected, omit
  it; `session_id` scopes to a side chat; `limit` works. History events use
  `event_name` (`message.user` / `message.assistant`), carry the text in both
  top-level and `payload.display_text`, and are the source of truth.
- Genuine assistant replies have an **empty `reply_to_message_id`**; proactive
  pushes (Telegram drafts, background task updates) are self-referential
  there. That is how `send` tells a reply apart from background chatter.
- Generated media arrives as a **separate** assistant event after the text
  reply, ~20 s later for an image. `send --download` therefore waits until
  the history seq has been quiet for `SETTLE` seconds before collecting files.
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
- **Agent files** (`sandbox://workspace/<p>` in `payload.data.videos[]` /
  `images[]` / `fallback_text`): each entry carries `mime`, `byte_len` and
  `variants.original = https://<vm>.metaaivm.com/media/raw/workspace/<p>`.
  The bytes come from `GET /media/raw/workspace/<p>` on the VM. That route is
  not in `routes.json`; sent as a raw-path daemon request over the Noise
  tunnel it returns the file (body chunks). `Gateway.download_file()` wraps
  this. `artifacts.fetch_url` is unrelated (needs `project_dir`).
- `session.start`: `{method: "/api/session/start", params: {origin: "fresh",
  lifecycle: "persistent"}}`. A `title` param is accepted but ignored (the
  chat stays untitled), so `start_session` follows up with `session.rename`.
- `session.rename`: flat `{session_id, title}`. pin/unpin/archive/unarchive/
  delete: `{method: "/api/session/<op>", session_id}`.
- `feed.unit.reaction`: `{reaction}` must be `like`, `love` or `dislike` (the
  server's 400 lists them).
- `api.idea-cards.execute`: `{ideaCardId, mode: "full"}` plus path param. A
  `session_id` in the body did not move the run into that side chat; the
  user message and the agent's reply landed in the main chat.
- **Re-deriving the method table:** `scripts/extract_routes.py` crawls the web
  app and rewrites `routes.json`, `desc0.bin` and `desc1.bin`. Logged out,
  every muse.ai page redirects to the marketing page (`?aymh_complete=1`),
  whose ~50 chunks do not include the app. The script therefore loads `/`
  with the saved cookies, then follows `static/chunks/*.js` references
  (about 1300 chunks, all public). The route table is one array of
  `{method,httpMethod,path,...}` literals; the descriptors are base64
  `FileDescriptorProto` blobs (`noise_transport.proto`,
  `noise_envelope.proto`). Route literals may carry `requestBody: "empty"`,
  `requestTimeoutMs`, `responseIdleTimeoutMs` and `maxResponseBytes`
  (numbers such as `12e4`, `0x2400000`, `1/0` for no limit).
- **How the web client builds a request:** GET routes fill `{path}` params
  from the params object and send the rest as query; non-GET routes send the
  whole params object (path params included) as the JSON body, except
  `requestBody: "empty"` routes, which send no body and no content-type.
  `Gateway` matches this. List filters are repeated query keys:
  `voice.catalog?source=library&gender=F&gender=M` works.
- `Gateway.request()` with `timeout=None` uses the route's `requestTimeoutMs`
  (30 s when absent); `raw` and `export-data` default to that.
- `tasks.list` returns `{schedules: [{id, title, mode, enabled,
  schedule_key, next_run_at_utc (s), cadence, ...}], invalid}`;
  `tasks.runs` takes `{limit, job_id?}` and returns `{runs: [{run_id,
  job_id, status, trigger_reason, scheduled_for_utc, result_summary,
  error_text}]}`. `tasks.run` is POST `/tasks/{job_id}/run` with body
  `{job_id}`, and the web client treats it as an inference call like
  `chat.stream`.
- `voice.catalog`: `{source: "library", query?, gender?: [F|M|N], accent?:
  [..], tone?: [..], limit, offset}`; `voice.catalog_filters` lists the
  values with counts. `voice.speak` (`{voice_id, text, format: "mp3",
  stream: true}`, binary `audio/mpeg`) returned 404 `preview_audio_disabled`
  on the test account.
- Muse Mail (`email.*`) answers 403 `{"code": "email_not_enabled"}` when the
  account has no mailbox. Thread list: `{data: [{id, subject,
  message_count, participants, last_message}], paging: {cursors: {after}}}`,
  next page with `{cursor}`. Messages carry `header_from`,
  `header_from_name`, `header_to`, `text_body`/`html_body`/`extracted_text`,
  `sender_authentication.verdict`, `attachments[{index, filename, mime_type,
  size}]`. `email.attachment.get` returns JSON with `content_base64` and
  `metadata.mime_type`, not raw bytes.
- Trusted Network (`peers.*`, `grants.list`, `peerSpaces.*`): `peers.status`
  always answers, with `availability` (`"disabled"` when off), `features`,
  `limits` and the agent's `muse_id`. While it is off, the list calls return
  503 `peer_operation_unavailable` (`peers.connections.list`:
  `connections_unavailable`). Page params are `{limit (1-100), cursor?}`.
- `dyi.export` (POST, empty body, ~65 min client timeout) streams the whole
  data export as `application/zip` with `content-length` and a
  `content-disposition` file name (`EYI Package_<date>_<n>.zip`). The test
  account's export was 347 MB / 290 files in ~21 s. `export-data` writes the
  body chunks straight to disk and checks type and length before keeping it.
- Services `ssh_access` (4, `ssh.operator.*`) and `yolk` (5,
  `rv_migration.enable_export`) joined the `ServiceType` enum. Both are
  operator/migration switches; muse-cli has no named commands for them.
- `vault.luks_status` returns 401 `request must come through nginx
  auth_request` over the tunnel.
- POSTs to muse.ai need browser `Sec-Fetch-*` headers or they return 403.
- `auth export` on macOS decrypts the muse.ai rows of the browser's own cookie
  database (`~/Library/Application Support/<browser>/<profile>/{Network/,}Cookies`,
  Chrome, Brave, Arc, Edge, Chromium). Values are `v10` + AES-128-CBC, key =
  PBKDF2-HMAC-SHA1(password from keychain item "<Browser> Safe Storage",
  salt `saltysalt`, 1003 rounds, 16 bytes), IV = 16 spaces. Cookie DB
  version 24+ (Chromium 130+) prefixes the plaintext with SHA-256(host_key);
  strip it when it matches. `expires_utc` is microseconds since 1601. The first
  keychain read shows a macOS Allow dialog. The desktop Muse.app is not a
  source: its OAuth tokens live in the keychain access group
  `V9WTTPBFK9.com.meta.endo`, readable only by the app itself.
  Copy the DB and its WAL/rollback journal together, checking their file
  metadata before and after the copy; retry a changing store at most three
  times. A checkpoint during copying can otherwise silently omit cookies.
  Expired rows are ignored before keychain access, and unreadable or
  undecryptable profiles do not block another usable profile. Cache both
  keys and keychain failures per browser to avoid repeated prompts.
  Select only host keys `muse.ai` and `.muse.ai`: subdomain-only cookies are
  not valid for the CLI's requests to `https://muse.ai/api/`.
- Elsewhere (and with `--browser agent-browser`) `auth export` reads cookies
  from the user's own Google Chrome through agent-browser `--auto-connect`.
  Chrome 144+ shares that profile only after remote debugging is enabled at
  `chrome://inspect/#remote-debugging`. That export follows the active tab, so
  a muse.ai tab has to be focused first.
- Either way, `auth export` must never overwrite a working jar without a
  non-empty, unexpired `hatch_sess` in the new one, and a freshly launched
  browser has no login; do not fall back to one.
