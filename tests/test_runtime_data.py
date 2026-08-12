from __future__ import annotations

from custom_components.hypercolor.runtime_data import ConnectionState


def test_connection_state_notifies_only_on_transitions() -> None:
    state = ConnectionState()
    notifications = 0

    def listener() -> None:
        nonlocal notifications
        notifications += 1

    remove = state.async_add_listener(listener)
    state.set_connected()
    state.set_connected()
    state.set_disconnected(ConnectionError("offline"))
    state.set_disconnected(ConnectionError("offline"))
    remove()
    state.set_connected()

    assert notifications == 2
