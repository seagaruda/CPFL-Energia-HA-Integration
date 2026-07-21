# -*- coding: utf-8 -*-
"""Sensors for the CPFL Energia integration."""
from __future__ import annotations

import asyncio
import datetime
import logging
import traceback
from datetime import timedelta
from typing import Any

import async_timeout
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    STATE_UNAVAILABLE,
    UnitOfEnergy,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import (
    ATTR_KEY_BILL_HISTORY,
    ATTR_KEY_CONSUMPTION_HISTORY,
    CONF_AUTH_TOKEN,
    CONF_DOCUMENT,
    CONF_INSTALLATIONS,
    CONF_SETTINGS,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
    SETTING_UPDATE_TIMEOUT,
    SUFFIX_BALANCE,
    SUFFIX_BILL_AMOUNT,
    SUFFIX_BILL_DUE_DATE,
    SUFFIX_BILL_REFERENCE_MONTH,
    SUFFIX_DAILY_AVERAGE_KWH,
    SUFFIX_LAST_BILL_AMOUNT,
    SUFFIX_LAST_BILL_DUE_DATE,
    SUFFIX_LAST_BILL_KWH,
    SUFFIX_LAST_MONTH_AMOUNT,
    SUFFIX_LAST_MONTH_KWH,
    SUFFIX_LAST_YEAR_AMOUNT,
    SUFFIX_LAST_YEAR_KWH,
    SUFFIX_TARIFF_FLAGS,
    SUFFIX_THIS_MONTH_ESTIMATE,
    SUFFIX_THIS_MONTH_KWH,
    SUFFIX_THIS_YEAR_AMOUNT,
    SUFFIX_THIS_YEAR_KWH,
)
from .cpfl_client import (
    CPFLError,
    CPFLAuthExpired,
    CPFLClient,
    NotLoggedIn,
)

_LOGGER = logging.getLogger(__name__)


def _mask_document(document: str | None) -> str:
    """Mask a CPF/CNPJ for logging, keeping only the last 4 digits."""
    if not document:
        return "***"
    digits = "".join(ch for ch in str(document) if ch.isdigit())
    if len(digits) <= 4:
        return "***"
    return f"***{digits[-4:]}"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    """Set up sensors from a config entry."""
    installations = config_entry.data.get(CONF_INSTALLATIONS, {})
    if not installations:
        _LOGGER.info("No installations in config, exit entry setup")
        return

    coordinator = CPFLCoordinator(hass, config_entry.entry_id)

    all_sensors: list[CPFLBaseSensor] = []
    for inst_num, _ in installations.items():
        sensors = [
            # Current bill
            CPFLCostSensor(coordinator, inst_num, SUFFIX_BILL_AMOUNT),
            CPFLEnergySensor(coordinator, inst_num, SUFFIX_LAST_BILL_KWH),
            CPFLStringSensor(coordinator, inst_num, SUFFIX_BILL_DUE_DATE),
            CPFLStringSensor(coordinator, inst_num, SUFFIX_BILL_REFERENCE_MONTH),
            # Balance
            CPFLCostSensor(coordinator, inst_num, SUFFIX_BALANCE),
            # This month
            CPFLEnergySensor(
                coordinator, inst_num, SUFFIX_THIS_MONTH_KWH,
                extra_state_attributes_key=ATTR_KEY_CONSUMPTION_HISTORY,
            ),
            CPFLCostSensor(coordinator, inst_num, SUFFIX_THIS_MONTH_ESTIMATE),
            # This year totals
            CPFLEnergySensor(coordinator, inst_num, SUFFIX_THIS_YEAR_KWH),
            CPFLCostSensor(coordinator, inst_num, SUFFIX_THIS_YEAR_AMOUNT),
            # Last month
            CPFLEnergySensor(coordinator, inst_num, SUFFIX_LAST_MONTH_KWH),
            CPFLCostSensor(coordinator, inst_num, SUFFIX_LAST_MONTH_AMOUNT),
            # Last year
            CPFLEnergySensor(coordinator, inst_num, SUFFIX_LAST_YEAR_KWH),
            CPFLCostSensor(coordinator, inst_num, SUFFIX_LAST_YEAR_AMOUNT),
            # Daily average
            CPFLEnergySensor(coordinator, inst_num, SUFFIX_DAILY_AVERAGE_KWH),
            # Tariff flags
            CPFLStringSensor(coordinator, inst_num, SUFFIX_TARIFF_FLAGS),
        ]
        all_sensors.extend(sensors)

    async_add_entities(all_sensors)
    _LOGGER.debug("Created %d sensors for config %s", len(all_sensors), config_entry.title)

    # Schedule the first update
    config_entry.async_create_task(
        hass,
        coordinator.async_config_entry_first_refresh(),
        f"{config_entry.title}_first_update",
    )


# -- Base sensor -------------------------------------------------------------


class CPFLBaseSensor(CoordinatorEntity, SensorEntity):
    """Base CPFL sensor."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        installation_number: str,
        entity_suffix: str,
        extra_state_attributes_key: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._installation_number = installation_number
        self._entity_suffix = entity_suffix
        self._attr_extra_state_attributes = {}
        self._extra_state_attributes_key = extra_state_attributes_key

    @property
    def unique_id(self) -> str | None:
        return f"{DOMAIN}.{self._installation_number}.{self._entity_suffix}"

    @property
    def name(self) -> str | None:
        return f"CPFL-{self._installation_number}-{self._entity_suffix}"

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._installation_number)},
            name=f"CPFL-{self._installation_number}",
            manufacturer="CPFL Energia",
            model="CPFL Virtual Electricity Meter",
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if not self.coordinator.data:
            _LOGGER.error("%s coordinator has no data", self.unique_id)
            self._attr_available = False
            self.async_write_ha_state()
            return

        inst_data = self.coordinator.data.get(self._installation_number)
        if inst_data is None:
            _LOGGER.warning("%s not found in coordinator data", self.unique_id)
            self._attr_available = False
            self.async_write_ha_state()
            return

        new_value = inst_data.get(self._entity_suffix)
        if new_value is None:
            self._attr_available = False
            self.async_write_ha_state()
            return

        if new_value == STATE_UNAVAILABLE:
            self._attr_available = False
            self.async_write_ha_state()
            return

        # Value is available
        self._attr_available = True

        self._attr_native_value = new_value

        if self._extra_state_attributes_key:
            new_attrs = inst_data.get(self._extra_state_attributes_key)
            if new_attrs is None:
                new_attrs = {}
                _LOGGER.warning(
                    "%s attribute %s not found in coordinator data",
                    self.unique_id,
                    self._extra_state_attributes_key,
                )
            self._attr_extra_state_attributes = new_attrs

        _LOGGER.debug("%s state update done!", self.unique_id)
        self.async_write_ha_state()


class CPFLEnergySensor(CPFLBaseSensor):
    """Energy (kWh) sensor."""

    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:lightning-bolt"


class CPFLCostSensor(CPFLBaseSensor):
    """Cost (BRL) sensor."""

    _attr_native_unit_of_measurement = "BRL"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:currency-brl"


class CPFLStringSensor(CPFLBaseSensor):
    """String-type sensor for dates, flags, etc."""

    _attr_icon = "mdi:calendar"


# -- Coordinator -------------------------------------------------------------


class CPFLCoordinator(DataUpdateCoordinator):
    """CPFL custom coordinator."""

    def __init__(self, hass: HomeAssistant, config_entry_id: str) -> None:
        self._config_entry_id = config_entry_id
        self._config = hass.config_entries.async_get_entry(
            self._config_entry_id
        ).data
        super().__init__(
            hass,
            _LOGGER,
            name=f"CPFL Account {self._config.get(CONF_DOCUMENT, 'unknown')}",
            update_interval=timedelta(
                seconds=self._config[CONF_SETTINGS][CONF_UPDATE_INTERVAL]
            ),
        )
        self._client: CPFLClient | None = None
        self._if_update_last_month = True
        self._if_update_last_year = True
        self._this_day: int | None = None
        self._this_year: int | None = None
        self._this_month_ym: str | None = None
        self._last_year: int | None = None
        self._last_month_ym: str | None = None
        self._gathered_data: dict[str, dict] = {}

    async def _async_refresh_client(self):
        """Refresh the API client."""
        _LOGGER.debug("Refreshing CPFL client")
        # Close any previous client to avoid leaking its HTTP connection pool.
        if self._client is not None:
            await self.hass.async_add_executor_job(self._client.close)
            self._client = None
        self._client = await self.hass.async_add_executor_job(
            CPFLClient.load,
            {CONF_AUTH_TOKEN: self._config[CONF_AUTH_TOKEN]},
        )
        logged_in = await self.hass.async_add_executor_job(
            self._client.verify_login,
        )
        if not logged_in:
            _LOGGER.warning(
                "%s: Login expired",
                _mask_document(self._config.get(CONF_DOCUMENT, "")),
            )
            raise ConfigEntryAuthFailed("Login expired")
        _LOGGER.debug(
            "%s: Session still valid",
            _mask_document(self._config.get(CONF_DOCUMENT, "")),
        )

    async def _async_fetch(self, func, *args, **kwargs) -> tuple[bool, Any]:
        """Wrapper to fetch data from API with timeout."""
        try:
            async with async_timeout.timeout(SETTING_UPDATE_TIMEOUT):
                return True, await self.hass.async_add_executor_job(
                    func, *args, **kwargs
                )
        except asyncio.TimeoutError as err:
            _LOGGER.error("Timeout fetching data in function: %s", func.__name__)
            return False, (func.__name__, err)
        except (NotLoggedIn, CPFLAuthExpired) as err:
            _LOGGER.error(
                "Session invalidated in function: %s", func.__name__
            )
            return False, (func.__name__, err)
        except CPFLError as err:
            _LOGGER.error(
                "API error in function %s: %s", func.__name__, err
            )
            return False, (func.__name__, err)
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.error("Unexpected exception: %s", err)
            _LOGGER.error(traceback.format_exc())
            return False, (func.__name__, err)

    async def _async_update_bill(self, installation_number: str):
        """Update current bill data."""
        success, result = await self._async_fetch(
            self._client.get_current_bill, installation_number
        )
        if success and result:
            self._gathered_data[installation_number][SUFFIX_BILL_AMOUNT] = result.amount
            self._gathered_data[installation_number][SUFFIX_LAST_BILL_KWH] = (
                result.consumption_kwh
            )
            self._gathered_data[installation_number][SUFFIX_BILL_DUE_DATE] = (
                result.due_date
            )
            self._gathered_data[installation_number][SUFFIX_BILL_REFERENCE_MONTH] = (
                result.reference_month
            )
        else:
            for key in [
                SUFFIX_BILL_AMOUNT,
                SUFFIX_LAST_BILL_KWH,
                SUFFIX_BILL_DUE_DATE,
                SUFFIX_BILL_REFERENCE_MONTH,
            ]:
                self._gathered_data[installation_number][key] = STATE_UNAVAILABLE
            _LOGGER.error(
                "Error updating bill for installation %s: %s",
                installation_number,
                result,
            )

    async def _async_update_balance(self, installation_number: str):
        """Update account balance."""
        success, result = await self._async_fetch(
            self._client.get_balance, installation_number
        )
        if success:
            self._gathered_data[installation_number][SUFFIX_BALANCE] = result
        else:
            self._gathered_data[installation_number][SUFFIX_BALANCE] = STATE_UNAVAILABLE

    async def _async_update_consumption(self, installation_number: str):
        """Update consumption history."""
        success, result = await self._async_fetch(
            self._client.get_consumption_history, installation_number, 12
        )
        if success:
            # This year total
            self._gathered_data[installation_number][SUFFIX_THIS_YEAR_KWH] = result.kwh
            self._gathered_data[installation_number][SUFFIX_THIS_YEAR_AMOUNT] = (
                result.amount
            )
            # Daily average
            self._gathered_data[installation_number][SUFFIX_DAILY_AVERAGE_KWH] = (
                result.average_daily_kwh
            )
            # Consumption history as attributes
            self._gathered_data[installation_number][
                ATTR_KEY_CONSUMPTION_HISTORY
            ] = {ATTR_KEY_CONSUMPTION_HISTORY: result.history}

            # Try to extract this month and last month from history
            if result.history:
                # Most recent entry = this month
                this_month = result.history[0]
                self._gathered_data[installation_number][SUFFIX_THIS_MONTH_KWH] = (
                    this_month.get("kwh", STATE_UNAVAILABLE)
                )
                self._gathered_data[installation_number][SUFFIX_THIS_MONTH_ESTIMATE] = (
                    this_month.get("amount", STATE_UNAVAILABLE)
                )

                # Second entry = last month
                if len(result.history) > 1:
                    last_month = result.history[1]
                    self._gathered_data[installation_number][SUFFIX_LAST_MONTH_KWH] = (
                        last_month.get("kwh", STATE_UNAVAILABLE)
                    )
                    self._gathered_data[installation_number][SUFFIX_LAST_MONTH_AMOUNT] = (
                        last_month.get("amount", STATE_UNAVAILABLE)
                    )
                else:
                    self._gathered_data[installation_number][SUFFIX_LAST_MONTH_KWH] = (
                        STATE_UNAVAILABLE
                    )
                    self._gathered_data[installation_number][SUFFIX_LAST_MONTH_AMOUNT] = (
                        STATE_UNAVAILABLE
                    )

                # Last year: sum of entries from ~12 months ago
                # (history is monthly, index 11 = 12 months ago)
                if len(result.history) >= 12:
                    last_year_entry = result.history[11]
                    self._gathered_data[installation_number][SUFFIX_LAST_YEAR_KWH] = (
                        last_year_entry.get("kwh", STATE_UNAVAILABLE)
                    )
                    self._gathered_data[installation_number][SUFFIX_LAST_YEAR_AMOUNT] = (
                        last_year_entry.get("amount", STATE_UNAVAILABLE)
                    )
                else:
                    self._gathered_data[installation_number][SUFFIX_LAST_YEAR_KWH] = (
                        STATE_UNAVAILABLE
                    )
                    self._gathered_data[installation_number][SUFFIX_LAST_YEAR_AMOUNT] = (
                        STATE_UNAVAILABLE
                    )
            else:
                for key in [
                    SUFFIX_THIS_MONTH_KWH,
                    SUFFIX_THIS_MONTH_ESTIMATE,
                    SUFFIX_LAST_MONTH_KWH,
                    SUFFIX_LAST_MONTH_AMOUNT,
                    SUFFIX_LAST_YEAR_KWH,
                    SUFFIX_LAST_YEAR_AMOUNT,
                ]:
                    self._gathered_data[installation_number][key] = STATE_UNAVAILABLE
        else:
            for key in [
                SUFFIX_THIS_YEAR_KWH,
                SUFFIX_THIS_YEAR_AMOUNT,
                SUFFIX_DAILY_AVERAGE_KWH,
                SUFFIX_THIS_MONTH_KWH,
                SUFFIX_THIS_MONTH_ESTIMATE,
                SUFFIX_LAST_MONTH_KWH,
                SUFFIX_LAST_MONTH_AMOUNT,
                SUFFIX_LAST_YEAR_KWH,
                SUFFIX_LAST_YEAR_AMOUNT,
            ]:
                self._gathered_data[installation_number][key] = STATE_UNAVAILABLE
            _LOGGER.error(
                "Error updating consumption for installation %s: %s",
                installation_number,
                result,
            )

    async def _async_update_invoice_history(self, installation_number: str):
        """Update invoice history for additional context."""
        success, result = await self._async_fetch(
            self._client.get_invoice_history, installation_number, 12
        )
        if success and result:
            bill_list = [
                {
                    "month": bill.reference_month,
                    "due_date": bill.due_date,
                    "amount": bill.amount,
                    "kwh": bill.consumption_kwh,
                    "status": bill.status,
                }
                for bill in result
            ]
            self._gathered_data[installation_number][ATTR_KEY_BILL_HISTORY] = {
                ATTR_KEY_BILL_HISTORY: bill_list
            }

            # Also update last bill info if available
            if result:
                last_bill = result[0]
                self._gathered_data[installation_number][SUFFIX_LAST_BILL_KWH] = (
                    last_bill.consumption_kwh
                )
                self._gathered_data[installation_number][SUFFIX_LAST_BILL_AMOUNT] = (
                    last_bill.amount
                )
                self._gathered_data[installation_number][SUFFIX_LAST_BILL_DUE_DATE] = (
                    last_bill.due_date
                )
        else:
            self._gathered_data[installation_number][ATTR_KEY_BILL_HISTORY] = {
                ATTR_KEY_BILL_HISTORY: []
            }

    async def _async_update_data(self) -> dict[str, dict]:
        """Fetch data from CPFL API for all installations."""
        await self._async_refresh_client()

        installations = self._config.get(CONF_INSTALLATIONS, {})
        self._gathered_data = {}

        for inst_num in installations:
            self._gathered_data[inst_num] = {}

            # Run all updates for this installation concurrently
            await asyncio.gather(
                self._async_update_bill(inst_num),
                self._async_update_balance(inst_num),
                self._async_update_consumption(inst_num),
                self._async_update_invoice_history(inst_num),
            )

            # Tariff flags (static for now, could be fetched from API)
            self._gathered_data[inst_num][SUFFIX_TARIFF_FLAGS] = STATE_UNAVAILABLE

        return self._gathered_data
