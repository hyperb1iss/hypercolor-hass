from __future__ import annotations

import pytest
import voluptuous as vol
from homeassistant.helpers import config_validation as cv

from custom_components.hypercolor.services import CONF_CONFIG_ENTRY_ID, _schema


def test_service_schema_requires_mutation_fields() -> None:
    schema = _schema({vol.Required("effect_id"): cv.string})

    with pytest.raises(vol.MultipleInvalid, match="effect_id"):
        schema({CONF_CONFIG_ENTRY_ID: "entry-1"})
