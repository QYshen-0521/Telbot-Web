"""Block apt/dpkg transactions that would remove or replace the Debian Telbot INDI driver stack."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Keep in sync with deploy/install-indi-drivers-debian.sh
PROTECTED_PACKAGES: frozenset[str] = frozenset(
    {
        "indi-bin",
        "indi-sbig",
        "indi-asi",
        "libsbig4t64",
        "libindidriver1",
        "libindiclient1",
        "libindi-data",
    }
)

# astroberry / INDI 2.x stack — conflicts with libindidriver1 + indi-sbig
FORBIDDEN_INSTALL_PACKAGES: frozenset[str] = frozenset({"libindi1"})

# trixie often has no candidate; if forced from third-party mirror, same conflict risk
RISKY_INSTALL_PACKAGES: frozenset[str] = frozenset(
    {"indi-qhy", "indi-astroasis", "indi-celestron"}
)

REQUIRED_BINARIES: tuple[str, ...] = (
    "indiserver",
    "indi_getprop",
    "indi_lx200gemini",
    "indi_sbig_ccd",
    "indi_asi_ccd",
)

OPTIONAL_BINARIES: tuple[str, ...] = (
    "indi_qhy_ccd",
    "indi_oasis_focuser",
    "indi_qhycfw3_wheel",
    "indi_celestron_gps",
)

_REMOVAL_STATUS = frozenset({"remove", "removal", "purge", "deinstall", "disappear"})


@dataclass
class AptTransaction:
    installs: set[str] = field(default_factory=set)
    upgrades: set[str] = field(default_factory=set)
    removals: set[str] = field(default_factory=set)

    def all_install_like(self) -> set[str]:
        return self.installs | self.upgrades


@dataclass
class GuardReport:
    ok: bool
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def raise_if_blocked(self) -> None:
        if not self.ok:
            raise SystemExit(format_blocked_message(self))


def guard_disabled() -> bool:
    return os.environ.get("TELBOT_INDI_GUARD_DISABLED", "").strip() in (
        "1",
        "true",
        "yes",
    )


def format_blocked_message(report: GuardReport) -> str:
    lines = [
        "TELBOT INDI 驱动保护：已阻止本次 apt/dpkg 操作。",
        "（会破坏已安装的 Debian indi-bin / indi-sbig / indi-asi 等同栈）",
        "",
    ]
    for v in report.violations:
        lines.append(f"  • {v}")
    if report.warnings:
        lines.append("")
        lines.append("警告：")
        for w in report.warnings:
            lines.append(f"  • {w}")
    lines.extend(
        [
            "",
            "建议：",
            "  • 先查看计划：telbot indi apt-guard check -- apt install <包名>",
            "  • 恢复驱动：sudo bash ~/Telbot/deploy/install-indi-drivers-debian.sh",
            "  • 文档：docs/INDI_APT_STACK.md",
            "  • 仅紧急维护可临时：TELBOT_INDI_GUARD_DISABLED=1 sudo apt …",
        ]
    )
    return "\n".join(lines)


def parse_dpkg_hook_line(line: str) -> tuple[str, str] | None:
    """Parse ``DPkg::Pre-Install-Pkgs`` line: ``status package version arch``."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    parts = line.split()
    if len(parts) < 2:
        return None
    status = parts[0].lower()
    package = parts[1].lower()
    return status, package


def transaction_from_hook_lines(lines: list[str]) -> AptTransaction:
    txn = AptTransaction()
    for line in lines:
        parsed = parse_dpkg_hook_line(line)
        if not parsed:
            continue
        status, package = parsed
        if status == "install":
            txn.installs.add(package)
        elif status == "upgrade":
            txn.upgrades.add(package)
        elif status in _REMOVAL_STATUS:
            txn.removals.add(package)
    return txn


_RE_SECTION_REMOVED = re.compile(
    r"^The following packages will be REMOVED:\s*$", re.MULTILINE
)
_RE_SECTION_INSTALLED = re.compile(
    r"^The following NEW packages will be installed:\s*$", re.MULTILINE
)
_RE_SECTION_UPGRADED = re.compile(
    r"^The following packages will be upgraded:\s*$", re.MULTILINE
)


def _packages_from_section(text: str, start: int) -> set[str]:
    pkgs: set[str] = set()
    started = False
    for line in text[start:].splitlines():
        s = line.strip()
        if not s:
            if started:
                break
            continue
        if s.startswith("The following") or s.startswith("WARNING") or s.startswith("debconf"):
            break
        if s[0] in "-+":
            continue
        pkgs.update(s.split())
        started = True
    return {p.lower() for p in pkgs}


def parse_apt_simulate_output(text: str) -> AptTransaction:
    txn = AptTransaction()
    for m in _RE_SECTION_REMOVED.finditer(text):
        txn.removals |= _packages_from_section(text, m.end())
    for m in _RE_SECTION_INSTALLED.finditer(text):
        txn.installs |= _packages_from_section(text, m.end())
    for m in _RE_SECTION_UPGRADED.finditer(text):
        txn.upgrades |= _packages_from_section(text, m.end())
    # apt sometimes prints "REMOVING indi-sbig" inline
    for pkg in PROTECTED_PACKAGES | FORBIDDEN_INSTALL_PACKAGES | RISKY_INSTALL_PACKAGES:
        if re.search(rf"\bREMOVING\s+{re.escape(pkg)}\b", text, re.IGNORECASE):
            txn.removals.add(pkg)
    return txn


def dpkg_installed_packages(candidates: frozenset[str] | None = None) -> set[str]:
    names = candidates or PROTECTED_PACKAGES
    if not names:
        return set()
    try:
        proc = subprocess.run(
            [
                "dpkg-query",
                "-W",
                "-f",
                "${Package}\t${Status}\n",
                *sorted(names),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return set()
    if proc.returncode != 0:
        return set()
    installed: set[str] = set()
    for line in (proc.stdout or "").splitlines():
        if "\t" not in line:
            continue
        pkg, status = line.split("\t", 1)
        if status.strip() == "install ok installed":
            installed.add(pkg.strip().lower())
    return installed


def binaries_on_path(names: tuple[str, ...]) -> set[str]:
    return {b for b in names if shutil.which(b)}


def evaluate_transaction(
    txn: AptTransaction,
    *,
    installed_protected: set[str] | None = None,
) -> GuardReport:
    if guard_disabled():
        return GuardReport(ok=True)

    installed = installed_protected
    if installed is None:
        installed = dpkg_installed_packages(PROTECTED_PACKAGES)

    violations: list[str] = []
    warnings: list[str] = []

    for pkg in sorted(txn.removals):
        if pkg in installed:
            violations.append(
                f"将卸载已安装的保护包「{pkg}」（当前为 Telbot 现场 INDI 栈的一部分）。"
            )

    for pkg in sorted(txn.all_install_like()):
        if pkg in FORBIDDEN_INSTALL_PACKAGES:
            violations.append(
                f"将安装「{pkg}」（INDI 2.x / astroberry 栈），与已装的 libindidriver1 / indi-sbig 冲突。"
            )
        elif pkg in RISKY_INSTALL_PACKAGES:
            warnings.append(
                f"将安装「{pkg}」：trixie 官方源通常无此包；若来自第三方源，可能触发卸载 indi-bin / indi-sbig。"
            )

    # Classic conflict: new indi-bin (2.x) removes indi-sbig
    if "indi-sbig" in txn.removals and "indi-sbig" in installed:
        if txn.all_install_like() & ({"indi-bin", "libindi1"} | RISKY_INSTALL_PACKAGES):
            violations.append(
                "将卸载 indi-sbig，同时安装 indi-bin / libindi1 / 第三方 indi-qhy 等（典型 astroberry 冲突）。"
            )

    if "libindidriver1" in txn.removals and installed & {"indi-sbig", "indi-bin", "indi-asi"}:
        violations.append(
            "将卸载 libindidriver1，但 indi-bin / indi-sbig / indi-asi 仍应保留（会破坏全部 Debian 驱动）。"
        )

    if "indi-bin" in txn.removals and "indi-bin" in installed:
        if "indi-bin" not in txn.all_install_like():
            violations.append(
                "将卸载 indi-bin 且不会在同一次事务中装回（indiserver / indi_lx200gemini 会丢失）。"
            )

    present_bins = binaries_on_path(REQUIRED_BINARIES)
    for pkg in txn.removals:
        for binary in present_bins:
            owner = _binary_owned_by_package(binary)
            if owner == pkg:
                violations.append(
                    f"将卸载「{pkg}」，而系统上仍有 /usr/bin/{binary}（现场必需驱动）。"
                )

    ok = len(violations) == 0
    return GuardReport(ok=ok, violations=violations, warnings=warnings)


def _binary_owned_by_package(binary: str) -> str | None:
    path = shutil.which(binary)
    if not path:
        return None
    try:
        proc = subprocess.run(
            ["dpkg-query", "-S", path],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    # "indi-sbig: /usr/bin/indi_sbig_ccd"
    head = (proc.stdout or "").split(":", 1)[0].strip().lower()
    return head or None


def run_apt_simulate(apt_argv: list[str]) -> str:
    if not apt_argv:
        raise SystemExit("用法：telbot indi apt-guard check -- apt install <包…>")
    cmd = ["apt-get", "-s", "-o", "Debug::NoLocking=true", *apt_argv]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0 and "Simulation complete" not in out:
        raise SystemExit(f"apt 模拟失败 ({proc.returncode}):\n{out.strip()}")
    return out


def check_apt_argv(apt_argv: list[str]) -> GuardReport:
    text = run_apt_simulate(apt_argv)
    txn = parse_apt_simulate_output(text)
    return evaluate_transaction(txn)


def hook_main() -> int:
    lines = sys.stdin.read().splitlines()
    txn = transaction_from_hook_lines(lines)
    if not (txn.installs or txn.upgrades or txn.removals):
        return 0
    report = evaluate_transaction(txn)
    if report.ok:
        for w in report.warnings:
            print(f"telbot-indi-guard: 警告: {w}", file=sys.stderr)
        return 0
    print(format_blocked_message(report), file=sys.stderr)
    return 1


def status_lines() -> list[str]:
    lines: list[str] = []
    lines.append("INDI apt 保护（telbot indi apt-guard）")
    if guard_disabled():
        lines.append("  状态：已禁用（TELBOT_INDI_GUARD_DISABLED=1）")
    else:
        lines.append("  状态：已启用")
    hook = Path("/etc/apt/apt.conf.d/99telbot-indi-guard")
    if hook.is_file():
        lines.append(f"  apt 钩子：{hook}（已安装）")
    else:
        lines.append(
            "  apt 钩子：未安装 → sudo bash ~/Telbot/deploy/install-indi-apt-guard.sh"
        )
    installed = dpkg_installed_packages(PROTECTED_PACKAGES)
    lines.append(f"  已安装保护包：{', '.join(sorted(installed)) or '(无)'}")
    req = binaries_on_path(REQUIRED_BINARIES)
    lines.append(f"  必需二进制：{', '.join(sorted(req)) or '(缺失)'}")
    opt = binaries_on_path(OPTIONAL_BINARIES)
    if opt:
        lines.append(f"  可选二进制：{', '.join(sorted(opt))}")
    return lines


def cli_main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args or args[0] in ("-h", "--help"):
        print(
            "用法:\n"
            "  python -m telbot.indi_apt_guard hook          # apt Pre-Install-Pkgs（stdin）\n"
            "  python -m telbot.indi_apt_guard status\n"
            "  python -m telbot.indi_apt_guard check -- apt install …\n"
        )
        return 0
    cmd = args[0]
    if cmd == "hook":
        return hook_main()
    if cmd == "status":
        for line in status_lines():
            print(line)
        return 0
    if cmd == "check":
        rest = args[1:]
        if rest and rest[0] == "--":
            rest = rest[1:]
        report = check_apt_argv(rest)
        for w in report.warnings:
            print(f"警告: {w}")
        if report.ok:
            print("检查通过：本次模拟不会卸载已保护的核心 INDI 包。")
            return 0
        print(format_blocked_message(report))
        return 1
    print(f"未知子命令: {cmd}", file=sys.stderr)
    return 2
