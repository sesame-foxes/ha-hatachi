"""DataUpdateCoordinator for ha-hatachi."""

from datetime import timedelta, datetime
import logging
import time

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.exceptions import ConfigEntryAuthFailed

from .const import (
    CODE_OK, CODE_UNAUTHORIZED,
    KEY_STATE, KEY_TARGET_TEMP, KEY_MODE, KEY_FAN_SPEED, KEY_CUR_TEMP,
    KEY_XKQ_MODE, KEY_TS, KEY_CODE, KEY_HOME_ID, KEY_DEVICE_TYPE, KEY_XKQ_TYPE,
    KEY_IU_NO, KEY_SYSTEM_NO, KEY_IU_SN, KEY_IU_TYPE, KEY_IEZ_CODE,
    KEY_VERSION_PROTOCOL,
    CTRL_ONOFF, XKQ_MODE_FLOOR_HEAT, FLOOR_HEAT_PANEL_CMD,
)
from .api import HitachiApi

_LOGGER = logging.getLogger(__name__)

INTERVAL = timedelta(seconds=10)
PANEL_POLL_INTERVAL = timedelta(seconds=20)


def _as_number(value, default):
    """Tolerate None / string / unexpected types in status fields."""
    try:
        return type(default)(value)
    except (TypeError, ValueError):
        return default


class Coordinator(DataUpdateCoordinator[dict]):
    """Coordinator for Hisense Hitachi devices."""

    def __init__(
        self,
        hass: HomeAssistant,
        username: str,
        password: str,
        token: str,
        refresh_token: str,
    ):
        super().__init__(
            hass,
            _LOGGER,
            name="Hitachi",
            update_interval=INTERVAL,
            always_update=True,
        )
        self._hass = hass
        self._username = username
        self._password = password
        self._token = token
        self._refresh_token = refresh_token
        self._api = HitachiApi(username, password, token)
        self._devices: dict[str, dict] = {}  # home_id -> {"xkqList": [...]}
        self._ts = datetime.now()
        self._last_relogin: datetime | None = None
        self._panels: dict[str, list[dict]] = {}  # home_id -> wired controllers
        self._panel_modes: dict[str, dict[str, int]] = {}  # home_id -> {iuNo: mode}
        self._last_panel_poll: datetime | None = None

    async def _async_setup(self):
        """Authenticate and discover devices."""
        res = await self._auth()
        if not res:
            raise ConfigEntryAuthFailed

        for home in res["data"]["homeList"]:
            home_id = home[KEY_HOME_ID]
            home_data = await self._api.get_home_detail(home_id, self._hass)
            if home_data and home_data.get("code") == CODE_UNAUTHORIZED:
                if await self._relogin_once():
                    home_data = await self._api.get_home_detail(home_id, self._hass)
            if not home_data or home_data.get("code") != CODE_OK:
                _LOGGER.warning("Failed to get home detail for home_id %s", home_id)
                continue

            self._panels[home_id] = self._api.extract_panel_devices(home_data)
            devices = self._api.extract_devices(home_data, home_id)
            if not devices:
                _LOGGER.warning("No devices found for home_id %s", home_id)
                continue
            self._devices[home_id] = {"xkqList": devices}

        _LOGGER.debug("Devices discovered: %s", list(self._devices))

    async def _async_update_data(self) -> dict:
        """Poll indoor-unit and wired-controller status."""
        await self._refresh_auth()

        try:
            for home_id, home_devices in self._devices.items():
                xkq_list = home_devices["xkqList"]
                res = await self._fetch_status(home_id, xkq_list)
                if not res or res.get("code") != CODE_OK:
                    continue

                status_list = res.get("data", {}).get("statusList", [])
                panel_modes = await self._poll_panel_modes(home_id)

                status_map = {}
                for group in status_list:
                    for value in group.get("values", []):
                        iu_id = value.get("iuId")
                        if iu_id:
                            status_map[iu_id] = value

                for xkq in xkq_list:
                    xkq_code = xkq[KEY_CODE]
                    matched = status_map.get(xkq_code)
                    if matched is None:
                        _LOGGER.warning("No status for device %s", xkq_code)
                        continue

                    xkq.update({
                        KEY_STATE: _as_number(matched.get("iu28Onoff"), 0),
                        KEY_TARGET_TEMP: _as_number(matched.get("iu31Temp"), 26.0),
                        KEY_MODE: _as_number(matched.get("iu29Mode"), 1),
                        KEY_FAN_SPEED: _as_number(matched.get("iu30Wind"), 2),
                        KEY_CUR_TEMP: _as_number(matched.get("iu39Ti"), 25.0),
                        # 地暖 is only visible on the wired controller
                        KEY_XKQ_MODE: _as_number(
                            panel_modes.get(xkq_code[-2:]), 0
                        ),
                        KEY_TS: int(time.time()),
                    })

            return self._devices
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}")

    async def _poll_panel_modes(self, home_id: str) -> dict[str, int]:
        """Return {iuNo: xkq21Mode}; 地暖 (11) exists only on this channel."""
        now = datetime.now()
        if (self._last_panel_poll is not None
                and now - self._last_panel_poll < PANEL_POLL_INTERVAL):
            return self._panel_modes.get(home_id, {})

        panels = self._panels.get(home_id, [])
        if not panels:
            return {}
        self._last_panel_poll = now
        try:
            res = await self._api.get_panel_status(home_id, panels, self._hass)
        except Exception as err:
            _LOGGER.warning("Panel status failed for home %s: %s", home_id, err)
            return self._panel_modes.get(home_id, {})
        if not res or res.get("code") != CODE_OK:
            return self._panel_modes.get(home_id, {})

        by_code = {
            item.get("xkqCode"): item
            for item in res.get("data", {}).get("xkqStatusList", [])
        }
        modes: dict[str, int] = {}
        for panel in panels:
            mode = by_code.get(panel["xkqCode"], {}).get(KEY_XKQ_MODE)
            for iu_no in panel.get("iuNos", []):
                modes[iu_no] = _as_number(mode, 0)
        self._panel_modes[home_id] = modes
        return modes

    async def _auth(self):
        """Authenticate and store new token."""
        par = await self._api.login(self._hass)
        if not par:
            return False
        self._token = self._api.token
        return par

    async def _relogin_once(self) -> bool:
        """Re-login after a 401, throttled to at most once per minute."""
        now = datetime.now()
        if self._last_relogin and now - self._last_relogin < timedelta(minutes=1):
            return False
        self._last_relogin = now
        try:
            _LOGGER.warning("Session invalid (401), re-authenticating")
            return bool(await self._auth())
        except Exception:
            _LOGGER.error("re-login failed", exc_info=True)
            return False

    async def _fetch_status(self, home_id: str, xkq_list: list) -> dict | None:
        """Fetch status with 401 self-healing and transient-error tolerance."""
        try:
            res = await self._api.get_status(home_id, xkq_list, self._hass)
            if res and res.get("code") == CODE_UNAUTHORIZED:
                if await self._relogin_once():
                    res = await self._api.get_status(home_id, xkq_list, self._hass)
            return res
        except Exception as err:
            # e.g. "Server disconnected without sending a response":
            # skip this poll instead of failing the whole coordinator.
            _LOGGER.warning("Status request failed for home %s: %s", home_id, err)
            return None

    async def _refresh_auth(self):
        """Re-login once per day."""
        now = datetime.now()
        if now - self._ts > timedelta(days=1):
            self._ts = now
            try:
                await self._auth()
            except Exception:
                _LOGGER.error("auth poll failed", exc_info=True)

    # ---- Public helpers ----

    def get_devices(self) -> dict:
        return self._devices

    def get_data(self, home_id: str, xkq_code: str) -> dict | None:
        devices = self._devices.get(home_id, {}).get("xkqList", [])
        for dev in devices:
            if dev[KEY_CODE] == xkq_code:
                return dev
        return None

    async def control(self, home_id: str, xkq_code: str, cmd_dict: dict):
        """Send a command to an indoor unit."""
        dev = self.get_data(home_id, xkq_code)
        if not dev:
            _LOGGER.error("Device not found: %s/%s", home_id, xkq_code)
            return None
        device_info = {
            KEY_HOME_ID: home_id,
            KEY_CODE: xkq_code,
            KEY_DEVICE_TYPE: dev.get(KEY_DEVICE_TYPE, "1"),
            KEY_XKQ_TYPE: dev.get(KEY_XKQ_TYPE, ""),
            KEY_IEZ_CODE: dev.get(KEY_IEZ_CODE, xkq_code[:12]),
            KEY_IU_NO: dev.get(KEY_IU_NO, ""),
            KEY_SYSTEM_NO: dev.get(KEY_SYSTEM_NO, ""),
            KEY_IU_SN: dev.get(KEY_IU_SN, dev.get("macImei", "")),
            KEY_IU_TYPE: dev.get(KEY_IU_TYPE, ""),
            KEY_VERSION_PROTOCOL: dev.get(KEY_VERSION_PROTOCOL, 11),
        }
        res = await self._api.control(device_info, cmd_dict, self._hass)
        if res and res.get("code") == CODE_UNAUTHORIZED:
            if await self._relogin_once():
                res = await self._api.control(device_info, cmd_dict, self._hass)
        return res

    def _panel_for(self, home_id: str, iu_code: str) -> dict | None:
        """Find the wired controller paired with an indoor unit (by iuNo)."""
        iu_no = iu_code[-2:]
        for panel in self._panels.get(home_id, []):
            if iu_no in panel.get("iuNos", []):
                return panel
        return None

    async def control_floor_heat(
        self, home_id: str, iu_code: str, turn_on: bool
    ):
        """Turn 地暖 on/off.

        Power on/off goes through the indoor-unit channel. Switching INTO
        地暖 additionally needs the wired-controller command
        {"onoff":1,"mode":11} (verified: xkq21Mode becomes 11).
        """
        if not turn_on:
            return await self.control(home_id, iu_code, {CTRL_ONOFF: 0})

        res = await self.control(home_id, iu_code, {CTRL_ONOFF: 1})
        dev = self.get_data(home_id, iu_code) or {}
        if dev.get(KEY_XKQ_MODE) == XKQ_MODE_FLOOR_HEAT:
            return res

        panel = self._panel_for(home_id, iu_code)
        if not panel:
            _LOGGER.warning(
                "No wired controller paired with %s; cannot switch into 地暖",
                iu_code,
            )
            return res
        try:
            result = await self._api.control_panel_mode(
                home_id, panel, FLOOR_HEAT_PANEL_CMD, self._hass
            )
            if result and result.get("code") == CODE_UNAUTHORIZED:
                if await self._relogin_once():
                    result = await self._api.control_panel_mode(
                        home_id, panel, FLOOR_HEAT_PANEL_CMD, self._hass
                    )
            if result and result.get("code") == CODE_OK:
                # Reflect the new mode immediately; the 20 s panel poll will
                # confirm it from the device afterwards.
                self._panel_modes.setdefault(home_id, {})[iu_code[-2:]] = (
                    XKQ_MODE_FLOOR_HEAT
                )
                dev[KEY_XKQ_MODE] = XKQ_MODE_FLOOR_HEAT
            else:
                _LOGGER.warning("Setting 地暖 mode failed: %s", result)
        except Exception as err:
            _LOGGER.warning("Setting 地暖 mode failed: %s", err)
        return res
