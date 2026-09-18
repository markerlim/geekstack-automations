#!/usr/bin/env python3
"""Bake a new jihuanshe APK into the AVD snapshot the scraper boots from.

The orchestrator (crawl_parallel.py) always boots read-only + -no-snapshot-save
from a named snapshot (default "jp_library"), so an `adb install` on a live
run never sticks -- the next boot reverts to whatever APK was installed when
that snapshot was captured. When jihuanshe ships an update (an in-app "有新
版本" dialog the scraper doesn't know how to dismiss), refresh the snapshot
with the new APK using this script instead of doing it by hand:

    python3 refresh_apk_snapshot.py                    # uses JHS.apk in this dir
    python3 refresh_apk_snapshot.py --apk /path/to.apk
    python3 refresh_apk_snapshot.py --no-verify         # skip the reboot check

Needs exclusive access to the AVD (only one writable instance at a time), so
it refuses to run while any emulator for this AVD is already up -- kill those
first (`adb -s <serial> emu kill`) or pass --force-kill.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

import crawl_union_arena_all_sets as C

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_APK = os.path.join(HERE, "JHS.apk")
SERIAL = "emulator-5554"     # fixed ports so we know exactly which device to talk to


def _run(*args, timeout=30, check=True):
    return subprocess.run(list(args), capture_output=True, timeout=timeout, check=check)


def _running_avd_pids(avd: str) -> list[str]:
    out = subprocess.run(["pgrep", "-f", f"emulator -avd {avd}"],
                          capture_output=True, text=True).stdout
    return [p for p in out.split() if p]


def _adb(*args, timeout=30, check=False):
    return subprocess.run(["adb", "-s", SERIAL, *args],
                          capture_output=True, timeout=timeout, check=check)


def _version_name() -> str | None:
    out = _adb("shell", "dumpsys", "package", C.APP_PKG, timeout=15).stdout.decode()
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("versionName="):
            return line.split("=", 1)[1]
    return None


def _boot_writable(avd: str, snapshot: str | None, timeout_s: float) -> None:
    emu = C._find_emulator_bin()
    if not emu:
        raise RuntimeError("no `emulator` binary found; set ANDROID_SDK_ROOT.")
    cmd = [emu, "-avd", avd, "-ports", "5554,5555", "-no-boot-anim"]
    cmd += (["-snapshot", snapshot] if snapshot else ["-no-snapshot-load"])
    print(f"booting writable {avd} (snapshot={snapshot or '-'}) ...", flush=True)
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    if not C._wait_boot(timeout_s, serial=SERIAL):
        raise RuntimeError(f"{SERIAL} didn't finish booting in {timeout_s:.0f}s")


def _kill(timeout_s: float = 60) -> None:
    _adb("emu", "kill")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not C._device_online(SERIAL):
            return
        time.sleep(2)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apk", default=DEFAULT_APK)
    ap.add_argument("--avd", default="Pixel_3a_API_34")
    ap.add_argument("--snapshot", default="jp_library")
    ap.add_argument("--boot-timeout", type=float, default=180)
    ap.add_argument("--force-kill", action="store_true",
                    help="kill any already-running instance of --avd first")
    ap.add_argument("--no-verify", action="store_true",
                    help="skip the post-save read-only reboot check")
    args = ap.parse_args()

    if not os.path.exists(args.apk):
        print(f"apk not found: {args.apk}", file=sys.stderr)
        return 2

    pids = _running_avd_pids(args.avd)
    if pids:
        if not args.force_kill:
            print(f"{args.avd} is already running (pid {', '.join(pids)}) -- "
                  f"the snapshot needs exclusive write access. Stop it first "
                  f"(adb -s <serial> emu kill) or re-run with --force-kill.",
                  file=sys.stderr)
            return 1
        print(f"--force-kill: stopping {len(pids)} running instance(s) of {args.avd} ...",
              flush=True)
        subprocess.run(["pkill", "-f", f"emulator -avd {args.avd}"], check=False)
        deadline = time.time() + 30
        while time.time() < deadline and _running_avd_pids(args.avd):
            time.sleep(1)

    # 1. boot writable from the current snapshot (falls back to a cold boot if
    #    the snapshot doesn't exist yet) so login/nav state carries over.
    have_snapshot = os.path.exists(os.path.expanduser(
        f"~/.android/avd/{args.avd}.avd/snapshots/{args.snapshot}"))
    _boot_writable(args.avd, args.snapshot if have_snapshot else None, args.boot_timeout)

    before = _version_name()
    print(f"snapshot's current app version: {before or 'not installed'}", flush=True)

    # 2. install the new APK (adds -g to auto-grant runtime permissions, same
    #    as the scraper's own _install_and_launch()).
    print(f"installing {args.apk} ...", flush=True)
    r = _adb("install", "-r", "-g", args.apk, timeout=300)
    if r.returncode != 0:
        print(f"adb install failed: {r.stderr.decode()[:400]}", file=sys.stderr)
        _kill()
        return 1
    after = _version_name()
    print(f"installed app version: {after}", flush=True)

    # 3. navigate to the card-library screen with the scraper's own recovery
    #    logic -- if it can't get there, don't save a broken snapshot.
    C.ADB = ["adb", "-s", SERIAL]
    try:
        C.ensure_library_screen()
    except RuntimeError as e:
        print(f"could not reach the card-library screen after install: {e}",
              file=sys.stderr)
        _kill()
        return 1
    print("on the card-library screen -- saving snapshot", flush=True)

    # 4. persist it.
    r = _adb("emu", "avd", "snapshot", "save", args.snapshot, timeout=60)
    if r.returncode != 0:
        print(f"snapshot save failed: {r.stderr.decode()[:400]}", file=sys.stderr)
        _kill()
        return 1
    print(f"snapshot '{args.snapshot}' saved.", flush=True)
    _kill()

    if args.no_verify:
        return 0

    # 5. verification: boot it exactly the way the orchestrator does
    #    (-read-only -no-snapshot-save) and confirm the version + screen stick.
    print("verifying: rebooting read-only from the saved snapshot ...", flush=True)
    proc = C.boot_emulator_instance(args.avd, 5554, snapshot=args.snapshot)
    try:
        if not C._wait_boot(args.boot_timeout, serial=SERIAL):
            print("verification boot timed out", file=sys.stderr)
            return 1
        got = _version_name()
        if got != after:
            print(f"verification FAILED: snapshot has {got!r}, expected {after!r}",
                  file=sys.stderr)
            return 1
        try:
            C.ensure_library_screen()
        except RuntimeError as e:
            print(f"verification FAILED: {e}", file=sys.stderr)
            return 1
        print(f"verified: fresh read-only boot is on {got} and reaches the "
              f"library screen.", flush=True)
    finally:
        _kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
