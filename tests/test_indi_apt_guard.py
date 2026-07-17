"""INDI apt/dpkg guard (simulate parsing and policy)."""

from __future__ import annotations

from telbot.indi_apt_guard import (
    AptTransaction,
    evaluate_transaction,
    parse_apt_simulate_output,
    parse_dpkg_hook_line,
    transaction_from_hook_lines,
)


def test_parse_dpkg_hook_line() -> None:
    assert parse_dpkg_hook_line("install indi-asi 1.9.9 arm64") == ("install", "indi-asi")
    assert parse_dpkg_hook_line("removal indi-sbig 1.9.9 arm64") == ("removal", "indi-sbig")


def test_transaction_from_hook_lines() -> None:
    txn = transaction_from_hook_lines(
        [
            "install indi-bin 1.9.9 arm64",
            "removal indi-sbig 1.9.9 arm64",
        ]
    )
    assert txn.installs == {"indi-bin"}
    assert txn.removals == {"indi-sbig"}


def test_blocks_removing_installed_indi_sbig() -> None:
    txn = AptTransaction(removals={"indi-sbig"}, installs={"indi-bin"})
    report = evaluate_transaction(txn, installed_protected={"indi-sbig", "indi-bin"})
    assert not report.ok
    assert any("indi-sbig" in v for v in report.violations)


def test_blocks_libindi1_install() -> None:
    txn = AptTransaction(installs={"libindi1"})
    report = evaluate_transaction(txn, installed_protected={"indi-bin", "indi-sbig"})
    assert not report.ok
    assert any("libindi1" in v for v in report.violations)


def test_allows_empty_transaction() -> None:
    report = evaluate_transaction(AptTransaction(), installed_protected={"indi-bin"})
    assert report.ok


def test_parse_apt_simulate_removed_section() -> None:
    text = """
NOTE: This is only a simulation.
The following packages will be REMOVED:
  indi-sbig indi-asi
The following NEW packages will be installed:
  indi-bin
"""
    txn = parse_apt_simulate_output(text)
    assert txn.removals == {"indi-sbig", "indi-asi"}
    assert txn.installs == {"indi-bin"}


def test_simulate_conflict_report() -> None:
    txn = parse_apt_simulate_output(
        "The following packages will be REMOVED:\n  indi-sbig\n"
        "The following NEW packages will be installed:\n  libindi1\n"
    )
    report = evaluate_transaction(txn, installed_protected={"indi-sbig", "libindidriver1"})
    assert not report.ok
