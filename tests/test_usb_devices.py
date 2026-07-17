"""USB device scan for voice / status."""

from telbot.usb_devices import (
    format_usb_devices_message,
    list_connected_usb_devices,
)


def test_list_connected_empty() -> None:
    assert list_connected_usb_devices(vid_pids=set()) == []


def test_list_connected_gemini_and_sbig() -> None:
    devices = list_connected_usb_devices(vid_pids={"1fc9:1705", "0d97:0101", "dead:beef"})
    assert len(devices) == 2
    assert devices[0]["vid_pid"] == "0d97:0101"
    assert devices[1]["vid_pid"] == "1fc9:1705"
    assert "SBIG" in devices[0]["label_zh"]


def test_format_message_none() -> None:
    assert "没有" in format_usb_devices_message([])


def test_format_message_some() -> None:
    devices = list_connected_usb_devices(vid_pids={"338f:a0f0"})
    msg = format_usb_devices_message(devices)
    assert "已连接" in msg
    assert "Oasis" in msg or "电调" in msg
