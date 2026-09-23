"""SmartThings Schema Connector request handler.

Handles the st-schema webhook interactions:
- discoveryRequest      → list the user's Philips locks
- stateRefreshRequest   → return current lock/battery state
- commandRequest        → lock or unlock a device
- grantCallbackAccess   → acknowledge (proactive updates not yet implemented)
- integrationDeleted    → revoke the stored tokens

SmartThings Schema Connector spec:
https://developer.smartthings.com/docs/devices/cloud-connected/st-schema
"""

import logging

_LOGGER = logging.getLogger(__name__)

ST_SCHEMA = "st-schema"
ST_VERSION = "1.0"


def _headers(interaction_type: str, request_id: str) -> dict:
    return {
        "schema": ST_SCHEMA,
        "version": ST_VERSION,
        "interactionType": interaction_type,
        "requestId": request_id,
    }


class SmartThingsConnector:
    def __init__(self, auth_manager):
        self._auth = auth_manager

    # ------------------------------------------------------------------
    # Public dispatch entry point
    # ------------------------------------------------------------------

    def handle(self, body: dict) -> dict:
        interaction = body.get("headers", {}).get("interactionType", "")
        request_id = body.get("headers", {}).get("requestId", "")
        access_token = body.get("authentication", {}).get("token", "")

        _LOGGER.debug("Connector received interactionType=%s", interaction)

        if interaction == "discoveryRequest":
            return self._discovery(body, access_token, request_id)
        if interaction == "stateRefreshRequest":
            return self._state_refresh(body, access_token, request_id)
        if interaction == "commandRequest":
            return self._command(body, access_token, request_id)
        if interaction == "grantCallbackAccess":
            return self._grant_callback(body, request_id)
        if interaction == "integrationDeleted":
            self._auth.revoke(access_token)
            return {"headers": _headers("integrationDeletedResponse", request_id)}

        _LOGGER.warning("Unknown interactionType: %s", interaction)
        return self._global_error(
            f"{interaction}Response",
            request_id,
            "INVALID_INTERACTION",
            f"Unknown interaction: {interaction}",
        )

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def _discovery(self, body, access_token, request_id) -> dict:
        api = self._auth.get_api(access_token)
        if not api:
            return self._global_error(
                "discoveryResponse", request_id, "INVALID_TOKEN", "Invalid or expired token"
            )

        try:
            raw_devices = api.get_devices()
        except Exception as exc:
            _LOGGER.error("Discovery: get_devices failed: %s", exc)
            return self._global_error(
                "discoveryResponse", request_id, "DEVICE_UNAVAILABLE", str(exc)
            )

        _LOGGER.warning("DISCOVERY RAW FULL: %s", raw_devices)

        devices = []
        for d in raw_devices:
            if d.get("deviceType") != "LOCK":
                _LOGGER.warning("DISCOVERY: skipping non-LOCK device: type=%s wifiSN=%s", d.get("deviceType"), d.get("wifiSN"))
                continue
            esn = d.get("wifiSN")
            if not esn:
                _LOGGER.warning("DISCOVERY: skipping device with no wifiSN: %s", d)
                continue
            devices.append(self._build_st_device(d, esn))

        return {
            "headers": _headers("discoveryResponse", request_id),
            "devices": devices,
        }

    def _build_st_device(self, d: dict, esn: str) -> dict:
        name = d.get("lockNickname") or d.get("deviceName") or "Philips Lock"
        model = d.get("productModel", "Home Access Lock")

        capabilities = [
            {"id": "st.lock", "version": 1},
            {"id": "st.battery", "version": 1},
        ]

        return {
            "externalDeviceId": esn,
            "friendlyName": name,
            "manufacturerInfo": {
                "manufacturerName": "Philips",
                "modelName": model,
                "hwVersion": "1.0",
                "swVersion": d.get("lockSoftwareVersion", "1.0"),
            },
            "deviceContext": {
                "categories": ["Lock"],
            },
            "deviceHandlerType": "c2c-lock-2",
            "capabilities": capabilities,
        }

    # ------------------------------------------------------------------
    # State refresh
    # ------------------------------------------------------------------

    def _state_refresh(self, body, access_token, request_id) -> dict:
        api = self._auth.get_api(access_token)
        if not api:
            return self._global_error(
                "stateRefreshResponse", request_id, "INVALID_TOKEN", "Invalid or expired token"
            )

        requested_ids = [
            d.get("externalDeviceId") for d in body.get("devices", [])
        ]

        try:
            raw_devices = api.get_devices()
        except Exception as exc:
            _LOGGER.error("StateRefresh: get_devices failed: %s", exc)
            return self._global_error(
                "stateRefreshResponse", request_id, "DEVICE_UNAVAILABLE", str(exc)
            )

        device_map = {
            d["wifiSN"]: d for d in raw_devices if d.get("wifiSN")
        }

        device_state = []
        for esn in requested_ids:
            if not esn or esn not in device_map:
                continue
            states = self._build_states(device_map[esn])
            device_state.append({"externalDeviceId": esn, "states": states})

        return {
            "headers": _headers("stateRefreshResponse", request_id),
            "deviceState": device_state,
        }

    # ------------------------------------------------------------------
    # Command
    # ------------------------------------------------------------------

    def _command(self, body, access_token, request_id) -> dict:
        api = self._auth.get_api(access_token)
        if not api:
            return self._global_error(
                "commandResponse", request_id, "INVALID_TOKEN", "Invalid or expired token"
            )

        try:
            raw_devices = api.get_devices()
        except Exception as exc:
            _LOGGER.error("Command: get_devices failed: %s", exc)
            return self._global_error(
                "commandResponse", request_id, "DEVICE_UNAVAILABLE", str(exc)
            )

        device_map = {
            d["wifiSN"]: d for d in raw_devices if d.get("wifiSN")
        }

        device_state = []
        for dev_cmd in body.get("devices", []):
            esn = dev_cmd.get("externalDeviceId")
            if not esn or esn not in device_map:
                _LOGGER.warning("Command: unknown device %s", esn)
                continue

            for cmd in dev_cmd.get("commands", []):
                capability = cmd.get("capability")
                command = cmd.get("command")
                if capability == "st.lock":
                    lock_it = command == "lock"
                    try:
                        resp = api.set_lock_state(esn, lock_it)
                        _LOGGER.debug(
                            "Command %s on %s → %s", command, esn, resp
                        )
                        # Optimistically update in-memory state for the response
                        device_map[esn]["openStatus"] = 1 if lock_it else 0
                    except Exception as exc:
                        _LOGGER.error(
                            "Command: set_lock_state failed for %s: %s", esn, exc
                        )

            states = self._build_states(device_map[esn])
            device_state.append({"externalDeviceId": esn, "states": states})

        return {
            "headers": _headers("commandResponse", request_id),
            "deviceState": device_state,
        }

    # ------------------------------------------------------------------
    # Grant callback access
    # ------------------------------------------------------------------

    def _grant_callback(self, body: dict, request_id: str) -> dict:
        # Store callback credentials for future proactive updates.
        callback_auth = body.get("callbackAuthentication", {})
        callback_urls = body.get("callbackUrls", {})
        if callback_auth or callback_urls:
            access_token = body.get("authentication", {}).get("token", "")
            self._auth.store_callback_credentials(access_token, callback_auth, callback_urls)
        return {"headers": _headers("grantCallbackAccessResponse", request_id)}

    # ------------------------------------------------------------------
    # State builder
    # ------------------------------------------------------------------

    def _build_states(self, d: dict) -> list:
        """Build SmartThings state list from a Philips device dict."""
        states = []

        # Lock state: openStatus == 1 means LOCKED
        # Omit entirely when unknown — "unknown" is not a valid st.lock enum value.
        open_status = d.get("openStatus")
        if open_status is not None:
            states.append(
                {
                    "component": "main",
                    "capability": "st.lock",
                    "attribute": "lock",
                    "value": "locked" if open_status == 1 else "unlocked",
                }
            )

        # Battery (percentage)
        battery = d.get("power")
        if battery is not None:
            try:
                states.append(
                    {
                        "component": "main",
                        "capability": "st.battery",
                        "attribute": "battery",
                        "value": int(battery),
                        "unit": "%",
                    }
                )
            except (ValueError, TypeError):
                pass

        return states

    # ------------------------------------------------------------------
    # Error helpers
    # ------------------------------------------------------------------

    def _global_error(
        self,
        response_type: str,
        request_id: str,
        error_enum: str,
        description: str,
    ) -> dict:
        _LOGGER.warning("Global error [%s]: %s – %s", response_type, error_enum, description)
        return {
            "headers": _headers(response_type, request_id),
            "globalError": {"errorEnum": error_enum, "description": description},
        }
