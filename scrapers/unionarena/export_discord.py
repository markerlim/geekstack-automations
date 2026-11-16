"""
Run DiscordChatExporter against the Union Arena card_list forum.

Reads DISCORD_TOKEN from the repo's .env (falling back to the environment) (never from the
command line, never printed). Used by `make ua-discord-export`.

    python scrapers/unionarena/export_discord.py --since 2026-11-01
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"), override=True)   # .env wins over a stale `export DISCORD_TOKEN` in the shell


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dce", default=os.path.expanduser("~/dce/DiscordChatExporter.Cli"),
                    help="path to the DiscordChatExporter CLI")
    ap.add_argument("--channel", default="1089711876130226236", help="card_list forum channel id")
    ap.add_argument("--since", required=True, help="only posts after this date (YYYY-MM-DD)")
    ap.add_argument("--out", default=os.path.join(ROOT, "unionarenadb", "discord_exports"))
    args = ap.parse_args()

    token = (os.getenv("DISCORD_TOKEN") or "").strip()
    if not token:
        sys.exit("DISCORD_TOKEN is not set: add DISCORD_TOKEN=... to .env (or export it in your shell)")
    if not (os.path.isfile(args.dce) and os.access(args.dce, os.X_OK)):
        sys.exit(f"DiscordChatExporter CLI not found/executable at {args.dce} "
                 f"(download it, chmod +x, or pass DCE=/path/to/DiscordChatExporter.Cli to make)")

    os.makedirs(args.out, exist_ok=True)
    cmd = [args.dce, "export", "-t", token, "-c", args.channel, "--include-threads", "All",
           "-f", "Json", "-o", args.out + os.sep, "--after", args.since]
    print(f"exporting channel {args.channel} posts after {args.since} -> {args.out}", flush=True)
    sys.exit(subprocess.run(cmd).returncode)


if __name__ == "__main__":
    main()
