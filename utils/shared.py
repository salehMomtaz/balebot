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
    "max_cache_age_hours": 2,   # Auto-clean files older than this in cache/.
    "max_disk_usage_pct": 95,   # Refuse downloads if disk usage exceeds this.
}


# --- Safety limits (not admin-adjustable at runtime) ---
MAX_QUEUE_DEPTH = 20            # Reject new jobs if queue grows beyond this
MIN_FREE_DISK_GB = 1            # Minimum free space headroom in GB


def get_setting_bytes(key: str) -> int:
    """Return a RUNTIME_SETTINGS value (stored in MB) as bytes."""
    return int(RUNTIME_SETTINGS[key]) * 1024 * 1024


def set_setting(key: str, value: int) -> None:
    """Admin-console helper: update a runtime setting (value as integer)."""
    if key not in RUNTIME_SETTINGS:
        raise KeyError(f"Unknown setting: {key}")
    RUNTIME_SETTINGS[key] = int(value)


# Backwards-compatible alias
set_setting_mb = set_setting
