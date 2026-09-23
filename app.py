"""Philips Home Access – SmartThings Schema Connector

Entry point for the Flask web application.  Two top-level route groups:

  /oauth/*   – OAuth 2.0 Authorization Code flow that SmartThings uses to
               obtain a token representing the user's Philips account.

  /webhook   – SmartThings st-schema webhook (device discovery, state
               refresh, commands, …).

Environment variables (see .env.example):
  ST_CLIENT_ID      SmartThings connector client ID (from Developer Workspace)
  ST_CLIENT_SECRET  SmartThings connector client secret
  SECRET_KEY        Flask session secret (any random string)
  DATA_DIR          Directory for token JSON files (default: current dir)
  PORT              TCP port to listen on (default: 5000)
"""

import logging
import os

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from dotenv import load_dotenv

from philips_smartthings.auth import AuthManager
from philips_smartthings.connector import SmartThingsConnector
from philips_smartthings.const import REGIONS

load_dotenv()

logging.basicConfig(
    level=logging.DEBUG if os.getenv("DEBUG") else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s – %(message)s",
)
_LOGGER = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24))

DATA_DIR = os.environ.get("DATA_DIR", ".")
ST_CLIENT_ID = os.environ.get("ST_CLIENT_ID", "")
ST_CLIENT_SECRET = os.environ.get("ST_CLIENT_SECRET", "")

auth_manager = AuthManager(data_dir=DATA_DIR)
connector = SmartThingsConnector(auth_manager)


# ---------------------------------------------------------------------------
# OAuth – Authorization endpoint
# ---------------------------------------------------------------------------


@app.route("/oauth/authorize", methods=["GET"])
def oauth_authorize_get():
    """Show the Philips login form.

    SmartThings redirects the user here with:
      ?response_type=code&client_id=...&redirect_uri=...&state=...&scope=...
    """
    # Persist OAuth params so the POST handler can use them.
    session["oauth_redirect_uri"] = request.args.get("redirect_uri", "")
    session["oauth_state"] = request.args.get("state", "")
    session["oauth_client_id"] = request.args.get("client_id", "")

    _LOGGER.debug("OAUTH GET: redirect_uri=%s", session["oauth_redirect_uri"])
    return render_template("login.html", regions=REGIONS, error=None)


@app.route("/oauth/authorize", methods=["POST"])
def oauth_authorize_post():
    """Process the login form, authenticate with Philips, issue auth code."""
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    region_code = request.form.get("region", "")

    redirect_uri = session.get("oauth_redirect_uri", "")
    state = session.get("oauth_state", "")

    _LOGGER.debug("OAUTH POST: redirect_uri=%s state_present=%s", redirect_uri, bool(state))

    if not username or not password or not region_code:
        return render_template(
            "login.html",
            regions=REGIONS,
            error="All fields are required.",
        )

    try:
        philips_token, philips_uid = auth_manager.philips_login(
            username, password, region_code
        )
    except Exception as exc:
        error_map = {
            "invalid_auth": "Invalid username or password.",
            "account_not_find": "Account not found. Check your email address.",
            "region_not_found": "Account not found in the selected region.",
            "cannot_connect": "Could not reach Philips servers. Try again later.",
        }
        error_msg = error_map.get(str(exc), f"Login failed: {exc}")
        return render_template("login.html", regions=REGIONS, error=error_msg)

    code = auth_manager.create_auth_code(philips_token, philips_uid, region_code)

    # Redirect back to SmartThings with the authorization code.
    separator = "&" if "?" in redirect_uri else "?"
    return redirect(f"{redirect_uri}{separator}code={code}&state={state}")


# ---------------------------------------------------------------------------
# OAuth – Token endpoint
# ---------------------------------------------------------------------------


@app.route("/oauth/token", methods=["POST"])
def oauth_token():
    """Exchange an authorization code or refresh token for access tokens.

    SmartThings authenticates this request with HTTP Basic auth using
    the client_id and client_secret from the Developer Workspace.
    """
    # Validate client credentials (Basic auth or form params)
    auth_header = request.authorization
    if auth_header:
        client_id = auth_header.username
        client_secret = auth_header.password
    else:
        client_id = request.form.get("client_id", "")
        client_secret = request.form.get("client_secret", "")

    if ST_CLIENT_ID and ST_CLIENT_SECRET:
        if client_id != ST_CLIENT_ID or client_secret != ST_CLIENT_SECRET:
            _LOGGER.warning("Token endpoint: invalid client credentials")
            return jsonify({"error": "invalid_client"}), 401

    grant_type = request.form.get("grant_type", "")

    if grant_type == "authorization_code":
        code = request.form.get("code", "")
        token_resp = auth_manager.exchange_code(code)
        if not token_resp:
            _LOGGER.warning("Token exchange failed for grant_type=authorization_code")
            return jsonify({"error": "invalid_grant"}), 400
        return jsonify(token_resp)

    if grant_type == "refresh_token":
        refresh_token = request.form.get("refresh_token", "")
        token_resp = auth_manager.refresh_access_token(refresh_token)
        if not token_resp:
            return jsonify({"error": "invalid_grant"}), 400
        return jsonify(token_resp)

    return jsonify({"error": "unsupported_grant_type"}), 400


# ---------------------------------------------------------------------------
# SmartThings Schema Connector webhook
# ---------------------------------------------------------------------------


@app.route("/webhook", methods=["POST"])
def webhook():
    """Handle all st-schema interactions from SmartThings."""
    body = request.get_json(force=True, silent=True)
    if not body:
        return jsonify({"error": "invalid_json"}), 400

    response = connector.handle(body)
    return jsonify(response)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = bool(os.environ.get("DEBUG"))
    _LOGGER.info("Starting Philips Home Access SmartThings Connector on port %d", port)
    app.run(host="0.0.0.0", port=port, debug=debug)
