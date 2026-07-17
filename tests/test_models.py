import pytest
from pydantic import ValidationError

from telbot.models import GotoRequest, PlatesolveRequest, VoiceIntentV1


def test_goto_request_valid() -> None:
    g = GotoRequest(ra_hours=12.5, dec_deg=-10.0, frame="JNOW", dry_run=True)
    assert g.ra_hours == 12.5


def test_goto_request_rejects_bad_ra() -> None:
    with pytest.raises(ValidationError):
        GotoRequest(ra_hours=25.0, dec_deg=0.0)


def test_voice_intent_park() -> None:
    v = VoiceIntentV1(version=1, action="park", raw_text="归位")
    assert v.action == "park"


def test_voice_intent_goto_body() -> None:
    v = VoiceIntentV1(version=1, action="goto", target="jupiter")
    assert v.target == "jupiter"


def test_voice_intent_goto_radec() -> None:
    v = VoiceIntentV1(version=1, action="goto", ra_hours=12.0, dec_deg=0.0)
    assert v.ra_hours == 12.0


def test_voice_intent_goto_rejects_both_target_and_radec() -> None:
    with pytest.raises(ValidationError):
        VoiceIntentV1(version=1, action="goto", target="mars", ra_hours=1.0, dec_deg=2.0)


def test_voice_intent_goto_requires_payload() -> None:
    with pytest.raises(ValidationError):
        VoiceIntentV1(version=1, action="goto")


def test_voice_intent_nudge() -> None:
    v = VoiceIntentV1(version=1, action="nudge", nudge_direction="left")
    assert v.nudge_direction == "left"


def test_voice_intent_nudge_requires_direction() -> None:
    with pytest.raises(ValidationError):
        VoiceIntentV1(version=1, action="nudge")


def test_voice_intent_connect_unpark() -> None:
    c = VoiceIntentV1(version=1, action="connect")
    assert c.action == "connect"
    u = VoiceIntentV1(version=1, action="unpark")
    assert u.action == "unpark"


def test_voice_intent_snap() -> None:
    v = VoiceIntentV1(version=1, action="snap", exposure_seconds=2.5)
    assert v.action == "snap"
    assert v.exposure_seconds == 2.5


def test_voice_intent_snap_default_seconds_optional() -> None:
    v = VoiceIntentV1(version=1, action="snap")
    assert v.exposure_seconds is None


def test_voice_intent_describe() -> None:
    v = VoiceIntentV1(version=1, action="describe", target="jupiter")
    assert v.action == "describe"
    assert v.target == "jupiter"


def test_voice_intent_describe_requires_target() -> None:
    with pytest.raises(ValidationError):
        VoiceIntentV1(version=1, action="describe")


def test_voice_intent_snap_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        VoiceIntentV1(version=1, action="snap", target="jupiter")


def test_voice_intent_platesolve_with_sync() -> None:
    v = VoiceIntentV1(version=1, action="platesolve", platesolve_align="sync")
    assert v.platesolve_align == "sync"


def test_voice_intent_platesolve_align_rejects_non_platesolve() -> None:
    with pytest.raises(ValidationError):
        VoiceIntentV1(version=1, action="snap", platesolve_align="sync")


def test_voice_intent_platesolve() -> None:
    v = VoiceIntentV1(version=1, action="platesolve", exposure_seconds=2.0)
    assert v.action == "platesolve"
    assert v.exposure_seconds == 2.0


def test_voice_intent_platesolve_rejects_target() -> None:
    with pytest.raises(ValidationError):
        VoiceIntentV1(version=1, action="platesolve", target="jupiter")


def test_voice_intent_goto_rejects_exposure_seconds() -> None:
    with pytest.raises(ValidationError):
        VoiceIntentV1(version=1, action="goto", target="jupiter", exposure_seconds=1.0)


def test_platesolve_request_use_latest() -> None:
    p = PlatesolveRequest(use_latest=True)
    assert p.use_latest is True
    assert p.fits_path is None


def test_platesolve_request_fits_path() -> None:
    p = PlatesolveRequest(fits_path="/tmp/a.fits")
    assert p.use_latest is False


def test_platesolve_request_rejects_both_modes() -> None:
    with pytest.raises(ValidationError):
        PlatesolveRequest(use_latest=True, fits_path="/a.fits")


def test_platesolve_request_requires_one_mode() -> None:
    with pytest.raises(ValidationError):
        PlatesolveRequest()


def test_platesolve_request_align_requires_execute() -> None:
    with pytest.raises(ValidationError, match="align"):
        PlatesolveRequest(use_latest=True, align="sync", execute=False)


def test_platesolve_request_align_with_execute_ok() -> None:
    p = PlatesolveRequest(use_latest=True, align="slew", execute=True)
    assert p.align == "slew"
    assert p.execute is True


def test_platesolve_request_snap_first_ok() -> None:
    p = PlatesolveRequest(snap_first=True, execute=True)
    assert p.snap_first is True


def test_platesolve_request_snap_first_requires_execute() -> None:
    with pytest.raises(ValidationError, match="snap_first"):
        PlatesolveRequest(snap_first=True, execute=False)


def test_platesolve_request_snap_first_conflicts_use_latest() -> None:
    with pytest.raises(ValidationError):
        PlatesolveRequest(snap_first=True, use_latest=True, execute=True)
