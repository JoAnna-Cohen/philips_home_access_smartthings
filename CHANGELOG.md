# Changelog

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
