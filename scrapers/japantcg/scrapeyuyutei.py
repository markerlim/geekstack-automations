import argparse
import os
import sys

sys.path.append(os.path.dirname(__file__))
from yuyutei_scraper import YuyuTeiScraper, run_cli

# Per-game config: every TCG Yuyu-Tei sells runs the same shop template,
# so a new game only needs an entry here.
GAMES = {
    'ua': {
        'label': 'Union Arena',
        'base_url': 'https://yuyu-tei.jp/top/ua',
        'collection_name': 'cardprices_yyt',
        'backup_prefix': 'yuyutei_cardlist_backup_',
    },
    'op': {
        'label': 'One Piece',
        'base_url': 'https://yuyu-tei.jp/top/opc',
        'collection_name': 'cardprices_yyt_op',
        'backup_prefix': 'yuyutei_op_cardlist_backup_',
    },
}


def main():
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument('--game', choices=GAMES.keys(), required=True, help='Which TCG to scrape')
    game_args, remaining_argv = pre_parser.parse_known_args()

    config = GAMES[game_args.game]

    def make_scraper(headless=True):
        return YuyuTeiScraper(
            base_url=config['base_url'],
            collection_name=config['collection_name'],
            backup_prefix=config['backup_prefix'],
            headless=headless,
        )

    run_cli(
        description=f"Yuyu-Tei {config['label']} scraper with backup/upload support",
        scraper_factory=make_scraper,
        script_path=f"scrapers/japantcg/scrapeyuyutei.py --game {game_args.game}",
        argv=remaining_argv,
    )


if __name__ == "__main__":
    main()
