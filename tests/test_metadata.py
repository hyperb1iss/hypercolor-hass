from __future__ import annotations

from scripts import check_integration_metadata


def test_metadata_contract() -> None:
    check_integration_metadata.main()
