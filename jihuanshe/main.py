#!/usr/bin/env python3
"""JHS (jihuanshe) run-job entry point.

Scrapes one TCG on the jihuanshe app -- its in-app category tabs, in parallel
across emulators -- and folds the result into a canonical price file.

Four run modes:

    python main.py union_arena --daily
        Full re-scrape of every category from scratch. Re-enumerates each
        tab's set strip, re-scrapes every set, then AUTO-RETRIES whatever
        still failed (up to --retries targeted passes, default 2, no
        intervention). Writes this date's snapshot + a coverage diff, and
        merges into the live canonical file ONLY on a clean finish. Cron
        entry point.  Tuning: --workers 3 --chunk 4 --retries 3

    python main.py union_arena --retry [--categories promo ...]
    python main.py union_arena --sets UA56BT UA55BT --categories booster
        Re-scrape only the sets that failed (from the latest run's
        missed.json) or the exact sets you name. Skips strip enumeration
        entirely -- goes straight to those sets -- then merges.

    python main.py union_arena --resume
        Continue the run that was interrupted (Ctrl-C, crash, power). Picks
        up from work/<game>/.run_state.json + the per-tab progress on disk;
        only the sets not yet captured are scraped.

    python main.py union_arena
        Incremental: adds set codes not yet in the canonical file. Does NOT
        refresh prices of sets already present -- use --daily for that.

Layout (all under this directory):

    union_arena_boosters_all_sets.json     canonical / file of record (tracked)
    runs/union_arena/<YYYY-MM-DD>/
        snapshot.json                      full scrape for that date, pre-merge
        coverage_missing.txt  coverage_added.txt
        missed.json                        {tab: {set_code: reason}} still missing
    work/union_arena/                       live scratch for the in-progress run
        <tab>.json  <tab>.part_*.json  enum_*.json  sets_manifest.json
        .run_state.json                    resume marker (deleted on clean finish)

Nothing in runs/ or the canonical is ever deleted by a run: --daily/--retry
write a dated snapshot and only union-merge the canonical (rows added/updated,
never removed). Only the disposable work/ scratch is cleared, and the dated
snapshot is the rollback point.

Prerequisite: the AVD snapshot named by the game entry (default "jp_library")
must exist and sit on the logged-in card-library screen, OR pass --manual to
cold-boot and navigate each emulator by hand. Capture the snapshot once:

    ~/Library/Android/sdk/emulator/emulator -avd Pixel_3a_API_34 -no-snapshot-load -no-boot-anim
    # log in, pick the JP game, open the card-library screen
    adb emu avd snapshot save jp_library
    adb emu kill
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime

import crawl_parallel as P
import crawl_union_arena_all_sets as C

HERE = os.path.dirname(os.path.abspath(__file__))
RUNS_KEEP = 7                       # dated run folders to retain per game
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RUN_STATE = ".run_state.json"

# TCG registry. `categories` maps a friendly CLI name -> the in-app tab label.
GAMES: dict[str, dict] = {
    "union_arena": {
        "label": "Union Arena (携战之境UA 日文)",
        "categories": {
            "booster": "补充包",
            "structure": "构筑",
            "event": "现场活动",
            "promo": "PR",
        },
        "canonical": "union_arena_boosters_all_sets.json",
        "snapshot": "jp_library",
    },
}


# --------------------------------------------------------------------------- #
# paths + small json helpers
# --------------------------------------------------------------------------- #
def _work_dir(game: str) -> str:
    return os.path.join(HERE, "work", game)


def _runs_dir(game: str) -> str:
    return os.path.join(HERE, "runs", game)


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


class _Tee:
    """Mirrors writes to the real stream and an append-mode log file, so
    everything printed during a run (including crawl_parallel's [TAG]-prefixed
    worker output, since it's relayed through this same process's stdout)
    lands in runs/<game>/<date>/run.log for later review -- not just the
    terminal scrollback."""

    def __init__(self, stream, log_file):
        self._stream = stream
        self._log_file = log_file

    def write(self, data):
        self._stream.write(data)
        self._log_file.write(data)

    def flush(self):
        self._stream.flush()
        self._log_file.flush()


def _tee_output_to(run_dir: str) -> None:
    log_path = os.path.join(run_dir, "run.log")
    log_file = open(log_path, "a", encoding="utf-8")
    log_file.write(f"\n=== {datetime.now().isoformat(timespec='seconds')} "
                    f"{' '.join(sys.argv)} ===\n")
    sys.stdout = _Tee(sys.stdout, log_file)
    sys.stderr = _Tee(sys.stderr, log_file)


def _read_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _run_dates(game: str, exclude: str | None = None) -> list[str]:
    d = _runs_dir(game)
    if not os.path.isdir(d):
        return []
    return sorted(x for x in os.listdir(d) if _DATE_RE.match(x) and x != exclude)


def _latest_run_dir(game: str, exclude: str | None = None) -> str | None:
    """Most recent PREVIOUS run dir. `exclude` must be the current run's own
    run_date -- main() creates that dir (for run.log) before a --retry/--sets
    pass resolves its target sets, so without this a run started right after
    midnight finds its own empty, just-created folder as "latest" instead of
    the actual prior run it's meant to retry from."""
    dates = _run_dates(game, exclude=exclude)
    return os.path.join(_runs_dir(game), dates[-1]) if dates else None


def _prune_runs(game: str, keep: int = RUNS_KEEP) -> None:
    dates = _run_dates(game)
    for old in dates[:-keep]:
        shutil.rmtree(os.path.join(_runs_dir(game), old), ignore_errors=True)


def _manifest_path(work: str) -> str:
    return os.path.join(work, "sets_manifest.json")


# --------------------------------------------------------------------------- #
# work/ scratch lifecycle
# --------------------------------------------------------------------------- #
def _clear_tab_progress(work: str, tabs: list[str], *, wipe_manifest: bool) -> int:
    """Drop the per-tab resume state so JOB 2 re-queues those sets. The dated
    snapshot in runs/ holds the same data, so nothing here is irreplaceable."""
    victims: list[str] = []
    for tab in tabs:
        s = P.slug(tab)
        victims.append(os.path.join(work, f"{s}.json"))
        victims.append(os.path.join(work, f"{s}.json.missed.json"))
        victims += glob.glob(os.path.join(work, f"{s}.part_*.json"))
        victims += glob.glob(os.path.join(work, f"{s}.part_*.json.missed.json"))
        if wipe_manifest:
            victims.append(os.path.join(work, f"enum_{s}.json"))
    if wipe_manifest:
        victims.append(_manifest_path(work))
    n = 0
    for f in victims:
        try:
            os.remove(f)
            n += 1
        except FileNotFoundError:
            pass
    return n


def _write_state(work: str, state: dict) -> None:
    os.makedirs(work, exist_ok=True)
    C._atomic_write_json(os.path.join(work, RUN_STATE), state)


def _read_state(work: str) -> dict | None:
    return _read_json(os.path.join(work, RUN_STATE), None)


def _clear_state(work: str) -> None:
    try:
        os.remove(os.path.join(work, RUN_STATE))
    except FileNotFoundError:
        pass


# --------------------------------------------------------------------------- #
# retry / sets target resolution
# --------------------------------------------------------------------------- #
def _resolve_targets(game: str, cat_map: dict, picked: list[str],
                     explicit_sets: list[str] | None,
                     exclude_run_date: str | None = None) -> dict[str, list[str]]:
    """{tab_label: [set codes]} to re-scrape for a --retry / --sets run."""
    if explicit_sets:
        if len(picked) != 1:
            raise SystemExit("--sets needs exactly one --categories value so the "
                             "set codes can be assigned to a tab")
        return {cat_map[picked[0]]: sorted(dict.fromkeys(explicit_sets))}

    run_dir = _latest_run_dir(game, exclude=exclude_run_date)
    if not run_dir:
        raise SystemExit("--retry: no previous run under runs/{}/ -- do a "
                         "--daily run first, or pass --sets".format(game))
    missed = _read_json(os.path.join(run_dir, "missed.json"), {})
    if not missed:
        raise SystemExit(f"--retry: {run_dir}/missed.json is empty -- nothing "
                         f"to retry (pass --sets to force specific codes)")
    wanted = {cat_map[c] for c in picked} if picked else None
    targets = {tab: sorted(codes) for tab, codes in missed.items()
               if codes and (wanted is None or tab in wanted)}
    if not targets:
        raise SystemExit("--retry: nothing missing for the chosen categories")
    return targets


# --------------------------------------------------------------------------- #
# coverage report
# --------------------------------------------------------------------------- #
def _key(r) -> tuple:
    return (r.jhs_code, r.cardId, r.rarity)


def coverage_report(game: str, live_path: str, snapshot_path: str,
                    tabs: list[str], run_dir: str) -> None:
    ref = C._load_rows(live_path)
    new = C._load_rows(snapshot_path)
    ref_ids = {_key(r) for r in ref}
    new_ids = {_key(r) for r in new}
    missing = ref_ids - new_ids
    added = new_ids - ref_ids

    ref_sets = {r.jhs_code for r in ref}
    new_sets = {r.jhs_code for r in new}
    missing_by_set = Counter(s for (s, _, _) in missing)
    fully_missing = sorted(s for s in ref_sets - new_sets)

    os.makedirs(run_dir, exist_ok=True)
    mfile = os.path.join(run_dir, "coverage_missing.txt")
    afile = os.path.join(run_dir, "coverage_added.txt")
    with open(mfile, "w", encoding="utf-8") as f:
        f.writelines("\t".join(k) + "\n" for k in sorted(missing))
    with open(afile, "w", encoding="utf-8") as f:
        f.writelines("\t".join(k) + "\n" for k in sorted(added))

    print("\n" + "#" * 64, flush=True)
    print(f"# coverage: this run's snapshot vs live {os.path.basename(live_path)}", flush=True)
    print("#" * 64, flush=True)
    print(f"  live rows           : {len(ref):>6}   ({len(ref_sets)} set codes)", flush=True)
    print(f"  snapshot rows       : {len(new):>6}   ({len(new_sets)} set codes)", flush=True)
    print(f"  missing this run    : {len(missing):>6}   (in live, not in snapshot)", flush=True)
    print(f"  newly found         : {len(added):>6}", flush=True)
    if fully_missing:
        print(f"  set codes with NOTHING in the snapshot ({len(fully_missing)}):", flush=True)
        for s in fully_missing[:40]:
            print(f"      {s:<16} -{missing_by_set[s]} rows", flush=True)
        if len(fully_missing) > 40:
            print(f"      ... +{len(fully_missing) - 40} more", flush=True)
    elif missing:
        print("  partially-missing set codes (top 20 by rows):", flush=True)
        for s, n in missing_by_set.most_common(20):
            print(f"      {s:<16} -{n} rows", flush=True)
    print(f"\n  lists: {mfile}", flush=True)
    print(f"         {afile}", flush=True)
    print("  NOTE: for a partial (retry / single-category) run, 'missing' just "
          "means 'not part of this run' -- eyeball before worrying.", flush=True)
    print("#" * 64, flush=True)


# --------------------------------------------------------------------------- #
# the run
# --------------------------------------------------------------------------- #
def _build_p_args(*, tabs, snapshot, out_dir, seed_flag, game_snapshot,
                  args, re_enumerate: bool, workers: int | None = None) -> argparse.Namespace:
    argv = [
        "--tabs", *tabs,
        "--workers", str(args.workers if workers is None else workers),
        "--avd", "Pixel_3a_API_34",
        "--snapshot", ("" if args.manual else game_snapshot),
        "--canonical", snapshot,
        "--out-dir", out_dir,
        "--boot-timeout", str(args.boot_timeout),
        seed_flag,
    ]
    if args.chunk:
        argv += ["--chunk", str(args.chunk)]
    if re_enumerate:
        argv.append("--re-enumerate")
    if args.manual:
        argv.append("--manual")
    if args.no_window:
        argv.append("--no-window")
    if args.keep_emulators:
        argv.append("--keep-emulators")
    return P.build_parser().parse_args(argv)


def _kill_emulators(timeout: float = 90) -> None:
    """`emu kill` every running AVD instance and BLOCK until the console ports
    are actually free. crawl_parallel's own teardown fires `emu kill` and
    returns before qemu has exited, so a back-to-back P.run() trips its
    preflight ("port(s) already in use"). Call this between passes."""
    def _emus() -> list[str]:
        try:
            out = subprocess.run(["adb", "devices"], capture_output=True,
                                 text=True, timeout=15).stdout
        except Exception:  # noqa: BLE001
            return []
        return [ln.split("\t")[0] for ln in out.splitlines()[1:]
                if ln.startswith("emulator-") and ln.rstrip().endswith("device")]

    serials = _emus()
    if not serials:
        return
    print(f"  killing {len(serials)} running emulator(s): {', '.join(serials)}",
          flush=True)
    for s in serials:
        subprocess.run(["adb", "-s", s, "emu", "kill"], capture_output=True, timeout=20)
    deadline = time.time() + timeout
    while _emus() and time.time() < deadline:
        time.sleep(2)
    time.sleep(3)                    # console port lingers a beat after adb drops it


def _prep_targeted(targets: dict, work: str, snapshot: str,
                   game: str, live_canonical: str,
                   exclude_run_date: str | None = None) -> str:
    """Set up a targeted (retry / --sets / auto-retry) pass: a throwaway
    scratch dir with a trimmed manifest so JOB 1 is skipped and JOB 2 queues
    exactly `targets`. The snapshot must already hold the rest of the picture
    -- workers overwrite the retried sets when their parts merge into it."""
    scratch = os.path.join(work, "_targeted")
    shutil.rmtree(scratch, ignore_errors=True)
    os.makedirs(scratch, exist_ok=True)
    C._atomic_write_json(_manifest_path(scratch), targets)
    if not os.path.exists(snapshot):
        prev = _latest_run_dir(game, exclude=exclude_run_date)
        prev_snap = os.path.join(prev, "snapshot.json") if prev else None
        src = prev_snap if (prev_snap and os.path.exists(prev_snap)) else live_canonical
        if os.path.exists(src):
            shutil.copyfile(src, snapshot)
            print(f"  seeded snapshot from {os.path.relpath(src, HERE)}", flush=True)
    return scratch


def _finalize(*, game, run_dir, snapshot, live_canonical, tabs, res,
              do_apply, mode_label, run_date, picked, work, cat_map) -> tuple[bool, dict]:
    """Write coverage + missed.json + status.json, merge into the canonical
    when the run is clean. Returns (ok, still_missing {tab_label: {code: why}})."""
    coverage_report(game, live_canonical, snapshot, tabs, run_dir)
    still_missing = {t: dict(m) for t, m in res.get("missed", {}).items() if m}
    if still_missing:
        C._atomic_write_json(os.path.join(run_dir, "missed.json"), still_missing)
    else:
        try:
            os.remove(os.path.join(run_dir, "missed.json"))
        except FileNotFoundError:
            pass
    _prune_runs(game)

    bad = [t for t, rc in res.get("rc", {}).items() if rc != 0]
    ok = not (bad or still_missing)
    snap_rows = len(C._load_rows(snapshot)) if os.path.exists(snapshot) else 0

    C._atomic_write_json(os.path.join(run_dir, "status.json"), {
        "ok": ok,
        "mode": mode_label.lower(),
        "date": run_date,
        "categories": picked,
        "rows": snap_rows,
        "tabs_nonzero": bad,
        "sets_missed": sum(len(m) for m in still_missing.values()),
        "finished_at": datetime.now().isoformat(timespec="seconds"),
    })

    if do_apply and ok and os.path.exists(snapshot):
        before, after = C.merge_union([snapshot], live_canonical)
        print(f"\nmerged snapshot -> {os.path.basename(live_canonical)}: "
              f"{before} -> {after} rows", flush=True)
    elif do_apply and not ok:
        print(f"\nNOT merged into {os.path.basename(live_canonical)} -- run "
              f"incomplete ({sum(len(m) for m in still_missing.values())} set(s) "
              f"missing). Fix + resume/retry; it merges on a clean finish.", flush=True)
    return ok, still_missing


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("game", nargs="?", default="union_arena", choices=sorted(GAMES),
                    help="which TCG to scrape (default: union_arena)")

    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--daily", action="store_true",
                      help="full re-scrape of every category + merge into canonical (cron entry point)")
    mode.add_argument("--retry", action="store_true",
                      help="re-scrape only the sets in the latest run's missed.json "
                           "(optionally filtered by --categories); skips strip enumeration")
    mode.add_argument("--resume", action="store_true",
                      help="continue the interrupted run recorded in work/<game>/.run_state.json")
    mode.add_argument("--fresh", action="store_true",
                      help="like --daily but honours --categories and needs explicit --apply")

    ap.add_argument("--sets", nargs="+", metavar="CODE", default=None,
                    help="exact set codes to re-scrape (needs one --categories value); "
                         "implies a targeted run, skips strip enumeration")
    ap.add_argument("--categories", nargs="*", default=None,
                    help="friendly category names to run (default: all for the game)")
    ap.add_argument("--apply", action="store_true",
                    help="merge this run's snapshot into the live canonical file "
                         "(implied by --daily / --retry / --sets)")
    ap.add_argument("--keep-manifest", action="store_true",
                    help="with --daily/--fresh: reuse the existing set manifest instead of "
                         "re-enumerating each tab (faster; misses newly released sets)")
    ap.add_argument("--retries", type=int, default=None,
                    help="after the main pass, auto-retry the sets that still failed, up to "
                         "N more targeted passes (default: 2 for --daily/--fresh/--resume, "
                         "0 otherwise). Stops early once nothing is missing or a pass makes "
                         "no progress.")
    ap.add_argument("--workers", type=int, default=2,
                    help="concurrent emulators (default 2; 3 works if the host has the RAM). "
                         "1 = one emulator, tabs sequential: slowest but the most reliable.")
    ap.add_argument("--chunk", type=int, default=None,
                    help="sets handed to a worker per assignment (crawl_parallel default 8). "
                         "Smaller = finer load-balancing across workers + less lost on a "
                         "worker death; try 4-5 with --workers 3.")
    ap.add_argument("--manual", action="store_true",
                    help="cold-boot emulators and pause for manual navigation (no snapshot)")
    ap.add_argument("--no-window", action="store_true")
    ap.add_argument("--keep-emulators", action="store_true")
    ap.add_argument("--boot-timeout", type=float, default=300)
    args = ap.parse_args()

    g = GAMES[args.game]
    cat_map = g["categories"]
    live_canonical = os.path.join(HERE, g["canonical"])
    work = _work_dir(args.game)
    targeted = bool(args.retry or args.sets)
    if args.retries is None:
        args.retries = 0 if targeted else 2

    # ---- resolve categories -------------------------------------------------
    if args.resume:
        state = _read_state(work)
        if not state:
            raise SystemExit(f"--resume: no {os.path.join(work, RUN_STATE)} -- "
                             f"nothing to resume")
        picked = state["categories"]
        run_date = state["date"]
        do_apply = state.get("apply", False)
    else:
        picked = args.categories or list(cat_map)
        unknown = [c for c in picked if c not in cat_map]
        if unknown:
            ap.error(f"unknown categor{'y' if len(unknown) == 1 else 'ies'} {unknown} "
                     f"for {args.game}; valid: {sorted(cat_map)}")
        if args.daily and args.categories:
            ap.error("--daily always runs every category; drop --categories "
                     "(or use --fresh --categories ...)")
        if args.sets and (args.daily or args.fresh):
            ap.error("--sets is a targeted run on its own; don't combine it with "
                     "--daily / --fresh")
        run_date = _today()
        do_apply = args.apply or args.daily or targeted
    tabs = [cat_map[c] for c in picked]
    run_dir = os.path.join(_runs_dir(args.game), run_date)
    os.makedirs(run_dir, exist_ok=True)
    os.makedirs(work, exist_ok=True)
    _tee_output_to(run_dir)
    snapshot = os.path.join(run_dir, "snapshot.json")

    # ---- per-mode preparation --------------------------------------------- #
    re_enumerate = False
    if args.resume:
        mode_label = "RESUME"
        scratch = work
        seed_flag = "--no-seed"                       # progress files already on disk
        if not os.path.exists(snapshot) and os.path.exists(live_canonical):
            shutil.copyfile(live_canonical, snapshot)

    elif targeted:
        mode_label = "RETRY" if args.retry else "SETS"
        targets = _resolve_targets(args.game, cat_map, picked, args.sets,
                                    exclude_run_date=run_date)
        tabs = list(targets)                          # only tabs that have targets
        seed_flag = "--no-seed"
        scratch = _prep_targeted(targets, work, snapshot, args.game, live_canonical,
                                  exclude_run_date=run_date)
        print(f"  targets: { {t: len(c) for t, c in targets.items()} }", flush=True)

    else:                                             # --daily / --fresh
        mode_label = "DAILY" if args.daily else "FRESH"
        scratch = work
        seed_flag = "--no-seed"
        re_enumerate = not args.keep_manifest
        n = _clear_tab_progress(work, tabs, wipe_manifest=not args.keep_manifest)
        if n:
            print(f"  cleared {n} stale work/ file(s) -- JOB 2 re-scrapes every set "
                  f"(rollback: runs/{args.game}/*/snapshot.json)", flush=True)
        # start the snapshot empty so it is a true full re-scrape
        try:
            os.remove(snapshot)
        except FileNotFoundError:
            pass

    # only full runs are resumable; a targeted run is re-run by repeating the
    # same --retry/--sets command (it re-resolves its targets each time).
    if not args.resume and not targeted:
        _write_state(work, {
            "date": run_date, "mode": mode_label.lower(),
            "categories": picked, "apply": do_apply,
            "started_at": datetime.now().isoformat(timespec="seconds"),
        })

    p_args = _build_p_args(tabs=tabs, snapshot=snapshot, out_dir=scratch,
                           seed_flag=seed_flag, game_snapshot=g["snapshot"],
                           args=args, re_enumerate=re_enumerate)

    print("=" * 64, flush=True)
    print(f"JHS {mode_label} :: {g['label']}", flush=True)
    print(f"  categories : {', '.join(f'{c} ({cat_map[c]})' for c in picked if c in cat_map)}", flush=True)
    print(f"  run folder : runs/{args.game}/{run_date}/", flush=True)
    print(f"  snapshot   : {snapshot}", flush=True)
    print(f"  merge live : {'yes' if do_apply else 'no (snapshot only)'}", flush=True)
    print(f"  started    : {datetime.now():%Y-%m-%d %H:%M:%S}", flush=True)
    print("=" * 64, flush=True)

    _fin = dict(game=args.game, run_dir=run_dir, snapshot=snapshot,
                live_canonical=live_canonical, do_apply=do_apply,
                run_date=run_date, picked=picked, work=work, cat_map=cat_map)

    if not args.manual and not args.keep_emulators:
        _kill_emulators()               # clear any leftovers from a crashed run

    t0 = time.monotonic()
    res = P.run(p_args)
    ok, still_missing = _finalize(tabs=tabs, res=res, mode_label=mode_label, **_fin)

    # ---- auto-retry the stragglers, no intervention --------------------- #
    passes = 0
    while not ok and still_missing and passes < args.retries:
        passes += 1
        before_n = sum(len(m) for m in still_missing.values())
        retry_targets = {tab: sorted(codes) for tab, codes in still_missing.items()}
        print("\n" + "=" * 64, flush=True)
        print(f">>> AUTO-RETRY {passes}/{args.retries}: {before_n} set(s) "
              f"{ {t: len(c) for t, c in retry_targets.items()} }", flush=True)
        print("=" * 64, flush=True)
        if not args.manual and not args.keep_emulators:
            _kill_emulators()          # crawl_parallel's teardown races its own preflight
        r_scratch = _prep_targeted(retry_targets, work, snapshot,
                                   args.game, live_canonical)
        r_tabs = list(retry_targets)
        # Every set reaching auto-retry already failed once under the main
        # pass's --workers concurrency -- 2 workers means 2 emulators sharing
        # host RAM/CPU, and a tab needing tab-bar swipes (PR is the classic
        # case) degrades badly under that contention: swipes get dropped or
        # mistimed, the app gets knocked off-screen, and recovering means a
        # full cold restart, which is itself slow under the same contention --
        # a death spiral that just re-fails the identical sets every pass (see
        # --workers help text; this used to need `--workers 1` typed by hand
        # after the fact). Auto-retry has far fewer sets left than the main
        # pass, so the throughput lost by going to 1 worker here is small --
        # drop to it automatically instead of repeating a known-bad config.
        r_pargs = _build_p_args(tabs=r_tabs, snapshot=snapshot, out_dir=r_scratch,
                                seed_flag="--no-seed", game_snapshot=g["snapshot"],
                                args=args, re_enumerate=False, workers=1)
        res = P.run(r_pargs)
        ok, still_missing = _finalize(tabs=r_tabs, res=res,
                                      mode_label=f"{mode_label}+retry{passes}", **_fin)
        after_n = sum(len(m) for m in still_missing.values())
        if after_n >= before_n:
            print(f">>> auto-retry made no progress ({before_n} -> {after_n}); "
                  f"stopping. The emulator/snapshot likely needs attention.", flush=True)
            break

    elapsed = time.monotonic() - t0
    print(f"\nJHS {mode_label} finished in {P.fmt_hms(elapsed)}"
          + (f"  ({passes} auto-retry pass(es))" if passes else "")
          + ("  (all sets OK)" if ok else "  -- SETS STILL MISSING"),
          flush=True)

    if ok:
        _clear_state(work)
    else:
        rev = {lbl: cat for cat, lbl in cat_map.items()}
        cats = sorted({rev.get(t, t) for t in still_missing})
        total = sum(len(m) for m in still_missing.values())
        print(f">>> {total} set(s) still missing after {passes} auto-retr"
              f"{'y' if passes == 1 else 'ies'}: {still_missing}", flush=True)
        print(f">>> manual retry:  python main.py {args.game} --retry "
              f"--categories {' '.join(cats)} --workers 1", flush=True)
        if not args.resume:
            print(f">>> or resume:     python main.py {args.game} --resume", flush=True)
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
