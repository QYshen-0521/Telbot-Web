"""Filter wheel slot resolution and dry-run setprop."""

import pytest

from telbot.cfw_indi import (
    cfw_connect,
    cfw_disconnect,
    cfw_set_slot,
    list_filter_slots,
    resolve_filter_slot,
)


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("1", 1),
        ("7", 7),
        ("red", 1),
        ("Red", 1),
        ("H_Alpha", 4),
        ("h-alpha", 4),
        ("ha", 4),
        ("SII", 5),
        ("oiii", 6),
        ("LPR", 7),
        ("红", 1),
        ("氢阿尔法", 4),
    ],
)
def test_resolve_filter_slot(token: str, expected: int) -> None:
    assert resolve_filter_slot(token) == expected


def test_resolve_filter_slot_invalid() -> None:
    with pytest.raises(ValueError, match="unknown filter"):
        resolve_filter_slot("magenta")


def test_cfw_connect_dry_run() -> None:
    r = cfw_connect("QHYCFW3", "127.0.0.1", 7624, dry_run=True)
    assert r.returncode == 0
    assert "QHYCFW3.CONNECTION.CONNECT=On" in r.stdout


def test_cfw_disconnect_dry_run() -> None:
    r = cfw_disconnect("QHYCFW3", "127.0.0.1", 7624, dry_run=True)
    assert "DISCONNECT=On" in r.stdout


def test_list_filter_slots() -> None:
    rows = list_filter_slots()
    assert len(rows) == 7
    assert rows[0]["slot"] == 1
    assert rows[0]["name"] == "Red"


def test_cfw_set_slot_dry_run() -> None:
    r = cfw_set_slot("QHYCFW3", "127.0.0.1", 7624, 4, dry_run=True)
    assert "FILTER_SLOT.FILTER_SLOT_VALUE=4" in r.stdout
