# Changelog

## 2026-09-24: gateway lock command fixes (from rjbogz upstream comparison)

Two bugs in `api.py` identified by comparing against the original
[rjbogz/philips_home_access](https://github.com/rjbogz/philips_home_access)
API research.

### `esn`/`masterSn` swapped in gateway lock commands

The gateway lock/unlock payload had `esn` set to the *gateway's* `wifiSN`
and `masterSn` set to the *lock's* `wifiSN` — exactly backwards. The Philips
API expects `esn` = lock serial, `masterSn` = gateway serial. Lock and unlock
commands silently failed for any lock operated through a gateway (the most
common cloud-connected topology).

### `_normalize_mac` didn't canonicalise MAC format

`_normalize_mac` only stripped spaces. The Philips API expects
`AA:BB:CC:DD:EE:FF` format; MACs arriving with dashes or no separators
produced a malformed field. The method now strips `:` and `-`, then
reformats as colon-separated octets.

## 2026-09-24: st-schema error format

SmartThings didn't recognise this connector's error responses:

- **Wrong code format.** Error codes used underscores (`INVALID_TOKEN`,
  `DEVICE_UNAVAILABLE`, `INVALID_INTERACTION`). The st-schema spec uses
  hyphenated codes (`INVALID-TOKEN`, `TOKEN-EXPIRED`,
  `INVALID-INTERACTION-TYPE`, `BAD-REQUEST`).
- **Wrong field name.** The message was sent as `description`, but the spec
  field is `detail`.
- **No expired-token signal.** Expired access tokens were reported the
  same way as unknown ones. SmartThings only calls `/oauth/token` with the
  refresh token when it gets `TOKEN-EXPIRED`. Otherwise devices just stop
  responding after 24 hours, when the access token runs out.

**Fix:**
- Expired tokens now return `TOKEN-EXPIRED` (new `AuthManager.token_error()`),
  and unknown ones return `INVALID-TOKEN`.
- Philips API failures return `BAD-REQUEST`. `DEVICE-UNAVAILABLE` is only
  valid as a per-device error, not a global one.
- Errors now use the `detail` field.

## 2026-09-24: token storage fixes

These fixes were found while building the Leviton smart panel connector
([smart-panel-st](https://github.com/JoAnna-Cohen/smart-panel-st)), which
started from this repo's code. They were fixed there and ported back here.

### Deleting a token could erase tokens from the other gunicorn worker

`gunicorn.conf.py` runs 2 worker processes that share the same JSON token
files. `TokenStore.delete()` wrote back the process's in-memory copy
without re-reading the file first. Suppose worker A handled a
token refresh (deleting the old token) just after worker B saved a brand-new
token. Worker A's write then silently dropped worker B's token, and
SmartThings got `INVALID_TOKEN` on the next webhook call.

Also, `threading.Lock` only protects threads inside one process, so even
`set()` could interleave with the other worker.

**Fix:** `storage.py` now takes an exclusive `fcntl` file lock (shared by all
processes) around every read/write. It always re-reads the file before
changing it and writes atomically (temp file + rename, so a crash can't
leave half-written JSON). Token files are now created with `chmod 600`.

### Unlinking left refresh tokens behind

On `integrationDeleted`, `AuthManager.revoke()` called
`refresh_tokens.delete(access_token)`. But refresh tokens are stored under
the *refresh token* as the key, so nothing was ever deleted, and the old
refresh token stayed valid. It now removes every refresh token whose
stored `access_token` matches.

### Known, not changed

- Callback credentials are stored as `callback:<access_token>`. When
  SmartThings refreshes the token, the new access token doesn't carry them
  over. This connector doesn't send proactive updates yet, so nothing uses
  them. If that's added, key them by a stable account id instead, as
  smart-panel-st does.
