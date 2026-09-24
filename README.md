# Philips Home Access – SmartThings Integration

Control your **Philips Home Access WiFi locks** directly from the **SmartThings** app.

This project is a **SmartThings Schema Connector** (cloud-to-cloud integration) that
bridges the Philips Home Access cloud API with the SmartThings platform. Once set up,
your Philips locks appear in SmartThings as native devices — you can lock/unlock them,
monitor battery and alarm state, build automations, and use them with voice assistants.

> This is an independent SmartThings Schema Connector, not a fork of rjbogz's project.
> The Philips cloud API was reverse-engineered by
> [rjbogz](https://github.com/rjbogz/philips_home_access) for their Home Assistant
> integration; this connector was built from scratch using that API research as a reference.

---

## Supported features

| Feature | SmartThings capability |
|---|---|
| Lock / Unlock | `st.lock` |
| Lock alarm (tamper, forced open, duress) | `st.lockAlarm` |
| Battery level | `st.battery` |

Device profile: `c2c-lock-5`

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

1. You register a **Schema Connector** in the SmartThings Developer Center.
2. You host this Python server somewhere with a **public HTTPS URL**
   (see [Deployment](#deployment) below).
3. A SmartThings user opens the SmartThings app → *Add device → Partner devices →
   My Testing Devices* and is redirected to the login page hosted by this server.
4. After signing in with Philips credentials, the lock(s) appear in SmartThings.

---

## Notes

- Using a **dedicated Philips account** (e.g. `smartthings@yourdomain.com`) that is
  shared on the lock is recommended over using your primary account, so the integration
  doesn't affect your personal Philips app session.
- State polling is triggered by SmartThings (`stateRefreshRequest`).
- An internet connection is required — this integration talks to the Philips cloud.

---

## Prerequisites

- Python 3.11+
- A publicly reachable **HTTPS** endpoint (VPS, cloud function, or a tunnel such as
  [ngrok](https://ngrok.com/) for local development)
- A [SmartThings Developer Center](https://developer.smartthings.com/) account

---

## Quick start (local development with ngrok)

```bash
# 1. Clone and install
git clone https://github.com/JoAnna-Cohen/philips_home_access_smartthings
cd philips_home_access_smartthings
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env – fill in SECRET_KEY now; add ST_CLIENT_ID + ST_CLIENT_SECRET
# after completing the Developer Center steps below.

# 3. Expose publicly (separate terminal)
ngrok http 5000
# Note the  https://xxxx.ngrok.io  forwarding URL.

# 4. Register the connector (see next section), then start the server:
python app.py
```

---

## Registering the SmartThings Schema Connector

> The SmartThings Developer Center was redesigned in 2025. The old Developer Workspace
> is no longer active. Use <https://developer.smartthings.com/> (new console).

1. Sign in and create a **Product** for your connector.
2. Under the product, add a **Schema App** with these settings:

   | Field | Value |
   |---|---|
   | Connector type | Webhook |
   | Webhook URL | `https://<your-host>/webhook` |
   | OAuth Authorization URL | `https://<your-host>/oauth/authorize` |
   | OAuth Token URL | `https://<your-host>/oauth/token` |
   | OAuth Client ID | Any string you choose |
   | OAuth Client Secret | Any string you choose |
   | OAuth Scopes | *(leave blank)* |

3. Save. Copy the **Client ID** and **Client Secret** into your `.env` as
   `ST_CLIENT_ID` and `ST_CLIENT_SECRET`.

### Testing in the SmartThings app

SmartThings requires **Developer Mode** to test unpublished connectors:

1. Open the SmartThings app → tap the menu → **About SmartThings**.
2. Long-press **About SmartThings** for 10 seconds until Developer Mode activates.
3. Add device → **Partner devices** → **My Testing Devices** → select your connector.
4. Sign in with your Philips credentials → your locks appear.

---

## Deployment

### Production VPS (recommended)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in all values
```

Start with gunicorn using the included config (sets 2 workers and 120 s timeout):

```bash
gunicorn app:app -c gunicorn.conf.py
```

Or as a systemd service:

```ini
[Unit]
Description=Philips Home Access SmartThings Connector
After=network.target

[Service]
User=youruser
WorkingDirectory=/path/to/philips_home_access_smartthings
EnvironmentFile=/path/to/philips_home_access_smartthings/.env
ExecStart=/path/to/.venv/bin/gunicorn app:app -c /path/to/philips_home_access_smartthings/gunicorn.conf.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Put the server behind a reverse proxy (nginx / Caddy) that terminates HTTPS and
proxies all traffic to `127.0.0.1:5000`.

> **Token storage** – tokens are written to JSON files in `DATA_DIR` (default `.`).
> Set `DATA_DIR` to an absolute path writable by the service user.

### Docker

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 5000
CMD ["gunicorn", "app:app", "-c", "gunicorn.conf.py", "--bind", "0.0.0.0:5000"]
```

---

## Project structure

```
app.py                        Flask entry point (OAuth routes + webhook)
gunicorn.conf.py              Gunicorn settings (timeout, workers, bind)
philips_smartthings/
  api.py                      Philips cloud API client (lock/unlock, device list)
  auth.py                     OAuth 2.0 server + Philips session management
  connector.py                SmartThings st-schema request handler
  const.py                    RSA keys and region codes
  storage.py                  Thread-safe file-backed key/value store
templates/
  login.html                  OAuth login page shown to users during setup
  index.html                  Landing page served at the root URL
requirements.txt
.env.example                  Configuration template
```

---

## Configuration reference

| Variable | Required | Description |
|---|---|---|
| `ST_CLIENT_ID` | Yes | Client ID from SmartThings Developer Center |
| `ST_CLIENT_SECRET` | Yes | Client Secret from SmartThings Developer Center |
| `SECRET_KEY` | Yes | Random string for Flask session cookie signing |
| `DATA_DIR` | No | Directory for token JSON files (default `.`) |
| `PORT` | No | Port to listen on (default `5000`) |
| `DEBUG` | No | Set to `1` for verbose logging |

Generate a `SECRET_KEY`:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

---

## Regions

| Region code | Description |
|---|---|
| `PhilipsNorthAmerica` | USA / Canada |
| `PhilipsSingapore` | Singapore / APAC |
| `PhilipsOneness` | Europe / other |

---

## License

Apache License 2.0 – see [LICENSE](LICENSE).
