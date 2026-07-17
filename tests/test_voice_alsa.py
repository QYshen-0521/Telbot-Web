from telbot.voice_alsa import (
    _parse_arecord_list,
    autodetect_capture_plughw,
    resolve_listen_arecord_device,
)


def test_parse_arecord_list_usb_first() -> None:
    sample = """**** LIST OF CAPTURE HARDWARE DEVICES ****
card 0: Headphones [bcm2835 Headphones], device 0: bcm2835 Headphones [bcm2835 Headphones]
card 1: Device [USB PnP Sound Device], device 0: USB Audio [USB Audio]
"""
    devs = _parse_arecord_list(sample)
    assert len(devs) == 2
    assert devs[0].card == 0
    assert devs[1].card == 1
    assert "USB" in devs[1].card_name


def test_autodetect_prefers_usb(monkeypatch) -> None:
    sample = """card 0: bcm2835 [bcm2835], device 0: bcm2835 [bcm2835]
card 2: Mic [USB Advanced Audio], device 0: USB Audio [USB Audio]
"""
    monkeypatch.setattr(
        "telbot.voice_alsa.list_capture_devices",
        lambda: _parse_arecord_list(sample),
    )
    assert autodetect_capture_plughw() == "plughw:2,0"


def test_autodetect_skips_bcm_when_no_usb(monkeypatch) -> None:
    sample = """card 0: bcm2835 [bcm2835], device 0: x [x]
card 1: sndrpihifiberry [snd_rpi_hifiberry], device 0: y [y]
"""
    monkeypatch.setattr(
        "telbot.voice_alsa.list_capture_devices",
        lambda: _parse_arecord_list(sample),
    )
    assert autodetect_capture_plughw() == "plughw:1,0"


def test_resolve_cli_override() -> None:
    d, g = resolve_listen_arecord_device(cli_override="hw:9,0", settings_device="default")
    assert d == "hw:9,0"
    assert g is None


def test_resolve_settings_non_default() -> None:
    d, g = resolve_listen_arecord_device(cli_override=None, settings_device="plughw:1,0")
    assert d == "plughw:1,0"
    assert g is None


def test_resolve_autodetect(monkeypatch) -> None:
    monkeypatch.setattr(
        "telbot.voice_alsa.autodetect_capture_plughw",
        lambda: "plughw:3,0",
    )
    d, g = resolve_listen_arecord_device(cli_override=None, settings_device="default")
    assert d == "plughw:3,0"
    assert g == "plughw:3,0"


def test_resolve_fallback_default(monkeypatch) -> None:
    monkeypatch.setattr("telbot.voice_alsa.autodetect_capture_plughw", lambda: None)
    d, g = resolve_listen_arecord_device(cli_override=None, settings_device="default")
    assert d == "default"
    assert g is None
