from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class GotoRequest(BaseModel):
    """JSON body for `telbot mount goto --json` or HTTP POST /goto."""

    ra_hours: float = Field(..., ge=0.0, lt=24.0, description="Right ascension in decimal hours")
    dec_deg: float = Field(..., ge=-90.0, le=90.0, description="Declination in degrees")
    frame: Literal["JNOW", "J2000"] = "JNOW"
    dry_run: bool = True

    @field_validator("ra_hours", "dec_deg")
    @classmethod
    def finites(cls, v: float) -> float:
        if not isinstance(v, float | int):
            raise TypeError("expected number")
        return float(v)


class GotoBodyRequest(BaseModel):
    """HTTP API: same fields without nested dry_run default for execute."""

    ra_hours: float = Field(..., ge=0.0, lt=24.0)
    dec_deg: float = Field(..., ge=-90.0, le=90.0)
    frame: Literal["JNOW", "J2000"] = "JNOW"


class GotoTargetRequest(BaseModel):
    """HTTP POST /goto/body: solar system body name → ephemeris → GOTO."""

    target: str = Field(..., min_length=1, description="e.g. jupiter, mars, moon")
    frame: Literal["JNOW", "J2000"] = "JNOW"


class CameraSnapRequest(BaseModel):
    """HTTP POST /camera/snap: single CCD exposure via INDI CCD_EXPOSURE."""

    exposure_seconds: float | None = Field(
        default=None,
        gt=0.0,
        le=3600.0,
        description="省略则用 TELBOT_CCD_DEFAULT_EXPOSURE_SECONDS",
    )


PlatesolveAlignMode = Literal["sync", "slew"]


class PlatesolveRequest(BaseModel):
    """HTTP POST /platesolve: ASTAP；可选先真机曝光再解算，或指定 FITS / use_latest。"""

    fits_path: str | None = Field(default=None, description="允许目录内的绝对路径")
    use_latest: bool = Field(default=False, description="使用 CCD 保存目录中最新的 *.fits（不先拍照）")
    snap_first: bool = Field(
        default=False,
        description="先执行一次真机 CCD 曝光，再对刚落盘的 FITS 解算；不要与 fits_path / use_latest 同用",
    )
    exposure_seconds: float | None = Field(
        default=None,
        gt=0.0,
        le=3600.0,
        description="snap_first 时曝光秒数；省略则用 TELBOT_CCD_DEFAULT_EXPOSURE_SECONDS",
    )
    execute: bool = Field(
        default=False,
        description="snap_first 时必须为 true（真曝光）；若指定 align，亦为真机对准望远镜",
    )
    align: PlatesolveAlignMode | None = Field(
        default=None,
        description='解算成功后对准：sync=ON_COORD_SET.SYNC；slew=ON_COORD_SET.SLEW；需 execute=true 才会写 INDI',
    )

    @model_validator(mode="after")
    def _validate_modes_and_align(self) -> PlatesolveRequest:
        fp = (self.fits_path or "").strip()
        if self.snap_first:
            if self.use_latest or fp:
                raise ValueError("snap_first 不要与 fits_path 或 use_latest 同时指定")
            if not self.execute:
                raise ValueError("snap_first 须 execute=true（真机曝光后再解算）")
            return self
        if self.use_latest and fp:
            raise ValueError("不要同时指定 fits_path 与 use_latest")
        if not self.use_latest and not fp:
            raise ValueError("请提供 fits_path、use_latest=true，或 snap_first=true")
        if self.align is not None and not self.execute:
            raise ValueError("指定 align 时必须同时 execute=true，避免误触望远镜")
        return self


class VoiceIntentV1(BaseModel):
    """
    Unified intent for NLU / voice (see README.md「语音与意图架构」).
    action=goto: either `target` (body or star name) or both `ra_hours` and `dec_deg`.
    action=nudge: `nudge_direction` required.
    action=snap: optional `exposure_seconds` (else use Settings default).
    action=platesolve: CCD 曝光后 ASTAP；可选 `exposure_seconds`；可选 **`platesolve_align`**（sync/slew）在解算成功后对准镜筒。
    action=describe: `target` = celestial object name; print ephemeris / catalog summary (no mount motion).
    action=focuser_position: query focuser absolute position (and max when available).
    action=focuser_rel: `focuser_direction` in|out + `focuser_steps` for relative move.
    action=focuser_autofocus: CCD V-curve autofocus (optional `exposure_seconds`).
    action=cfw_current: query current filter wheel slot (and label when known).
    action=cfw_list: list available filter slots/names (default QHY CFW3 map).
    action=cfw_goto: `target` = filter slot number or name (e.g. red, H_Alpha, 4).
    action=usb_devices: list known astronomy USB devices on Pi (lsusb + registry); no INDI motion.
    action=help: product capabilities overview for first-time users; no hardware action.
    action=preflight: device readiness diagnostic (INDI connect, .env, save dir); read-only.
    """

    version: Literal[1] = 1
    action: Literal[
        "goto",
        "abort",
        "park",
        "nudge",
        "connect",
        "unpark",
        "snap",
        "platesolve",
        "describe",
        "focuser_position",
        "focuser_rel",
        "focuser_autofocus",
        "cfw_current",
        "cfw_list",
        "cfw_goto",
        "usb_devices",
        "help",
        "preflight",
        "exoplanet_transits",
        "plan_exoplanet_transit",
    ]
    target: str | None = None
    ra_hours: float | None = Field(None, ge=0.0, lt=24.0)
    dec_deg: float | None = Field(None, ge=-90.0, le=90.0)
    frame: Literal["JNOW", "J2000"] = "JNOW"
    confidence: float | None = Field(None, ge=0.0, le=1.0)
    raw_text: str | None = None
    nudge_direction: Literal["up", "down", "left", "right"] | None = None
    focuser_direction: Literal["in", "out"] | None = None
    focuser_steps: int | None = Field(None, gt=0, le=500_000)
    exposure_seconds: float | None = Field(None, gt=0.0, le=3600.0)
    event_index: int | None = Field(
        None,
        ge=1,
        le=100,
        description="1-based index into last exoplanet transits list (plan_exoplanet_transit)",
    )
    platesolve_align: PlatesolveAlignMode | None = Field(
        default=None,
        description='仅 action=platesolve：解算成功后对准望远镜，sync=SYNC，slew=SLEW；真机须 execute=true',
    )

    @model_validator(mode="after")
    def _payload(self) -> VoiceIntentV1:
        if self.platesolve_align is not None and self.action != "platesolve":
            raise ValueError("platesolve_align 仅用于 action=platesolve")
        if self.action == "describe":
            if self.nudge_direction is not None or self.ra_hours is not None or self.dec_deg is not None:
                raise ValueError("describe 不要带 ra_hours / dec_deg / nudge_direction")
            if self.exposure_seconds is not None:
                raise ValueError("exposure_seconds 仅用于 action=snap、platesolve 或 focuser_autofocus")
            if not (self.target and self.target.strip()):
                raise ValueError("describe 需要非空 target（天体名）")
            return self
        if self.action == "snap":
            if self.nudge_direction is not None or self.target or self.ra_hours is not None or self.dec_deg is not None:
                raise ValueError("snap 不要带 target / ra_hours / dec_deg / nudge_direction")
            return self
        if self.action == "platesolve":
            if self.nudge_direction is not None or self.target or self.ra_hours is not None or self.dec_deg is not None:
                raise ValueError("platesolve 不要带 target / ra_hours / dec_deg / nudge_direction")
            return self
        if self.action == "focuser_position":
            if self.focuser_direction is not None or self.focuser_steps is not None:
                raise ValueError("focuser_position 不要带 focuser_direction / focuser_steps")
            if self.target or self.ra_hours is not None or self.dec_deg is not None:
                raise ValueError("focuser_position 不要带 target / ra_hours / dec_deg")
            return self
        if self.action == "focuser_rel":
            if self.focuser_direction is None or self.focuser_steps is None:
                raise ValueError("focuser_rel 需要 focuser_direction 与 focuser_steps")
            if self.target or self.ra_hours is not None or self.dec_deg is not None:
                raise ValueError("focuser_rel 不要带 target / ra_hours / dec_deg")
            return self
        if self.action == "focuser_autofocus":
            if self.focuser_direction is not None or self.focuser_steps is not None:
                raise ValueError("focuser_autofocus 不要带 focuser_direction / focuser_steps")
            if self.target or self.ra_hours is not None or self.dec_deg is not None:
                raise ValueError("focuser_autofocus 不要带 target / ra_hours / dec_deg")
            return self
        if self.action == "cfw_current":
            if self.focuser_direction is not None or self.focuser_steps is not None:
                raise ValueError("cfw_current 不要带 focuser_direction / focuser_steps")
            if self.target or self.ra_hours is not None or self.dec_deg is not None:
                raise ValueError("cfw_current 不要带 target / ra_hours / dec_deg")
            return self
        if self.action == "cfw_list":
            if self.focuser_direction is not None or self.focuser_steps is not None:
                raise ValueError("cfw_list 不要带 focuser_direction / focuser_steps")
            if self.target or self.ra_hours is not None or self.dec_deg is not None:
                raise ValueError("cfw_list 不要带 target / ra_hours / dec_deg")
            return self
        if self.action == "cfw_goto":
            if not (self.target and self.target.strip()):
                raise ValueError("cfw_goto 需要非空 target（滤镜槽号或名称）")
            if self.focuser_direction is not None or self.focuser_steps is not None:
                raise ValueError("cfw_goto 不要带 focuser_direction / focuser_steps")
            if self.ra_hours is not None or self.dec_deg is not None:
                raise ValueError("cfw_goto 不要带 ra_hours / dec_deg")
            return self
        if self.action == "usb_devices":
            if self.focuser_direction is not None or self.focuser_steps is not None:
                raise ValueError("usb_devices 不要带 focuser_direction / focuser_steps")
            if self.target or self.ra_hours is not None or self.dec_deg is not None:
                raise ValueError("usb_devices 不要带 target / ra_hours / dec_deg")
            return self
        if self.action == "help":
            if self.focuser_direction is not None or self.focuser_steps is not None:
                raise ValueError("help 不要带 focuser_direction / focuser_steps")
            if self.target or self.ra_hours is not None or self.dec_deg is not None:
                raise ValueError("help 不要带 target / ra_hours / dec_deg")
            return self
        if self.action == "exoplanet_transits":
            if self.focuser_direction is not None or self.focuser_steps is not None:
                raise ValueError("exoplanet_transits 不要带 focuser_direction / focuser_steps")
            if self.target or self.ra_hours is not None or self.dec_deg is not None:
                raise ValueError("exoplanet_transits 不要带 target / ra_hours / dec_deg")
            if self.event_index is not None:
                raise ValueError("exoplanet_transits 不要带 event_index")
            return self
        if self.action == "plan_exoplanet_transit":
            if self.focuser_direction is not None or self.focuser_steps is not None:
                raise ValueError("plan_exoplanet_transit 不要带 focuser_direction / focuser_steps")
            if self.ra_hours is not None or self.dec_deg is not None:
                raise ValueError("plan_exoplanet_transit 不要带 ra_hours / dec_deg")
            if not (self.target and self.target.strip()) and self.event_index is None:
                raise ValueError("plan_exoplanet_transit 需要 target（行星名）或 event_index（序号）")
            return self
        if self.action == "preflight":
            if self.focuser_direction is not None or self.focuser_steps is not None:
                raise ValueError("preflight 不要带 focuser_direction / focuser_steps")
            if self.target or self.ra_hours is not None or self.dec_deg is not None:
                raise ValueError("preflight 不要带 target / ra_hours / dec_deg")
            if self.exposure_seconds is not None:
                raise ValueError("preflight 不要带 exposure_seconds")
            return self
        if self.exposure_seconds is not None:
            raise ValueError("exposure_seconds 仅用于 action=snap、platesolve 或 focuser_autofocus")
        if self.focuser_direction is not None or self.focuser_steps is not None:
            raise ValueError("focuser_* 字段仅用于 focuser_position / focuser_rel")
        if self.action == "nudge":
            if self.nudge_direction is None:
                raise ValueError("nudge 需要 nudge_direction")
            if self.target or self.ra_hours is not None or self.dec_deg is not None:
                raise ValueError("nudge 不要带 target / ra_hours / dec_deg")
            return self
        if self.nudge_direction is not None:
            raise ValueError("nudge_direction 仅用于 action=nudge")
        if self.action != "goto":
            return self
        has_target = bool(self.target and self.target.strip())
        has_radec = self.ra_hours is not None and self.dec_deg is not None
        if has_target and has_radec:
            raise ValueError("goto: specify either target (body name) or ra_hours+dec_deg, not both")
        if not has_target and not has_radec:
            raise ValueError("goto: need target (body name) or both ra_hours and dec_deg")
        return self
