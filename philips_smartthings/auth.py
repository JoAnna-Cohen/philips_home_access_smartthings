"""OAuth 2.0 authorization server for the SmartThings Schema Connector.

SmartThings requires an OAuth server that:
1. Presents a login page to the user (Authorization Code flow)
2. Issues an authorization code after successful Philips login
3. Exchanges the code for access/refresh tokens
4. Supports token refresh

Token storage is file-based (tokens.json in the working directory).
For production deployments, replace TokenStore with a database-backed store.
"""

import time
import uuid
import logging

from .storage import TokenStore
from .api import PhilipsHomeAccessAPI

_LOGGER = logging.getLogger(__name__)

# Auth code TTL: 10 minutes
AUTH_CODE_TTL = 600

# Access token TTL: 24 hours
ACCESS_TOKEN_TTL = 86400


class AuthManager:
    def __init__(self, data_dir: str = "."):
        self._auth_codes = TokenStore(f"{data_dir}/auth_codes.json")
        self._access_tokens = TokenStore(f"{data_dir}/access_tokens.json")
        self._refresh_tokens = TokenStore(f"{data_dir}/refresh_tokens.json")
        self._philips_sessions = TokenStore(f"{data_dir}/philips_sessions.json")

    # ------------------------------------------------------------------
    # Philips login helper
    # ------------------------------------------------------------------

    def philips_login(self, username: str, password: str, region_code: str):
        """Authenticate with Philips and return (token, uid).

        Raises Exception with a string error code on failure.
        """
        api = PhilipsHomeAccessAPI(username, password, region_code)
        api.login()  # raises on failure
        return api.token, api.uid

    # ------------------------------------------------------------------
    # Authorization code
    # ------------------------------------------------------------------

    def create_auth_code(
        self,
        philips_token: str,
        philips_uid: str,
        region_code: str,
    ) -> str:
        code = str(uuid.uuid4())
        self._auth_codes.set(
            code,
            {
                "philips_token": philips_token,
                "philips_uid": philips_uid,
                "region_code": region_code,
                "created_at": time.time(),
            },
        )
        _LOGGER.debug("Created auth code (masked): %s***", code[:8])
        return code

    # ------------------------------------------------------------------
    # Token exchange
    # ------------------------------------------------------------------

    def exchange_code(self, code: str) -> dict | None:
        """Exchange an authorization code for access + refresh tokens.

        Returns a token response dict or None if the code is invalid/expired.
        """
        code_data = self._auth_codes.get(code)
        if not code_data:
            _LOGGER.warning("exchange_code: unknown code")
            return None

        if time.time() - code_data["created_at"] > AUTH_CODE_TTL:
            self._auth_codes.delete(code)
            _LOGGER.warning("exchange_code: code expired")
            return None

        access_token = str(uuid.uuid4())
        refresh_token = str(uuid.uuid4())

        self._philips_sessions.set(
            access_token,
            {
                "philips_token": code_data["philips_token"],
                "philips_uid": code_data["philips_uid"],
                "region_code": code_data["region_code"],
            },
        )
        self._access_tokens.set(
            access_token,
            {"created_at": time.time(), "expires_in": ACCESS_TOKEN_TTL},
        )
        self._refresh_tokens.set(
            refresh_token,
            {"access_token": access_token, "created_at": time.time()},
        )
        self._auth_codes.delete(code)

        _LOGGER.debug("Issued access token (masked): %s***", access_token[:8])
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "Bearer",
            "expires_in": ACCESS_TOKEN_TTL,
        }

    def refresh_access_token(self, refresh_token: str) -> dict | None:
        """Issue a new access token from a refresh token."""
        rt_data = self._refresh_tokens.get(refresh_token)
        if not rt_data:
            _LOGGER.warning("refresh_access_token: unknown refresh token")
            return None

        old_at = rt_data["access_token"]
        session = self._philips_sessions.get(old_at)
        if not session:
            _LOGGER.warning("refresh_access_token: no session for old access token")
            return None

        # Re-authenticate with Philips to get a fresh token
        try:
            api = PhilipsHomeAccessAPI(
                "",  # username not stored; use existing Philips token directly
                "",
                session["region_code"],
            )
            api.token = session["philips_token"]
            api.uid = session["philips_uid"]
            # Verify session is still valid by fetching device list
            api.get_devices()
            new_philips_token = session["philips_token"]
            new_philips_uid = session["philips_uid"]
        except Exception:
            _LOGGER.warning(
                "refresh_access_token: Philips session invalid; caller must re-authenticate"
            )
            return None

        new_at = str(uuid.uuid4())
        new_rt = str(uuid.uuid4())

        self._philips_sessions.set(
            new_at,
            {
                "philips_token": new_philips_token,
                "philips_uid": new_philips_uid,
                "region_code": session["region_code"],
            },
        )
        self._access_tokens.set(
            new_at,
            {"created_at": time.time(), "expires_in": ACCESS_TOKEN_TTL},
        )
        self._refresh_tokens.set(
            new_rt, {"access_token": new_at, "created_at": time.time()}
        )

        # Clean up old tokens
        self._access_tokens.delete(old_at)
        self._philips_sessions.delete(old_at)
        self._refresh_tokens.delete(refresh_token)

        return {
            "access_token": new_at,
            "refresh_token": new_rt,
            "token_type": "Bearer",
            "expires_in": ACCESS_TOKEN_TTL,
        }

    # ------------------------------------------------------------------
    # Session lookup
    # ------------------------------------------------------------------

    def get_philips_session(self, access_token: str) -> dict | None:
        """Return the Philips session dict for a valid access token, or None."""
        token_data = self._access_tokens.get(access_token)
        if not token_data:
            return None
        if time.time() - token_data["created_at"] > token_data["expires_in"]:
            _LOGGER.debug("get_philips_session: access token expired")
            return None
        return self._philips_sessions.get(access_token)

    def get_api(self, access_token: str) -> PhilipsHomeAccessAPI | None:
        """Return a ready-to-use PhilipsHomeAccessAPI for the given token."""
        session = self.get_philips_session(access_token)
        if not session:
            return None
        api = PhilipsHomeAccessAPI("", "", session["region_code"])
        api.token = session["philips_token"]
        api.uid = session["philips_uid"]
        return api

    # ------------------------------------------------------------------
    # Revocation
    # ------------------------------------------------------------------

    def revoke(self, access_token: str):
        self._access_tokens.delete(access_token)
        self._philips_sessions.delete(access_token)
        _LOGGER.debug("Revoked access token (masked): %s***", access_token[:8])
