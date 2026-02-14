"""Constants and defaults for the PV Load Manager."""

# Limits
DEFAULT_TOTAL_CURRENT_LIMIT = 32  # Amperes
MIN_STATION_CURRENT = 6  # Below this -> pause
MAX_STATIONS = 3
DEFAULT_VOLTAGE = 230

# Ramp control
DEFAULT_RAMP_UP_DELAY = 30  # seconds
RAMP_DOWN_DELAY = 0  # immediate
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
EVSE_OFFLINE_TIMEOUT = 90  # seconds without message -> offline
PV_STALE_TIMEOUT = 60  # seconds without PV data -> stale
MQTT_RECONNECT_DELAY = 5  # seconds

# HA Supervisor API
HA_SUPERVISOR_API_URL = "http://supervisor/core/api"

# Overbooking tolerance buffer
ACTUAL_TOLERANCE = 1.0  # A - station is "satisfied" if actual >= alloc - this
SLACK_BUFFER = 0.5  # A - keep this buffer when trimming allocation
OVERBOOKING_ITERATIONS = 3  # convergence iterations

# Safety
SAFETY_MARGIN = 2.0  # A - emergency scale-down triggers at limit - margin

# OpenEVSE MQTT topic suffixes (relative to base topic)
EVSE_TOPIC_AMP = "amp"  # Actual current (mA, divide by 1000)
EVSE_TOPIC_PILOT = "pilot"  # Pilot current (A)
EVSE_TOPIC_STATE = "state"  # EVSE state code
EVSE_TOPIC_WH = "wh"  # Session energy (Wh)
EVSE_TOPIC_OVERRIDE = "override"  # Override command endpoint

# OpenEVSE state codes
EVSE_STATE_NOT_CONNECTED = 1
EVSE_STATE_CONNECTED = 2
EVSE_STATE_CHARGING = 3
EVSE_STATE_ERROR = 4
EVSE_STATE_DISABLED = 254

# Load manager publish topics
LM_TOPIC_MODE = "loadmanager/mode"
LM_TOPIC_MODE_SET = "loadmanager/mode/set"
LM_TOPIC_TOTAL_ALLOCATED = "loadmanager/total_allocated"
LM_TOPIC_STATUS = "loadmanager/status"
LM_TOPIC_CONFIG_HYSTERESIS = "loadmanager/config/hysteresis"
LM_TOPIC_CONFIG_HYSTERESIS_SET = "loadmanager/config/hysteresis/set"
LM_TOPIC_CONFIG_RAMP_DELAY = "loadmanager/config/ramp_delay"
LM_TOPIC_CONFIG_RAMP_DELAY_SET = "loadmanager/config/ramp_delay/set"

# Per-station publish topics (format with station_id)
LM_TOPIC_EVSE_SETPOINT = "evse/{}/setpoint"
LM_TOPIC_EVSE_ACTUAL = "evse/{}/actual_current"
LM_TOPIC_EVSE_STATE = "evse/{}/state"
LM_TOPIC_EVSE_ENERGY = "evse/{}/energy"
LM_TOPIC_EVSE_ALLOCATED = "evse/{}/allocated"

# Persistence
STATE_FILE = "/data/state.json"

# HA Discovery
DEFAULT_HA_DISCOVERY_PREFIX = "homeassistant"
DEVICE_IDENTIFIER = "openevse_pv_loadmanager"
DEVICE_NAME = "OpenEVSE PV Load Manager"
DEVICE_MANUFACTURER = "Custom"
DEVICE_MODEL = "PV Load Manager v1.0"
