#!/usr/bin/env python3
"""One command: scrape Yuyu-Tei + Jihuanshe, then normalise both feeds.

Chains the three existing entry points:

  1. YYT   scrapers/japantcg/scrapeyuyutei.py --game ua --no-upload
           -> yuyuteidb/yuyutei_cardlist_backup_<ts>.json  (dated; legacy
              cardprices_yyt write skipped -- step 4 owns price_yyt)
  2. JHS   jihuanshe/main.py union_arena --daily
           -> jihuanshe/runs/union_arena/<YYYY-MM-DD>/snapshot.json  (dated full re-scrape)
           -> jihuanshe/union_arena_boosters_all_sets.json  (snapshot union-merged in)
  3. norm  pricescraper/normalise_prices.py
           -> pricescraper/out/{jhs,yyt}_normalised.json + match_report.json
  4. upload pricescraper/upload_normalised.py
           -> MongoDB collections price_jhs / price_yyt (upsert on `key`)

Both scrapers run as a fresh job every time: YYT always writes a new dated
backup, and JHS defaults to "--daily" (a full re-scrape of every set into a
dated snapshot folder, then union-merged into the canonical). If a --daily
run is interrupted, resume it with `jihuanshe/main.py union_arena --resume`;
to re-scrape only the sets that failed, `jihuanshe/main.py union_arena
--retry`. Plain "union_arena" with no mode flag is an INCREMENTAL run that
picks up new set codes but never refreshes existing prices.

A scraper that exits non-zero ABORTS the chain by default -- normalise and
upload do NOT run on stale data. normalise_prices.py also refuses a source
file older than 18h unless --stale-ok, so a skipped scrape can't get
re-uploaded with a fresh timestamp. Use --lenient to fall back to the old
"normalise whatever is on disk" behaviour.

    python3 pricescraper/run.py                       # all four, JHS full re-scrape
    python3 pricescraper/run.py --skip jhs            # YYT + normalise + upload
    python3 pricescraper/run.py --only normalise upload
    python3 pricescraper/run.py --skip upload         # scrape + normalise, no DB write
    python3 pricescraper/run.py --jhs-args="union_arena --resume"      # continue an interrupted JHS run
    python3 pricescraper/run.py --jhs-args="union_arena --retry"       # re-scrape only JHS sets that failed
    python3 pricescraper/run.py --jhs-args="union_arena"               # incremental JHS (new sets only, no price refresh)
    python3 pricescraper/run.py --yyt-args="--use-latest-backup"
    python3 pricescraper/run.py --lenient             # don't abort the chain on a scrape failure
    python3 pricescraper/run.py --normalise-args=--stale-ok   # normalise old data on purpose
"""
from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# prefer the repo venv interpreter if it's there, else whatever ran this
_VENV_PY = os.path.join(REPO, "venv", "bin", "python3")
PY = _VENV_PY if os.path.exists(_VENV_PY) else sys.executable

STEPS = ("yyt", "jhs", "normalise", "upload")


def _fmt(secs: float) -> str:
    m, s = divmod(int(secs), 60)
    return f"{m}m{s:02d}s" if m else f"{s}s"


def run_step(name: str, argv: list[str], env: dict | None = None) -> int:
    print("\n" + "=" * 70, flush=True)
    print(f"[{name}] $ {' '.join(shlex.quote(a) for a in argv)}", flush=True)
    print("=" * 70, flush=True)
    t0 = time.monotonic()
    rc = subprocess.call(argv, cwd=REPO, env={**os.environ, **(env or {})})
    dt = time.monotonic() - t0
    print(f"[{name}] exit {rc} in {_fmt(dt)}", flush=True)
    return rc


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--skip", nargs="+", choices=STEPS, default=[],
                   help="steps to leave out")
    g.add_argument("--only", nargs="+", choices=STEPS, default=None,
                   help="run only these steps")
    ap.add_argument("--strict", action="store_true",
                    help="abort the chain on ANY step's non-zero exit "
                         "(default already aborts on a scrape failure; this adds "
                         "normalise)")
    ap.add_argument("--lenient", action="store_true",
                    help="a failed/skipped scrape is only a warning -- normalise + "
                         "upload still run on whatever data is on disk "
                         "(the pre-guard behaviour)")
    ap.add_argument("--jhs-args", default="union_arena --daily",
                    help='args passed to jihuanshe/main.py (default: "union_arena --daily" '
                         '-- full dated re-scrape union-merged into the canonical; other '
                         'forms: "union_arena --resume", "union_arena --retry", or '
                         '"union_arena" alone for an incremental new-sets-only run)')
    ap.add_argument("--yyt-args", default="--game ua --no-upload",
                    help='args passed to scrapeyuyutei.py (default: "--game ua --no-upload" '
                         '-- the legacy cardprices_yyt write is skipped; the upload step '
                         'below owns price_yyt. Drop --no-upload to also refresh cardprices_yyt.)')
    ap.add_argument("--normalise-args", default="",
                    help="args passed to normalise_prices.py")
    ap.add_argument("--upload-args", default="",
                    help="args passed to upload_normalised.py (e.g. --dry-run)")
    args = ap.parse_args()

    todo = list(args.only) if args.only else [s for s in STEPS if s not in args.skip]
    todo.sort(key=STEPS.index)
    print(f"interpreter : {PY}")
    print(f"steps       : {' -> '.join(todo)}")

    cmds = {
        "yyt": [PY, os.path.join("scrapers", "japantcg", "scrapeyuyutei.py"),
                *shlex.split(args.yyt_args)],
        "jhs": [PY, os.path.join("jihuanshe", "main.py"), *shlex.split(args.jhs_args)],
        "normalise": [PY, os.path.join("pricescraper", "normalise_prices.py"),
                      *shlex.split(args.normalise_args)],
        "upload": [PY, os.path.join("pricescraper", "upload_normalised.py"),
                   *shlex.split(args.upload_args)],
    }
    # the scrapers/upload import the repo's `service` package by top-level name
    envs = {"yyt": {"PYTHONPATH": REPO}, "jhs": {},
            "normalise": {}, "upload": {"PYTHONPATH": REPO}}

    results: dict[str, int] = {}
    for step in todo:
        rc = run_step(step, cmds[step], envs[step])
        results[step] = rc
        if rc != 0 and args.strict:
            print(f"\n--strict: stopping, {step} failed.", flush=True)
            break
        if rc != 0 and step in ("yyt", "jhs"):
            if args.lenient:
                print(f"[{step}] non-zero exit -- --lenient, continuing "
                      f"(normalise uses newest data on disk)", flush=True)
            else:
                print(f"\n[{step}] FAILED (exit {rc}) -- aborting the chain so stale "
                      f"data is not normalised/uploaded. Fix the scrape and re-run, "
                      f"or pass --lenient.", flush=True)
                break

    print("\n" + "#" * 70, flush=True)
    for step in todo:
        got = results.get(step)
        tag = "skipped (chain aborted)" if got is None else f"exit {got}"
        print(f"  {step:<10} {tag}", flush=True)
    print("#" * 70, flush=True)
    sys.exit(1 if any(rc for rc in results.values()) else 0)


if __name__ == "__main__":
    main()
