"""Push-to-talk recording: hold Space, release to stop (ALSA arecord)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from rich.console import Console


def _arecord_cmd(device: str, out_path: Path) -> list[str]:
    return [
        "arecord",
        "-D",
        device,
        "-f",
        "S16_LE",
        "-c",
        "1",
        "-r",
        "16000",
        "-t",
        "wav",
        str(out_path),
    ]


def record_fixed_seconds(
    out_path: Path,
    device: str,
    seconds: float,
    *,
    console: Console,
) -> None:
    """Record for a fixed duration (no pynput)."""
    if not shutil.which("arecord"):
        raise RuntimeError("未找到 arecord：请安装 alsa-utils（如 sudo apt install alsa-utils）")
    sec = max(0.5, min(120.0, float(seconds)))
    d = max(1, int(round(sec)))
    cmd = [
        "arecord",
        "-D",
        device,
        "-f",
        "S16_LE",
        "-c",
        "1",
        "-r",
        "16000",
        "-t",
        "wav",
        "-d",
        str(d),
        str(out_path),
    ]
    console.print(f"[dim]录音 {d} 秒…[/dim]")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=d + 15)
    if r.returncode != 0:
        raise RuntimeError(r.stderr or r.stdout or "arecord 失败")


def record_hold_space_until_release(
    out_path: Path,
    device: str,
    *,
    console: Console,
    max_seconds: float = 120.0,
) -> None:
    """
    Wait for Space key down → start arecord; Space up → stop.
    Runs on the machine where Python executes (Pi 本机键盘；SSH 时键盘事件在 Pi 侧）。
    """
    if not shutil.which("arecord"):
        raise RuntimeError("未找到 arecord：请安装 alsa-utils（如 sudo apt install alsa-utils）")

    try:
        from pynput import keyboard
    except ImportError as e:
        raise ImportError("需要 pynput：pip install -e '.[voice]'") from e

    proc: subprocess.Popen | None = None
    recording = False
    start_ts: float = 0.0

    def stop_recording() -> None:
        nonlocal proc, recording
        if proc is not None:
            p = proc
            proc = None
            p.terminate()
            try:
                p.wait(timeout=8)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(timeout=3)
        recording = False

    def on_press(key: keyboard.Key | keyboard.KeyCode) -> None:
        nonlocal proc, recording, start_ts
        if key != keyboard.Key.space or recording:
            return
        recording = True
        start_ts = time.monotonic()
        if out_path.exists():
            out_path.unlink()
        proc = subprocess.Popen(
            _arecord_cmd(device, out_path),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def on_release(key: keyboard.Key | keyboard.KeyCode) -> bool | None:
        nonlocal recording
        if key != keyboard.Key.space:
            return None
        if recording:
            stop_recording()
            return False
        return None

    console.print(
        "[bold]按住空格键说话，松开结束[/bold]（本机键盘；Ctrl+C 退出）"
    )
    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()

    try:
        while listener.running:
            time.sleep(0.05)
            if recording and (time.monotonic() - start_ts) > max_seconds:
                console.print("[yellow]已达最长录音时间，自动停止。[/yellow]")
                stop_recording()
                listener.stop()
                break
    except KeyboardInterrupt:
        stop_recording()
        listener.stop()
        raise

    listener.join(timeout=2.0)
    if not out_path.is_file() or out_path.stat().st_size < 200:
        raise RuntimeError("录音过短或失败；请确认麦克风与 ALSA 设备（TELBOT_ALSA_ARECORD_DEVICE）")
