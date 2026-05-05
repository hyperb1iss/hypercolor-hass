from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN

ISSUE_AUTH_INVALID = "auth_invalid"
ISSUE_DAEMON_UNAVAILABLE = "daemon_unavailable"


def async_create_auth_issue(hass: HomeAssistant, entry_id: str) -> None:
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"{ISSUE_AUTH_INVALID}_{entry_id}",
        is_fixable=True,
        severity=ir.IssueSeverity.ERROR,
        translation_key=ISSUE_AUTH_INVALID,
        data={"entry_id": entry_id},
    )


def async_create_unavailable_issue(hass: HomeAssistant, entry_id: str) -> None:
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"{ISSUE_DAEMON_UNAVAILABLE}_{entry_id}",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_DAEMON_UNAVAILABLE,
        data={"entry_id": entry_id},
    )


def async_delete_runtime_issues(hass: HomeAssistant, entry_id: str) -> None:
    ir.async_delete_issue(hass, DOMAIN, f"{ISSUE_AUTH_INVALID}_{entry_id}")
    ir.async_delete_issue(hass, DOMAIN, f"{ISSUE_DAEMON_UNAVAILABLE}_{entry_id}")
