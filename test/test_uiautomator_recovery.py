from unittest.mock import Mock

import pytest

from InstaAddict.core import device_facade


@pytest.fixture
def patched_device(monkeypatch):
    class Device:
        reset_uiautomator = Mock(side_effect=RuntimeError("reset depth exhausted"))

    class Service:
        start = Mock()

    monkeypatch.setattr(device_facade.uiautomator2, "Device", Device)
    monkeypatch.setattr(device_facade.uiautomator2, "_Service", Service)
    monkeypatch.setattr(device_facade, "sleep", lambda _: None)
    original_reset = Device.reset_uiautomator
    device_facade._apply_uiautomator2_compatibility_patches()
    device = Device()
    device._is_alive = Mock()
    device.shell = Mock()
    return device, original_reset


def test_recursive_reset_preserves_a_healthy_service(patched_device):
    device, original_reset = patched_device
    device._is_alive.return_value = True

    device.reset_uiautomator(reason="startup", depth=2)

    original_reset.assert_not_called()
    device.shell.assert_not_called()


def test_reset_failure_rechecks_health_before_resurrection(patched_device):
    device, original_reset = patched_device
    device._is_alive.side_effect = [False, True]

    device.reset_uiautomator(reason="startup")

    original_reset.assert_called_once()
    device.shell.assert_not_called()


def test_unhealthy_service_still_uses_recovery(patched_device):
    device, original_reset = patched_device
    device._is_alive.return_value = False

    with pytest.raises(RuntimeError, match="reset depth exhausted"):
        device.reset_uiautomator(reason="startup", depth=2)

    original_reset.assert_called_once()
    device.shell.assert_called()
