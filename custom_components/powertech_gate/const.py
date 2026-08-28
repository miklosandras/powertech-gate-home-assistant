"""Constants for the Powertech PW200 integration."""

DOMAIN = "powertech_gate"

BACKEND_BASE_URL = "https://backend.powertech-automation.com"

# Static OAuth application authorization embedded in the official Android Powertech/EyeOpen public client. It is not a per-user credential.
BACKEND_REST_TOKEN = (
    "Basic "
    "cE1Gdk9TQjRLeVNHUjdQREtmTWtscjRYeGJXenloMVFjMHY3Slg0ODpqTkllMXdWREN1MTRDNDJVNEpn"
    "MEN6VEcxSm9iWW5wdmhocFZoMTBod2taS1puUDVkQlM5a1ZoWmpJeEI2Q2ZIcjdlVEdUM2NjbmNCbnda"
    "ZVlvb3I1TWJrZkxtSnBoa3lCUnI1c2FXT1BSYUF0ZVR1TUVMWVlmV1FLZ3JWSUhIMA=="
)

CONF_SETUP_METHOD = "setup_method"
SETUP_ACCOUNT = "account"
SETUP_MANUAL = "manual"

CONF_ENDPOINT = "endpoint"
CONF_THING_ID = "thing_id"
CONF_CERT_PATH = "cert_path"
CONF_KEY_PATH = "key_path"
CONF_CA_PATH = "ca_path"
CONF_SOURCE_ID = "source_id"
CONF_DEVICE_LABEL = "device_label"
CONF_DEVICE_TYPE = "device_type"
CONF_PED_SUPPORTED = "pedestrian_supported"
CONF_EXPERIMENTAL_MODEL = "experimental_model"
CONF_PROTOCOL_VALIDATED = "protocol_validated"
CONF_PIN_VERIFIED = "pin_verified"
CONF_REFRESH_INTERVAL = "refresh_interval"
CONF_ENABLE_DEBUG_ATTRIBUTES = "enable_debug_attributes"

DEFAULT_ENDPOINT = "a1acnzxd6t4jcn-ats.iot.eu-central-1.amazonaws.com"
DEFAULT_SOURCE_ID = "P0045F3C"
DEFAULT_PORT = 8883

STATE_CLOSED = "closed"
STATE_OPENING = "opening"
STATE_OPEN = "open"
STATE_CLOSING = "closing"
STATE_STOPPED = "stopped"
STATE_PARTIAL_OPENING = "partial_opening"
STATE_PARTIAL_OPEN = "partial_open"
STATE_FACTORY = "factory_default"
STATE_UNKNOWN = "unknown"

DEFAULT_REFRESH_INTERVAL = 60

KNOWN_PEDESTRIAN_MODELS = {"PS20088", "PS20088D"}
