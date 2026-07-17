from __future__ import annotations

import json
import os
import subprocess
import time
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Literal, Optional

import typer
from rich.console import Console

from telbot import __version__
from telbot.config import Settings, load_settings, telbot_dotenv_layer_paths
from telbot.ephem_body import apparent_radec_jnow
from telbot.horizon import BelowHorizonError, apparent_altaz_deg, ensure_above_horizon
from telbot.ccd_indi import ccd_connect, ccd_disconnect
from telbot.cfw_indi import (
    DEFAULT_FILTER_SLOTS,
    cfw_connect,
    cfw_disconnect,
    cfw_set_slot,
    resolve_filter_slot,
)
from telbot.focuser_indi import (
    focuser_connect,
    focuser_disconnect,
    focuser_get_absolute_position,
    focuser_get_max_position,
    focuser_move_absolute,
    focuser_move_relative,
)
from telbot.indi import (
    abort_motion,
    connect_telescope,
    indi_available,
    park_telescope,
    read_equatorial_eod,
    read_horizontal_coord,
    run_getprop,
    slew_equatorial_eod,
    telescope_device_names_from_getprop_stdout,
    unpark_telescope,
)
from telbot.indi_apt_guard import check_apt_argv, status_lines as indi_apt_guard_status_lines
from telbot.indi_service import find_select_mount_script, indi_status_lines, indi_stop
from telbot.env_sync import resolve_dotenv_path, update_dotenv_keys
from telbot.mount_resolve import (
    list_usb_tty_paths,
    resolve_telescope_device,
    resolve_telescope_device_from_getprop_stdout,
)
from telbot.intent_exec import execute_voice_intent
from telbot.models import GotoRequest, VoiceIntentV1
from telbot.nl_pipeline import resolve_intent_from_sentence

app = typer.Typer(no_args_is_help=True, help="Telbot: INDI mount control (Gemini / Losmandy via indi_lx200gemini)")
console = Console(stderr=True)

mount_app = typer.Typer(no_args_is_help=True, help="Telescope: GOTO, park, abort, discover")
app.add_typer(mount_app, name="mount")

camera_app = typer.Typer(no_args_is_help=True, help="INDI CCD: snap exposure, connect (device from TELBOT_INDI_CCD_DEVICE)")
app.add_typer(camera_app, name="camera")

cal_app = typer.Typer(
    no_args_is_help=True,
    help="校准帧：偏置(bias)/暗场(dark)/平场(flat)/亮场(light)；见 docs/CCD_CALIBRATION.md",
)
camera_app.add_typer(cal_app, name="cal")

filter_app = typer.Typer(
    no_args_is_help=True,
    help="INDI filter wheel: connect, disconnect, goto slot (TELBOT_INDI_CFW_DEVICE, default QHYCFW3)",
)
app.add_typer(filter_app, name="filter")

focuser_app = typer.Typer(
    no_args_is_help=True,
    help="INDI focuser: connect, position, rel/abs move (TELBOT_INDI_FOCUSER_DEVICE, default Oasis Focuser)",
)
app.add_typer(focuser_app, name="focuser")

schedule_app = typer.Typer(
    no_args_is_help=True,
    help="定时调度：wait-until 等（凌星计划 execute 复用）",
)
app.add_typer(schedule_app, name="schedule")

indi_app = typer.Typer(
    no_args_is_help=True,
    help="INDI 服务：查看/停止 indiserver，避免在 SSH 里手起导致拔 USB 不卸驱动",
)
app.add_typer(indi_app, name="indi")


@indi_app.command("status")
def indi_status_cmd() -> None:
    """列出 indiserver 进程与 /run/telbot/indiserver.args 是否一致。"""
    for line in indi_status_lines():
        console.print(line)


@indi_app.command("stop")
def indi_stop_cmd() -> None:
    """停止 systemd 单元并杀掉所有 indiserver（含终端里 indiserver -v … &）。"""
    for line in indi_stop():
        console.print(line)
    console.print(
        "[dim]之后请：sudo systemctl enable --now indi-telescope.service；"
        "插拔 USB 由 udev 选镜，日志用 journalctl -u indi-telescope.service -f[/dim]"
    )


@indi_app.command("apt-guard")
def indi_apt_guard_cmd(
    action: str = typer.Argument(
        "status",
        help="status=保护状态；check=模拟 apt（例: check -- apt install foo）",
    ),
    apt_args: list[str] = typer.Argument(None, help="check 时 apt 参数，在 -- 之后"),
) -> None:
    """防止 apt 卸载/替换 Debian INDI 驱动栈（需 install-indi-apt-guard.sh 装钩子）。"""
    if action == "status":
        for line in indi_apt_guard_status_lines():
            console.print(line)
        return
    if action == "check":
        argv = list(apt_args or [])
        if argv and argv[0] == "--":
            argv = argv[1:]
        if not argv:
            console.print(
                "[red]用法: telbot indi apt-guard check -- apt install <包名>[/red]"
            )
            raise typer.Exit(2)
        report = check_apt_argv(argv)
        for w in report.warnings:
            console.print(f"[yellow]警告: {w}[/yellow]")
        if report.ok:
            console.print("[green]检查通过：模拟不会卸载已保护的核心 INDI 包。[/green]")
            return
        console.print("[red]" + "\n".join(report.violations) + "[/red]")
        raise typer.Exit(1)
    console.print(f"[red]未知 action: {action}（用 status 或 check）[/red]")
    raise typer.Exit(2)


@indi_app.command("sync-mount")
def indi_sync_mount_cmd() -> None:
    """运行 telbot-select-mount.sh（需已安装到 /usr/local；udev 插拔也会自动调用）。"""
    script = find_select_mount_script()
    if not script:
        console.print(
            "[red]未找到 telbot-select-mount.sh；请按 docs/MOUNT_AUTO.md 安装到 /usr/local。[/red]"
        )
        raise typer.Exit(1)
    console.print(f"[dim]执行：{script}[/dim]")
    r = subprocess.run([script], check=False)
    raise typer.Exit(r.returncode)


plan_app = typer.Typer(
    no_args_is_help=True,
    help="观测计划（分阶段）；含 window→preview→schedule→tonight→execute→monitor（天气 Park）",
)
app.add_typer(plan_app, name="plan")


def _print_ccd_target(ccd: str, host: str, port: int) -> None:
    """Show resolved CCD name (from .env / --device) before INDI calls."""
    layers = ", ".join(str(p) for p in telbot_dotenv_layer_paths()) or "(无 .env 文件)"
    console.print(f"[dim]CCD device={ccd!r} → {host}:{port}[/dim]")
    console.print(f"[dim]配置来源：TELBOT_INDI_CCD_DEVICE（.env：{layers}）[/dim]")


def _require_execute_guard(execute: bool, *, camera: bool = False) -> None:
    if not execute:
        return
    if camera:
        console.print(
            "[bold red]真机执行：将触发 CCD 曝光（时长见参数或 TELBOT_CCD_DEFAULT_EXPOSURE_SECONDS）。"
            "请确认制冷/供电/线缆与视场遮挡。[/bold red]"
        )
    else:
        console.print(
            "[bold red]真机执行：将转动赤道仪。请确认镜筒周围无障碍、已 Unpark（若需要）、目标安全。[/bold red]"
        )


def _print_listen_phases(
    *,
    t0: float,
    t_stt: float,
    t_nlu: float,
    t_end: float | None,
    t_real_indi: float | None,
    split_real_indi: bool,
) -> None:
    stt = t_stt - t0
    nlu = t_nlu - t_stt
    parts = [f"转写 {stt:.2f}s", f"意图解析 {nlu:.2f}s"]
    if t_end is not None:
        if split_real_indi and t_real_indi is not None:
            parts.append(f"解析→首条INDI {t_real_indi - t_nlu:.2f}s")
            parts.append(f"首条INDI后 {t_end - t_real_indi:.2f}s")
        else:
            parts.append(f"输出与执行 {t_end - t_nlu:.2f}s")
        total = t_end - t0
    else:
        total = t_nlu - t0
    console.print(f"[dim]耗时（录音结束起） {' | '.join(parts)} | 合计 {total:.2f}s[/dim]")


def _dispatch_resolved_intent(
    intent: VoiceIntentV1,
    s_cfg: Settings,
    *,
    send: bool,
    apply_local: bool,
    execute: bool,
    url: str,
    on_real_indi_start: Callable[[], None] | None = None,
) -> None:
    console.print("[dim]VoiceIntentV1[/dim]")
    console.print_json(data=intent.model_dump(mode="json", exclude_none=True))

    if intent.action == "describe":
        from telbot.object_intro import build_object_introduction, print_intro_console

        name = (intent.target or "").strip()
        if send:
            q = "true" if execute else "false"
            endpoint = f"{url.rstrip('/')}/intent?execute={q}"
            payload = json.dumps(intent.model_dump(mode="json", exclude_none=True)).encode("utf-8")
            req = urllib.request.Request(
                endpoint,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    body = resp.read().decode()
            except urllib.error.HTTPError as e:
                console.print(f"[red]HTTP {e.code}[/red] {e.read().decode()}")
                raise typer.Exit(1) from e
            except urllib.error.URLError as e:
                console.print(f"[red]请求失败：{e}[/red]（是否已 telbot serve？）")
                raise typer.Exit(1) from e
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                console.print(body)
                raise typer.Exit(1)
            console.print("[bold]天体简介[/bold]")
            print_intro_console(console, data)
            console.print("[dim]结构化 intro（JSON）[/dim]")
            intro_j = data.get("intro") if isinstance(data, dict) else None
            if isinstance(intro_j, dict):
                console.print_json(data=intro_j)
            else:
                console.print_json(data=data)
            return

        out = build_object_introduction(s_cfg, name)
        console.print("[bold]天体简介[/bold]")
        print_intro_console(console, out)
        console.print("[dim]结构化 intro（JSON，便于日后发送到 App）[/dim]")
        console.print_json(data=out.get("intro", {}))
        return

    if not send and not apply_local:
        return

    if send:
        q = "true" if execute else "false"
        endpoint = f"{url.rstrip('/')}/intent?execute={q}"
        payload = json.dumps(intent.model_dump(mode="json", exclude_none=True)).encode("utf-8")
        req = urllib.request.Request(
            endpoint,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read().decode()
        except urllib.error.HTTPError as e:
            console.print(f"[red]HTTP {e.code}[/red] {e.read().decode()}")
            raise typer.Exit(1) from e
        except urllib.error.URLError as e:
            console.print(f"[red]请求失败：{e}[/red]（是否已 telbot serve？）")
            raise typer.Exit(1) from e
        console.print("[dim]HTTP 响应[/dim]")
        try:
            console.print_json(data=json.loads(body))
        except json.JSONDecodeError:
            console.print(body)
        return

    if execute and intent.action != "describe":
        if intent.action == "platesolve" and intent.platesolve_align is not None:
            _require_execute_guard(True)
            _require_execute_guard(True, camera=True)
        else:
            _require_execute_guard(True, camera=intent.action in ("snap", "platesolve", "focuser_autofocus"))
        if not indi_available():
            console.print("[red]未找到 indi_setprop。[/red]")
            raise typer.Exit(1)
    try:
        out = execute_voice_intent(
            s_cfg,
            intent,
            execute=execute,
            on_real_indi_start=on_real_indi_start
            if apply_local and execute and on_real_indi_start is not None
            else None,
        )
    except KeyError as e:
        console.print(f"[red]天算或天体名错误：{e}[/red]")
        raise typer.Exit(1) from e
    except BelowHorizonError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    console.print("[dim]执行结果[/dim]")
    console.print_json(data=out)


@camera_app.command("snap")
def camera_snap(
    seconds: Annotated[
        Optional[float],
        typer.Option("--seconds", "-s", help="曝光秒数；省略则用 TELBOT_CCD_DEFAULT_EXPOSURE_SECONDS"),
    ] = None,
    execute: Annotated[
        bool,
        typer.Option("--execute", help="真实 indi_setprop；默认干跑"),
    ] = False,
    host: Annotated[Optional[str], typer.Option("--host")] = None,
    port: Annotated[Optional[int], typer.Option("--port")] = None,
    device: Annotated[
        Optional[str],
        typer.Option("--device", help="覆盖 TELBOT_INDI_CCD_DEVICE"),
    ] = None,
) -> None:
    """对 CCD_EXPOSURE.CCD_EXPOSURE_VALUE 设秒数并触发曝光（驱动 StartExposure）。默认干跑。"""
    s = load_settings()
    h = host or s.indi_host
    p = port or s.indi_port
    ccd = (device or s.indi_ccd_device or "").strip()
    if not ccd:
        console.print("[red]未设置 CCD 设备名：请在 .env 中配置 TELBOT_INDI_CCD_DEVICE（与 indi_getprop 一致）。[/red]")
        raise typer.Exit(2)
    _print_ccd_target(ccd, h, p)
    if execute:
        _require_execute_guard(True, camera=True)
        if not indi_available():
            console.print("[red]未找到 indi_setprop。[/red]")
            raise typer.Exit(1)
    try:
        out = execute_voice_intent(
            s.model_copy(update={"indi_ccd_device": ccd}),
            VoiceIntentV1(version=1, action="snap", exposure_seconds=seconds),
            execute=execute,
        )
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    console.print(f"CCD={ccd!r} host={h} port={p} execute={execute}")
    console.print_json(data=out)
    if not out.get("ok", False):
        for st in out.get("steps") or []:
            if st.get("code", 0) != 0:
                err = (st.get("stderr") or st.get("stdout") or "").strip()
                if err:
                    console.print(f"[red]步骤失败：{err}[/red]")
        console.print(
            f"[yellow]保存目录：{out.get('save_dir_hint', '?')}；"
            "若 UPLOAD 失败，在 Pi 上执行："
            f"indi_getprop -p {p} '{ccd}.UPLOAD_MODE.*'[/yellow]"
        )
        raise typer.Exit(1)


@camera_app.command("expose-loop")
def camera_expose_loop_cmd(
    until: Annotated[
        Optional[str],
        typer.Option("--until", help="结束时刻 ISO 8601（须含时区）；与 --duration 二选一"),
    ] = None,
    duration: Annotated[
        Optional[float],
        typer.Option("--duration", help="持续秒数（与 --until 二选一）"),
    ] = None,
    exposure: Annotated[
        Optional[float],
        typer.Option("-s", "--exposure", help="每帧曝光秒数"),
    ] = None,
    cadence: Annotated[
        Optional[float],
        typer.Option("--cadence", help="采样间隔秒数（默认 exposure + overhead）"),
    ] = None,
    session: Annotated[
        Optional[str],
        typer.Option("--session", help="FITS 会话子目录名（如 transit_WASP12b）"),
    ] = None,
    execute: Annotated[bool, typer.Option("--execute", help="真机循环曝光")] = False,
    json_out: Annotated[bool, typer.Option("--json", help="JSON 输出")] = False,
) -> None:
    """在 until/duration 时间窗内按 cadence 重复 CCD 曝光（Ctrl+C  cooperative 中止）。"""
    from telbot.expose_loop import run_expose_loop
    from telbot.scheduling.abort import AbortRequested
    from telbot.scheduling.time_util import parse_utc_iso

    s = load_settings()
    if execute:
        _require_execute_guard(True, camera=True)
        if not indi_available():
            console.print("[red]未找到 indi_setprop。[/red]")
            raise typer.Exit(1)
    if (until is None) == (duration is None):
        console.print("[red]须指定 --until 或 --duration 之一[/red]")
        raise typer.Exit(2)
    until_dt = parse_utc_iso(until) if until else None
    try:
        out = run_expose_loop(
            s,
            until_utc=until_dt,
            duration_seconds=duration,
            exposure_seconds=exposure,
            cadence_seconds=cadence,
            session_tag=session or (s.ccd_session_tag or None),
            execute=execute,
        )
    except (RuntimeError, ValueError, AbortRequested) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    if json_out:
        console.print_json(data=out)
    else:
        console.print(out.get("message") or "完成")
    if not out.get("ok", False):
        raise typer.Exit(1)


@camera_app.command("live-stack")
def camera_live_stack_cmd(
    duration: Annotated[
        float,
        typer.Option("--duration", help="拍摄总时长（秒）；与 App/HTTP 一致"),
    ],
    exposure: Annotated[
        Optional[float],
        typer.Option("-s", "--exposure", help="每帧曝光秒数"),
    ] = None,
    cadence: Annotated[
        Optional[float],
        typer.Option("--cadence", help="帧间隔秒数（默认 exposure + overhead）"),
    ] = None,
    session: Annotated[
        Optional[str],
        typer.Option("--session", help="会话目录名（原始 FITS 保存在其 raw/ 下）"),
    ] = None,
    cal_bias: Annotated[
        Optional[str],
        typer.Option("--cal-bias", help="偏置场会话目录（telbot camera cal bias 输出）"),
    ] = None,
    cal_dark: Annotated[
        Optional[str],
        typer.Option("--cal-dark", help="暗场目录；曝光建议与 -s 一致"),
    ] = None,
    cal_flat: Annotated[
        Optional[str],
        typer.Option("--cal-flat", help="平场目录"),
    ] = None,
    execute: Annotated[bool, typer.Option("--execute", help="真机边拍边叠")] = False,
    json_out: Annotated[bool, typer.Option("--json", help="JSON 输出")] = False,
) -> None:
    """边拍边叠：对齐叠加；可选 bias/dark/flat 主帧校准以提升预览质量。"""
    from telbot.live_stack import run_live_stack
    from telbot.repo_paths import live_stack_abort_flag_path
    from telbot.scheduling.abort import AbortController, AbortRequested

    s = load_settings()
    if execute:
        _require_execute_guard(True, camera=True)
        if not indi_available():
            console.print("[red]未找到 indi_setprop。[/red]")
            raise typer.Exit(1)
    try:
        out = run_live_stack(
            s,
            duration_seconds=duration,
            exposure_seconds=exposure,
            cadence_seconds=cadence,
            session_tag=session,
            cal_bias_dir=cal_bias,
            cal_dark_dir=cal_dark,
            cal_flat_dir=cal_flat,
            execute=execute,
            abort=AbortController(flag_path=live_stack_abort_flag_path()) if execute else None,
        )
    except (RuntimeError, ValueError, AbortRequested) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    if json_out:
        console.print_json(data=out)
    else:
        console.print(out.get("message") or "完成")
        if out.get("session_dir"):
            console.print(f"[dim]会话目录：{out['session_dir']}[/dim]")
        if out.get("preview_url"):
            console.print(f"[dim]HTTP 预览：{out['preview_url']}[/dim]")
    if not out.get("ok", False):
        raise typer.Exit(1)


def _run_camera_calibration(
    kind: str,
    *,
    count: Optional[int],
    exposure: Optional[float],
    session: Optional[str],
    device: Optional[str],
    interval: Optional[float],
    execute: bool,
    json_out: bool,
) -> None:
    from telbot.ccd_calibration import run_calibration_frames

    s = load_settings()
    ccd = (device or s.indi_ccd_device or "").strip()
    if not ccd:
        console.print("[red]未设置 TELBOT_INDI_CCD_DEVICE。[/red]")
        raise typer.Exit(2)
    if execute:
        _require_execute_guard(True, camera=True)
        if not indi_available():
            console.print("[red]未找到 indi_setprop。[/red]")
            raise typer.Exit(1)
    try:
        out = run_calibration_frames(
            s,
            kind,  # type: ignore[arg-type]
            count=count,
            exposure_seconds=exposure,
            session_tag=session,
            device=device,
            execute=execute,
            interval_seconds=interval or 0.0,
        )
    except (RuntimeError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    if json_out:
        console.print_json(data=out)
    else:
        console.print(out.get("message") or "完成")
        if out.get("save_dir"):
            console.print(f"[dim]目录：{out['save_dir']}[/dim]")
    if not out.get("ok", False):
        raise typer.Exit(1)


@cal_app.command("bias")
def camera_cal_bias(
    count: Annotated[
        Optional[int],
        typer.Option("-n", "--count", help="张数；默认 20 或 TELBOT_CAL_BIAS_COUNT"),
    ] = None,
    exposure: Annotated[
        Optional[float],
        typer.Option("-s", "--exposure", help="曝光秒数；默认 0（偏置）"),
    ] = None,
    session: Annotated[Optional[str], typer.Option("--session", help="保存子目录名")] = None,
    device: Annotated[Optional[str], typer.Option("--device")] = None,
    interval: Annotated[
        Optional[float],
        typer.Option("--interval", help="帧间间隔秒数"),
    ] = None,
    execute: Annotated[bool, typer.Option("--execute")] = False,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """偏置场（Bias）：盖紧镜盖、最短曝光；INDI FRAME_BIAS。"""
    _run_camera_calibration(
        "bias",
        count=count,
        exposure=exposure,
        session=session,
        device=device,
        interval=interval,
        execute=execute,
        json_out=json_out,
    )


@cal_app.command("dark")
def camera_cal_dark(
    count: Annotated[
        Optional[int],
        typer.Option("-n", "--count", help="张数"),
    ] = None,
    exposure: Annotated[
        Optional[float],
        typer.Option("-s", "--exposure", help="曝光秒数（建议与亮场一致）"),
    ] = None,
    session: Annotated[Optional[str], typer.Option("--session")] = None,
    device: Annotated[Optional[str], typer.Option("--device")] = None,
    interval: Annotated[Optional[float], typer.Option("--interval")] = None,
    execute: Annotated[bool, typer.Option("--execute")] = False,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """暗场（Dark）：盖紧镜盖、与亮场相同曝光；INDI FRAME_DARK。"""
    _run_camera_calibration(
        "dark",
        count=count,
        exposure=exposure,
        session=session,
        device=device,
        interval=interval,
        execute=execute,
        json_out=json_out,
    )


@cal_app.command("flat")
def camera_cal_flat(
    count: Annotated[
        Optional[int],
        typer.Option("-n", "--count", help="张数；平场建议 20+"),
    ] = None,
    exposure: Annotated[
        Optional[float],
        typer.Option("-s", "--exposure", help="曝光秒数；默认 1s 或 TELBOT_CAL_FLAT_EXPOSURE_SECONDS"),
    ] = None,
    session: Annotated[Optional[str], typer.Option("--session")] = None,
    device: Annotated[Optional[str], typer.Option("--device")] = None,
    interval: Annotated[Optional[float], typer.Option("--interval")] = None,
    execute: Annotated[bool, typer.Option("--execute")] = False,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """平场（Flat）：均匀光源或晨昏天空；INDI FRAME_FLAT。"""
    _run_camera_calibration(
        "flat",
        count=count,
        exposure=exposure,
        session=session,
        device=device,
        interval=interval,
        execute=execute,
        json_out=json_out,
    )


@cal_app.command("light")
def camera_cal_light(
    count: Annotated[
        Optional[int],
        typer.Option("-n", "--count", help="张数"),
    ] = None,
    exposure: Annotated[
        Optional[float],
        typer.Option("-s", "--exposure", help="曝光秒数"),
    ] = None,
    session: Annotated[Optional[str], typer.Option("--session")] = None,
    device: Annotated[Optional[str], typer.Option("--device")] = None,
    interval: Annotated[Optional[float], typer.Option("--interval")] = None,
    execute: Annotated[bool, typer.Option("--execute")] = False,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """亮场（Light）：科学曝光帧序列；INDI FRAME_LIGHT。"""
    _run_camera_calibration(
        "light",
        count=count,
        exposure=exposure,
        session=session,
        device=device,
        interval=interval,
        execute=execute,
        json_out=json_out,
    )


@camera_app.command("connect")
def camera_connect(
    execute: Annotated[bool, typer.Option("--execute", help="CONNECTION.CONNECT=On")] = False,
    host: Annotated[Optional[str], typer.Option("--host")] = None,
    port: Annotated[Optional[int], typer.Option("--port")] = None,
    device: Annotated[Optional[str], typer.Option("--device", help="覆盖 TELBOT_INDI_CCD_DEVICE")] = None,
) -> None:
    """CCD CONNECTION.CONNECT（真机需 --execute）。"""
    s = load_settings()
    h = host or s.indi_host
    pt = port or s.indi_port
    ccd = (device or s.indi_ccd_device or "").strip()
    if not ccd:
        console.print("[red]未设置 TELBOT_INDI_CCD_DEVICE。[/red]")
        raise typer.Exit(2)
    dry_run = not execute
    _print_ccd_target(ccd, h, pt)
    if execute:
        _require_execute_guard(True, camera=True)
        if not indi_available():
            console.print("[red]未找到 indi_setprop。[/red]")
            raise typer.Exit(1)
    r = ccd_connect(ccd, h, pt, dry_run=dry_run)
    console.print(r.stdout)
    if r.stderr:
        console.print(r.stderr)
    if r.returncode != 0:
        console.print(
            "[yellow]若报错为 No … from 127.0.0.1，说明 .env 中 TELBOT_INDI_CCD_DEVICE "
            "与 indi_getprop 设备名不一致；可改 .env 或加 --device \"QHY CCD QHY174M\" 等完整设备名。[/yellow]"
        )
        raise typer.Exit(r.returncode)


@camera_app.command("disconnect")
def camera_disconnect(
    execute: Annotated[bool, typer.Option("--execute", help="CONNECTION.DISCONNECT=On")] = False,
    host: Annotated[Optional[str], typer.Option("--host")] = None,
    port: Annotated[Optional[int], typer.Option("--port")] = None,
    device: Annotated[Optional[str], typer.Option("--device")] = None,
) -> None:
    """CCD CONNECTION.DISCONNECT（真机需 --execute）。"""
    s = load_settings()
    h = host or s.indi_host
    pt = port or s.indi_port
    ccd = (device or s.indi_ccd_device or "").strip()
    if not ccd:
        console.print("[red]未设置 TELBOT_INDI_CCD_DEVICE。[/red]")
        raise typer.Exit(2)
    dry_run = not execute
    _print_ccd_target(ccd, h, pt)
    if execute:
        _require_execute_guard(True, camera=True)
        if not indi_available():
            console.print("[red]未找到 indi_setprop。[/red]")
            raise typer.Exit(1)
    r = ccd_disconnect(ccd, h, pt, dry_run=dry_run)
    console.print(r.stdout)
    if r.stderr:
        console.print(r.stderr)
    if r.returncode != 0:
        raise typer.Exit(r.returncode)


def _cfw_device_from_settings(s: Settings, device: Optional[str]) -> str:
    cfw = (device or s.indi_cfw_device or "").strip()
    if not cfw:
        console.print(
            "[red]未设置滤镜轮设备名：请在 .env 中配置 TELBOT_INDI_CFW_DEVICE（与 indi_getprop 一致，如 QHYCFW3）。[/red]"
        )
        raise typer.Exit(2)
    return cfw


def _print_indi_result(r: object) -> None:
    from telbot.indi import IndiResult

    if not isinstance(r, IndiResult):
        return
    console.print(r.stdout)
    if r.stderr:
        console.print(r.stderr)


@filter_app.command("list")
def filter_list() -> None:
    """列出默认槽位 1–7 与名称（与 QHY CFW3 FILTER_SLOT_NAME_* 一致）。"""
    for slot, name in sorted(DEFAULT_FILTER_SLOTS.items()):
        console.print(f"  {slot}: {name}")


@filter_app.command("connect")
def filter_connect(
    execute: Annotated[bool, typer.Option("--execute", help="CONNECTION.CONNECT=On")] = False,
    host: Annotated[Optional[str], typer.Option("--host")] = None,
    port: Annotated[Optional[int], typer.Option("--port")] = None,
    device: Annotated[Optional[str], typer.Option("--device", help="覆盖 TELBOT_INDI_CFW_DEVICE")] = None,
) -> None:
    """滤镜轮 CONNECTION.CONNECT（真机需 --execute）。"""
    s = load_settings()
    h = host or s.indi_host
    pt = port or s.indi_port
    cfw = _cfw_device_from_settings(s, device)
    dry_run = not execute
    if execute:
        console.print("[bold yellow]真机：将连接滤镜轮（CONNECTION.CONNECT）。[/bold yellow]")
        if not indi_available():
            console.print("[red]未找到 indi_setprop。[/red]")
            raise typer.Exit(1)
    r = cfw_connect(cfw, h, pt, dry_run=dry_run)
    _print_indi_result(r)
    if r.returncode != 0:
        raise typer.Exit(r.returncode)


@filter_app.command("disconnect")
def filter_disconnect(
    execute: Annotated[bool, typer.Option("--execute", help="CONNECTION.DISCONNECT=On")] = False,
    host: Annotated[Optional[str], typer.Option("--host")] = None,
    port: Annotated[Optional[int], typer.Option("--port")] = None,
    device: Annotated[Optional[str], typer.Option("--device")] = None,
) -> None:
    """滤镜轮 CONNECTION.DISCONNECT（真机需 --execute）。"""
    s = load_settings()
    h = host or s.indi_host
    pt = port or s.indi_port
    cfw = _cfw_device_from_settings(s, device)
    dry_run = not execute
    if execute:
        console.print("[bold yellow]真机：将断开滤镜轮（CONNECTION.DISCONNECT）。[/bold yellow]")
        if not indi_available():
            console.print("[red]未找到 indi_setprop。[/red]")
            raise typer.Exit(1)
    r = cfw_disconnect(cfw, h, pt, dry_run=dry_run)
    _print_indi_result(r)
    if r.returncode != 0:
        raise typer.Exit(r.returncode)


@filter_app.command("goto")
def filter_goto(
    slot_or_name: Annotated[
        str,
        typer.Argument(help="槽位 1–7 或名称：red, green, blue, H_Alpha, SII, OIII, LPR 等"),
    ],
    execute: Annotated[bool, typer.Option("--execute", help="真实 FILTER_SLOT_VALUE")] = False,
    host: Annotated[Optional[str], typer.Option("--host")] = None,
    port: Annotated[Optional[int], typer.Option("--port")] = None,
    device: Annotated[Optional[str], typer.Option("--device", help="覆盖 TELBOT_INDI_CFW_DEVICE")] = None,
) -> None:
    """切换到指定滤镜槽（FILTER_SLOT.FILTER_SLOT_VALUE）。"""
    s = load_settings()
    h = host or s.indi_host
    pt = port or s.indi_port
    cfw = _cfw_device_from_settings(s, device)
    try:
        slot = resolve_filter_slot(slot_or_name)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(2) from e
    label = DEFAULT_FILTER_SLOTS.get(slot, str(slot))
    dry_run = not execute
    if execute:
        console.print(
            f"[bold yellow]真机：滤镜轮 {cfw!r} → 槽 {slot} ({label})。[/bold yellow]"
        )
        if not indi_available():
            console.print("[red]未找到 indi_setprop。[/red]")
            raise typer.Exit(1)
    r = cfw_set_slot(cfw, h, pt, slot, dry_run=dry_run)
    _print_indi_result(r)
    console.print(f"filter={cfw!r} slot={slot} ({label}) host={h} port={pt} execute={execute}")
    if r.returncode != 0:
        raise typer.Exit(r.returncode)


def _focuser_device_from_settings(s: Settings, device: Optional[str]) -> str:
    foc = (device or s.indi_focuser_device or "").strip()
    if not foc:
        console.print(
            "[red]未设置电调设备名：请在 .env 中配置 TELBOT_INDI_FOCUSER_DEVICE（与 indi_getprop 一致，如 Oasis Focuser）。[/red]"
        )
        raise typer.Exit(2)
    return foc


@focuser_app.command("connect")
def focuser_connect_cmd(
    execute: Annotated[bool, typer.Option("--execute", help="CONNECTION.CONNECT=On")] = False,
    host: Annotated[Optional[str], typer.Option("--host")] = None,
    port: Annotated[Optional[int], typer.Option("--port")] = None,
    device: Annotated[Optional[str], typer.Option("--device", help="覆盖 TELBOT_INDI_FOCUSER_DEVICE")] = None,
) -> None:
    """电调 CONNECTION.CONNECT（真机需 --execute）。"""
    s = load_settings()
    h = host or s.indi_host
    pt = port or s.indi_port
    foc = _focuser_device_from_settings(s, device)
    dry_run = not execute
    if execute:
        console.print("[bold yellow]真机：将连接电调（CONNECTION.CONNECT）。[/bold yellow]")
        if not indi_available():
            console.print("[red]未找到 indi_setprop。[/red]")
            raise typer.Exit(1)
    r = focuser_connect(foc, h, pt, dry_run=dry_run)
    _print_indi_result(r)
    if r.returncode != 0:
        raise typer.Exit(r.returncode)


@focuser_app.command("disconnect")
def focuser_disconnect_cmd(
    execute: Annotated[bool, typer.Option("--execute", help="CONNECTION.DISCONNECT=On")] = False,
    host: Annotated[Optional[str], typer.Option("--host")] = None,
    port: Annotated[Optional[int], typer.Option("--port")] = None,
    device: Annotated[Optional[str], typer.Option("--device")] = None,
) -> None:
    """电调 CONNECTION.DISCONNECT（真机需 --execute）。"""
    s = load_settings()
    h = host or s.indi_host
    pt = port or s.indi_port
    foc = _focuser_device_from_settings(s, device)
    dry_run = not execute
    if execute:
        console.print("[bold yellow]真机：将断开电调（CONNECTION.DISCONNECT）。[/bold yellow]")
        if not indi_available():
            console.print("[red]未找到 indi_setprop。[/red]")
            raise typer.Exit(1)
    r = focuser_disconnect(foc, h, pt, dry_run=dry_run)
    _print_indi_result(r)
    if r.returncode != 0:
        raise typer.Exit(r.returncode)


@focuser_app.command("position")
def focuser_position_cmd(
    host: Annotated[Optional[str], typer.Option("--host")] = None,
    port: Annotated[Optional[int], typer.Option("--port")] = None,
    device: Annotated[Optional[str], typer.Option("--device")] = None,
) -> None:
    """读取当前绝对位置（ABS_FOCUS_POSITION.FOCUS_ABSOLUTE_POSITION）。"""
    s = load_settings()
    h = host or s.indi_host
    pt = port or s.indi_port
    foc = _focuser_device_from_settings(s, device)
    if not indi_available():
        console.print("[red]未找到 indi_getprop。[/red]")
        raise typer.Exit(1)
    rc, pos, raw = focuser_get_absolute_position(
        foc, h, pt, timeout=s.indi_getprop_timeout
    )
    if rc != 0:
        console.print(raw)
        raise typer.Exit(rc)
    if pos is None:
        console.print("[red]无法解析当前位置。[/red]")
        console.print(raw)
        raise typer.Exit(1)
    console.print(f"{foc}: position={int(pos)}")


@focuser_app.command("max")
def focuser_max_cmd(
    host: Annotated[Optional[str], typer.Option("--host")] = None,
    port: Annotated[Optional[int], typer.Option("--port")] = None,
    device: Annotated[Optional[str], typer.Option("--device")] = None,
) -> None:
    """读取最大行程（FOCUS_MAX.FOCUS_MAX_VALUE）。"""
    s = load_settings()
    h = host or s.indi_host
    pt = port or s.indi_port
    foc = _focuser_device_from_settings(s, device)
    if not indi_available():
        console.print("[red]未找到 indi_getprop。[/red]")
        raise typer.Exit(1)
    rc, mx, raw = focuser_get_max_position(foc, h, pt, timeout=s.indi_getprop_timeout)
    if rc != 0:
        console.print(raw)
        raise typer.Exit(rc)
    if mx is None:
        console.print("[red]无法解析最大位置。[/red]")
        console.print(raw)
        raise typer.Exit(1)
    console.print(f"{foc}: max={int(mx)}")


@focuser_app.command("rel")
def focuser_rel_cmd(
    steps: Annotated[int, typer.Argument(help="相对步数（>0）")],
    direction: Annotated[
        Literal["in", "out"],
        typer.Argument(help="方向：in=向内 FOCUS_INWARD，out=向外 FOCUS_OUTWARD"),
    ],
    execute: Annotated[bool, typer.Option("--execute", help="真实移动")] = False,
    host: Annotated[Optional[str], typer.Option("--host")] = None,
    port: Annotated[Optional[int], typer.Option("--port")] = None,
    device: Annotated[Optional[str], typer.Option("--device")] = None,
) -> None:
    """相对移动：先设 REL_FOCUS_POSITION，再 FOCUS_MOTION。"""
    s = load_settings()
    h = host or s.indi_host
    pt = port or s.indi_port
    foc = _focuser_device_from_settings(s, device)
    try:
        if steps <= 0:
            raise ValueError("steps must be > 0")
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(2) from e
    dry_run = not execute
    if execute:
        console.print(
            f"[bold yellow]真机：电调 {foc!r} 相对移动 {steps} 步，方向 {direction!r}。[/bold yellow]"
        )
        if not indi_available():
            console.print("[red]未找到 indi_setprop。[/red]")
            raise typer.Exit(1)
    try:
        results = focuser_move_relative(
            foc, h, pt, steps, direction, dry_run=dry_run
        )
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(2) from e
    for r in results:
        _print_indi_result(r)
        if r.returncode != 0:
            raise typer.Exit(r.returncode)
    console.print(f"focuser={foc!r} rel={steps} direction={direction} execute={execute}")


@focuser_app.command("abs")
def focuser_abs_cmd(
    position: Annotated[int, typer.Argument(help="绝对位置（步数）")],
    execute: Annotated[bool, typer.Option("--execute", help="真实移动")] = False,
    host: Annotated[Optional[str], typer.Option("--host")] = None,
    port: Annotated[Optional[int], typer.Option("--port")] = None,
    device: Annotated[Optional[str], typer.Option("--device")] = None,
) -> None:
    """绝对移动（ABS_FOCUS_POSITION.FOCUS_ABSOLUTE_POSITION）。"""
    s = load_settings()
    h = host or s.indi_host
    pt = port or s.indi_port
    foc = _focuser_device_from_settings(s, device)
    dry_run = not execute
    if execute:
        console.print(f"[bold yellow]真机：电调 {foc!r} → 绝对位置 {position}。[/bold yellow]")
        if not indi_available():
            console.print("[red]未找到 indi_setprop。[/red]")
            raise typer.Exit(1)
    r = focuser_move_absolute(foc, h, pt, position, dry_run=dry_run)
    _print_indi_result(r)
    console.print(f"focuser={foc!r} abs={position} execute={execute}")
    if r.returncode != 0:
        raise typer.Exit(r.returncode)


@focuser_app.command("autofocus")
def focuser_autofocus_cmd(
    execute: Annotated[bool, typer.Option("--execute", help="真机：V 曲线扫描并移动到最佳焦点")] = False,
    exposure: Annotated[
        Optional[float],
        typer.Option("-s", "--exposure", help="每次采样曝光秒数（默认见 .env）"),
    ] = None,
    json_out: Annotated[bool, typer.Option("--json", help="JSON 输出")] = False,
) -> None:
    """V 曲线自动对焦：多位置拍照测 HFR，移动到最锐处（需 CCD + 电调 + astropy）。"""
    s = load_settings()
    if execute:
        _require_execute_guard(True, camera=True)
        if not indi_available():
            console.print("[red]未找到 indi_setprop。[/red]")
            raise typer.Exit(1)
    try:
        out = execute_voice_intent(
            s,
            VoiceIntentV1(version=1, action="focuser_autofocus", exposure_seconds=exposure),
            execute=execute,
        )
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    except TimeoutError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    if json_out:
        console.print_json(data=out)
    else:
        console.print(out.get("message") or "完成")
        if out.get("best_hfr") is not None:
            console.print(
                f"最佳位置 {out.get('best_position')}，HFR {out.get('best_hfr'):.2f}px"
            )
    if not out.get("ok", False):
        raise typer.Exit(1)


_RUN_TELBOT = Path("/run/telbot")


@schedule_app.command("wait-until")
def schedule_wait_until_cmd(
    until: Annotated[str, typer.Argument(help="目标时刻 ISO 8601（须含时区）")],
    json_out: Annotated[bool, typer.Option("--json", help="JSON 输出")] = False,
) -> None:
    """阻塞等待至 UTC 时刻（用于定时执行前测试；Ctrl+C 退出）。"""
    from telbot.scheduling.time_util import parse_utc_iso, seconds_until, utc_now, wait_until_utc

    target = parse_utc_iso(until)
    remaining = seconds_until(target)
    if remaining <= 0:
        console.print(f"[yellow]目标时刻已过：{target.isoformat()}[/yellow]")
        raise typer.Exit(0)
    console.print(f"等待至 {target.isoformat()}（约 {remaining:.0f}s）…")
    try:
        wait_until_utc(target, poll_seconds=1.0)
    except KeyboardInterrupt:
        console.print("[yellow]已取消等待[/yellow]")
        raise typer.Exit(130) from None
    payload = {"ok": True, "reached_utc": utc_now().isoformat(), "target_utc": target.isoformat()}
    if json_out:
        console.print_json(data=payload)
    else:
        console.print(f"已到达目标时刻（当前 UTC {payload['reached_utc']}）")


def _read_run_telbot_file(name: str) -> str:
    p = _RUN_TELBOT / name
    if not p.is_file():
        return ""
    return p.read_text(encoding="utf-8").strip()


@mount_app.command("verify-pointing")
def mount_verify_pointing_cmd(
    execute: Annotated[bool, typer.Option("--execute", help="真机：曝光 + plate solve")] = False,
    exposure: Annotated[
        Optional[float],
        typer.Option("-s", "--exposure", help="曝光秒数"),
    ] = None,
    sync: Annotated[
        bool,
        typer.Option("--sync", help="解算成功后 SYNC 对准（须 --execute）"),
    ] = False,
    slew: Annotated[
        bool,
        typer.Option("--slew", help="解算成功后 SLEW 到解算位置（须 --execute）"),
    ] = False,
    json_out: Annotated[bool, typer.Option("--json", help="JSON 输出")] = False,
) -> None:
    """拍照 + ASTAP 校验当前指向；可选 --sync / --slew。"""
    from telbot.mount_verify import verify_mount_pointing

    if sync and slew:
        console.print("[red]不要同时 --sync 与 --slew[/red]")
        raise typer.Exit(2)
    align = "sync" if sync else ("slew" if slew else None)
    s = load_settings()
    if execute:
        _require_execute_guard(True, camera=True)
        if align:
            _require_execute_guard(True)
        if not indi_available():
            console.print("[red]未找到 indi_setprop。[/red]")
            raise typer.Exit(1)
    try:
        out = verify_mount_pointing(
            s,
            execute=execute,
            exposure_seconds=exposure,
            align=align,
        )
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    if json_out:
        console.print_json(data=out)
    else:
        console.print(out.get("message") or "完成")
    if not out.get("ok", False):
        raise typer.Exit(1)


@mount_app.command("discover")
def mount_discover(
    host: Annotated[Optional[str], typer.Option("--host", "-h", help="INDI host")] = None,
    port: Annotated[Optional[int], typer.Option("--port", "-p", help="INDI port")] = None,
) -> None:
    """List indiserver properties and guess telescope device name (needs indi_getprop on Pi).

    仅 **一次** 全量 ``*.*.*`` 读取（超时 ``TELBOT_INDI_GETPROP_TIMEOUT``）；若输出明显截断可适度加大该值。
    """
    s = load_settings()
    h = host or s.indi_host
    p = port or s.indi_port
    if not indi_available():
        console.print("[yellow]indi_getprop 未找到：在树莓派上安装 indi-bin 后再试。[/yellow]")
        raise typer.Exit(1)
    profile_id = _read_run_telbot_file("mount_profile_id")
    hint = _read_run_telbot_file("indi_device_hint")
    if profile_id:
        console.print(f"[dim]选镜 profile:[/dim] {profile_id}")
    if hint:
        console.print(f"[dim]indi_device_hint:[/dim] {hint!r}")
    layers = telbot_dotenv_layer_paths()
    if layers:
        console.print(
            f"[dim]Telbot .env 层（后者覆盖前者；已 export 的 TELBOT_* 优先）:[/dim] "
            + ", ".join(str(p) for p in layers)
        )
    # 单次 ``*.*.*``：原先 discover_telescope_* 与 resolve_telescope_device 各拉全量，易导致 4×indi_getprop 拖延
    gp_t = max(1.0, float(s.indi_getprop_timeout))
    r = run_getprop(h, p, "*.*.*", timeout=gp_t)
    if r.returncode != 0:
        console.print(f"[red]indi_getprop 失败（-t {gp_t:g}s）：{r.stderr or r.stdout or r.returncode}[/red]")
        raise typer.Exit(r.returncode)
    blob = r.stdout or ""
    names = telescope_device_names_from_getprop_stdout(blob)
    if names:
        console.print(f"[green]望远镜设备（EQUATORIAL_EOD_COORD）:[/green] {', '.join(names)}")
    guess = names[0] if names else None
    if guess:
        console.print(f"[green]首项（排序后）:[/green] {guess}")
    resolved = resolve_telescope_device_from_getprop_stdout(s, blob)
    console.print(f"[cyan]当前解析（尊重 TELBOT_INDI_DEVICE_AUTO）:[/cyan] {resolved!r}")
    env_device = s.indi_device
    if env_device != resolved:
        console.print(
            f"[yellow].env TELBOT_INDI_DEVICE={env_device!r} 与当前解析 {resolved!r} 不一致；"
            "可运行 telbot-select-mount.sh 或 telbot mount sync-env[/yellow]"
        )
    ttys = sorted(list_usb_tty_paths())
    if ttys:
        console.print(f"[dim]USB 串口节点:[/dim] {ttys}")
    console.print("可设置: TELBOT_INDI_DEVICE=… 或 TELBOT_INDI_DEVICE_AUTO=true + telbot-select-mount.sh")
    console.print(blob[:8000] if blob else "(no output)")


@mount_app.command("sync-env")
def mount_sync_env(
    device: Annotated[
        Optional[str],
        typer.Option("--device", help="覆盖写入的设备名（默认用当前 resolve_telescope_device）"),
    ] = None,
) -> None:
    """将当前解析的望远镜设备名写入 .env（TELBOT_INDI_DEVICE + TELBOT_INDI_DEVICE_AUTO=true）。

    默认优先 **/run/telbot/indi_device_hint**（与 telbot-select-mount 一致）；无 hint 时用
    `resolve_telescope_device`。可用 `--device` 强制指定。
    """
    s = load_settings()
    explicit = (device or "").strip()
    hint = _read_run_telbot_file("indi_device_hint")
    if explicit:
        dev = explicit
    elif hint:
        dev = hint
    else:
        dev = resolve_telescope_device(s)
    profile_id = _read_run_telbot_file("mount_profile_id")
    mapping: dict[str, str] = {
        "TELBOT_INDI_DEVICE": dev,
        "TELBOT_INDI_DEVICE_AUTO": "true",
    }
    if profile_id:
        mapping["TELBOT_ACTIVE_MOUNT_PROFILE"] = profile_id
    env_path = resolve_dotenv_path()
    update_dotenv_keys(env_path, mapping)
    console.print(f"[green]已写入 {env_path}:[/green] TELBOT_INDI_DEVICE={dev!r}, TELBOT_INDI_DEVICE_AUTO=true")


@mount_app.command("position")
def mount_position(
    host: Annotated[Optional[str], typer.Option("--host", "-h", help="INDI host")] = None,
    port: Annotated[Optional[int], typer.Option("--port", "-p", help="INDI port")] = None,
    device: Annotated[Optional[str], typer.Option("--device", help="覆盖 TELBOT_INDI_DEVICE")] = None,
    json_out: Annotated[bool, typer.Option("--json", help="JSON 输出（脚本用）")] = False,
) -> None:
    """读取当前指向：EQUATORIAL_EOD_COORD（JNow RA 小时 / Dec 度）；可选 INDI 或推算地平高度/方位。"""
    s = load_settings()
    h = host or s.indi_host
    p = port or s.indi_port
    dev = device or resolve_telescope_device(s)
    if not indi_available():
        console.print("[red]未找到 indi_getprop。[/red]")
        raise typer.Exit(1)

    gp_t = max(1.0, float(s.indi_getprop_timeout))
    coords = read_equatorial_eod(dev, h, p, timeout=gp_t)
    if coords is None:
        console.print(
            f"[red]无法读取 {dev!r} 的 EQUATORIAL_EOD_COORD（请确认已 mount connect 且驱动在线）。[/red]"
        )
        raise typer.Exit(1)
    ra_h, dec_d = coords

    horiz = read_horizontal_coord(dev, h, p, timeout=gp_t)
    alt_src = "indi" if horiz is not None else None
    alt_d: float | None = None
    az_d: float | None = None
    if horiz is not None:
        alt_d, az_d = horiz
    elif abs(s.latitude) > 1e-9 or abs(s.longitude) > 1e-9:
        alt_d, az_d = apparent_altaz_deg(
            ra_h, dec_d, s.latitude, s.longitude, s.elevation_m
        )
        alt_src = "computed"

    payload: dict[str, Any] = {
        "device": dev,
        "frame": "EQUATORIAL_EOD",
        "ra_hours": round(ra_h, 6),
        "dec_deg": round(dec_d, 6),
    }
    if alt_d is not None and az_d is not None:
        payload["altitude_deg"] = round(alt_d, 2)
        payload["azimuth_deg"] = round(az_d, 2)
        if alt_src:
            payload["horizontal_source"] = alt_src

    if json_out:
        console.print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    console.print(f"设备: {dev}")
    console.print(f"RA (h)  = {ra_h:.6f}")
    console.print(f"Dec (°) = {dec_d:.6f}")
    if alt_d is not None and az_d is not None:
        src_note = "INDI" if alt_src == "indi" else "推算（.env 经纬度）"
        console.print(f"高度 (°) = {alt_d:.2f}  方位 (°) = {az_d:.2f}  [{src_note}]")
    else:
        console.print(
            "[dim]未读到地平坐标；在 .env 设置 TELBOT_LATITUDE / TELBOT_LONGITUDE 可推算高度/方位。[/dim]"
        )


@mount_app.command("goto")
def mount_goto(
    ra_hours: Annotated[Optional[float], typer.Option("--ra", help="RA decimal hours")] = None,
    dec_deg: Annotated[Optional[float], typer.Option("--dec", help="Dec degrees")] = None,
    json_path: Annotated[Optional[Path], typer.Option("--json", help="JSON file (GotoRequest)")] = None,
    execute: Annotated[
        bool,
        typer.Option("--execute", help="发送真实 INDI 命令（默认干跑）"),
    ] = False,
    host: Annotated[Optional[str], typer.Option("--host")] = None,
    port: Annotated[Optional[int], typer.Option("--port")] = None,
    device: Annotated[Optional[str], typer.Option("--device", help="覆盖 TELBOT_INDI_DEVICE")] = None,
) -> None:
    """GOTO 到 JNow 赤道坐标（EQUATORIAL_EOD_COORD + SLEW）。默认干跑。"""
    s = load_settings()
    h = host or s.indi_host
    p = port or s.indi_port
    dev = device or resolve_telescope_device(s)

    if json_path:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        req = GotoRequest.model_validate(data)
        ra_h, dec_d = req.ra_hours, req.dec_deg
        execute = execute or (not req.dry_run)
    else:
        if ra_hours is None or dec_deg is None:
            console.print("[red]请提供 --ra / --dec，或使用 --json[/red]")
            raise typer.Exit(2)
        ra_h, dec_d = ra_hours, dec_deg

    dry_run = not execute
    if execute:
        _require_execute_guard(True)
        if not indi_available():
            console.print("[red]未找到 indi_setprop，无法在真机执行。[/red]")
            raise typer.Exit(1)

    console.print(f"设备={dev!r} host={h} port={p} RA={ra_h}h Dec={dec_d}° dry_run={dry_run}")
    try:
        ensure_above_horizon(
            ra_h,
            dec_d,
            latitude_deg=s.latitude,
            longitude_deg=s.longitude,
            elevation_m=s.elevation_m,
            min_altitude_deg=s.min_altitude_deg,
            detail="mount goto",
        )
    except BelowHorizonError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    r1, r2 = slew_equatorial_eod(dev, h, p, ra_h, dec_d, dry_run=dry_run)
    for label, r in (("coord", r1), ("slew", r2)):
        console.print(f"[{label}] code={r.returncode}")
        if r.stdout:
            console.print(r.stdout)
        if r.stderr:
            console.print(r.stderr)
    if r1.returncode != 0 or r2.returncode != 0:
        raise typer.Exit(1)


@mount_app.command("connect")
def mount_connect(
    execute: Annotated[bool, typer.Option("--execute", help="真实 CONNECTION.CONNECT=On")] = False,
    host: Annotated[Optional[str], typer.Option("--host")] = None,
    port: Annotated[Optional[int], typer.Option("--port")] = None,
    device: Annotated[Optional[str], typer.Option("--device")] = None,
) -> None:
    """CONNECTION.CONNECT（真机需 --execute）。"""
    s = load_settings()
    h = host or s.indi_host
    p = port or s.indi_port
    dev = device or resolve_telescope_device(s)
    dry_run = not execute
    if execute:
        _require_execute_guard(True)
        if not indi_available():
            console.print("[red]未找到 indi_setprop。[/red]")
            raise typer.Exit(1)
    r = connect_telescope(dev, h, p, dry_run=dry_run)
    console.print(r.stdout)
    if r.stderr:
        console.print(r.stderr)
    if r.returncode != 0:
        raise typer.Exit(r.returncode)


@mount_app.command("unpark")
def mount_unpark(
    execute: Annotated[bool, typer.Option("--execute", help="真实 TELESCOPE_PARK.UNPARK=On")] = False,
    host: Annotated[Optional[str], typer.Option("--host")] = None,
    port: Annotated[Optional[int], typer.Option("--port")] = None,
    device: Annotated[Optional[str], typer.Option("--device")] = None,
) -> None:
    """TELESCOPE_PARK.UNPARK（真机需 --execute）。"""
    s = load_settings()
    h = host or s.indi_host
    p = port or s.indi_port
    dev = device or resolve_telescope_device(s)
    dry_run = not execute
    if execute:
        _require_execute_guard(True)
        if not indi_available():
            console.print("[red]未找到 indi_setprop。[/red]")
            raise typer.Exit(1)
    r = unpark_telescope(dev, h, p, dry_run=dry_run)
    console.print(r.stdout)
    if r.stderr:
        console.print(r.stderr)
    if r.returncode != 0:
        raise typer.Exit(r.returncode)


@mount_app.command("park")
def mount_park(
    execute: Annotated[bool, typer.Option("--execute", help="真实归位")] = False,
    host: Annotated[Optional[str], typer.Option("--host")] = None,
    port: Annotated[Optional[int], typer.Option("--port")] = None,
    device: Annotated[Optional[str], typer.Option("--device")] = None,
) -> None:
    """TELESCOPE_PARK（真机需 --execute）。"""
    s = load_settings()
    h = host or s.indi_host
    p = port or s.indi_port
    dev = device or resolve_telescope_device(s)
    dry_run = not execute
    if execute:
        _require_execute_guard(True)
        if not indi_available():
            console.print("[red]未找到 indi_setprop。[/red]")
            raise typer.Exit(1)
    r = park_telescope(dev, h, p, dry_run=dry_run)
    console.print(r.stdout)
    if r.stderr:
        console.print(r.stderr)
    if r.returncode != 0:
        raise typer.Exit(r.returncode)


@mount_app.command("abort")
def mount_abort(
    execute: Annotated[bool, typer.Option("--execute", help="真实停止")] = False,
    host: Annotated[Optional[str], typer.Option("--host")] = None,
    port: Annotated[Optional[int], typer.Option("--port")] = None,
    device: Annotated[Optional[str], typer.Option("--device")] = None,
) -> None:
    """TELESCOPE_ABORT_MOTION（须望远镜已连接，否则 INDI 不暴露 ABORT 开关；先 mount connect --execute）。"""
    s = load_settings()
    h = host or s.indi_host
    p = port or s.indi_port
    dev = device or resolve_telescope_device(s)
    dry_run = not execute
    if execute:
        _require_execute_guard(True)
        if not indi_available():
            console.print("[red]未找到 indi_setprop。[/red]")
            raise typer.Exit(1)
    r = abort_motion(dev, h, p, dry_run=dry_run)
    console.print(r.stdout)
    if r.stderr:
        console.print(r.stderr)
    if r.returncode != 0:
        raise typer.Exit(r.returncode)


@mount_app.command("nudge")
def mount_nudge(
    direction: Annotated[str, typer.Argument(help="up | down | left | right（相对当前赤经/赤纬微移）")],
    execute: Annotated[bool, typer.Option("--execute", help="发送真实 INDI 命令")] = False,
    host: Annotated[Optional[str], typer.Option("--host")] = None,
    port: Annotated[Optional[int], typer.Option("--port")] = None,
    device: Annotated[Optional[str], typer.Option("--device")] = None,
) -> None:
    """相对当前指向沿赤经/赤纬方向移动一小步（步长见 TELBOT_NUDGE_*）。"""
    s = load_settings()
    h = host or s.indi_host
    p = port or s.indi_port
    dev = device or resolve_telescope_device(s)
    d = direction.strip().lower()
    if d not in ("up", "down", "left", "right"):
        console.print("[red]direction 必须是 up、down、left、right[/red]")
        raise typer.Exit(2)
    dry_run = not execute
    if execute:
        _require_execute_guard(True)
        if not indi_available():
            console.print("[red]未找到 indi_setprop。[/red]")
            raise typer.Exit(1)
    console.print(f"设备={dev!r} nudge={d} dry_run={dry_run}")
    try:
        out = execute_voice_intent(
            s,
            VoiceIntentV1(version=1, action="nudge", nudge_direction=d),  # validated above
            execute=execute,
        )
    except BelowHorizonError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    console.print_json(data=out)
    if not out.get("ok", False):
        raise typer.Exit(1)


ephem_app = typer.Typer(no_args_is_help=True, help="Skyfield: body -> RA/Dec")
app.add_typer(ephem_app, name="ephem")


@ephem_app.command("where")
def ephem_where(
    body: Annotated[str, typer.Argument(help="e.g. jupiter, mars, moon")],
    execute: Annotated[bool, typer.Option("--execute", help="计算后直接 GOTO（危险，需确认）")] = False,
) -> None:
    """打印当前时刻（UTC）目标的地平视位置 RA/Dec（de421）。"""
    s = load_settings()
    from telbot.skyfield_data import get_skyfield_loader

    ts = get_skyfield_loader().timescale()
    t = ts.now()
    try:
        pos = apparent_radec_jnow(
            body,
            t,
            s.latitude,
            s.longitude,
            s.elevation_m,
        )
    except KeyError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    console.print(f"{pos.label}")
    console.print(f"RA (h) = {pos.ra_hours:.6f}")
    console.print(f"Dec (°) = {pos.dec_deg:.6f}")
    if execute:
        console.print("[red]--execute：将调用 mount goto，请确认安全。[/red]")
        _require_execute_guard(True)
        if not indi_available():
            console.print("[red]indi_setprop 不可用。[/red]")
            raise typer.Exit(1)
        try:
            ensure_above_horizon(
                pos.ra_hours,
                pos.dec_deg,
                latitude_deg=s.latitude,
                longitude_deg=s.longitude,
                elevation_m=s.elevation_m,
                min_altitude_deg=s.min_altitude_deg,
                detail=f"ephem {body}",
            )
        except BelowHorizonError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1) from e
        r1, r2 = slew_equatorial_eod(
            resolve_telescope_device(s),
            s.indi_host,
            s.indi_port,
            pos.ra_hours,
            pos.dec_deg,
            dry_run=False,
        )
        if r1.returncode != 0 or r2.returncode != 0:
            raise typer.Exit(1)


@app.command("text")
def text_natural(
    sentence: Annotated[
        Optional[str],
        typer.Argument(help="中文自然语言；省略则仅配合 --rebuild-semantic-cache"),
    ] = None,
    send: Annotated[bool, typer.Option("--send", help="POST 到 telbot serve 的 /intent")] = False,
    apply_local: Annotated[
        bool,
        typer.Option("--apply", help="本机直接执行意图（调 INDI，不经过 HTTP）"),
    ] = False,
    execute: Annotated[bool, typer.Option("--execute", help="真机（--send 或 --apply 时有效）")] = False,
    url: Annotated[str, typer.Option("--url", help="Telbot HTTP 根地址")] = "http://127.0.0.1:8765",
    no_semantic: Annotated[
        bool,
        typer.Option(
            "--no-semantic",
            help="禁用句向量：仅规则与星表（略快，无 PyTorch 依赖）",
        ),
    ] = False,
    semantic_only: Annotated[
        bool,
        typer.Option("--semantic-only", help="仅句向量（训练句），不调规则；用于调试阈值与样本"),
    ] = False,
    no_llm: Annotated[
        bool,
        typer.Option("--no-llm", help="禁用云端大模型意图（即使 .env 开启 TELBOT_INTENT_USE_LLM）"),
    ] = False,
    rebuild_semantic_cache: Annotated[
        bool,
        typer.Option("--rebuild-semantic-cache", help="预计算句向量缓存到 ~/.cache/telbot/semantic/ 后退出"),
    ] = False,
) -> None:
    """若 TELBOT_INTENT_USE_LLM：先云端 Qwen（硅基等）意图，失败再规则/句向量。可选 POST /intent 或本机执行。"""
    if send and apply_local:
        console.print("[red]不能同时使用 --send 与 --apply[/red]")
        raise typer.Exit(2)

    s_cfg = load_settings()

    if rebuild_semantic_cache:
        try:
            from telbot.embed_intent import rebuild_cache
        except ImportError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1) from e
        p = rebuild_cache(s_cfg.semantic_model)
        console.print(f"[green]句向量缓存已更新：{p}[/green]")
        raise typer.Exit(0)

    if sentence is None or not str(sentence).strip():
        console.print("[red]请提供一句中文，或使用 --rebuild-semantic-cache[/red]")
        raise typer.Exit(2)

    sentence = str(sentence).strip()
    try:
        intent = resolve_intent_from_sentence(
            sentence,
            s_cfg,
            console=console,
            no_semantic=no_semantic,
            semantic_only=semantic_only,
            no_llm=no_llm,
        )
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e

    if intent is None:
        console.print(
            "[yellow]未识别意图：可调低 TELBOT_SEMANTIC_THRESHOLD、扩展 intent_examples_zh.jsonl，"
            "或检查 TELBOT_INTENT_USE_LLM / API Key[/yellow]"
        )
        raise typer.Exit(2)

    _dispatch_resolved_intent(
        intent,
        s_cfg,
        send=send,
        apply_local=apply_local,
        execute=execute,
        url=url,
    )


@app.command("listen")
def listen_cmd(
    audio_file: Annotated[
        Optional[Path],
        typer.Option(
            "--audio-file",
            "-f",
            help="使用已有 WAV（16-bit PCM 等，与云端 Whisper 兼容），跳过麦克风录音；等价于仅替换录音来源",
            path_type=Path,
        ),
    ] = None,
    seconds: Annotated[
        Optional[float],
        typer.Option(
            "--seconds",
            "-s",
            help="固定秒数录音；不设则默认 TELBOT_LISTEN_DEFAULT_SECONDS（默认 3）；与 --audio-file 并用时忽略",
        ),
    ] = None,
    hold_space: Annotated[
        bool,
        typer.Option(
            "--hold-space",
            help="按住空格说话、松开结束（本机键盘；与默认固定秒数录音互斥）",
        ),
    ] = False,
    max_ptt_seconds: Annotated[
        float,
        typer.Option("--max-ptt-seconds", help="按住说话最长秒数（仅 --hold-space）"),
    ] = 120.0,
    device: Annotated[
        Optional[str],
        typer.Option("--device", "-D", help="强制 ALSA 设备；省略则 .env 非 default 优先，否则自动检测 USB 等"),
    ] = None,
    send: Annotated[bool, typer.Option("--send", help="POST 到 telbot serve 的 /intent")] = False,
    apply_local: Annotated[
        bool,
        typer.Option("--apply", help="本机直接执行意图（调 INDI，不经过 HTTP）"),
    ] = False,
    execute: Annotated[bool, typer.Option("--execute", help="真机（--send 或 --apply 时有效）")] = False,
    url: Annotated[str, typer.Option("--url", help="Telbot HTTP 根地址")] = "http://127.0.0.1:8765",
    no_semantic: Annotated[
        bool,
        typer.Option("--no-semantic", help="禁用句向量：仅规则与星表"),
    ] = False,
    semantic_only: Annotated[
        bool,
        typer.Option("--semantic-only", help="仅句向量，不调规则"),
    ] = False,
    no_llm: Annotated[
        bool,
        typer.Option("--no-llm", help="禁用云端大模型意图（即使 .env 开启 TELBOT_INTENT_USE_LLM）"),
    ] = False,
) -> None:
    """云端 Whisper 转写 → 与 telbot text 相同解析。默认固定录 TELBOT_LISTEN_DEFAULT_SECONDS 秒；自动选 USB 等麦克风（可用 -D 或 .env 覆盖）。需 pip install -e '.[voice]' 与 arecord。"""
    if send and apply_local:
        console.print("[red]不能同时使用 --send 与 --apply[/red]")
        raise typer.Exit(2)
    if audio_file is not None and hold_space:
        console.print("[red]不能同时使用 --audio-file 与 --hold-space[/red]")
        raise typer.Exit(2)

    from telbot.voice_alsa import resolve_listen_arecord_device
    from telbot.voice_listen import listen_pipeline_from_wav
    from telbot.voice_ptt import record_fixed_seconds, record_hold_space_until_release

    s_cfg = load_settings()
    wav_path: Path
    cleanup_wav: Path | None

    if audio_file is not None:
        wav_path = audio_file.expanduser().resolve()
        if not wav_path.is_file():
            console.print(f"[red]音频文件不存在：{wav_path}[/red]")
            raise typer.Exit(2)
        cleanup_wav = None
        console.print(f"[dim]输入 WAV：{wav_path}[/dim]")
    else:
        alsadev, autoguess = resolve_listen_arecord_device(
            cli_override=device,
            settings_device=s_cfg.alsa_arecord_device,
        )
        if autoguess:
            console.print(f"[dim]ALSA 录音设备（自动检测 USB 等）: {autoguess}[/dim]")
            console.print(
                "[dim]可写入 .env：TELBOT_ALSA_ARECORD_DEVICE="
                + autoguess
                + " 以固定使用此设备[/dim]"
            )

        fd, tmp = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        wav_path = Path(tmp)
        cleanup_wav = wav_path
        try:
            if hold_space:
                record_hold_space_until_release(
                    wav_path,
                    alsadev,
                    console=console,
                    max_seconds=max_ptt_seconds,
                )
            else:
                dur = float(seconds) if seconds is not None else float(s_cfg.listen_default_seconds)
                record_fixed_seconds(wav_path, alsadev, dur, console=console)
        except Exception:
            wav_path.unlink(missing_ok=True)
            raise

    try:
        t0 = time.perf_counter()
        try:
            pipe = listen_pipeline_from_wav(
                wav_path,
                s_cfg,
                no_semantic=no_semantic,
                semantic_only=semantic_only,
                no_llm=no_llm,
                console=console,
            )
        except (ValueError, ImportError) as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1) from e
        except RuntimeError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1) from e
        except Exception as e:
            console.print(f"[red]转写失败：{e}[/red]")
            raise typer.Exit(1) from e
        t_stt = t0 + pipe.stt_seconds
        t_nlu = t_stt + pipe.nlu_seconds
        text_out = pipe.transcript
        intent = pipe.intent
    finally:
        if cleanup_wav is not None:
            cleanup_wav.unlink(missing_ok=True)

    console.print(f"[green]识别：[/green]{text_out}")
    if not text_out.strip():
        console.print("[yellow]未得到有效文本[/yellow]")
        console.print(
            f"[dim]耗时（录音结束起） 转写 {t_stt - t0:.2f}s | 合计 {t_stt - t0:.2f}s[/dim]"
        )
        raise typer.Exit(2)

    if intent is None:
        console.print(
            "[yellow]未识别意图：可调低 TELBOT_SEMANTIC_THRESHOLD、扩展 intent_examples_zh.jsonl，"
            "或检查 TELBOT_INTENT_USE_LLM / API Key[/yellow]"
        )
        _print_listen_phases(
            t0=t0,
            t_stt=t_stt,
            t_nlu=t_nlu,
            t_end=None,
            t_real_indi=None,
            split_real_indi=False,
        )
        raise typer.Exit(2)

    t_real_indi: list[float] = []

    def mark_first_real_indi() -> None:
        if not t_real_indi:
            t_real_indi.append(time.perf_counter())

    _dispatch_resolved_intent(
        intent,
        s_cfg,
        send=send,
        apply_local=apply_local,
        execute=execute,
        url=url,
        on_real_indi_start=mark_first_real_indi if apply_local and execute else None,
    )
    t_end = time.perf_counter()
    _print_listen_phases(
        t0=t0,
        t_stt=t_stt,
        t_nlu=t_nlu,
        t_end=t_end,
        t_real_indi=t_real_indi[0] if t_real_indi else None,
        split_real_indi=bool(apply_local and execute),
    )


@plan_app.command("window")
def plan_window_cmd(
    from_ts: Annotated[
        Optional[str],
        typer.Option("--from", help="手动窗口开始（ISO 8601，须含时区）；须与 --to 成对"),
    ] = None,
    to_ts: Annotated[
        Optional[str],
        typer.Option("--to", help="手动窗口结束（ISO 8601，须含时区）"),
    ] = None,
) -> None:
    """阶段 0：解析「今晚」时间窗（或 --from/--to）并打印配置快照；不连 INDI。"""
    from telbot.planning import observer_timezone, planning_phase0_snapshot, resolve_plan_window
    from telbot.planning.phase0_config import validate_planning_settings
    from telbot.repo_paths import plans_dir

    s = load_settings()
    try:
        validate_planning_settings(s)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(2) from e
    try:
        w = resolve_plan_window(s, from_ts, to_ts)
    except (ValueError, RuntimeError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    tz = observer_timezone(s)
    payload = {
        "window": {
            "mode": w.mode,
            "start_utc": w.start_utc.isoformat(),
            "end_utc": w.end_utc.isoformat(),
            "duration_hours": round(w.duration_hours(), 4),
            "sun_altitude_threshold_deg": w.sun_altitude_threshold_deg,
            "start_local": w.start_utc.astimezone(tz).isoformat(),
            "end_local": w.end_utc.astimezone(tz).isoformat(),
        },
        "phase0_config": planning_phase0_snapshot(s),
        "plans_dir": str(plans_dir().resolve()),
    }
    console.print_json(data=payload)


@plan_app.command("transits")
def plan_transits_cmd(
    from_ts: Annotated[
        Optional[str],
        typer.Option("--from", help="手动窗口开始（ISO 8601，须含时区）；须与 --to 成对"),
    ] = None,
    to_ts: Annotated[
        Optional[str],
        typer.Option("--to", help="手动窗口结束（ISO 8601，须含时区）"),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="仅输出 JSON（含 events 列表）"),
    ] = False,
) -> None:
    """今晚可观测系外行星凌星（NASA Archive + astroplan；需 pip install -e \".[exoplanets]\"）。"""
    from telbot.exoplanet_transits import build_exoplanet_transit_report

    s = load_settings()
    try:
        out = build_exoplanet_transit_report(s, from_iso=from_ts, to_iso=to_ts)
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    except Exception as e:
        console.print(f"[red]凌星查询失败：{e}[/red]")
        raise typer.Exit(1) from e
    if json_out:
        console.print_json(data=out)
        return
    console.print(out.get("message") or "无结果")
    if out.get("count", 0) == 0:
        console.print(
            "[dim]提示：凌星周期较长，并非每晚都有；可调整 .env "
            "TELBOT_EXOPLANET_MAX_HOST_VMAG 或安装 exoplanets 依赖。[/dim]"
        )


@plan_app.command("transit-build")
def plan_transit_build_cmd(
    planet: Annotated[
        Optional[str],
        typer.Option("--planet", help="行星全名（如 WASP-12 b）；与 --index 二选一或兼有"),
    ] = None,
    index: Annotated[
        Optional[int],
        typer.Option("--index", help="pending 列表序号（1 起）"),
    ] = None,
    filter_name: Annotated[
        Optional[str],
        typer.Option("--filter", help="滤镜名（默认 .env TELBOT_TRANSIT_DEFAULT_FILTER）"),
    ] = None,
    exposure: Annotated[
        Optional[float],
        typer.Option("-s", "--exposure", help="每帧曝光秒数"),
    ] = None,
    no_save: Annotated[
        bool,
        typer.Option("--no-save", help="仅打印 JSON，不写入 data/plans/"),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="写入前不询问"),
    ] = False,
    dump_json: Annotated[
        bool,
        typer.Option("--json", help="stdout 打印完整 JSON"),
    ] = False,
) -> None:
    """生成 telbot.plan_transit.v1 凌星观测计划（干跑；真机执行用 transit-run --execute）。"""
    from telbot.planning.phase0_config import validate_planning_settings
    from telbot.planning.tonight import apply_confirmation
    from telbot.planning.transit_plan import (
        build_transit_plan,
        format_transit_plan_summary,
        print_transit_plan_table,
        save_transit_plan_json,
    )

    s = load_settings()
    try:
        validate_planning_settings(s)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(2) from e
    if not planet and index is None:
        console.print("[red]须指定 --planet 或 --index（或先 plan transits 再 --index）[/red]")
        raise typer.Exit(2)
    try:
        payload = build_transit_plan(
            s,
            planet=planet,
            event_index=index,
            filter_name=filter_name,
            exposure_seconds=exposure,
        )
    except (ValueError, RuntimeError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e

    console.print(format_transit_plan_summary(payload, s))
    print_transit_plan_table(console, payload, s)

    if no_save:
        if dump_json:
            console.print_json(data=payload)
        return

    if not yes:
        if not typer.confirm(
            "确认写入凌星计划到 data/plans/transit_*.json？（真机须 transit-run --execute）",
            default=False,
        ):
            console.print("[yellow]已取消，未写入文件。[/yellow]")
            if dump_json:
                console.print_json(data=payload)
            raise typer.Exit(0)

    apply_confirmation(payload, via="cli_yes" if yes else "cli_interactive")
    path = save_transit_plan_json(payload)
    payload = {**payload, "saved_path": str(path.resolve())}
    console.print(f"[green]已保存：{path.resolve()}[/green]")
    if dump_json:
        console.print_json(data=payload)


@plan_app.command("transit-run")
def plan_transit_run_cmd(
    plan: Annotated[
        Optional[Path],
        typer.Option("--plan", help="凌星计划 JSON；省略则用最新 transit_*.json"),
    ] = None,
    execute: Annotated[
        bool,
        typer.Option("--execute", help="真机按 UTC 时间线执行"),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="跳过 confirmation 校验（危险）"),
    ] = False,
    on_fail: Annotated[
        str,
        typer.Option("--on-fail", help="失败时：abort | continue | park"),
    ] = "abort",
    skip_wait: Annotated[
        bool,
        typer.Option("--skip-wait", help="干跑时跳过远期 wait（测试用）"),
    ] = False,
    json_out: Annotated[bool, typer.Option("--json", help="JSON 输出")] = False,
) -> None:
    """按 telbot.plan_transit.v1 时间线执行凌星观测（wait_until + expose_loop）。"""
    from telbot.planning.execute import load_plan_json
    from telbot.planning.phase0_config import validate_planning_settings
    from telbot.planning.transit_execute import execute_transit_plan
    from telbot.planning.transit_plan import resolve_latest_transit_plan

    if on_fail not in ("abort", "continue", "park"):
        console.print("[red]--on-fail 必须是 abort | continue | park[/red]")
        raise typer.Exit(2)

    s = load_settings()
    try:
        validate_planning_settings(s)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(2) from e

    if execute:
        _require_execute_guard(True)
        if not indi_available():
            console.print("[red]未找到 indi_setprop。[/red]")
            raise typer.Exit(1)

    try:
        path = plan if plan is not None else resolve_latest_transit_plan()
        payload = load_plan_json(path)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e

    console.print(f"加载计划：[cyan]{path.resolve()}[/cyan]")
    if execute:
        console.print(
            "[yellow]真机凌星执行：将阻塞等待各步骤 UTC 时刻；建议 tmux/screen。"
            "随时中止：本终端 Ctrl+C，或另开终端运行 "
            "[bold]telbot plan transit-abort[/bold]（立即停镜）。[/yellow]"
        )

    from telbot.planning.transit_abort import clear_run_session, write_run_session

    if execute:
        write_run_session(path.resolve())
    try:
        out = execute_transit_plan(
            s,
            payload,
            execute=execute,
            force=force,
            on_fail=on_fail,  # type: ignore[arg-type]
            skip_wait=skip_wait or not execute,
        )
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    finally:
        if execute:
            clear_run_session()

    if json_out:
        console.print_json(data=out)
    else:
        mode = "干跑" if out.get("dry_run") else "真机"
        console.print(
            f"{mode}完成：执行 {out.get('steps_executed', 0)} 步；"
            f"ok={out.get('ok')} stopped={out.get('stopped_reason')}"
        )
    if not out.get("ok", False):
        raise typer.Exit(1)


@plan_app.command("transit-abort")
def plan_transit_abort_cmd(
    execute: Annotated[
        bool,
        typer.Option(
            "--execute",
            help="同时直接对赤道仪发送 ABORT（即便没有正在运行的 transit-run 也立即停镜）",
        ),
    ] = False,
    host: Annotated[Optional[str], typer.Option("--host")] = None,
    port: Annotated[Optional[int], typer.Option("--port")] = None,
    device: Annotated[Optional[str], typer.Option("--device")] = None,
    reason: Annotated[
        str, typer.Option("--reason", help="写入中止标志的原因（出现在日志中）")
    ] = "user requested abort",
    json_out: Annotated[bool, typer.Option("--json", help="JSON 输出")] = False,
) -> None:
    """立即终止正在运行的凌星观测：写中止标志并通知运行进程停止所有运动（含赤道仪）。

    无需 --execute 也会让正在运行的 transit-run 立刻发送 TELESCOPE_ABORT_MOTION 停镜；
    --execute 额外由本命令直接对赤道仪发送一次 ABORT（双保险，幂等）。
    """
    from telbot.planning.transit_abort import (
        read_run_session,
        signal_run_session,
        write_abort_flag,
    )

    flag = write_abort_flag(reason)
    session = read_run_session()
    signaled_pid = signal_run_session()

    direct: Optional[dict[str, Any]] = None
    if execute:
        if not indi_available():
            console.print("[yellow]未找到 indi_setprop，跳过直接 ABORT（中止标志已写入）。[/yellow]")
        else:
            s = load_settings()
            h = host or s.indi_host
            p = port or s.indi_port
            dev = device or resolve_telescope_device(s)
            r = abort_motion(dev, h, p, dry_run=False)
            direct = {
                "device": dev,
                "code": r.returncode,
                "stdout": r.stdout,
                "stderr": r.stderr,
            }

    out = {
        "ok": True,
        "abort_flag": str(flag),
        "reason": reason,
        "session": session,
        "signaled_pid": signaled_pid,
        "direct_abort": direct,
    }
    if json_out:
        console.print_json(data=out)
        return

    console.print(f"[green]已写入中止标志：[/green]{flag}")
    if session and session.get("pid"):
        running = "（运行中）" if signaled_pid else "（进程可能已退出）"
        console.print(
            f"目标 transit-run：PID {session.get('pid')} 计划 {session.get('plan')} {running}"
        )
        if signaled_pid:
            console.print(f"已向 PID {signaled_pid} 发送 SIGTERM 以加速停止。")
        console.print("运行中的观测将立即发送赤道仪 ABORT 并停止曝光循环。")
    else:
        console.print("[yellow]未发现正在运行的 transit-run 会话。[/yellow]")
    if direct is not None:
        if direct["code"] == 0:
            console.print(f"[green]已直接对 {direct['device']!r} 发送 ABORT。[/green]")
        else:
            console.print(
                f"[red]直接 ABORT 失败（code={direct['code']}）：[/red]{direct['stderr']}"
            )


@plan_app.command("preview")
def plan_preview_cmd(
    from_ts: Annotated[
        Optional[str],
        typer.Option("--from", help="手动窗口开始（ISO 8601，须含时区）；须与 --to 成对"),
    ] = None,
    to_ts: Annotated[
        Optional[str],
        typer.Option("--to", help="手动窗口结束（ISO 8601，须含时区）"),
    ] = None,
    no_save: Annotated[
        bool,
        typer.Option("--no-save", help="仅打印 JSON，不写入 data/plans/"),
    ] = False,
) -> None:
    """阶段 1：在阶段 0 基础上拉取天气摘要（软警告）、可选写入 plan_preview_*.json；不连 INDI。"""
    from telbot.planning.phase0_config import validate_planning_settings
    from telbot.planning.preview import build_plan_preview_payload, save_plan_preview_json

    s = load_settings()
    try:
        validate_planning_settings(s)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(2) from e
    try:
        payload = build_plan_preview_payload(s, from_ts, to_ts)
    except (ValueError, RuntimeError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    if not no_save:
        path = save_plan_preview_json(payload)
        payload = {**payload, "saved_path": str(path.resolve())}
    console.print_json(data=payload)


@plan_app.command("schedule")
def plan_schedule_cmd(
    from_ts: Annotated[
        Optional[str],
        typer.Option("--from", help="手动窗口开始（ISO 8601，须含时区）；须与 --to 成对"),
    ] = None,
    to_ts: Annotated[
        Optional[str],
        typer.Option("--to", help="手动窗口结束（ISO 8601，须含时区）"),
    ] = None,
    no_save: Annotated[
        bool,
        typer.Option("--no-save", help="仅打印 JSON，不写入 data/plans/"),
    ] = False,
    no_weather: Annotated[
        bool,
        typer.Option("--no-weather", help="不拉取天气（加快、离线）"),
    ] = False,
    sources: Annotated[
        Optional[str],
        typer.Option(
            "--sources",
            help="星表来源：messier | ngc_bright | messier_ngc（默认读 .env TELBOT_PLAN_CATALOG_SOURCES）",
        ),
    ] = None,
    limit: Annotated[
        Optional[int],
        typer.Option("--limit", help="候选数量上限（覆盖 TELBOT_PLAN_CANDIDATE_LIMIT）"),
    ] = None,
) -> None:
    """阶段 2：OpenNGC 候选、高度角/禁区方位、月亮权重、子午线策略下的线性排程；不连 INDI。"""
    from telbot.planning.phase0_config import validate_planning_settings
    from telbot.planning.phase2_schedule import build_phase2_payload, save_phase2_plan_json

    s = load_settings()
    try:
        validate_planning_settings(s)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(2) from e
    try:
        payload = build_phase2_payload(
            s,
            from_ts,
            to_ts,
            include_weather=not no_weather,
            catalog_sources=sources,
            candidate_limit=limit,
        )
    except (ValueError, RuntimeError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    if not no_save:
        path = save_phase2_plan_json(payload)
        payload = {**payload, "saved_path": str(path.resolve())}
    console.print_json(data=payload)


@plan_app.command("tonight")
def plan_tonight_cmd(
    from_ts: Annotated[
        Optional[str],
        typer.Option("--from", help="手动窗口开始（ISO 8601，须含时区）；须与 --to 成对"),
    ] = None,
    to_ts: Annotated[
        Optional[str],
        typer.Option("--to", help="手动窗口结束（ISO 8601，须含时区）"),
    ] = None,
    no_save: Annotated[
        bool,
        typer.Option("--no-save", help="不落盘，仅预览（不触发确认）"),
    ] = False,
    no_weather: Annotated[
        bool,
        typer.Option("--no-weather", help="不拉取天气"),
    ] = False,
    sources: Annotated[
        Optional[str],
        typer.Option("--sources", help="星表：messier | ngc_bright | messier_ngc"),
    ] = None,
    limit: Annotated[
        Optional[int],
        typer.Option("--limit", help="候选数量上限"),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="写入前不询问（脚本/无人值守）"),
    ] = False,
    quiet: Annotated[
        bool,
        typer.Option("--quiet", "-q", help="不打印表格与天气软警告"),
    ] = False,
    dump_json: Annotated[
        bool,
        typer.Option("--json", help="在 stdout 打印完整 JSON"),
    ] = False,
) -> None:
    """阶段 3：合并感知+决策为今夜计划；终端表格；确认后写入 tonight_*.json（真机 GOTO 仍为后续阶段）。"""
    from telbot.planning.phase0_config import validate_planning_settings
    from telbot.planning.tonight import (
        apply_confirmation,
        build_tonight_payload,
        print_tonight_summary,
        save_tonight_plan_json,
    )

    s = load_settings()
    try:
        validate_planning_settings(s)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(2) from e
    try:
        payload = build_tonight_payload(
            s,
            from_ts,
            to_ts,
            include_weather=not no_weather,
            catalog_sources=sources,
            candidate_limit=limit,
        )
    except (ValueError, RuntimeError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e

    if not quiet:
        print_tonight_summary(console, payload, s)

    if no_save:
        if dump_json:
            console.print_json(data=payload)
        return

    if not yes:
        if not typer.confirm(
            "确认写入今夜计划到 data/plans/tonight_*.json？（真机 GOTO 须另行命令并加 --execute）",
            default=False,
        ):
            console.print("[yellow]已取消，未写入文件。[/yellow]")
            if dump_json:
                console.print_json(data=payload)
            raise typer.Exit(0)
        apply_confirmation(payload, via="cli_interactive")
    else:
        apply_confirmation(payload, via="cli_yes")

    path = save_tonight_plan_json(payload)
    payload = {**payload, "saved_path": str(path.resolve())}
    console.print(f"[green]已保存：{path.resolve()}[/green]")
    if dump_json:
        console.print_json(data=payload)


@plan_app.command("execute")
def plan_execute_cmd(
    plan: Annotated[
        Optional[Path],
        typer.Option(
            "--plan",
            help="今夜计划 JSON；省略则使用 data/plans/ 下最新 tonight_*.json",
        ),
    ] = None,
    execute: Annotated[
        bool,
        typer.Option("--execute", help="真机 GOTO / 曝光（默认干跑）"),
    ] = False,
    snap: Annotated[
        bool,
        typer.Option("--snap", help="每个目标 GOTO 后执行一次 CCD 曝光（须配置 TELBOT_INDI_CCD_DEVICE）"),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="跳过 confirmation 与 schema 校验（危险）"),
    ] = False,
    on_fail: Annotated[
        str,
        typer.Option("--on-fail", help="失败时：ask（询问继续）| park（归位并停）| abort（立即停止）"),
    ] = "ask",
) -> None:
    """阶段 4：按 tonight 计划串行 GOTO（J2000→当前 JNow）；可选曝光；失败策略可配。"""
    from telbot.planning.execute import (
        execute_tonight_plan,
        load_plan_json,
        resolve_latest_tonight_plan,
    )
    from telbot.planning.phase0_config import validate_planning_settings

    if on_fail not in ("ask", "park", "abort"):
        console.print("[red]--on-fail 必须是 ask | park | abort[/red]")
        raise typer.Exit(2)

    s = load_settings()
    try:
        validate_planning_settings(s)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(2) from e

    try:
        path = plan.expanduser().resolve() if plan is not None else resolve_latest_tonight_plan()
    except (OSError, FileNotFoundError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e

    try:
        payload = load_plan_json(path)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e

    if execute:
        _require_execute_guard(True, camera=snap)
        if not indi_available():
            console.print("[red]未找到 indi_setprop，无法真机执行。[/red]")
            raise typer.Exit(1)

    confirm_fn = (lambda m: typer.confirm(m, default=False)) if on_fail == "ask" else None

    try:
        out = execute_tonight_plan(
            s,
            payload,
            execute=execute,
            snap_after_goto=snap,
            on_failure=on_fail,  # type: ignore[arg-type]
            force=force,
            confirm_continue=confirm_fn,
        )
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(2) from e

    out = {**out, "plan_path": str(path.resolve())}
    console.print_json(data=out)
    if not out.get("ok", False):
        raise typer.Exit(1)


@plan_app.command("monitor")
def plan_monitor_cmd(
    interval_minutes: Annotated[
        Optional[float],
        typer.Option(
            "--interval-minutes",
            help="轮询间隔（分钟）；默认 TELBOT_PLAN_MONITOR_INTERVAL_MINUTES",
        ),
    ] = None,
    once: Annotated[
        bool,
        typer.Option("--once", help="只执行一轮检测后退出"),
    ] = False,
    execute: Annotated[
        bool,
        typer.Option("--execute", help="超阈时发送真实 Park（否则仅 JSON 报告）"),
    ] = False,
    max_iterations: Annotated[
        Optional[int],
        typer.Option(
            "--max-iterations",
            help="循环次数上限（与 --once 互斥时常用；默认无限直至 Ctrl+C）",
        ),
    ] = None,
) -> None:
    """阶段 5：按间隔拉取短时天气预报，超阈可 Park；自动调焦/导星未实现，脱焦风险见 README。"""
    from telbot.planning.monitor import run_monitor_cycle
    from telbot.planning.phase0_config import validate_planning_settings

    s = load_settings()
    try:
        validate_planning_settings(s)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(2) from e

    if once and max_iterations is not None:
        console.print("[red]不要同时使用 --once 与 --max-iterations[/red]")
        raise typer.Exit(2)

    interval = float(interval_minutes if interval_minutes is not None else s.plan_monitor_interval_minutes)
    interval_s = max(60.0, interval * 60.0)

    if execute:
        _require_execute_guard(True)
        if not indi_available():
            console.print("[red]未找到 indi_setprop，无法真机 Park。[/red]")
            raise typer.Exit(1)

    if once:
        out = run_monitor_cycle(s, execute_park=execute)
        console.print_json(data=out)
        if execute and out.get("park_triggered") and not out.get("park_executed", True):
            raise typer.Exit(1)
        return

    if max_iterations is None:
        console.print(
            f"[dim]阶段 5 持续监控，间隔约 {interval:.1f} 分钟；Ctrl+C 结束。每轮输出一条 JSON。[/dim]"
        )
        try:
            while True:
                out = run_monitor_cycle(s, execute_park=execute)
                console.print_json(data=out)
                if execute and out.get("park_triggered") and out.get("park_executed"):
                    break
                time.sleep(interval_s)
        except KeyboardInterrupt:
            console.print("[yellow]monitor 已停止[/yellow]")
        return

    results: list[dict[str, Any]] = []
    for i in range(int(max_iterations)):
        out = run_monitor_cycle(s, execute_park=execute)
        results.append(out)
        console.print_json(data=out)
        if execute and out.get("park_triggered") and out.get("park_executed"):
            break
        if i < int(max_iterations) - 1:
            time.sleep(interval_s)
    console.print_json(data={"cycles_done": len(results), "all": results})


@app.command("platesolve")
def platesolve_cmd(
    fits: Annotated[
        Optional[Path],
        typer.Argument(
            help="可选：已有 FITS 路径（须在 CCD 保存目录或 data/platesolve/in 下）；省略则先拍照再解算",
        ),
    ] = None,
    latest: Annotated[
        bool,
        typer.Option("--latest", "-l", help="不解算新图，仅用 CCD 保存目录内最新 .fits"),
    ] = False,
    seconds: Annotated[
        Optional[float],
        typer.Option(
            "-s",
            "--seconds",
            help="先拍再解算时的曝光秒数；省略则用 TELBOT_CCD_DEFAULT_EXPOSURE_SECONDS",
        ),
    ] = None,
    align: Annotated[
        str,
        typer.Option(
            "--align",
            help="解算成功后对准：none | sync（同步姿态）| slew（与 mount goto 同语义）；真机对准须加 --execute",
        ),
    ] = "none",
    execute: Annotated[
        bool,
        typer.Option(
            "--execute",
            help="先拍再解算时须加（真曝光）；对准望远镜时须加；仅解算旧图时仅在对准阶段生效",
        ),
    ] = False,
) -> None:
    """默认：真机 CCD 曝光一张，再对刚保存的 FITS 做 ASTAP（须 --execute）。另有 --latest 或 FITS 路径仅解算。"""
    if latest and fits is not None:
        console.print("[red]不能同时指定文件路径与 --latest[/red]")
        raise typer.Exit(2)
    if fits is not None:
        mode = "fits"
    elif latest:
        mode = "latest"
    else:
        mode = "snap_then_solve"

    align_n = align.strip().lower()
    if align_n not in ("none", "sync", "slew"):
        console.print("[red]--align 须为 none、sync 或 slew[/red]")
        raise typer.Exit(2)

    from telbot.ccd_paths import effective_ccd_save_dir
    from telbot.platesolve.security import (
        fits_files_in_dir,
        max_fits_mtime_ns_in_dir,
        resolve_new_capture_fits,
    )
    from telbot.platesolve.service import run_platesolve
    from telbot.platesolve_align import align_mount_after_platesolve

    s = load_settings()

    snap_out: dict | None = None
    try:
        if mode == "snap_then_solve":
            if not execute:
                console.print(
                    "[red]默认流程为「拍照再解算」，须加 --execute 才会真曝光；"
                    "若只解算已有图请加 --latest 或提供 FITS 路径。[/red]"
                )
                raise typer.Exit(2)
            _require_execute_guard(True, camera=True)
            if not indi_available():
                console.print("[red]未找到 indi_setprop。[/red]")
                raise typer.Exit(1)
            cap = effective_ccd_save_dir(s.ccd_save_dir)
            before_paths = fits_files_in_dir(cap)
            before_ns = max_fits_mtime_ns_in_dir(cap)
            snap_out = execute_voice_intent(
                s,
                VoiceIntentV1(version=1, action="snap", exposure_seconds=seconds),
                execute=True,
            )
            if not snap_out.get("ok"):
                console.print_json(data=snap_out)
                raise typer.Exit(1)
            cap_dir = cap
            hint = (snap_out.get("save_dir_hint") or "").strip()
            if hint:
                cap_dir = Path(hint).expanduser().resolve()
            new_fits = resolve_new_capture_fits(cap_dir, before_ns, before_paths)
            if new_fits is None:
                console.print(
                    f"[red]曝光后在 {cap} 未检测到新的 FITS；"
                    "请确认 INDI UPLOAD_SETTINGS.UPLOAD_DIR 与该目录一致且 UPLOAD_LOCAL=On。[/red]"
                )
                console.print_json(data={"snap": snap_out})
                raise typer.Exit(1)
            out = run_platesolve(s, fits_path=new_fits, use_latest=False)
        else:
            out = run_platesolve(s, fits_path=fits, use_latest=latest)
    except (ValueError, RuntimeError, ImportError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e

    if snap_out is not None:
        out = {**out, "snap": snap_out}

    if not out.get("ok"):
        console.print_json(data=out)
        raise typer.Exit(1)

    if align_n != "none":
        if execute:
            _require_execute_guard(True)
            if not indi_available():
                console.print("[red]未找到 indi_setprop。[/red]")
                raise typer.Exit(1)
        console.print(
            "[yellow]对准：确认镜筒周围无障碍、已 Unpark（若需）、单一控制源；"
            "sync 将当前指向在固件中同步为解算中心（JNow）。[/yellow]"
        )
        mode_align: Literal["sync", "slew"] = "sync" if align_n == "sync" else "slew"
        out["align"] = align_mount_after_platesolve(s, out, align=mode_align, execute=execute)

    console.print_json(data=out)
    if align_n != "none" and not (out.get("align") or {}).get("ok", False):
        raise typer.Exit(3)


serve_app = typer.Typer(
    no_args_is_help=False,
    help="本机 HTTP API（App / curl）；调试常用 serve restart",
)
app.add_typer(serve_app, name="serve")


def _print_serve_banner(host: str, port: int) -> None:
    console.print(
        f"Telbot API http://{host}:{port}  "
        "POST /goto  POST /goto/body  POST /park  POST /unpark  POST /connect  POST /disconnect  "
        "POST /abort  GET /focuser/position  POST /focuser/abs  "
        "POST /intent  POST /listen/text  POST /text  POST /listen/audio  POST /camera/snap  POST /platesolve  GET /health"
    )


@serve_app.callback(invoke_without_command=True)
def serve_entry(
    ctx: typer.Context,
    host: Annotated[
        str,
        typer.Option("--host", help="绑定地址；局域网 App 用 0.0.0.0"),
    ] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="HTTP 端口")] = 8765,
) -> None:
    """默认：前台运行 uvicorn（Ctrl+C 结束）。子命令 restart/stop/status 用于 Pi 调试。"""
    if ctx.invoked_subcommand is not None:
        return
    import uvicorn

    from telbot.http_app import app as fastapi_app

    _print_serve_banner(host, port)
    uvicorn.run(fastapi_app, host=host, port=port, log_level="info")


@serve_app.command("restart")
def serve_restart_cmd(
    host: Annotated[
        str,
        typer.Option("--host", help="绑定地址；默认读 TELBOT_SERVE_HOST 或 0.0.0.0"),
    ] = "",
    port: Annotated[int, typer.Option("--port", help="HTTP 端口")] = 0,
    reinstall: Annotated[
        bool,
        typer.Option(
            "--reinstall",
            "-r",
            help="重启前在 Telbot 目录执行 pip install -e .（Pi 上拉代码后建议加）",
        ),
    ] = False,
    no_wait: Annotated[
        bool,
        typer.Option("--no-wait", help="不等待 GET /health 成功"),
    ] = False,
) -> None:
    """停止占用端口的旧服务 → 可选重装包 → 后台启动新 telbot serve（App 调试专用）。"""
    from telbot.http_serve import restart_http_serve, serve_host, serve_port

    h = host.strip() or serve_host(restart=True)
    p = port or serve_port()
    try:
        for line in restart_http_serve(
            host=h,
            port=p,
            reinstall=reinstall,
            wait_health=not no_wait,
        ):
            console.print(line)
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    console.print(f"[green]HTTP 已重启：http://{h}:{p}[/green]")
    console.print(f"[dim]日志：见 telbot serve status[/dim]")


@serve_app.command("stop")
def serve_stop_cmd(
    port: Annotated[int, typer.Option("--port", help="HTTP 端口")] = 0,
) -> None:
    """停止 telbot serve（释放端口与 pid 文件）。"""
    from telbot.http_serve import serve_port, stop_http_serve

    for line in stop_http_serve(port=port or serve_port()):
        console.print(line)


@serve_app.command("status")
def serve_status_cmd(
    host: Annotated[str, typer.Option("--host", help="健康检查用的绑定地址")] = "",
    port: Annotated[int, typer.Option("--port")] = 0,
) -> None:
    """查看端口监听、pid 文件与 GET /health。"""
    from telbot.http_serve import http_serve_status_lines, serve_host, serve_port

    h = host.strip() or serve_host()
    p = port or serve_port()
    for line in http_serve_status_lines(host=h, port=p):
        console.print(line)


@app.command("preflight")
def preflight_cmd(
    json_out: Annotated[bool, typer.Option("--json", help="JSON 输出")] = False,
    host: Annotated[Optional[str], typer.Option("--host", "-h", help="INDI host（覆盖 .env）")] = None,
    port: Annotated[Optional[int], typer.Option("--port", "-p", help="INDI port")] = None,
) -> None:
    """设备就绪一键诊断：INDI 连接、赤道仪/CCD/电调/滤镜、.env、保存目录、PlaneWave PWI4 等。"""
    from telbot.preflight import run_preflight

    s = load_settings()
    if host is not None:
        s = s.model_copy(update={"indi_host": host})
    if port is not None:
        s = s.model_copy(update={"indi_port": port})
    out = run_preflight(s)
    if json_out:
        console.print_json(data=out)
    else:
        for line in (out.get("message") or "").splitlines():
            if line.startswith("  ✗") or "未通过" in line:
                console.print(f"[red]{line}[/red]")
            elif line.startswith("  !"):
                console.print(f"[yellow]{line}[/yellow]")
            elif line.startswith("  ✓"):
                console.print(f"[green]{line}[/green]")
            else:
                console.print(line)
    if not out.get("ready", False):
        raise typer.Exit(1)


@app.command("version")
def version_cmd() -> None:
    console.print(__version__)


catalog_app = typer.Typer(no_args_is_help=True, help="HYG 恒星表与 OpenNGC 深空表：下载与检索")
app.add_typer(catalog_app, name="catalog")


@catalog_app.command("download")
def catalog_download(
    url: Annotated[
        Optional[str],
        typer.Option("--url", help="覆盖默认 HYG CSV 地址"),
    ] = None,
) -> None:
    """下载 HYG 全表到 ~/.cache/telbot/catalog/（约数十 MB，需联网）。"""
    from telbot.catalog import HYG_CSV_URL, download_hyg_catalog

    u = url or HYG_CSV_URL
    console.print(f"下载中: {u}")
    try:
        path = download_hyg_catalog(url=u)
    except OSError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    console.print(f"[green]已保存：{path}[/green]")


@catalog_app.command("download-openngc")
def catalog_download_openngc(
    url: Annotated[
        Optional[str],
        typer.Option("--url", help="覆盖默认 OpenNGC NGC.csv 地址"),
    ] = None,
) -> None:
    """下载 OpenNGC（NGC/IC/梅西耶等）到 ~/.cache/telbot/catalog/（约数 MB，需联网）。"""
    from telbot.dso_catalog import OPENNGC_CSV_URL, download_openngc_catalog

    u = url or OPENNGC_CSV_URL
    console.print(f"下载 OpenNGC: {u}")
    try:
        path = download_openngc_catalog(url=u)
    except OSError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    console.print(f"[green]已保存：{path}[/green]")


@catalog_app.command("search")
def catalog_search(
    query: Annotated[str, typer.Argument(help="名称片段")],
    limit: Annotated[int, typer.Option("--limit", "-n", help="最多条数")] = 20,
) -> None:
    """在已下载的星表中按专名/Bayer 片段搜索。"""
    from telbot.catalog import search_stars

    try:
        names = search_stars(query, limit=limit)
    except FileNotFoundError as e:
        console.print(f"[yellow]{e}[/yellow]")
        raise typer.Exit(1) from e
    if not names:
        console.print("[dim]无匹配[/dim]")
        return
    for n in names:
        console.print(n)


@catalog_app.command("path")
def catalog_path_cmd() -> None:
    """打印本地 HYG CSV 路径。"""
    from telbot.catalog import catalog_csv_path

    console.print(str(catalog_csv_path()))


@catalog_app.command("path-openngc")
def catalog_path_openngc_cmd() -> None:
    """打印本地 OpenNGC CSV 路径。"""
    from telbot.dso_catalog import openngc_csv_path

    console.print(str(openngc_csv_path()))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
