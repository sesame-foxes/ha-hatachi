"""API client for Hisense Hitachi iEZ2."""

import time
import logging
import asyncio
from collections import defaultdict

from homeassistant.helpers.httpx_client import get_async_client

from .const import (
    API_DOMAIN, API_LOGIN, API_HOMES, API_STATUS, API_CONTROL,
    HEADER_APIKEY, HEADER_APPID, HEADER_OS, HEADER_VERSION,
    HEADER_APPTAG, HEADER_LOCALE, HEADER_HOST, HEADER_USER_AGENT,
    JG_REG_ID, LOGIN_VERSION, CODE_OK,
    KEY_CODE, KEY_NAME, KEY_HOME_ID, KEY_DEVICE_TYPE, KEY_XKQ_TYPE, KEY_MAC,
    KEY_IU_NO, KEY_SYSTEM_NO, KEY_IU_SN, KEY_IU_TYPE, KEY_IEZ_CODE,
    KEY_VERSION_PROTOCOL,
    KEY_STATE, KEY_TARGET_TEMP, KEY_MODE, KEY_FAN_SPEED, KEY_CUR_TEMP, KEY_TS,
    FAN_MEDIUM,
)

_LOGGER = logging.getLogger(__name__)


class HitachiApi:
    """HTTP client for Hisense Hitachi cloud API."""

    def __init__(self, username: str, password: str, token: str = ""):
        self._username = username
        self._password = password
        self._token = token

    def _headers(self) -> dict:
        h = {
            "Host": HEADER_HOST,
            "accept-charset": "UTF-8",
            "x-his-locale": HEADER_LOCALE,
            "x-his-apikey": HEADER_APIKEY,
            "x-his-timestamp": str(int(time.time() * 1000)),
            "x-his-appid": HEADER_APPID,
            "x-his-os": HEADER_OS,
            "x-his-version": HEADER_VERSION,
            "x-his-apptag": HEADER_APPTAG,
            "content-type": "application/json",
            "user-agent": HEADER_USER_AGENT,
            "accept-encoding": "gzip",
        }
        if self._token:
            h["authorization"] = f"Bearer {self._token}"
        return h

    # ---- Auth ----

    async def login(self, hass) -> dict | None:
        """POST /login with JSON body (exact match to working plugin)."""
        url = f"{API_DOMAIN}/{API_LOGIN}"
        body = {
            "phoneNo": self._username,
            "password": self._password,
            "jgRegId": JG_REG_ID,
            "version": LOGIN_VERSION,
        }
        _LOGGER.debug("login: %s", url)
        async with get_async_client(hass) as client:
            resp = await client.post(url, json=body, headers=self._headers())
            data = resp.json()
        _LOGGER.debug("login response code=%s", data.get("code"))
        if data.get("code") == CODE_OK:
            user = data["data"]["user"]
            self._token = user["token"]
            return data
        _LOGGER.error("login failed: %s", data)
        return None

    async def refresh_auth(self, hass) -> dict | None:
        """Re-login to refresh token."""
        return await self.login(hass)

    # ---- Home & Device Discovery ----

    async def get_home_detail(self, home_id: str, hass) -> dict | None:
        """GET /api/apphome/homes/{home_id}"""
        url = f"{API_DOMAIN}/{API_HOMES}/{home_id}"
        _LOGGER.debug("get_home_detail: %s", url)
        async with get_async_client(hass) as client:
            resp = await client.get(url, headers=self._headers())
            data = resp.json()
        if data.get("code") == CODE_OK:
            return data
        _LOGGER.error("get_home_detail failed: %s", data)
        return data  # return raw response so coordinator can detect 401

    def extract_devices(self, home_data: dict, home_id: str) -> list[dict]:
        """Extract indoor units from home detail response.
        
        Matches the working plugin's logic:
        - Iterates homeDetail.deviceList[].iuList[]
        - deviceList[].type -> deviceType
        - iu.iuId, iu.iuName, iu.iuType, etc.
        """
        devices = []
        home_detail = home_data.get("data", {}).get("homeDetail", {})

        for device in home_detail.get("deviceList", []):
            device_type = device.get("type", "")
            iez_code = device.get("iezCode", "")
            version_proto = device.get("versionModbusProtocol", 11)
            for iu in device.get("iuList", []):
                dev = {
                    KEY_CODE: iu["iuId"],
                    KEY_NAME: iu.get("iuName", ""),
                    KEY_XKQ_TYPE: iu.get("iuType", ""),
                    KEY_DEVICE_TYPE: device_type,
                    KEY_HOME_ID: home_id,
                    # Device identity for control commands
                    KEY_IEZ_CODE: iez_code,
                    KEY_IU_NO: iu.get("iuNo", ""),
                    KEY_SYSTEM_NO: iu.get("systemNo", ""),
                    KEY_IU_SN: iu.get("iuSn", ""),
                    KEY_IU_TYPE: iu.get("iuType", ""),
                    KEY_VERSION_PROTOCOL: version_proto,
                    # Capability limits
                    "heatMax": iu.get("heatMax", 32),
                    "heatMin": iu.get("heatMin", 16),
                    "coldMax": iu.get("coldMax", 32),
                    "coldMin": iu.get("coldMin", 16),
                    KEY_MAC: iu.get("iuSn", ""),
                    KEY_TS: 0,
                    # Default state fields (will be filled by status poll)
                    KEY_STATE: 0,
                    KEY_TARGET_TEMP: 26.0,
                    KEY_MODE: 1,
                    KEY_FAN_SPEED: FAN_MEDIUM,
                    KEY_CUR_TEMP: 25.0,
                }
                devices.append(dev)
                _LOGGER.debug("found device: %s (%s)", iu["iuId"], iu.get("iuName", ""))

        return devices

    # ---- Wired controllers (room panels) ----

    def extract_panel_devices(self, home_data: dict) -> list[dict]:
        """Extract wired controllers, paired to indoor units by iuNo."""
        home_detail = home_data.get("data", {}).get("homeDetail", {})
        result = []
        for xkq in home_detail.get("xkqList", []):
            code = xkq.get("xkqCode")
            if not code:
                continue
            iu_nos = [
                str(iu.get("iuNo", "")).zfill(2)
                for iu in xkq.get("iuList", [])
                if iu.get("iuNo") not in (None, "")
            ]
            result.append({
                "xkqCode": code,
                "deviceType": xkq.get("type", "F"),
                "xkqType": xkq.get("xkqType", "0"),
                "iuNos": iu_nos,
            })
        return result

    async def get_panel_status(
        self, home_id: str, panels: list[dict], hass
    ) -> dict | None:
        """Read xkqStatusList; 地暖 mode (xkq21Mode) lives on this channel."""
        body = {
            "homeId": int(home_id),
            "noNetTip": True,
            "iuIdListGjy": [],
            "boxList": [],
            "xkqList": [
                {"xkqCode": panel["xkqCode"], "timestamp": 0}
                for panel in panels
            ],
            "xkqListGjy": [],
            "iuIdList": [],
        }
        url = f"{API_DOMAIN}/{API_STATUS}/{home_id}/status"
        async with get_async_client(hass) as client:
            resp = await client.post(url, json=body, headers=self._headers())
            return resp.json()

    # ---- Status ----

    async def get_status(self, home_id: str, devices: list[dict], hass) -> dict | None:
        """POST /api/appstatus/homes/{home_id}/status
        
        Body format matches the working plugin's req_status():
        {
          "homeId": int,
          "iuIdList": [
            {"iezCode": "xxx", "iuIds": [{"iuId": "xxx", "timestamp": 0}]}
          ],
          ...
        }
        """
        # Build iuIdList from devices, grouping by iezCode (first 12 chars)
        iez_groups: dict[str, list] = defaultdict(list)
        for dev in devices:
            full_code = dev[KEY_CODE]
            iez_code = full_code[:12]
            iez_groups[iez_code].append({
                "iuId": full_code,
                "timestamp": dev.get(KEY_TS, 0)
            })

        iu_id_list = [
            {"iezCode": iez, "iuIds": iu_ids}
            for iez, iu_ids in iez_groups.items()
        ]

        body = {
            "homeId": int(home_id),
            "noNetTip": True,
            "iuIdListGjy": [],
            "boxList": [],
            "xkqList": [],
            "xkqListGjy": [],
            "iuIdList": iu_id_list,
        }

        url = f"{API_DOMAIN}/{API_STATUS}/{home_id}/status"
        _LOGGER.debug("get_status: %s", url)
        async with get_async_client(hass) as client:
            resp = await client.post(url, json=body, headers=self._headers())
            data = resp.json()
        if data.get("code") == CODE_OK:
            return data
        _LOGGER.error("get_status failed: %s", data)
        return data  # return raw response so coordinator can detect 401

    # ---- Control ----

    async def control(self, device_info: dict, cmd_dict: dict, hass) -> dict | None:
        """POST /api/appcontrol/cmds/multiIuOuCtrl
        
        Uses ctrlList (NOT xkqCtrlList — real app always leaves xkqCtrlList empty).
        Structure matches the actual app capture:
        {
          "ctrlList": [{
            "iuCtrlInfo": [{
              "ctrlJson": {"onoff": 1, "temp": 16},
              "iuNo": "00",
              "iuSn": "...",
              "iuType": "0D",
              "systemNo": "01"
            }],
            "ouCtrlInfo": [],
            "deviceType": "1",
            "iezCode": "80CBBC468C35",
            "versionModbusProtocol": 11
          }],
          "xkqCtrlList": [],
          "homeId": 179079,
          "ctrlType": "HA420",
          ...
        }
        """
        body = {
            "ctrlList": [
                {
                    "iuCtrlInfo": [
                        {
                            "ctrlJson": cmd_dict,
                            "iuNo": device_info[KEY_IU_NO],
                            "iuSn": device_info[KEY_IU_SN],
                            "iuType": device_info[KEY_IU_TYPE],
                            "systemNo": device_info[KEY_SYSTEM_NO],
                        }
                    ],
                    "ouCtrlInfo": [],
                    "deviceType": device_info[KEY_DEVICE_TYPE],
                    "iezCode": device_info[KEY_IEZ_CODE],
                    "versionModbusProtocol": device_info.get(KEY_VERSION_PROTOCOL, 11),
                }
            ],
            "xkqCtrlList": [],
            "homeId": int(device_info[KEY_HOME_ID]),
            "ctrlType": "HA420",
            "regionCode": "0",
            "positionLat": 4.9e-324,
            "positionLng": 4.9e-324,
            "position1": "  ",
            "position2": "",
            "positionCity": "",
        }

        url = f"{API_DOMAIN}/{API_CONTROL}"
        _LOGGER.debug("control: %s ctrlJson=%s", url, cmd_dict)
        async with get_async_client(hass) as client:
            resp = await client.post(url, json=body, headers=self._headers())
            data = resp.json()
        _LOGGER.debug("control response code=%s", data.get("code"))
        # Wait a moment for the command to take effect
        await asyncio.sleep(3)
        return data

    async def control_panel_mode(
        self, home_id: str, panel: dict, cmd_dict: dict, hass
    ) -> dict | None:
        """Set the wired-controller mode (e.g. 地暖) via xkqCtrlList.

        Verified request: ctrlType "HA420", ctrlList empty, and one
        xkqCtrlList item {xkqCode, deviceType, xkqType, ctrlJson}.
        Unlike the indoor-unit channel, mode=11 is valid here.
        """
        body = {
            "ctrlList": [],
            "xkqCtrlList": [
                {
                    "xkqCode": panel["xkqCode"],
                    "deviceType": panel.get("deviceType", "F"),
                    "xkqType": panel.get("xkqType", "0"),
                    "ctrlJson": cmd_dict,
                }
            ],
            "homeId": int(home_id),
            "ctrlType": "HA420",
            "regionCode": "0",
            "positionLat": 4.9e-324,
            "positionLng": 4.9e-324,
            "position1": "  ",
            "position2": "",
            "positionCity": "",
        }
        url = f"{API_DOMAIN}/{API_CONTROL}"
        _LOGGER.debug(
            "panel control %s ctrlJson=%s", panel["xkqCode"], cmd_dict
        )
        async with get_async_client(hass) as client:
            resp = await client.post(url, json=body, headers=self._headers())
            data = resp.json()
        _LOGGER.debug("panel control response code=%s", data.get("code"))
        return data

    # ---- Token management ----

    @property
    def token(self) -> str:
        return self._token

    def set_token(self, token: str):
        self._token = token
