# utils/shared.py
from utils.queue_manager import DownloadQueue

# Globally shared thread-safe task queue and in-memory caches
queue = DownloadQueue()
DOWNLOAD_CACHE = {}
LAST_UPDATE_TIME = {}

# --- Runtime-configurable settings (mutable at runtime via admin console) ---
# Bale hard limit is 20 MB. We keep a safety margin below it.
# Values are in MB so they are easy to set from a chat command.
RUNTIME_SETTINGS = {
    "bale_hard_limit_mb": 20,   # Bale's real cap. Never upload at/above this.
    "split_target_mb": 18,      # Target size per video segment (margin under 20).
    "binary_chunk_mb": 18,      # Target size per binary (document/audio) chunk.
}


def get_setting_bytes(key: str) -> int:
    """Return a RUNTIME_SETTINGS value (stored in MB) as bytes."""
    return int(RUNTIME_SETTINGS[key]) * 1024 * 1024


def set_setting_mb(key: str, value_mb: int) -> None:
    """Admin-console helper: update a size setting at runtime (value in MB)."""
    if key not in RUNTIME_SETTINGS:
        raise KeyError(f"Unknown setting: {key}")
    RUNTIME_SETTINGS[key] = int(value_mb)
