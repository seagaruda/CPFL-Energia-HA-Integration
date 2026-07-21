# -*- coding: utf-8 -*-
"""
Config flow for CPFL Energia integration.

Steps:
1. User enters CPF/CNPJ and password
2. Credentials are validated, installations are fetched
3. User selects an installation to monitor
4. Config entry is created with the auth token and selected installation
"""
from __future__ import annotations

import copy
import logging
import time
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from requests import RequestException

from .const import (
    ABORT_ALL_ADDED,
    ABORT_NO_INSTALLATION,
    CONF_ACTION,
    CONF_AUTH_TOKEN,
    CONF_DOCUMENT,
    CONF_GENERAL_ERROR,
    CONF_INSTALLATION_NUMBER,
    CONF_INSTALLATIONS,
    CONF_SETTINGS,
    CONF_UPDATE_INTERVAL,
    CONF_UPDATED_AT,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    ERROR_CANNOT_CONNECT,
    ERROR_INVALID_AUTH,
    ERROR_UNKNOWN,
    STEP_ADD_INSTALLATION,
    STEP_INIT,
    STEP_LOGIN,
    STEP_SELECT_INSTALLATION,
    STEP_SETTINGS,
    STEP_USER,
)
from .cpfl_client import (
    CPFLError,
    CPFLClient,
    InvalidCredentials,
)

_LOGGER = logging.getLogger(__name__)


class CPFLConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for CPFL Energia."""

    VERSION = 1
    _reauth_entry: config_entries.ConfigEntry | None = None

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return CPFLOptionsFlowHandler(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Initial step — directly show login form."""
        return await self.async_step_login(user_input)

    async def async_step_login(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle login with document and password."""
        errors: dict[str, str] = {}
        error_detail = ""

        if user_input is not None:
            document = user_input[CONF_DOCUMENT]
            password = user_input[CONF_PASSWORD]

            client = CPFLClient()
            try:
                token = await self.hass.async_add_executor_job(
                    client.login, document, password
                )
            except InvalidCredentials:
                errors[CONF_GENERAL_ERROR] = ERROR_INVALID_AUTH
            except CPFLError:
                errors[CONF_GENERAL_ERROR] = ERROR_CANNOT_CONNECT
            except RequestException:
                errors[CONF_GENERAL_ERROR] = ERROR_CANNOT_CONNECT
            except Exception as ge:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception during CPFL login")
                errors[CONF_GENERAL_ERROR] = ERROR_UNKNOWN
                error_detail = str(ge)
            else:
                # Login succeeded — fetch installations
                try:
                    installations = await self.hass.async_add_executor_job(
                        client.get_installations
                    )
                except Exception as ge:  # pylint: disable=broad-except
                    _LOGGER.exception("Error fetching installations")
                    errors[CONF_GENERAL_ERROR] = ERROR_UNKNOWN
                    error_detail = str(ge)
                else:
                    if not installations:
                        return self.async_abort(reason=ABORT_NO_INSTALLATION)

                    # Store for the next step
                    self.context["installations"] = installations
                    self.context["auth_token"] = token
                    self.context["document"] = document
                    self.context["password"] = password

                    return await self.async_step_select_installation()

        schema = vol.Schema(
            {
                vol.Required(CONF_DOCUMENT): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )

        return self.async_show_form(
            step_id=STEP_LOGIN,
            data_schema=schema,
            errors=errors,
            description_placeholders={"error_detail": error_detail},
        )

    async def async_step_select_installation(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Let user select an installation to monitor."""
        installations: list = self.context.get("installations", [])

        if user_input is not None:
            selected = user_input[CONF_INSTALLATION_NUMBER]
            # Find the selected installation
            inst_data = None
            for inst in installations:
                if inst.installation_number == selected:
                    inst_data = inst.dump()
                    break

            if inst_data is None:
                inst_data = {"installation_number": selected}

            return await self._create_entry(
                token=self.context["auth_token"],
                document=self.context["document"],
                installation=inst_data,
            )

        # Build selection dict
        selections = {}
        for inst in installations:
            label = f"{inst.installation_number}"
            if inst.address:
                label += f" ({inst.address})"
            elif inst.name:
                label += f" ({inst.name})"
            selections[inst.installation_number] = label

        schema = vol.Schema(
            {
                vol.Required(CONF_INSTALLATION_NUMBER): vol.In(selections),
            }
        )

        return self.async_show_form(
            step_id=STEP_SELECT_INSTALLATION,
            data_schema=schema,
        )

    async def _create_entry(
        self, token: str, document: str, installation: dict
    ) -> FlowResult:
        """Create or update the config entry."""
        inst_num = installation["installation_number"]

        data = {
            CONF_DOCUMENT: document,
            CONF_AUTH_TOKEN: token,
            CONF_INSTALLATIONS: {inst_num: installation},
            CONF_SETTINGS: {
                CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL,
            },
            CONF_UPDATED_AT: str(int(time.time() * 1000)),
        }

        # Handle reauth
        if self._reauth_entry:
            old_config = copy.deepcopy(self._reauth_entry.data)
            data[CONF_INSTALLATIONS] = old_config.get(CONF_INSTALLATIONS, {})
            data[CONF_SETTINGS] = old_config.get(CONF_SETTINGS, {
                CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL,
            })
            self.hass.config_entries.async_update_entry(
                self._reauth_entry, data=data
            )
            await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
            self._reauth_entry = None
            return self.async_abort(reason="reauth_successful")

        unique_id = f"CPFL-{document}"
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=f"CPFL-{document}",
            data=data,
        )

    async def async_step_reauth(self, user_input=None) -> FlowResult:
        """Perform reauth upon an API authentication error."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input=None
    ) -> FlowResult:
        """Dialog informing user reauth is required."""
        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=vol.Schema({}),
            )
        return await self.async_step_login()


class CPFLOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for CPFL Energia."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        schema = vol.Schema(
            {
                vol.Required(CONF_ACTION, default=STEP_ADD_INSTALLATION): vol.In(
                    {
                        STEP_ADD_INSTALLATION: "Add installation",
                        STEP_SETTINGS: "Settings",
                    }
                ),
            }
        )
        if user_input:
            if user_input[CONF_ACTION] == STEP_ADD_INSTALLATION:
                return await self.async_step_add_installation()
            if user_input[CONF_ACTION] == STEP_SETTINGS:
                return await self.async_step_settings()
        return self.async_show_form(step_id=STEP_INIT, data_schema=schema)

    async def async_step_add_installation(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Select an installation to add."""
        all_entries = self.hass.config_entries.async_entries(DOMAIN)
        all_inst_nums: list[str] = []
        for entry in all_entries:
            all_inst_nums.extend(
                entry.data.get(CONF_INSTALLATIONS, {}).keys()
            )

        if user_input:
            inst_num = user_input[CONF_INSTALLATION_NUMBER]
            for inst in self.context.get("available_installations", []):
                if inst.installation_number == inst_num:
                    new_data = self.config_entry.data.copy()
                    new_data[CONF_INSTALLATIONS][inst_num] = inst.dump()
                    new_data[CONF_UPDATED_AT] = str(int(time.time() * 1000))
                    self.hass.config_entries.async_update_entry(
                        self.config_entry, data=new_data
                    )
                    _LOGGER.info("Added installation: %s", inst_num)
                    await self.hass.config_entries.async_reload(
                        self.config_entry.entry_id
                    )
                    return self.async_create_entry(title="", data={})

        # Fetch available installations
        client = CPFLClient.load(
            {CONF_AUTH_TOKEN: self.config_entry.data[CONF_AUTH_TOKEN]}
        )
        if not await self.hass.async_add_executor_job(client.verify_login):
            from homeassistant.exceptions import ConfigEntryAuthFailed
            raise ConfigEntryAuthFailed("Login expired")

        installations = await self.hass.async_add_executor_job(
            client.get_installations
        )
        if not installations:
            return self.async_abort(reason=ABORT_NO_INSTALLATION)

        self.context["available_installations"] = installations

        selections = {}
        for inst in installations:
            if inst.installation_number not in all_inst_nums:
                label = f"{inst.installation_number}"
                if inst.address:
                    label += f" ({inst.address})"
                selections[inst.installation_number] = label

        if not selections:
            return self.async_abort(reason=ABORT_ALL_ADDED)

        schema = vol.Schema(
            {vol.Required(CONF_INSTALLATION_NUMBER): vol.In(selections)}
        )
        return self.async_show_form(
            step_id=STEP_ADD_INSTALLATION, data_schema=schema
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Settings — update interval."""
        update_interval = self.config_entry.data[CONF_SETTINGS][CONF_UPDATE_INTERVAL]
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_UPDATE_INTERVAL, default=update_interval
                ): vol.All(int, vol.Range(min=60)),
            }
        )
        if user_input:
            new_data = self.config_entry.data.copy()
            new_data[CONF_SETTINGS][CONF_UPDATE_INTERVAL] = user_input[
                CONF_UPDATE_INTERVAL
            ]
            new_data[CONF_UPDATED_AT] = str(int(time.time() * 1000))
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data
            )
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)
            return self.async_create_entry(title="", data={})

        return self.async_show_form(step_id=STEP_SETTINGS, data_schema=schema)
