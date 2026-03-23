# Philips Home Access – SmartThings Integration

Control your **Philips Home Access WiFi locks** directly from the **SmartThings** app.

This project is a **SmartThings Schema Connector** (cloud-to-cloud integration) that
bridges the Philips Home Access cloud API with the SmartThings platform.  Once set up,
your Philips locks appear in SmartThings just like native devices — you can lock/unlock
them, check battery level, build automations, and use them with voice assistants.

> Original Philips Home Access API research and Home Assistant integration by
> [rjbogz](https://github.com/rjbogz/philips_home_access).

---

## Supported features

| Feature | SmartThings capability |
|---|---|
| Lock / Unlock | `st.lock` |
| Battery level | `st.battery` |

Both direct-WiFi locks and gateway-controlled locks are supported.

---

## How it works

```
SmartThings app
      │  (webhook / st-schema)
      ▼
 This Python server   ──────►  Philips cloud API  ──────►  Your lock
      │
      │  (OAuth login page – one-time setup)
      ▼
  Your browser
```

1. You register a **Schema Connector** in the SmartThings Developer Workspace.
2. You host this Python server somewhere with a **public HTTPS URL**
   (see [Deployment](#deployment) below).
3. A SmartThings user opens the SmartThings app → *Add device → By brand →
   Philips Home Access* and is redirected to the login page hosted by this server.
4. After signing in with Philips credentials, the lock(s) appear in SmartThings.

---

## Notes

- You cannot be logged into the Philips Home Access mobile app and this integration at
  the same time.  Logging into one will sign you out of the other.
- Polling interval is 60 seconds (SmartThings triggers `stateRefreshRequest`).
- An internet connection is required (Philips cloud access).

---

## Prerequisites

- Python 3.11+
- A publicly reachable **HTTPS** endpoint (VPS, cloud function, or a tunnel such as
  [ngrok](https://ngrok.com/) for local development)
- A [SmartThings Developer Workspace](https://developer.smartthings.com/) account

---

## Quick start (local development with ngrok)

```bash
# 1. Clone and install
git clone https://github.com/JoAnna-Cohen/philips_home_access_smartthings
cd philips_home_access_smartthings
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env – fill in SECRET_KEY now; add ST_CLIENT_ID + ST_CLIENT_SECRET
# after completing the Developer Workspace steps below.

# 3. Expose publicly (separate terminal)
ngrok http 5000
# Note the  https://xxxx.ngrok.io  forwarding URL.

# 4. Register the connector (see next section), then start the server:
python app.py
```

---

## Registering the SmartThings Schema Connector

1. Sign in at <https://developer.smartthings.com/>.
2. Navigate to **Develop → SmartThings Schema Connectors → + New Schema Connector**.
3. Fill in the form:

   | Field | Value |
   |---|---|
   | Connector name | Philips Home Access |
   | Connector type | Webhook |
   | Webhook URL | `https://<your-host>/webhook` |
   | OAuth Authorization URL | `https://<your-host>/oauth/authorize` |
   | OAuth Token URL | `https://<your-host>/oauth/token` |
   | OAuth Client ID | Any string you choose |
   | OAuth Client Secret | Any string you choose |
   | OAuth Scopes | *(leave blank)* |

4. Save.  Copy the **Client ID** and **Client Secret** into your `.env` file as
   `ST_CLIENT_ID` and `ST_CLIENT_SECRET`.

5. In the SmartThings Developer Workspace, go to **Test → Install connector** to add
   it to your SmartThings account.

6. Open the SmartThings app → **Add device** → search for your connector name →
   sign in with your Philips credentials → your locks will appear.

---

## Deployment

### Option A – Any Python host (VPS, Railway, Render, Fly.io, …)

```bash
pip install -r requirements.txt
gunicorn app:app --bind 0.0.0.0:5000 --workers 2
```

Put the server behind a reverse proxy (nginx / Caddy) that terminates HTTPS.
Set all environment variables from `.env.example` in your host's config panel.

> **Token storage** – tokens are written to JSON files in `DATA_DIR` (default `.`).
> For multi-process deployments, point `DATA_DIR` at a shared volume, or replace
> `TokenStore` in `philips_smartthings/storage.py` with a database-backed store.

### Option B – Docker

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 5000
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:5000", "--workers", "2"]
```

---

## Project structure

```
app.py                        Flask entry point (OAuth routes + webhook)
philips_smartthings/
  __init__.py
  api.py                      Philips cloud API client (lock/unlock, device list)
  const.py                    RSA keys and region codes
  auth.py                     OAuth 2.0 server + Philips session management
  connector.py                SmartThings st-schema request handler
  storage.py                  Thread-safe file-backed key/value store
templates/
  login.html                  OAuth login page shown to users in SmartThings
requirements.txt
.env.example                  Configuration template
```

---

## Configuration reference

| Variable | Required | Description |
|---|---|---|
| `ST_CLIENT_ID` | Yes | Client ID from SmartThings Developer Workspace |
| `ST_CLIENT_SECRET` | Yes | Client Secret from SmartThings Developer Workspace |
| `SECRET_KEY` | Yes | Random string for Flask session cookie signing |
| `PORT` | No | Port to listen on (default `5000`) |
| `DATA_DIR` | No | Directory for token JSON files (default `.`) |
| `DEBUG` | No | Set to `1` for verbose logging |

---

## Regions

| Region code | Description |
|---|---|
| `PhilipsNorthAmerica` | USA / Canada |
| `PhilipsSingapore` | Singapore / APAC |
| `PhilipsOneness` | Europe / other |

---

## Debug logging

Set `DEBUG=1` in your `.env` file, or export it before starting the server:

```bash
DEBUG=1 python app.py
```

---

## License

Apache License 2.0 – see [LICENSE](LICENSE).
