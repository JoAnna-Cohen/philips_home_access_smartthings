import json
import os
import threading


class TokenStore:
    """Simple thread-safe file-backed key-value store for tokens and sessions."""

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self._data = self._load()

    def _load(self) -> dict:
        if os.path.exists(self.path):
            try:
                with open(self.path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save(self):
        with open(self.path, "w") as f:
            json.dump(self._data, f, indent=2)

    def set(self, key: str, value):
        with self._lock:
            self._data[key] = value
            self._save()

    def get(self, key: str, default=None):
        with self._lock:
            self._data = self._load()
            return self._data.get(key, default)

    def delete(self, key: str):
        with self._lock:
            self._data.pop(key, None)
            self._save()

    def all(self) -> dict:
        with self._lock:
            return dict(self._data)
