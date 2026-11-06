"""Climate platform for ha-hatachi."""

import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.components.climate.const import PRESET_NONE
from homeassistant.const import UnitOfTemperature

from . import HitachiConfigEntry
from .coordinator import Coordinator
from .const import (
    DOMAIN,
    KEY_CODE, KEY_NAME, KEY_XKQ_TYPE,
    KEY_STATE, KEY_TARGET_TEMP, KEY_MODE, KEY_FAN_SPEED, KEY_CUR_TEMP,
    CTRL_ONOFF, CTRL_TEMP, CTRL_MODE, CTRL_WIND,
    DEVICE_TYPE_NAMES, DEVICE_TYPE_FRESH_AIR,
    MODE_OFF, MODE_COOL, MODE_DRY, MODE_FAN_ONLY, MODE_HEAT,
    XKQ_MODE_FLOOR_HEAT, KEY_XKQ_MODE,
    PRESET_FLOOR_HEAT,
    FAN_LOW, FAN_MEDIUM, FAN_HIGH,
)

_LOGGER = logging.getLogger(__name__)

# Mapping: API mode value -> HA HVACMode (both iu29Mode and xkq21Mode use
# these values for normal operation; 送风/fan_only = 3 really exists).
# 地暖 is a separate wired-controller mode (xkq21Mode=11) and is surfaced
# through preset_mode, because HA's set_hvac_mode only accepts standard modes.
HVAC_MODES = {
    MODE_OFF: HVACMode.OFF,
    MODE_COOL: HVACMode.COOL,
    MODE_DRY: HVACMode.DRY,
    MODE_FAN_ONLY: HVACMode.FAN_ONLY,
    MODE_HEAT: HVACMode.HEAT,
}

# Modes that use the heating temperature range (heatMin/heatMax)
HEAT_RANGE_MODES = (MODE_HEAT, XKQ_MODE_FLOOR_HEAT)

# Mapping: API fan value -> HA fan mode string
FAN_MODES = {
    FAN_LOW: "low",
    FAN_MEDIUM: "medium",
    FAN_HIGH: "high",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HitachiConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    devices = coordinator.get_devices()
    entities = []
    for home_id, home_devices in devices.items():
        for xkq in home_devices["xkqList"]:
            entities.append(
                HitachiClimate(home_id, xkq[KEY_CODE], coordinator)
            )
    _LOGGER.debug("Adding %d climate entities", len(entities))
    async_add_entities(entities)


class HitachiClimate(CoordinatorEntity[Coordinator], ClimateEntity):
    """Climate entity for a single Hisense Hitachi indoor unit."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 1.0
    # Enables entity translations for preset_mode values, so the custom
    # "floor_heat" preset is displayed as 地暖 in zh-Hans / "Floor heating"
    # in English. The underlying preset value stays "floor_heat", so
    # automations and climate.set_preset_mode calls are unchanged.
    _attr_translation_key = "hitachi_climate"

    def __init__(self, home_id: str, xkq_code: str, coordinator: Coordinator):
        super().__init__(coordinator)
        self._home_id = home_id
        self._xkq_code = xkq_code
        self._is_fresh_air = False
        self._last_mode_floor_heat = False
        self._heat_min, self._heat_max = 16, 32
        self._cold_min, self._cold_max = 16, 32
        self._update_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_state()
        self.async_write_ha_state()

    def _update_state(self):
        dev = self.coordinator.get_data(self._home_id, self._xkq_code)
        if dev:
            # Device type detection (use xkqType = API iuType, not deviceType which is always "1")
            device_type = dev.get(KEY_XKQ_TYPE, "")
            self._is_fresh_air = (device_type == DEVICE_TYPE_FRESH_AIR)

            self._attr_name = dev.get(KEY_NAME, f"Hitachi {self._xkq_code}")
            self._attr_unique_id = f"hitachi-{self._home_id}-{self._xkq_code}-climate"
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, f"hitachi_{self._home_id}_{self._xkq_code}")},
                name=self._attr_name,
                manufacturer="Hisense Hitachi",
                model=DEVICE_TYPE_NAMES.get(device_type, "未知"),
            )

            # Supported features: fresh air has no temperature control
            if self._is_fresh_air:
                self._attr_supported_features = ClimateEntityFeature.FAN_MODE
            else:
                self._attr_supported_features = (
                    ClimateEntityFeature.TARGET_TEMPERATURE
                    | ClimateEntityFeature.FAN_MODE
                    | ClimateEntityFeature.PRESET_MODE
                )

            self._attr_target_temperature = dev.get(KEY_TARGET_TEMP)
            self._attr_current_temperature = dev.get(KEY_CUR_TEMP)

            # Temperature limits reported by the device (fall back to 16-32)
            self._heat_min = dev.get("heatMin", 16)
            self._heat_max = dev.get("heatMax", 32)
            self._cold_min = dev.get("coldMin", 16)
            self._cold_max = dev.get("coldMax", 32)

            # ---- On/off from iu28Onoff; 地暖 from the wired controller ----
            onoff = dev.get(KEY_STATE, 0)
            mode = dev.get(KEY_MODE, MODE_COOL)
            panel_mode = dev.get(KEY_XKQ_MODE, 0)
            self._attr_preset_mode = None
            # xkq21Mode=11 is 地暖. In that state the indoor unit still
            # reports iu29Mode=3 (送风), so the panel mode is the only
            # reliable discriminator between 送风 and 地暖.
            if panel_mode:
                self._last_mode_floor_heat = (
                    panel_mode == XKQ_MODE_FLOOR_HEAT
                )
            floor_heat = (
                panel_mode == XKQ_MODE_FLOOR_HEAT
                or (not panel_mode and self._last_mode_floor_heat)
            )
            if onoff == 0:
                self._attr_hvac_mode = HVACMode.OFF
            elif floor_heat:
                self._attr_hvac_mode = HVACMode.HEAT
                self._attr_preset_mode = PRESET_FLOOR_HEAT
            elif self._is_fresh_air:
                self._attr_hvac_mode = HVACMode.FAN_ONLY
            else:
                self._attr_hvac_mode = HVAC_MODES.get(mode, HVACMode.COOL)

            self._attr_fan_mode = FAN_MODES.get(
                dev.get(KEY_FAN_SPEED, FAN_LOW), "off"
            )
        else:
            self._attr_target_temperature = None
            self._attr_current_temperature = None
            self._attr_hvac_mode = HVACMode.OFF
            self._attr_preset_mode = None
            self._attr_fan_mode = "off"

    @property
    def hvac_modes(self):
        if self._is_fresh_air:
            return [HVACMode.OFF, HVACMode.FAN_ONLY]
        # mode 3 is a genuine 送风 mode; 地暖 is a separate preset.
        return [
            HVACMode.OFF, HVACMode.COOL, HVACMode.DRY,
            HVACMode.FAN_ONLY, HVACMode.HEAT,
        ]

    @property
    def preset_modes(self):
        """Floor heating (地暖) is exposed as a custom preset."""
        if self._is_fresh_air:
            return [PRESET_NONE]
        return [PRESET_NONE, PRESET_FLOOR_HEAT]

    @property
    def supported_preset_modes(self):
        return self.preset_modes

    def _current_api_mode(self) -> int:
        """Current API mode value, derived from hvac_mode + preset."""
        if self._attr_preset_mode == PRESET_FLOOR_HEAT:
            return XKQ_MODE_FLOOR_HEAT
        return {v: k for k, v in HVAC_MODES.items()}.get(
            self._attr_hvac_mode, MODE_COOL
        )

    @property
    def min_temp(self):
        """Minimum temperature by mode: heating/floor heating uses heatMin."""
        if self._current_api_mode() in HEAT_RANGE_MODES:
            return float(self._heat_min)
        return float(self._cold_min)

    @property
    def max_temp(self):
        """Maximum temperature by mode: heating/floor heating uses heatMax."""
        if self._current_api_mode() in HEAT_RANGE_MODES:
            return float(self._heat_max)
        return float(self._cold_max)

    @property
    def fan_modes(self):
        return list(FAN_MODES.values())

    # ---- Control methods ----

    async def async_set_temperature(self, **kwargs):
        target_temp = kwargs.get("temperature")
        if target_temp is not None:
            # Control API uses flat key "temp", not "iu31Temp"
            await self.coordinator.control(
                self._home_id, self._xkq_code, {CTRL_TEMP: int(target_temp)}
            )
            self._attr_target_temperature = target_temp
            self.async_write_ha_state()

    async def async_turn_on(self):
        """Power on: restore 地暖 when that was the last active mode."""
        if self._last_mode_floor_heat:
            await self.async_set_preset_mode(PRESET_FLOOR_HEAT)
        else:
            await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode | str):
        if hvac_mode == HVACMode.OFF:
            cmd = {CTRL_ONOFF: 0}
            self._attr_hvac_mode = HVACMode.OFF
            self._attr_preset_mode = None
            # Keep the 地暖 memory so a later power-on restores it.
        else:
            if self._is_fresh_air:
                mode_key = MODE_FAN_ONLY
                cmd = {CTRL_ONOFF: 1, CTRL_MODE: mode_key}
            elif self._last_mode_floor_heat and hvac_mode == HVACMode.HEAT:
                # Panel is in 地暖 (xkq21Mode=11). Do NOT send mode=4: the
                # cloud would kick the panel out of 地暖 into normal heating.
                cmd = {CTRL_ONOFF: 1}
                self._attr_preset_mode = PRESET_FLOOR_HEAT
            else:
                mode_key = {v: k for k, v in HVAC_MODES.items()}.get(
                    hvac_mode, MODE_COOL
                )
                cmd = {CTRL_ONOFF: 1, CTRL_MODE: mode_key}
                self._attr_preset_mode = None
                self._last_mode_floor_heat = False
            self._attr_hvac_mode = hvac_mode
        await self.coordinator.control(self._home_id, self._xkq_code, cmd)
        self.async_write_ha_state()

    async def async_set_preset_mode(self, preset_mode: str):
        if preset_mode == PRESET_FLOOR_HEAT:
            # Power on and switch the wired controller into 地暖 mode.
            _LOGGER.debug("Setting floor heating on %s", self._xkq_code)
            await self.coordinator.control_floor_heat(
                self._home_id, self._xkq_code, True
            )
            self._attr_preset_mode = PRESET_FLOOR_HEAT
            self._attr_hvac_mode = HVACMode.HEAT
            self._last_mode_floor_heat = True
        elif preset_mode == PRESET_NONE:
            # Turning 地暖 off only changes iu28Onoff (confirmed by captures);
            # keep the panel mode untouched so power-on restores 地暖.
            _LOGGER.debug("Floor heating off on %s", self._xkq_code)
            await self.coordinator.control_floor_heat(
                self._home_id, self._xkq_code, False
            )
            self._attr_preset_mode = None
            self._attr_hvac_mode = HVACMode.OFF
        self.async_write_ha_state()

    async def async_set_fan_mode(self, fan_mode: str):
        fan_key = {v: k for k, v in FAN_MODES.items()}.get(fan_mode, FAN_LOW)
        # Control API uses flat key "wind", not "iu30Wind"
        await self.coordinator.control(
            self._home_id, self._xkq_code, {CTRL_WIND: fan_key}
        )
        self._attr_fan_mode = fan_mode
        self.async_write_ha_state()
