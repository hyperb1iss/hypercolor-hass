from __future__ import annotations

from typing import Any, cast

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .api import CannotConnectError, InvalidAuthError, ServerInfo, async_validate_daemon
from .const import (
    CONF_API_KEY,
    CONF_AUDIO_BEAT_HOLD_MS,
    CONF_CHANNELS_AUDIO,
    CONF_CHANNELS_DEVICE_METRICS,
    CONF_CHANNELS_METRICS,
    CONF_DISCONNECT_GRACE_S,
    CONF_LIVE_CONTROLS_ENABLED,
    CONF_PER_DEVICE_ENTITIES,
    CONF_RECONCILE_INTERVAL_S,
    CONF_UNAVAILABLE_AFTER_S,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DOMAIN,
    OPTIONS_DEFAULTS,
)


class HypercolorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    MINOR_VERSION = 1

    _discovery: dict[str, Any] | None = None

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return HypercolorOptionsFlow(config_entry)

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            result = await self._async_validate_input(user_input, errors)
            if result is not None:
                return result

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(user_input),
            errors=errors,
        )

    async def async_step_zeroconf(
        self,
        discovery_info: ZeroconfServiceInfo,
    ) -> config_entries.ConfigFlowResult:
        properties = _decode_properties(discovery_info.properties)
        instance_id = properties.get("id")
        if not instance_id:
            return self.async_abort(reason="missing_instance_id")

        await self.async_set_unique_id(instance_id)
        self._abort_if_unique_id_configured(
            updates={
                CONF_HOST: discovery_info.host,
                CONF_PORT: discovery_info.port or DEFAULT_PORT,
            }
        )

        self._discovery = {
            CONF_HOST: discovery_info.host,
            CONF_NAME: properties.get("name", discovery_info.name),
            CONF_PORT: discovery_info.port or DEFAULT_PORT,
            "version": properties.get("version"),
        }
        self.context["title_placeholders"] = {
            CONF_NAME: self._discovery[CONF_NAME],
            CONF_HOST: self._discovery[CONF_HOST],
        }
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        if self._discovery is None:
            return self.async_abort(reason="missing_discovery")

        errors: dict[str, str] = {}
        if user_input is not None:
            payload = {
                **self._discovery,
                CONF_API_KEY: user_input.get(CONF_API_KEY),
            }
            result = await self._async_validate_input(payload, errors)
            if result is not None:
                return result

        return self.async_show_form(
            step_id="zeroconf_confirm",
            data_schema=vol.Schema({vol.Optional(CONF_API_KEY): str}),
            errors=errors,
            description_placeholders={
                CONF_NAME: str(self._discovery[CONF_NAME]),
                CONF_HOST: str(self._discovery[CONF_HOST]),
            },
        )

    async def async_step_reauth(
        self,
        entry_data: dict[str, Any],
    ) -> config_entries.ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            payload = {**entry.data, CONF_API_KEY: user_input.get(CONF_API_KEY)}
            result = await self._async_validate_reauth(entry, payload, errors)
            if result is not None:
                return result

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): str}),
            errors=errors,
            description_placeholders={
                CONF_NAME: entry.title,
                CONF_HOST: str(entry.data[CONF_HOST]),
            },
        )

    async def _async_validate_input(
        self,
        user_input: dict[str, Any],
        errors: dict[str, str],
    ) -> config_entries.ConfigFlowResult | None:
        try:
            server = await _validate(self, user_input)
        except CannotConnectError:
            errors["base"] = "cannot_connect"
            return None
        except InvalidAuthError:
            errors["base"] = "invalid_auth"
            return None

        await self.async_set_unique_id(server.instance_id)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=server.instance_name,
            data={
                CONF_HOST: user_input[CONF_HOST],
                CONF_PORT: user_input[CONF_PORT],
                CONF_API_KEY: _api_key(user_input),
            },
            options=OPTIONS_DEFAULTS,
        )

    async def _async_validate_reauth(
        self,
        entry: config_entries.ConfigEntry,
        user_input: dict[str, Any],
        errors: dict[str, str],
    ) -> config_entries.ConfigFlowResult | None:
        try:
            await _validate(self, user_input)
        except CannotConnectError:
            errors["base"] = "cannot_connect"
            return None
        except InvalidAuthError:
            errors["base"] = "invalid_auth"
            return None

        return self.async_update_reload_and_abort(
            entry,
            data_updates={CONF_API_KEY: _api_key(user_input)},
        )


class HypercolorOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data={**OPTIONS_DEFAULTS, **user_input})

        options = {**OPTIONS_DEFAULTS, **self._config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_RECONCILE_INTERVAL_S,
                        default=options[CONF_RECONCILE_INTERVAL_S],
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=10,
                            max=600,
                            step=5,
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(
                        CONF_CHANNELS_AUDIO,
                        default=options[CONF_CHANNELS_AUDIO],
                    ): bool,
                    vol.Required(
                        CONF_CHANNELS_METRICS,
                        default=options[CONF_CHANNELS_METRICS],
                    ): bool,
                    vol.Required(
                        CONF_CHANNELS_DEVICE_METRICS,
                        default=options[CONF_CHANNELS_DEVICE_METRICS],
                    ): bool,
                    vol.Required(
                        CONF_LIVE_CONTROLS_ENABLED,
                        default=options[CONF_LIVE_CONTROLS_ENABLED],
                    ): bool,
                    vol.Required(
                        CONF_AUDIO_BEAT_HOLD_MS,
                        default=options[CONF_AUDIO_BEAT_HOLD_MS],
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=25,
                            max=1000,
                            step=25,
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(
                        CONF_DISCONNECT_GRACE_S,
                        default=options[CONF_DISCONNECT_GRACE_S],
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0,
                            max=60,
                            step=1,
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(
                        CONF_UNAVAILABLE_AFTER_S,
                        default=options[CONF_UNAVAILABLE_AFTER_S],
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=5,
                            max=300,
                            step=5,
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_PER_DEVICE_ENTITIES,
                        default=options[CONF_PER_DEVICE_ENTITIES],
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=cast(list[str], options[CONF_PER_DEVICE_ENTITIES]),
                            multiple=True,
                            custom_value=True,
                        )
                    ),
                }
            ),
        )


async def _validate(flow: HypercolorConfigFlow, user_input: dict[str, Any]) -> ServerInfo:
    return await async_validate_daemon(
        get_async_client(flow.hass),
        host=user_input[CONF_HOST],
        port=user_input[CONF_PORT],
        api_key=_api_key(user_input),
    )


def _user_schema(user_input: dict[str, Any] | None) -> vol.Schema:
    defaults = user_input or {}
    fields: dict[Any, type] = {
        vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, DEFAULT_HOST)): str,
        vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): int,
    }
    api_key = _api_key(defaults)
    if api_key is None:
        fields[vol.Optional(CONF_API_KEY)] = str
    else:
        fields[vol.Optional(CONF_API_KEY, default=api_key)] = str
    return vol.Schema(fields)


def _api_key(data: dict[str, Any]) -> str | None:
    value = data.get(CONF_API_KEY)
    if value is None:
        return None
    api_key = str(value).strip()
    return api_key or None


def _decode_properties(raw: dict[str, Any]) -> dict[str, str]:
    decoded: dict[str, str] = {}
    for key, value in raw.items():
        if isinstance(value, bytes):
            decoded[str(key)] = value.decode()
        else:
            decoded[str(key)] = str(value)
    return decoded
