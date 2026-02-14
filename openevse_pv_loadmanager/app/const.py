"""Constants for the PV Load Manager."""

# Limits
DEFAULT_TOTAL_CURRENT_LIMIT = 32  # Amperes
MIN_STATION_CURRENT = 6  # Below this -> pause
DEFAULT_VOLTAGE = 230

# Ramp control
DEFAULT_RAMP_UP_DELAY = 30  # seconds
MAX_RAMP_UP_STEP = 4.0  # amps per cycle

# Hysteresis
DEFAULT_HYSTERESIS_THRESHOLD = 2.0  # Amperes
DEFAULT_HYSTERESIS_DELAY = 10  # seconds

# Measurement
DEFAULT_MEASUREMENT_INTERVAL = 5.0  # seconds

# Cloud detection
CLOUD_DETECTION_WINDOW = 60  # seconds
CLOUD_DETECTION_VARIANCE_THRESHOLD = 500  # watts^2

# Timeouts
PV_STALE_TIMEOUT = 60  # seconds without PV data -> stale

# Overbooking
ACTUAL_TOLERANCE = 1.0  # A
SLACK_BUFFER = 0.5  # A
OVERBOOKING_ITERATIONS = 3

# Safety
SAFETY_MARGIN = 2.0  # A

# HA Supervisor API
HA_API_BASE = "http://supervisor/core/api"
HA_API_STATES = HA_API_BASE + "/states/{}"
HA_API_SERVICES = HA_API_BASE + "/services/{}/{}"

# Persistence
STATE_FILE = "/data/state.json"
