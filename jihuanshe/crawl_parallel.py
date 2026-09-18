#!/usr/bin/env python3
"""Run crawl_union_arena_all_sets.py for several tabs at once, one emulator per worker.

One device can only be driven by one worker (uiautomator dump + input tap act on a
single screen), so real parallelism = one Android emulator per concurrent tab. This
orchestrator:

  1. boots --workers read-only instances of a single AVD on fixed ports
     (emulator-5554, emulator-5556, ...), SEQUENTIALLY with a stagger, from a snapshot,
  2. JOB 1 -- enumerate: workers sweep each tab's strip once and write the full
     {tab: [set codes]} manifest to out/sets_manifest.json (reused on re-runs;
     --re-enumerate to refresh),
  3. JOB 2 -- scrape: a SET-level queue. Each worker pulls a chunk of --chunk
     consecutive sets (sticky to its current tab, so navigation stays cheap) and
     runs `crawl_union_arena_all_sets.py --tabs <tab> --sets <codes...>`. A failed
     set goes back on the queue (3 attempts) and a bad chunk gets that emulator
     rebooted from the snapshot -- one dying emulator now costs a few sets,
     not a whole tab,
  4. kills the emulators (always, even on crash),
  5. merges every out/<tab>.json plus the existing canonical file back into the
     canonical file (dedupe on jhs_code+cardId+rarity, atomic write),
  6. prints a timing table (per tab + total) and any sets still missing.

Prerequisite: a saved AVD snapshot whose state is the logged-in 携战之境UA 日文 card
library (horizontal set-icon strip visible). Capture it once -- see the project plan.
Or pass --manual to cold-boot and navigate each emulator by hand before the crawl.

Example:
    cd jihuanshe
    python crawl_parallel.py --workers 2                       # 2 emulators, 4 tabs, pooled
    python crawl_parallel.py --tabs PR 现场活动 --workers 2     # just these two
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

import crawl_union_arena_all_sets as C

HERE = os.path.dirname(os.path.abspath(__file__))
CRAWLER = os.path.join(HERE, "crawl_union_arena_all_sets.py")

# stable, filesystem-friendly names for the per-tab output files
TAB_SLUG = {"补充包": "booster", "构筑": "structure", "现场活动": "event", "PR": "pr", "其他＆周边":"others"}


def slug(tab: str) -> str:
    return TAB_SLUG.get(tab) or re.sub(r"\W+", "_", tab).strip("_") or "tab"


def _read_missed(out_path: str) -> dict:
    """{set_code: reason} of sets a worker could not capture (from the
    <out>.missed.json sidecar the crawler writes)."""
    try:
        with open(out_path + ".missed.json", "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    out: dict = {}
    for per_tab in data.values():
        out.update(per_tab)
    return out


def fmt_hms(secs: float) -> str:
    secs = int(round(secs))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}h{m:02d}m{s:02d}s" if h else f"{m:d}m{s:02d}s"


_print_lock = threading.Lock()


def _pump(tag: str, stream, activity: list) -> None:
    """Relay a worker's stdout with a [tag] prefix; `activity[0]` is bumped to
    time.monotonic() on every line so the watchdog can tell a live worker from
    a hung one."""
    for line in iter(stream.readline, ""):
        activity[0] = time.monotonic()
        with _print_lock:
            sys.stdout.write(f"[{tag}] " + (line if line.endswith("\n") else line + "\n"))
            sys.stdout.flush()
    stream.close()


def _devices() -> set[str]:
    try:
        out = subprocess.run(["adb", "devices"], capture_output=True, timeout=10).stdout.decode()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return set()
    return {ln.split("\t")[0].strip()
            for ln in out.splitlines()[1:] if ln.strip() and "\t" in ln}


def preflight(ports: list[int], avd: str) -> None:
    """Fail fast on the things that silently wreck a parallel run."""
    live = _devices()
    clash = [f"emulator-{p}" for p in ports if f"emulator-{p}" in live]
    if clash:
        raise SystemExit(
            f"port(s) already in use by a running device: {', '.join(clash)}.\n"
            f"Kill it first:  " + "  ".join(f"adb -s {s} emu kill" for s in clash))
    avd_dir = os.path.expanduser(f"~/.android/avd/{avd}.avd")
    if not live and os.path.isdir(avd_dir):
        locks = [f for f in os.listdir(avd_dir) if f.endswith(".lock")]
        if locks:
            print(f"WARNING: stale lock(s) in {avd_dir}: {locks} -- "
                  f"delete them if no emulator is running.", flush=True)


def _slot_healthy(serial: str) -> bool:
    """Quick check that an emulator is still usable: online AND uiautomator
    still answers within a bounded time (a wedged uiautomator is the classic
    parallel-load failure)."""
    try:
        st = subprocess.run(["adb", "-s", serial, "get-state"],
                            capture_output=True, timeout=8).stdout.decode().strip()
        if st != "device":
            return False
        r = subprocess.run(["adb", "-s", serial, "exec-out", "uiautomator", "dump", "/dev/tty"],
                           capture_output=True, timeout=25).stdout.decode("utf-8", "replace")
        return "</hierarchy>" in r
    except (subprocess.SubprocessError, OSError):
        return False


def _spawn_watched(tag: str, cmd: list[str], outp: str, args,
                   warmup_s: float | None = None,
                   track_rows: bool = True) -> tuple[int, bool]:
    """Run one crawler subprocess with [tag]-prefixed output and a watchdog.
    JOB 2 (track_rows=True): kill if no new card row for --stall-timeout AND
    stdout idle > warmup. JOB 1 (track_rows=False, e.g. enumeration writes a
    manifest, not card rows): kill only on a fully frozen stdout.
    Returns (rc, was_killed_by_watchdog)."""
    before = len(C._load_rows(outp)) if track_rows else 0
    t = time.monotonic()
    env = {**os.environ, "UA_PARALLEL": "1"}
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, bufsize=1, env=env)
    activity = [time.monotonic()]
    killed = threading.Event()

    def watchdog() -> None:
        # PROGRESS, not chatter: a stuck worker still prints "budget hit"
        # lines forever, so watch the row count. Warm-up grace covers
        # boot-to-first-set.
        last_rows = before
        last_progress = time.monotonic()
        warmup = t + (warmup_s if warmup_s is not None
                      else max(args.stall_timeout * 2, 900))
        while p.poll() is None:
            time.sleep(20)
            if track_rows:
                rows = len(C._load_rows(outp))
                if rows > last_rows:
                    last_rows, last_progress = rows, time.monotonic()
            no_progress = time.monotonic() - last_progress
            frozen = time.monotonic() - activity[0]
            row_stall = (track_rows and no_progress >= args.stall_timeout
                         and time.monotonic() > warmup)
            if row_stall or frozen >= args.stall_timeout:
                killed.set()
                with _print_lock:
                    what = (f"no new rows for {fmt_hms(no_progress)} "
                            if row_stall else "stdout frozen ")
                    print(f"[orchestrator] {tag}: {what}"
                          f"(stdout idle {fmt_hms(frozen)}) -- killing (stalled)",
                          flush=True)
                p.kill()
                return

    wd = threading.Thread(target=watchdog, daemon=True)
    wd.start()
    _pump(tag, p.stdout, activity)
    rc = p.wait()
    wd.join(timeout=2)
    return rc, killed.is_set()


def _tab_outp(tab: str, args) -> str:
    outp = os.path.join(args.out_dir, f"{slug(tab)}.json")
    if args.seed and not os.path.exists(outp) and os.path.exists(args.canonical):
        shutil.copyfile(args.canonical, outp)               # resume: skip done sets
    return outp


def _captured_codes(*paths: str) -> set[str]:
    out: set[str] = set()
    for p in paths:
        out |= {r.jhs_code for r in C._load_rows(p)}
    return out


def _tab_parts(out_dir: str, tab: str) -> list[str]:
    """Every JOB-2 part file for a tab (each chunk writes its own so parallel
    workers on the same tab never clobber a shared file)."""
    import glob
    return sorted(glob.glob(os.path.join(out_dir, f"{slug(tab)}.part_*.json")))


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tabs", nargs="*", default=list(C.TABS))
    ap.add_argument("--workers", type=int, default=2,
                    help="concurrent emulators (default 2). Use 1 for the most reliable "
                         "run -- one emulator, tabs sequential, no flaky 2nd -read-only "
                         "instance (this is what keeps losing the PR tab).")
    ap.add_argument("--avd", default="Pixel_3a_API_34")
    ap.add_argument("--apk", default=C._DEFAULT_APK if os.path.exists(C._DEFAULT_APK) else None)
    ap.add_argument("--snapshot", default="jp_library",
                    help='AVD snapshot to boot from; "" disables (cold boot)')
    ap.add_argument("--manual", action="store_true",
                    help="cold-boot (ignore --snapshot) and pause for you to navigate each "
                         "emulator to the library screen before crawling")
    ap.add_argument("--out-dir", default="out")
    ap.add_argument("--base-port", type=int, default=5554, help="console port of the first worker")
    ap.add_argument("--canonical", default="union_arena_boosters_all_sets.json")
    ap.add_argument("--boot-timeout", type=float, default=300)
    ap.add_argument("--stall-timeout", type=float, default=480,
                    help="kill+recover a worker with no stdout AND no output-file growth "
                         "for this many seconds (degraded emulator)")
    ap.add_argument("--boot-stagger", type=float, default=20,
                    help="seconds between starting each emulator "
                         "(concurrent starts break one instance's networking)")
    ap.add_argument("--no-window", action="store_true",
                    help="headless emulators (-no-window -gpu swiftshader_indirect)")
    ap.add_argument("--keep-emulators", action="store_true",
                    help="don't `emu kill` when the run finishes")
    ap.add_argument("--seed", dest="seed", action="store_true", default=True,
                    help="pre-fill each out/<tab>.json from the canonical file so workers resume")
    ap.add_argument("--no-seed", dest="seed", action="store_false",
                    help="start every tab from an empty file (full re-scrape)")
    ap.add_argument("--merge", dest="merge", action="store_true", default=True)
    ap.add_argument("--no-merge", dest="merge", action="store_false",
                    help="leave out/<tab>.json alone; don't fold them into --canonical")
    ap.add_argument("--chunk", type=int, default=8,
                    help="sets per worker assignment in JOB 2 (smaller = finer fault "
                         "isolation, larger = less tab-switch overhead)")
    ap.add_argument("--re-enumerate", action="store_true",
                    help="ignore an existing out/sets_manifest.json and re-run JOB 1")
    return ap


def run(args) -> dict:
    """Execute the parallel crawl. `--workers` long-lived emulators pull tabs
    off a shared queue -- an emulator that finishes its tab early immediately
    starts the next one instead of idling until its batch-mate is done.
    Returns a result dict: rc, tab_secs, counts {tab:[before,after]},
    missed {tab:{...}}, slot_of {tab:serial}, merge (before,after)|None,
    total_secs."""
    os.makedirs(args.out_dir, exist_ok=True)
    tabs = list(args.tabs)
    n_slots = min(max(1, args.workers), len(tabs))
    ports = [args.base_port + 2 * i for i in range(n_slots)]
    preflight(ports, args.avd)

    results: dict = {"rc": {}, "tab_secs": {}, "counts": {}, "missed": {},
                     "slot_of": {}, "merge": None, "total_secs": 0.0}
    t0 = time.monotonic()

    # boot the slot emulators once, SEQUENTIALLY with a stagger (concurrent
    # starts race QEMU NAT init and leave one instance with dead networking).
    snapshot = None if (args.manual or not args.snapshot) else args.snapshot
    t_boot = time.monotonic()
    serials: list[str] = []
    for i, port in enumerate(ports):
        if i:
            time.sleep(args.boot_stagger)
        serials.append(C.ensure_emulator_instance(
            args.avd, args.apk, port, snapshot=snapshot,
            boot_timeout=args.boot_timeout, no_window=args.no_window))
    print(f"[orchestrator] {len(serials)} emulator(s) up in "
          f"{fmt_hms(time.monotonic() - t_boot)}: {', '.join(serials)}", flush=True)

    if args.manual:
        try:
            input(f"\n>>> navigate EACH emulator ({', '.join(serials)}) to the JP Union "
                  f"Arena card-library screen -- the HORIZONTAL row of set icons, NOT the "
                  f"分类 list -- then press Enter to start... ")
        except EOFError:
            print("[orchestrator] --manual but no stdin; waiting 90s instead", flush=True)
            time.sleep(90)

    q_lock = threading.Lock()
    can_reboot = bool(snapshot)          # a snapshot boot restores app state; --manual can't
    manifest_path = os.path.join(args.out_dir, "sets_manifest.json")

    def _reboot(serial: str, port: int) -> bool:
        # plain `adb emu kill` only works over a live transport -- once a slot
        # is unhealthy enough to be rebooted that's often already gone, which
        # used to leave the old qemu process running as an orphan on the same
        # ports while a fresh one booted alongside it. kill_emulator() escalates
        # past adb to killing the process directly.
        C.kill_emulator(port, serial)
        time.sleep(5)
        try:
            C.ensure_emulator_instance(
                args.avd, args.apk, port, snapshot=snapshot,
                boot_timeout=args.boot_timeout, no_window=args.no_window)
            return True
        except Exception as e:               # noqa: BLE001
            with _print_lock:
                print(f"[orchestrator] {serial} reboot FAILED ({e})", flush=True)
            return False

    def _healthy_or_reboot(serial: str, port: int, reboots: list) -> bool:
        """True if this slot is usable (rebooting it if needed and allowed)."""
        if _slot_healthy(serial):
            return True
        with _print_lock:
            print(f"[orchestrator] {serial} unhealthy", flush=True)
        if can_reboot and reboots[0] < 6:
            reboots[0] += 1
            with _print_lock:
                print(f"[orchestrator] rebooting {serial} ({reboots[0]}/6) ...", flush=True)
            return _reboot(serial, port)
        return False

    # ---------------- JOB 1: enumerate every tab -> manifest -----------------
    manifest: dict[str, list[str]] = {}
    if not args.re_enumerate:
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            manifest = {}
    enum_queue = [t for t in tabs if not manifest.get(t)]
    if enum_queue:
        print(f"[orchestrator] JOB 1: enumerating {enum_queue}", flush=True)

        def enum_worker(serial: str) -> None:
            port = int(serial.rsplit("-", 1)[1])
            reboots = [0]
            while True:
                with q_lock:
                    if not enum_queue:
                        return
                    tab = enum_queue.pop(0)
                if not _healthy_or_reboot(serial, port, reboots):
                    with q_lock:
                        enum_queue.append(tab)
                    return
                efile = os.path.join(args.out_dir, f"enum_{slug(tab)}.json")
                try:
                    os.unlink(efile)
                except OSError:
                    pass
                rc, _ = _spawn_watched(
                    f"enum:{tab}",
                    [sys.executable, CRAWLER, "--enumerate-only", "--tabs", tab,
                     "--serial", serial, "--enum-out", efile,
                     "--out", os.path.join(args.out_dir, f"{slug(tab)}.json")],
                    efile, args, track_rows=False)  # enum writes a manifest,
                                                    # not card rows
                try:
                    with open(efile, "r", encoding="utf-8") as f:
                        got = json.load(f).get(tab) or []
                except (FileNotFoundError, json.JSONDecodeError):
                    got = []
                with q_lock:
                    if got:
                        manifest[tab] = got
                        C._atomic_write_json(manifest_path, manifest)
                        print(f"[orchestrator] JOB 1: {tab} -> {len(got)} sets", flush=True)
                    else:
                        print(f"[orchestrator] JOB 1: {tab} enumeration FAILED "
                              f"(rc={rc}) -- re-queueing", flush=True)
                        enum_queue.append(tab)
                if not got and can_reboot and reboots[0] < 6:
                    reboots[0] += 1
                    _reboot(serial, port)

        threads = [threading.Thread(target=enum_worker, args=(s,), daemon=True)
                   for s in serials]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
    tabs = [t for t in tabs if manifest.get(t)]
    print(f"[orchestrator] manifest: "
          f"{ {t: len(manifest[t]) for t in tabs} }", flush=True)

    # ---------------- JOB 2: drain the set queue ----------------------------
    # per-tab final file (seeded from canonical for resume) + a monotonic
    # chunk counter -- every chunk gets its OWN part file so two workers on
    # the same tab never overwrite each other's rows.
    outp_by_tab = {t: _tab_outp(t, args) for t in tabs}
    _chunk_seq = [0]
    pending: dict[str, list[str]] = {}
    for t in tabs:
        done = _captured_codes(outp_by_tab[t], *_tab_parts(args.out_dir, t))
        pending[t] = [c for c in manifest[t] if c not in done]
    attempts: dict[tuple[str, str], int] = {}
    gave_up: dict[str, dict[str, str]] = {t: {} for t in tabs}
    total_sets = sum(len(v) for v in pending.values())
    print(f"[orchestrator] JOB 2: {total_sets} set(s) pending "
          f"{ {t: len(v) for t, v in pending.items() if v} }", flush=True)
    for t in tabs:
        base = _captured_codes(outp_by_tab[t], *_tab_parts(args.out_dir, t))
        results["counts"][t] = [len(base), None]
        results["tab_secs"][t] = 0.0
        results["rc"][t] = 0

    def _take_chunk(prefer: str | None) -> tuple[str, list[str]] | None:
        with q_lock:
            order = ([prefer] if prefer and pending.get(prefer) else []) + \
                    sorted((t for t in tabs if pending.get(t)),
                           key=lambda t: -len(pending[t]))
            for t in order:
                if pending.get(t):
                    chunk = pending[t][:args.chunk]
                    del pending[t][:args.chunk]
                    return t, chunk
        return None

    def _queue_has_work() -> bool:
        with q_lock:
            return any(pending.get(t) for t in tabs)

    def _wait_for_recovery(serial: str, port: int) -> bool:
        """A slot never dies permanently while the queue still has work --
        emulators very often come back on their own. Loop: wait, re-check
        health, reboot if we can, up to ~30 min. Return True once usable."""
        deadline = time.monotonic() + 1800
        n = 0
        while time.monotonic() < deadline and _queue_has_work():
            n += 1
            time.sleep(90)
            if _slot_healthy(serial):
                with _print_lock:
                    print(f"[orchestrator] {serial} recovered after {n} check(s)",
                          flush=True)
                return True
            if can_reboot:
                with _print_lock:
                    print(f"[orchestrator] {serial} still down -- reboot attempt {n}",
                          flush=True)
                if _reboot(serial, port) and _slot_healthy(serial):
                    return True
        return False

    def set_worker(serial: str) -> None:
        port = int(serial.rsplit("-", 1)[1])
        reboots = [0]
        last_tab: str | None = None
        while True:
            got = _take_chunk(last_tab)
            if got is None:
                return
            tab, chunk = got
            if not _healthy_or_reboot(serial, port, reboots):
                with q_lock:
                    pending[tab] = chunk + pending[tab]
                with _print_lock:
                    print(f"[orchestrator] {serial} down -- pausing this slot, "
                          f"returned {len(chunk)} set(s) of {tab} to the queue",
                          flush=True)
                if not _wait_for_recovery(serial, port):
                    with _print_lock:
                        print(f"[orchestrator] {serial} unrecoverable -- slot stops",
                              flush=True)
                    return
                reboots = [0]
                last_tab = None
                continue

            with q_lock:
                _chunk_seq[0] += 1
                part = os.path.join(args.out_dir,
                                    f"{slug(tab)}.part_{_chunk_seq[0]:03d}.json")
            with _print_lock:
                print(f"[orchestrator] {serial} -> {tab} chunk {chunk}", flush=True)
            t_chunk = time.monotonic()
            try:
                rc, was_killed = _spawn_watched(
                    tab,
                    [sys.executable, CRAWLER, "--tabs", tab, "--sets", *chunk,
                     "--manifest", manifest_path, "--serial", serial, "--out", part,
                     "--revisit", "1"],   # orchestrator retries across chunks
                    part, args)
            except Exception as e:               # noqa: BLE001
                rc, was_killed = 98, False
                with _print_lock:
                    print(f"[orchestrator] chunk crashed: {type(e).__name__}: {e}",
                          flush=True)
            dt = time.monotonic() - t_chunk

            captured = _captured_codes(part)
            done = [c for c in chunk if c in captured]
            failed = [c for c in chunk if c not in captured]
            retry: list[str] = []
            for c in failed:
                attempts[(tab, c)] = attempts.get((tab, c), 0) + 1
                if attempts[(tab, c)] < 3:
                    retry.append(c)
                else:
                    gave_up[tab][c] = "gave_up_after_3_attempts"
            with q_lock:
                results["tab_secs"][tab] += dt
                results["slot_of"][tab] = serial
                if rc != 0:
                    results["rc"][tab] = rc
                pending[tab].extend(retry)
            with _print_lock:
                print(f"[orchestrator] {serial} chunk done: {len(done)}/{len(chunk)} "
                      f"captured in {fmt_hms(dt)}"
                      + (f", retrying {retry}" if retry else "")
                      + (f", GAVE UP {sorted(gave_up[tab])}" if failed and not retry
                         and gave_up[tab] else ""), flush=True)

            if done:
                reboots = [0]                # a good chunk clears the strike count
            elif (was_killed or rc != 0 or not done) and can_reboot:
                # a chunk that captured NOTHING -> emulator is suspect.
                reboots[0] += 1
                with _print_lock:
                    print(f"[orchestrator] rebooting {serial} after bad chunk "
                          f"({reboots[0]})", flush=True)
                if not (_reboot(serial, port) and _slot_healthy(serial)):
                    if not _wait_for_recovery(serial, port):
                        with _print_lock:
                            print(f"[orchestrator] {serial} unrecoverable -- slot stops",
                                  flush=True)
                        return
                    reboots = [0]
            last_tab = tab

    threads = [threading.Thread(target=set_worker, args=(s,), daemon=True) for s in serials]
    try:
        for th in threads:
            th.start()
        for th in threads:
            th.join()
    finally:
        # ALWAYS tear the emulators down, even if the orchestrator throws --
        # a crashed run used to leave 2 emulators eating ~5 GB.
        if not args.keep_emulators:
            for p in ports:
                C.kill_emulator(p, f"emulator-{p}")

    # fold every chunk part file into the per-tab file, then clean the parts
    for t in tabs:
        parts = _tab_parts(args.out_dir, t)
        if parts:
            C.merge_union(parts, outp_by_tab[t])
            for p in parts:
                try:
                    os.unlink(p); os.unlink(p + ".missed.json")
                except OSError:
                    pass
        results["counts"][t][1] = len(C._load_rows(outp_by_tab[t]))
        leftover = {c: "unclaimed" for c in pending.get(t, [])}
        results["missed"][t] = {**_read_missed(outp_by_tab[t]), **gave_up[t], **leftover}
        if results["missed"][t]:
            results["rc"][t] = results["rc"][t] or 1

    if args.merge:
        inputs = [outp_by_tab[t] for t in tabs if os.path.exists(outp_by_tab[t])]
        results["merge"] = C.merge_union(inputs, args.canonical)
        print(f"[orchestrator] merged {len(inputs)} file(s) -> {args.canonical}: "
              f"{results['merge'][0]} -> {results['merge'][1]} rows", flush=True)

    results["total_secs"] = time.monotonic() - t0
    _print_summary(args, results)
    return results


def _print_summary(args, r: dict) -> None:
    print("\n" + "=" * 70, flush=True)
    print(f"{'tab':<12}{'slot':>16}{'rc':>4}{'rows +':>10}{'wall time':>12}", flush=True)
    print("-" * 70, flush=True)
    for tab in args.tabs:
        if tab not in r["rc"]:
            continue
        before, after = r["counts"].get(tab, [0, 0])
        after = after if after is not None else before
        print(f"{tab:<12}{r['slot_of'].get(tab, '-'):>16}{r['rc'][tab]:>4}"
              f"{('+' + str(after - before)):>10}{fmt_hms(r['tab_secs'].get(tab, 0)):>12}",
              flush=True)
    print("-" * 70, flush=True)
    if r["merge"]:
        print(f"canonical: {r['merge'][0]} -> {r['merge'][1]} rows  ({args.canonical})", flush=True)
    missed = {t: m for t, m in r.get("missed", {}).items() if m}
    if missed:
        total = sum(len(m) for m in missed.values())
        print(f"STILL MISSING {total} set(s) after revisits:", flush=True)
        for t, m in missed.items():
            print(f"  {t}: {m}", flush=True)
        print("  (per-tab detail in out/<tab>.json.missed.json)", flush=True)
    else:
        print("no missing sets", flush=True)
    print(f"TOTAL wall time: {fmt_hms(r['total_secs'])}", flush=True)
    print("=" * 64, flush=True)


def main() -> None:
    args = build_parser().parse_args()
    res = run(args)
    sys.exit(1 if any(v != 0 for v in res["rc"].values()) else 0)


if __name__ == "__main__":
    main()
