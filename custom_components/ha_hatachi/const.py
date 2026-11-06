"""Constants for ha-hatachi integration."""

DOMAIN = "ha_hatachi"
CONF_TOKEN = "token"
CONF_REFRESH_TOKEN = "refresh_token"

# API
API_DOMAIN = "https://1app.hicloud.hisensehitachi.com"
API_LOGIN = "login"
API_RT_LOGIN = "rtLogin"
API_HOMES = "api/apphome/homes"
API_STATUS = "api/appstatus/homes"
API_CONTROL = "api/appcontrol/cmds/multiIuOuCtrl"

# Request headers (from working plugin)
HEADER_APIKEY = "1QiLCJhbGciOiJIUzI1NiJ9"
HEADER_APPID = "com.hisensehitachi.iez2"
HEADER_OS = "Android"
HEADER_VERSION = "7.5.3.260417183002_release"
HEADER_APPTAG = "V3"
HEADER_LOCALE = "zh_CN"
HEADER_HOST = "1app.hicloud.hisensehitachi.com"
HEADER_USER_AGENT = "Dalvik/2.1.0 (Linux; U; Android 12; V2304A Build/W528JS)"

# Login params (from working plugin)
JG_REG_ID = "1507bfd3f6ce767df06"
LOGIN_VERSION = 0

# Response codes
CODE_OK = "200"
CODE_UNAUTHORIZED = "401"

# Device keys (internal storage)
KEY_CODE = "xkqCode"
KEY_NAME = "xkqName"
KEY_HOME_ID = "homeId"
# ---- Status fields (read from API) ----
KEY_STATE = "iu28Onoff"
KEY_TARGET_TEMP = "iu31Temp"
KEY_MODE = "iu29Mode"
KEY_FAN_SPEED = "iu30Wind"
KEY_CUR_TEMP = "iu39Ti"
KEY_TS = "timestamp"
# ---- Device metadata ----
KEY_DEVICE_TYPE = "deviceType"
KEY_XKQ_TYPE = "xkqType"
KEY_HEAT_MAX = "heatMax"
KEY_HEAT_MIN = "heatMin"
KEY_COLD_MAX = "coldMax"
KEY_COLD_MIN = "coldMin"
KEY_MAC = "macImei"
# ---- Control payload fields (needed per device) ----
KEY_IU_NO = "iuNo"
KEY_SYSTEM_NO = "systemNo"
KEY_IU_SN = "iuSn"
KEY_IU_TYPE = "iuType"
KEY_IEZ_CODE = "iezCode"
KEY_VERSION_PROTOCOL = "versionModbusProtocol"
# ---- Control command keys (flat names, not iuXX prefixed) ----
CTRL_ONOFF = "onoff"
CTRL_TEMP = "temp"
CTRL_MODE = "mode"
CTRL_WIND = "wind"

# Device types
DEVICE_TYPE_CLIMATE = "05"
DEVICE_TYPE_SPECIAL = "03"
DEVICE_TYPE_FRESH_AIR = "0D"

DEVICE_TYPE_NAMES = {
    DEVICE_TYPE_CLIMATE: "标准空调",
    DEVICE_TYPE_SPECIAL: "特殊机型",
    DEVICE_TYPE_FRESH_AIR: "新风系统",
}

# HVAC mode mapping (from working plugin climate.py)
# mode values in API: 0=off, 1=cool, 2=dry, 3=fan_only, 4=heat
# This mapping is shared by the indoor-unit channel (iu29Mode) and the
# wired-controller channel (xkq21Mode); real captures show 1<->1 and 2<->2
# on two untouched rooms, so mode 3 really IS 送风 (fan_only).
MODE_OFF = 0
MODE_COOL = 1
MODE_DRY = 2
MODE_FAN_ONLY = 3
MODE_HEAT = 4

# 地暖 (floor heating) is a wired-controller mode, not an indoor-unit mode.
# Verified 2026-11-06 on a gateway + type-F panel:
#   - state:   panel xkq21Mode=11 while the indoor unit keeps reporting
#              iu29Mode=3 (送风). iu29Mode == xkq21Mode & 7.
#   - control: POST multiIuOuCtrl, ctrlType "HA420",
#              xkqCtrlList[].ctrlJson = {"onoff": 1, "mode": 11}
#              -> code 200 and xkq21Mode becomes 11.
# The indoor-unit channel (ctrlList[].ctrlJson.mode) only accepts 1-4 and
# cannot switch into 地暖.
XKQ_MODE_FLOOR_HEAT = 11
KEY_XKQ_MODE = "xkq21Mode"
FLOOR_HEAT_PANEL_CMD = {CTRL_ONOFF: 1, CTRL_MODE: XKQ_MODE_FLOOR_HEAT}

# Preset name for floor heating (地暖) exposed through preset_mode.
# HA's climate.set_hvac_mode only accepts standard HVACMode values, so the
# floor heating is surfaced as a custom preset instead of a custom HVAC mode.
PRESET_FLOOR_HEAT = "floor_heat"

# Fan speed mapping (from API status: 1=low, 2=medium, 3=high)
FAN_LOW = 1
FAN_MEDIUM = 2
FAN_HIGH = 3
