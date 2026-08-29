"""
Full-catalog UI-scraper for Jihuanshe's Union Arena (携战之境UA) game.

Extends scrape_union_arena.py: instead of just the default/latest set,
this walks every set exposed in each of the top browse tabs (补充包 /
简中版 / 构筑 / 现场活动), selecting each set's icon in turn and scraping
its name/code/rarity/price grid. Still pure UI automation via adb +
uiautomator -- no network interception, no login.

Algorithm per tab:
  1. switch to the tab, scroll the page to the top (so the set-icon
     strip is at a known position).
  2. repeat:
       - dump the screen, find set-icon codes currently visible
         (bare TextViews with no resource-id, matching a code-like
         pattern, e.g. "UA55BT", "EX14BT", "WCS23-AE").
       - if there's a code we haven't visited yet: tap it, scrape its
         price grid (vertical swipe+dump loop, same as
         scrape_union_arena.py), tag rows with the set code, mark
         visited, scroll back to top.
       - else: swipe the icon strip left to reveal more sets. If that
         also yields nothing new after a couple of tries, this tab is
         exhausted.

Usage:
    python3 crawl_union_arena_all_sets.py --out all_sets_cards.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict

NS = "com.jihuanshe:id/"
CODE_RE = re.compile(r"^[A-Z]+[A-Z0-9]*(?:[/-][A-Z0-9]+)*$")
# A set code as it appears on a strip icon: 2-letter prefix, short body,
# optional single "/ABBR" or "-ABBR" suffix. Deliberately rejects card
# numbers like "UA55BT/IMC-1-004" (extra separators + digit groups) and
# anything with a "-N-" card infix.
STRIP_CODE_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{1,6}(?:[/-][A-Z]{2,5})?$")
TAB_LABELS = ("近期更新", "补充包", "简中版", "构筑", "现场活动", "PR", "其他 & 周边", "分类")
# Tabs that carry a set-icon strip worth crawling (JP Union Arena).
# The tab bar is a horizontal scroller -- switch_tab() scrolls to find
# each one. "PR" holds the UAPR promo singles.
TABS = ["补充包", "构筑", "现场活动", "PR"]
APP_PKG = "com.jihuanshe"


@dataclass
class CardRow:
    jhs_code: str       # the jihuanshe set folder code, e.g. "UAPR/KMR"
    animeCode: str      # series code parsed from the card id, e.g. "KMR" (Union Arena only)
    booster: str        # booster code, e.g. "UAPR" -- from the card id, else jhs_code prefix
    name: str
    cardId: str         # the raw card number as shown, e.g. "KMR-2-052"
    rarity: str
    price: str


# a booster token as it may appear in a card id's trailing "(...)" group
_BOOSTER_TOK_RE = re.compile(r"^(?:UA|EX|PC|BCF|WCS)[A-Z0-9]*$")


def derive_codes(jhs_code: str, card_id: str) -> tuple[str, str]:
    """(animeCode, booster) for a row.

    animeCode: the leading segment of the card id before the first "-"
               ("KMR-2-052" -> "KMR", "BCF24-UAZ01" -> "BCF24").
    booster:   a booster token embedded in the card id's trailing "(...)"
               group if there is one ("ARK-AP01(UAPB)" -> "UAPB"), else the
               jhs_code prefix before "/" ("UAPR/KMR" -> "UAPR").
    """
    anime = card_id.split("-", 1)[0]
    anime = re.split(r"[(\[]", anime, maxsplit=1)[0].strip()

    booster = ""
    m = re.search(r"[(\[]([^)\]]+)[)\]]\s*$", card_id)
    if m and _BOOSTER_TOK_RE.match(m.group(1).strip()):
        booster = m.group(1).strip()
    if not booster:
        booster = jhs_code.split("/", 1)[0]
    return anime, booster


def _extract_hierarchy(out: str) -> str | None:
    end = out.rfind("</hierarchy>")
    if end == -1:
        return None
    start = out.find("<?xml")
    return out[start if start != -1 else 0: end + len("</hierarchy>")]


def adb_dump(retries: int = 5) -> str:
    """uiautomator dump, tolerant of the transient failures that happen
    mid-animation or on error screens. Retries, with a dump-to-file
    fallback, before giving up."""
    last = ""
    for attempt in range(retries):
        try:
            out = subprocess.run(
                ["adb", "exec-out", "uiautomator", "dump", "/dev/tty"],
                capture_output=True, timeout=20,
            ).stdout.decode("utf-8", errors="replace")
            xml = _extract_hierarchy(out)
            if xml:
                return xml
            last = out
        except subprocess.TimeoutExpired:
            last = "<timeout>"
        # fallback path: write to a file on the device, read it back
        try:
            subprocess.run(["adb", "shell", "uiautomator", "dump", "/sdcard/uidump.xml"],
                           capture_output=True, timeout=20)
            out = subprocess.run(["adb", "exec-out", "cat", "/sdcard/uidump.xml"],
                                 capture_output=True, timeout=20).stdout.decode("utf-8", "replace")
            xml = _extract_hierarchy(out)
            if xml:
                return xml
        except subprocess.TimeoutExpired:
            pass
        if attempt < retries - 1:
            time.sleep(1.5)
    raise RuntimeError(f"uiautomator dump failed after {retries} tries "
                       f"(last output head: {last[:120]!r})")


def tap_back():
    """Bail out of an error / dead-end screen. Prefer the real top-left
    back element from the tree; fall back to hardware BACK (coordinate
    free) rather than guessing pixels."""
    try:
        root = get_root(adb_dump())
        for node in root.iter("node"):
            desc = (node.get("content-desc", "") + " " + node.get("text", "")).lower()
            b = node.get("bounds", "")
            if b and ("返回" in desc or "back" in desc or "navigate up" in desc):
                x, y = bounds_center(b)
                if y < 400:                       # a top-bar back control
                    subprocess.run(["adb", "shell", "input", "tap", str(x), str(y)], check=False)
                    time.sleep(1.0)
                    return
    except RuntimeError:
        pass
    subprocess.run(["adb", "shell", "input", "keyevent", "4"], check=False)
    time.sleep(1.0)


def get_root(xml_text: str) -> ET.Element:
    return ET.fromstring(xml_text)


def _on_grid_page(root: ET.Element) -> bool:
    """On a set's card-grid page: either card rows are parsed, or the
    pinned 最新在售 / 最新求购 toggle is present (it stays put while you
    scroll the grid, and disappears on card-detail / login)."""
    if parse_price_grid(root):
        return True
    t = {n.get("text", "") for n in root.iter("node")}
    return "最新在售" in t or "最新求购" in t


def recover_to_grid(max_back: int = 4) -> bool:
    """Misclick recovery (the flow the app forces on you):
        stray card tap  ->  card-detail page  ->  login prompt
    BACK to leave the login page, BACK again to leave card-detail, landing
    back on the card grid. Coordinate-free; re-checks after each BACK and
    stops the moment the grid is showing again."""
    for _ in range(max_back):
        try:
            if _on_grid_page(get_root(adb_dump())):
                return True
        except RuntimeError:
            pass
        subprocess.run(["adb", "shell", "input", "keyevent", "4"], check=False)
        time.sleep(1.2)
    try:
        return _on_grid_page(get_root(adb_dump()))
    except RuntimeError:
        return False


def bounds_center(b: str) -> tuple[int, int]:
    nums = list(map(int, re.findall(r"-?\d+", b)))
    x1, y1, x2, y2 = nums
    return (x1 + x2) // 2, (y1 + y2) // 2


def tap_bounds(b: str):
    x, y = bounds_center(b)
    subprocess.run(["adb", "shell", "input", "tap", str(x), str(y)], check=True)


def find_tab_bounds(root: ET.Element, tab_text: str) -> str | None:
    for node in root.iter("node"):
        if node.get("text", "") == tab_text:
            return node.get("bounds")
    return None


_ANY_TAB = ("近期更新", "补充包", "简中版", "构筑", "现场活动", "PR", "其他 & 周边", "分类")


def _library_tabs_visible(root: ET.Element) -> bool:
    """True if we're on the card library: a tab label is visible, or the
    set-icon strip is (which only renders on a library tab)."""
    return any(find_tab_bounds(root, t) for t in _ANY_TAB) or bool(find_icon_codes(root))


def _wait_for_library(secs: float = 4.0) -> bool:
    """Poll for the library to (re)appear -- e.g. after tap_back() exits a
    set page and the view is mid-transition. No BACK, no relaunch."""
    deadline = time.time() + secs
    while time.time() < deadline:
        try:
            if _library_tabs_visible(get_root(adb_dump())):
                return True
        except RuntimeError:
            pass
        time.sleep(0.6)
    return False


class BlockerError(RuntimeError):
    """Raised when the app is sitting on a login wall / error page that a
    quick BACK could not clear. Callers treat it as 'skip, maybe abort
    this tab' -- never as a reason to retry the same tap in a tight loop."""


# Screens the crawl can get trapped on: a login wall (some taps on promo
# sets prompt it), a mini-program error page, a card-detail modal.
_LOGIN_MARKERS = ("登录/注册", "获取验证码", "请输入手机号", "其他登录方式", "国家/地区")
_ERROR_MARKERS = ("服务异常", "网络异常", "加载失败", "请求失败")


def _texts(root: ET.Element) -> set[str]:
    return {n.get("text", "") for n in root.iter("node")}


def on_blocker_screen(root: ET.Element) -> bool:
    t = _texts(root)
    return (sum(m in t for m in _LOGIN_MARKERS) >= 2
            or any(m in x for x in t for m in _ERROR_MARKERS))


def dismiss_blockers(max_tries: int = 5) -> bool:
    """Back out of a login wall / error page / modal. Escalates:
    BACK a few times, then relaunch the app. Returns True once a normal
    screen shows (or nothing was blocking)."""
    for i in range(max_tries):
        try:
            if not on_blocker_screen(get_root(adb_dump())):
                return True
        except RuntimeError:
            pass
        if i < 3:
            subprocess.run(["adb", "shell", "input", "keyevent", "4"], check=False)
            time.sleep(1.2)
        else:
            print("    blocker won't dismiss -- relaunching app", flush=True)
            subprocess.run(["adb", "shell", "monkey", "-p", APP_PKG, "-c",
                            "android.intent.category.LAUNCHER", "1"],
                           check=False, capture_output=True)
            time.sleep(5.0)
    try:
        return not on_blocker_screen(get_root(adb_dump()))
    except RuntimeError:
        return False


def ensure_library_screen(max_back: int = 4) -> None:
    """Make sure the app is on the card-library screen (tab bar visible).

    The previous run can leave the app buried in a set's price grid, in a
    card-detail modal, or on another bottom-nav section -- then every
    switch_tab() silently no-ops and the crawl "succeeds" with nothing
    done. Recover by backing out, then as a last resort relaunching and
    tapping the 集换 bottom-nav entry. Raises if it still can't get there.
    """
    dismiss_blockers()
    # First just wait -- most calls land here right after tap_back() while
    # the library is still repainting; a BACK now would over-navigate.
    if _wait_for_library(3.0):
        return
    for attempt in range(max_back + 1):
        if _library_tabs_visible(get_root(adb_dump())):
            return
        if attempt < max_back:
            subprocess.run(["adb", "shell", "input", "keyevent", "4"], check=False)  # BACK
            time.sleep(1.2)
            if _wait_for_library(2.0):
                return

    print("  card library not visible -- relaunching app", flush=True)
    subprocess.run(
        ["adb", "shell", "monkey", "-p", APP_PKG, "-c",
         "android.intent.category.LAUNCHER", "1"],
        check=False, capture_output=True,
    )
    time.sleep(5.0)
    root = get_root(adb_dump())
    b = find_tab_bounds(root, "集换")
    if b:
        tap_bounds(b)
        time.sleep(2.5)
        root = get_root(adb_dump())
    if not _library_tabs_visible(root):
        raise RuntimeError(
            "could not reach the card-library screen (tab bar not found). "
            "Open the 携战之境UA 日文 card library manually, then re-run."
        )
    return None


def _ycenter(bounds: str) -> int:
    n = list(map(int, re.findall(r"-?\d+", bounds)))
    return (n[1] + n[3]) // 2 if len(n) == 4 else -1


def _bounds_width(b: str) -> int:
    n = list(map(int, re.findall(r"-?\d+", b)))
    return (n[2] - n[0]) if len(n) == 4 else 0


_CLIP_RE = re.compile(r"^[A-Z0-9][A-Z0-9/-]{3,}$")


def _resolve_clipped(text: str, known: set[str] | None) -> str | None:
    """A strip icon scrolled half past a screen edge dumps a clipped label
    (e.g. "UAPR/RL" or "PR/RLY"). If it can only be a fragment of exactly
    one enumerated set code, return that code; otherwise give up (ambiguous
    or not a strip icon at all)."""
    if not known or not _CLIP_RE.match(text):
        return None
    hits = [k for k in known
            if k != text and (k.startswith(text) or k.endswith(text) or text in k)]
    return hits[0] if len(hits) == 1 else None


def find_icon_codes(root: ET.Element, known_codes=None) -> list[tuple[str, str]]:
    """returns [(code, bounds), ...] for the icons of the SET STRIP only.

    The strip is a horizontal row: several set codes sharing ~the same y.
    We take the top-most such row and return just its members -- this
    excludes the tab bar, the set-detail header code, breadcrumbs and any
    stray code-like text elsewhere on the page, all of which were getting
    tapped/swiped before and flipping tabs or the sub-language.

    When `known_codes` (the tab's enumerated set list) is supplied, labels
    that are clipped at a screen edge are resolved back to the full code so
    an icon that always lands half-off-screen is still found.
    """
    known = set(known_codes) if known_codes else None
    cand = []
    for node in root.iter("node"):
        if node.get("resource-id", ""):
            continue
        text = node.get("text", "")
        if not text or len(text) < 4:
            continue
        if STRIP_CODE_RE.match(text) and text not in TAB_LABELS:
            code = text
        else:
            code = _resolve_clipped(text, known)
        if code is None:
            continue
        yc = _ycenter(node.get("bounds", ""))
        if yc >= 0:
            cand.append((code, node.get("bounds"), yc))
    if not cand:
        return []
    # bucket by y (20px), pick the top-most bucket that holds a real row (>=2)
    buckets: dict[int, list] = {}
    for text, bounds, yc in cand:
        buckets.setdefault(round(yc / 20), []).append((text, bounds))
    for key in sorted(buckets):
        if len(buckets[key]) >= 2:
            # a clipped copy and a full copy of the same icon can co-exist
            # in one dump; keep the widest (best tap target) per code.
            best: dict[str, str] = {}
            for c, b in buckets[key]:
                if c not in best or _bounds_width(b) > _bounds_width(best[c]):
                    best[c] = b
            return list(best.items())
    return []


def parse_price_grid(root: ET.Element) -> list[dict]:
    rows = []
    pending: dict[str, str] = {}
    for node in root.iter("node"):
        rid = node.get("resource-id", "")
        text = node.get("text", "")
        if not rid.startswith(NS) or not text:
            continue
        field = rid[len(NS):]
        if field == "nameTv":
            if "name" in pending:
                pending = {}
            pending["name"] = text
        elif field == "numberTv" and "name" in pending:
            pending["number"] = text
        elif field == "rarityTv" and "name" in pending:
            pending["rarity"] = text
        elif field == "priceTv" and "name" in pending:
            pending["price"] = text
            rows.append(dict(pending))
            pending = {}
    return rows


def scroll_to_top(max_swipes: int = 25):
    """Swipe (pull-down gesture) until the set-icon strip is visible, or
    give up after max_swipes. Raises BlockerError immediately if a login /
    error screen is up, so callers don't burn 25 swipes against it."""
    for _ in range(max_swipes):
        root = get_root(adb_dump())
        if on_blocker_screen(root):
            raise BlockerError("login/error screen while scrolling to strip")
        if find_icon_codes(root):
            return
        # pull-down gesture to reveal the strip at the top of the page
        subprocess.run(
            ["adb", "shell", "input", "swipe", "540", "700", "540", "1900", "150"],
            check=True,
        )
        time.sleep(0.3)


# Small scroll step (~1/4 screen) so every row lands in two consecutive
# dumps -- a bigger jump can flick a row past unseen. Dedup is on
# (number, rarity), so the repeated rows cost nothing.
# CRITICAL: every gesture endpoint stays in y[560,1360] -- clear of the
# persistent "集换社欢迎您 立即登录" banner pinned near the bottom (~y1470+).
# A drag that starts/ends on that banner, on a page that can't scroll
# further, registers as a TAP and drops us on the login wall.
_SCROLL_TOP_Y = 1340
_SCROLL_STEP = 460
_SETTLE_S = 0.9


def swipe_up_page(frac: float = 1.0):
    dy = int(_SCROLL_STEP * frac)
    subprocess.run(
        ["adb", "shell", "input", "swipe", "540", str(_SCROLL_TOP_Y),
         "540", str(_SCROLL_TOP_Y - dy), "450"],
        check=True,
    )


def swipe_down_page(frac: float = 0.7):
    dy = int(_SCROLL_STEP * frac)
    subprocess.run(
        ["adb", "shell", "input", "swipe", "540", str(_SCROLL_TOP_Y - _SCROLL_STEP),
         "540", str(_SCROLL_TOP_Y - _SCROLL_STEP + dy), "450"],
        check=True,
    )


def swipe_strip_left(y: int):
    # Short horizontal step (~2 icons) with ~2 icons of overlap so no set
    # icon slips through un-dumped. Swipe at the icon-label y from
    # find_icon_codes -- the known-good surface. Category-jump is prevented
    # upstream (find_icon_codes returns ONLY the real strip row; open_set
    # re-selects the tab on a miss), so no y-clamp games here.
    subprocess.run(
        ["adb", "shell", "input", "swipe", "950", str(int(y)), "440", str(int(y)), "400"],
        check=True,
    )


def swipe_strip_right(y: int):
    """Nudge the strip back the other way -- shorter than swipe_strip_left,
    used by the overlap guard to un-skip an icon that flew past."""
    subprocess.run(
        ["adb", "shell", "input", "swipe", "440", str(int(y)), "820", str(int(y)), "400"],
        check=True,
    )


def _center_strip_icon(code: str, bounds: str, known, band=(140, 940)) -> str:
    """If `code`'s icon is sitting half off a screen edge (its centre x is
    outside `band`), nudge the strip a few times to walk it inward and
    return the fresh, fully-tappable bounds. Falls back to the original
    bounds if the icon can't be re-located."""
    cx, y = bounds_center(bounds)
    for _ in range(3):
        if band[0] <= cx <= band[1]:
            return bounds
        (swipe_strip_right if cx < band[0] else swipe_strip_left)(y)
        time.sleep(0.5)
        codes = find_icon_codes(get_root(adb_dump()), known)
        nb = next((b for c, b in codes if c == code), None)
        if nb is None:
            break
        bounds = nb
        cx, y = bounds_center(bounds)
    return bounds


def _tab_row_y(root: ET.Element) -> int:
    """y-centre of the (horizontally scrollable) tab bar, found via any
    tab label currently on screen. Falls back to a sensible constant."""
    for t in ("近期更新", "补充包", "简中版", "构筑", "现场活动", "PR", "分类"):
        b = find_tab_bounds(root, t)
        if b:
            return bounds_center(b)[1]
    return 1132


def _tab_scroller_box(root: ET.Element) -> tuple[int, int, int, int] | None:
    """Bounds (x1,y1,x2,y2) of the horizontal tab-bar scroller. Every
    tab-bar swipe must stay INSIDE this box: the 分类 (category) button is a
    fixed control just past its right edge, and a swipe that starts on it
    opens the category view -- a second, unrelated scrollable container."""
    for node in root.iter("node"):
        rid = node.get("resource-id", "")
        if rid.endswith("scroll_view") or rid.endswith("title_container"):
            n = list(map(int, re.findall(r"-?\d+", node.get("bounds", ""))))
            if len(n) == 4 and n[2] - n[0] > 200:
                return n[0], n[1], n[2], n[3]
    # fallback: bounding box of the visible tab labels, minus 分类
    xs: list[int] = []
    ys: list[int] = []
    for t in _ANY_TAB:
        if t == "分类":
            continue
        b = find_tab_bounds(root, t)
        if b:
            n = list(map(int, re.findall(r"-?\d+", b)))
            xs += [n[0], n[2]]
            ys += [n[1], n[3]]
    if xs:
        return min(xs), min(ys), max(xs), max(ys)
    return None


def _swipe_tab_bar(root: ET.Element, direction: str):
    """Scroll the tab bar. "left" reveals tabs off the RIGHT edge
    (现场活动, PR, 其他 & 周边); "right" reveals tabs off the LEFT edge
    (补充包, 近期更新). Endpoints are clamped inside the scroller so the
    gesture never touches the 分类 button beyond its right edge."""
    box = _tab_scroller_box(root)
    if box:
        lo, hi = box[0] + 40, box[2] - 40
        y = (box[1] + box[3]) // 2
    else:
        lo, hi, y = 60, 800, _tab_row_y(root)
    x1, x2 = (hi, lo) if direction == "left" else (lo, hi)
    subprocess.run(
        ["adb", "shell", "input", "swipe", str(x1), str(y), str(x2), str(y), "300"],
        check=True,
    )
    time.sleep(0.6)


def _nudge_tab_into_view(root: ET.Element, tab_text: str, b: str) -> str:
    """If the located tab is clipped against a scroller edge, scroll it a
    little further in and return its fresh bounds."""
    box = _tab_scroller_box(root)
    if not box:
        return b
    cx = bounds_center(b)[0]
    if box[0] + 60 <= cx <= box[2] - 60:
        return b
    _swipe_tab_bar(root, "right" if cx < box[0] + 60 else "left")
    time.sleep(0.4)
    return find_tab_bounds(get_root(adb_dump()), tab_text) or b


def _tab_bar_showing(root: ET.Element) -> bool:
    return any(find_tab_bounds(root, t) for t in _ANY_TAB) or bool(find_icon_codes(root))


def switch_tab(tab_text: str) -> bool:
    """Tap the named tab. First make sure we're actually on the card
    library (a prior set-scrape leaves us buried in a grid), THEN scroll
    the horizontal tab bar to the target. Never blind-swipe at a guessed y
    -- only scroll the bar when a real tab label is visible to anchor it,
    otherwise a horizontal swipe lands on card content and can trip the
    login wall."""
    dismiss_blockers()
    _wait_for_library(3.0)          # let the view settle after a tap_back()
    # 现场活动 / PR / 其他 & 周边 sit off the RIGHT edge from the default
    # 近期更新 position, so sweep the bar left first, then right as a
    # fallback. Swipes at the scroller end simply no-op.
    for direction in ["left"] * 8 + ["right"] * 10:
        root = get_root(adb_dump())
        b = find_tab_bounds(root, tab_text)
        if b is not None:
            b = _nudge_tab_into_view(root, tab_text, b)
            tap_bounds(b)
            time.sleep(1.2)
            return True
        if not _tab_bar_showing(root):
            # genuinely not on the library -> recover, but only after a
            # short settle wait already failed inside _wait_for_library
            if not _wait_for_library(2.0):
                try:
                    ensure_library_screen()
                except RuntimeError:
                    return False
            continue
        _swipe_tab_bar(root, direction)
    return False


def reveal_grid_top(max_down: int = 6) -> bool:
    """After opening a set: scroll DOWN only as far as needed for grid rows
    to appear, then the same distance back UP so we sit on the grid's first
    rows -- no thrashing. False if no grid ever shows (mis-tap / login /
    error screen)."""
    if on_blocker_screen(get_root(adb_dump())):
        return False
    downs = 0
    while downs < max_down:
        if parse_price_grid(get_root(adb_dump())):
            break
        swipe_up_page(0.5)          # finger up = content scrolls DOWN
        downs += 1
        time.sleep(_SETTLE_S)
    else:
        return False               # never found a grid
    for _ in range(downs + 1):     # undo, +1 to seat firmly at the top
        swipe_down_page(0.6)       # finger down = content scrolls UP
        time.sleep(0.3)
    return True


def scrape_current_set_price_grid(set_code: str, max_idle_swipes: int = 8) -> list[CardRow]:
    seen: dict[tuple[str, str], CardRow] = {}
    idle_streak = 0
    stuck_streak = 0
    swipes = 0
    misclicks = 0
    prev_keys: set[tuple[str, str]] = set()
    while idle_streak < max_idle_swipes and swipes < 400:
        xml_text = adb_dump()
        root = get_root(xml_text)
        raw_rows = parse_price_grid(root)
        if not _on_grid_page(root):
            # accidental card tap -> card-detail -> login. Back out to the
            # grid and carry on scraping this same set from here.
            misclicks += 1
            if misclicks > 6 or not recover_to_grid():
                print("    !! can't get back to the card grid -- ending set", flush=True)
                break
            print(f"    misclick recovered ({misclicks}), resuming set", flush=True)
            prev_keys = set()
            continue
        cur_keys = {(r.get("number", ""), r.get("rarity", "")) for r in raw_rows if r.get("number")}

        new_count = 0
        for r in raw_rows:
            key = (r.get("number", ""), r.get("rarity", ""))
            if key not in seen and r.get("number"):
                card_id = r.get("number", "")
                anime, booster = derive_codes(set_code, card_id)
                seen[key] = CardRow(
                    jhs_code=set_code,
                    animeCode=anime,
                    booster=booster,
                    name=r.get("name", ""),
                    cardId=card_id,
                    rarity=r.get("rarity", ""),
                    price=r.get("price", ""),
                )
                new_count += 1

        # Overlap guard: no shared row with the previous dump => the last
        # swipe skipped a gap. Back up and re-read before moving on.
        jumped = bool(prev_keys) and bool(cur_keys) and prev_keys.isdisjoint(cur_keys)
        if jumped and stuck_streak < 3:
            stuck_streak += 1
            print(f"    ⚠ no overlap, backing up ({stuck_streak}/3)", flush=True)
            swipe_down_page(0.7)
            swipes += 1
            time.sleep(_SETTLE_S)
            prev_keys = cur_keys
            continue
        stuck_streak = 0

        idle_streak = idle_streak + 1 if new_count == 0 else 0
        prev_keys = cur_keys
        swipe_up_page()
        swipes += 1
        time.sleep(_SETTLE_S)
    return list(seen.values())


def save(all_rows: list[CardRow], out_path: str):
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in all_rows], f, ensure_ascii=False, indent=2)


def load_existing(out_path: str) -> tuple[list[CardRow], set[str]]:
    try:
        with open(out_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return [], set()
    rows = [_row_from_dict(d) for d in data]
    codes = {r.jhs_code for r in rows}
    return rows, codes


def _row_from_dict(d: dict) -> CardRow:
    """Build a CardRow from a stored dict, upgrading the old
    {set_code,name,number,rarity,price} schema on the fly."""
    if "jhs_code" in d:
        return CardRow(**d)
    jhs_code = d.get("set_code", "")
    card_id = d.get("number", "")
    anime, booster = derive_codes(jhs_code, card_id)
    return CardRow(jhs_code=jhs_code, animeCode=anime, booster=booster,
                   name=d.get("name", ""), cardId=card_id,
                   rarity=d.get("rarity", ""), price=d.get("price", ""))


def _strip_y(default: int = 1490) -> int:
    codes = find_icon_codes(get_root(adb_dump()))
    return bounds_center(codes[0][1])[1] if codes else default


def scroll_strip_to_start(max_swipes: int = 40) -> None:
    """Rewind the set-icon strip to its first icon. Swipe it RIGHT until the
    visible icons stop changing (left end reached).

    Needed because switch_tab(), when we're already on the target tab (the
    common case on a re-run -- the app is parked in the last set's grid with
    the strip pinned above it), taps the tab but does NOT reset the strip's
    horizontal scroll. Without this rewind, enumerate_strip_codes() would
    start halfway down the strip and miss every set before that point."""
    prev_sig = None
    stable = 0
    for _ in range(max_swipes):
        try:
            root = get_root(adb_dump())
        except RuntimeError:
            return
        codes = find_icon_codes(root)
        if not codes:
            try:
                scroll_to_top()
            except (RuntimeError, BlockerError):
                return
            continue
        sig = frozenset(codes)
        if sig == prev_sig:
            stable += 1
            if stable >= 2:
                return
        else:
            stable = 0
        prev_sig = sig
        swipe_strip_right(bounds_center(codes[0][1])[1])
        time.sleep(0.4)


def enumerate_strip_codes(tab_text: str, max_no_new: int = 8) -> list[str]:
    """The ordered, de-duped list of set codes on a tab's icon strip.
    Sweeps the strip left from its start until it stops yielding new codes."""
    if not switch_tab(tab_text):
        return []
    scroll_to_top()
    scroll_strip_to_start()
    ordered: list[str] = []
    seen: set[str] = set()
    no_new = 0
    while no_new < max_no_new and len(ordered) < 300:
        codes = find_icon_codes(get_root(adb_dump()))
        added = 0
        for c, _ in codes:
            if c not in seen:
                seen.add(c)
                ordered.append(c)
                added += 1
        no_new = 0 if added else no_new + 1
        swipe_strip_left(_strip_y())
        time.sleep(0.5)
    return ordered


def _sweep_strip_and_tap(code: str, max_swipes: int = 90, known_codes=None) -> bool | None:
    """Sweep the icon strip left looking for `code`; tap it when found.
    True  = opened a grid
    False = tapped the icon but no card grid ever rendered
    None  = swept the whole strip, `code` isn't on it (caller re-selects tab)
    Raises BlockerError on a login wall.

    Guards: an overlap check (if a swipe skips a whole screenful, nudge
    back so nothing flies past) and end-of-strip detection -- three dumps
    in a row with the exact same icons *and* positions (one stale dump no
    longer aborts the sweep mid-strip)."""
    known = list(known_codes) if known_codes else None
    if known and code in known:
        # guarantee we can cover the whole strip even with back-ups / the
        # occasional re-dump, instead of bailing early on a known code.
        max_swipes = max(max_swipes, len(known) * 3 + 20)
    prev: set[str] = set()
    prev_sig = None
    disjoint_streak = 0
    end_streak = 0
    for _ in range(max_swipes):
        codes = find_icon_codes(get_root(adb_dump()), known)
        cur = {c for c, _ in codes}
        sig = frozenset(codes)

        hit = next((b for c, b in codes if c == code), None)
        if hit is not None:
            hit = _center_strip_icon(code, hit, known)
            tap_bounds(hit)
            time.sleep(1.5)
            if on_blocker_screen(get_root(adb_dump())):
                raise BlockerError(f"tapping {code} opened a login/error screen")
            return bool(reveal_grid_top())

        if not codes:
            scroll_to_top()
            prev = set()
            prev_sig = None
            continue

        y = bounds_center(codes[0][1])[1]

        # reached the end: same icons in the same spots, several dumps running
        if sig == prev_sig:
            end_streak += 1
            if end_streak >= 3:
                return None
        else:
            end_streak = 0

        # a swipe jumped a whole screenful with no overlap -> back up once
        if prev and cur.isdisjoint(prev) and disjoint_streak < 3:
            disjoint_streak += 1
            swipe_strip_right(y)
            time.sleep(0.4)
            prev = cur
            prev_sig = sig
            continue
        disjoint_streak = 0

        prev = cur
        prev_sig = sig
        swipe_strip_left(y)
        time.sleep(0.5)
    return None


def open_set(tab_text: str, code: str, max_swipes: int = 90, known_codes=None):
    """Open the set `code` on tab `tab_text`.

    Fast path: we're usually already on the right tab (the previous set's
    page keeps the strip pinned above the grid, and crawl_tab scrolled it
    back into view), so just sweep the strip. Only if that fails do we
    re-select the tab (which also resets the strip to its start).

    Returns True  = grid opened
            False = icon tapped but no grid rendered
            None  = code never seen on the strip
    Raises BlockerError if a tap lands on a login / error wall.
    """
    try:
        scroll_to_top()
        got = _sweep_strip_and_tap(code, max_swipes, known_codes)
        if got is not None:
            return got
    except BlockerError:
        raise
    except RuntimeError:
        pass
    # fall back: explicitly (re)select the tab, rewind the strip, sweep it
    if not switch_tab(tab_text):
        return None
    scroll_to_top()
    scroll_strip_to_start()
    got = _sweep_strip_and_tap(code, max_swipes, known_codes)
    if got is None and known_codes and code in known_codes:
        # enumeration proved this code IS on the strip -> the sweep hit a
        # transient stall, not a real miss. Hard-reset and try once more.
        print(f"    {code}: enumerated but sweep missed it -- hard retry", flush=True)
        _safe_recover()
        if switch_tab(tab_text):
            try:
                scroll_to_top()
                scroll_strip_to_start()
                got = _sweep_strip_and_tap(code, max_swipes, known_codes)
            except (RuntimeError, BlockerError):
                pass
    return got


def crawl_tab(tab_text: str, all_rows: list[CardRow], visited_codes: set[str], out_path: str):
    print(f"=== tab: {tab_text} ===", flush=True)
    ensure_library_screen()
    codes = enumerate_strip_codes(tab_text)
    if not codes:
        print(f"  tab {tab_text!r} not present / no sets, skipping", flush=True)
        return
    todo = [c for c in codes if c not in visited_codes]
    print(f"  {len(codes)} sets on strip, {len(todo)} to scrape: {todo}", flush=True)

    # Bounded, no-infinite-loop guarantees:
    #  - each code is attempted at most once per run (`attempted`)
    #  - 2 unrecoverable login walls on a tab  -> abort the tab
    #  - 5 plain misses in a row               -> abort the tab
    #  - 3 transient adb errors in a row       -> abort the tab
    attempted: set[str] = set()
    blocker_hits = miss_streak = error_streak = 0

    for code in todo:
        if code in attempted:
            continue
        attempted.add(code)

        if blocker_hits >= 2:
            print(f"  ABORT tab {tab_text!r}: login wall keeps returning "
                  f"(gated?). {len(todo) - len(attempted)} sets left for resume.", flush=True)
            return
        if miss_streak >= 5 or error_streak >= 3:
            print(f"  ABORT tab {tab_text!r}: {miss_streak} misses / {error_streak} errors "
                  f"in a row. Left for resume.", flush=True)
            return

        print(f"  selecting set {code}", flush=True)
        try:
            opened = open_set(tab_text, code, known_codes=codes)
        except BlockerError as e:
            print(f"    !! {code}: {e}", flush=True)
            blocker_hits += 1
            if not dismiss_blockers():          # escalates: BACK x3 -> relaunch
                print("    !! could not clear the login wall", flush=True)
            _safe_recover()
            continue
        except RuntimeError as e:               # adb_dump gave up, etc.
            print(f"    !! {code}: {e} -- recovering", flush=True)
            error_streak += 1
            _safe_recover()
            continue

        if not opened:
            reason = ("never appeared on strip after a full sweep"
                      if opened is None else
                      "icon tapped but no card grid rendered")
            print(f"    !! {code}: {reason}, skipping", flush=True)
            miss_streak += 1
            _safe_recover()
            continue

        try:
            rows = scrape_current_set_price_grid(code)
        except RuntimeError as e:
            print(f"    !! {code}: {e} during scrape -- recovering", flush=True)
            error_streak += 1
            _safe_recover()
            continue

        blocker_hits = miss_streak = error_streak = 0
        print(f"    -> {len(rows)} cards", flush=True)
        all_rows.extend(rows)
        visited_codes.add(code)
        save(all_rows, out_path)
        print(f"    (saved, {len(all_rows)} rows so far)", flush=True)
        # scroll the grid back up so the tab bar + set-icon strip (pinned
        # above the grid on the same page) are in view again -- no BACK,
        # no relaunch, next open_set just sweeps the strip.
        try:
            scroll_to_top()
        except (RuntimeError, BlockerError):
            _safe_recover()


def _safe_recover():
    """Best-effort return to the card library; never raises."""
    try:
        dismiss_blockers()
        ensure_library_screen()
    except Exception as e:                       # noqa: BLE001 - last-ditch
        print(f"    (recover: {e})", flush=True)


def _find_emulator_bin() -> str | None:
    for base in (os.environ.get("ANDROID_SDK_ROOT"), os.environ.get("ANDROID_HOME"),
                 os.path.expanduser("~/Library/Android/sdk")):
        if base:
            p = os.path.join(base, "emulator", "emulator")
            if os.path.exists(p):
                return p
    return shutil.which("emulator")


def _device_online() -> bool:
    try:
        out = subprocess.run(["adb", "devices"], capture_output=True, timeout=10).stdout.decode()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
    return any(ln.split("\t")[-1].strip() == "device" for ln in out.splitlines()[1:] if ln.strip())


def _wait_boot(timeout_s: float) -> bool:
    subprocess.run(["adb", "wait-for-device"], check=False)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            done = subprocess.run(["adb", "shell", "getprop", "sys.boot_completed"],
                                  capture_output=True, timeout=10).stdout.decode().strip()
        except subprocess.TimeoutExpired:
            done = ""
        if done == "1":
            return True
        time.sleep(2)
    return False


def ensure_emulator(avd: str | None, apk: str | None, boot_timeout: float = 240) -> None:
    """No-op if a device is already connected. Otherwise boot an AVD, wait
    for it to finish booting, install the app if it's missing, and launch
    it. Navigating to the JP Union Arena card library is still manual --
    ensure_library_screen() will complain if you haven't."""
    if _device_online():
        print("device already online -- skipping emulator boot", flush=True)
    else:
        emu = _find_emulator_bin()
        if not emu:
            raise RuntimeError("no device connected and no `emulator` binary found; "
                               "set ANDROID_SDK_ROOT or connect a phone.")
        if not avd:
            avds = subprocess.run([emu, "-list-avds"], capture_output=True, timeout=15
                                  ).stdout.decode().split()
            if not avds:
                raise RuntimeError("no AVDs found -- create one in Android Studio.")
            avd = avds[0]
        print(f"booting emulator @{avd} (up to {boot_timeout:.0f}s) ...", flush=True)
        subprocess.Popen([emu, "-avd", avd, "-no-snapshot-load", "-no-boot-anim"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        if not _wait_boot(boot_timeout):
            raise RuntimeError(f"emulator @{avd} didn't finish booting in {boot_timeout:.0f}s")
        time.sleep(3)
        subprocess.run(["adb", "shell", "input", "keyevent", "82"], check=False)  # wake/unlock
        print("emulator booted", flush=True)

    installed = subprocess.run(["adb", "shell", "pm", "list", "packages", APP_PKG],
                               capture_output=True, timeout=15).stdout.decode()
    if APP_PKG not in installed:
        if not apk or not os.path.exists(apk):
            raise RuntimeError(f"{APP_PKG} not installed and no valid --apk given "
                               f"(try --apk {_DEFAULT_APK}).")
        print(f"installing {apk} ...", flush=True)
        r = subprocess.run(["adb", "install", "-r", "-g", apk], capture_output=True, timeout=600)
        if r.returncode != 0:
            raise RuntimeError(f"adb install failed: {r.stderr.decode()[:300]}")
    subprocess.run(["adb", "shell", "monkey", "-p", APP_PKG, "-c",
                    "android.intent.category.LAUNCHER", "1"],
                   check=False, capture_output=True)
    time.sleep(5)


_DEFAULT_APK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "JHSUPDATED.apk")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="union_arena_all_sets.json")
    ap.add_argument("--tabs", nargs="*", default=TABS)
    ap.add_argument("--boot-emulator", action="store_true",
                    help="start an Android emulator first if no device is connected")
    ap.add_argument("--avd", default=None,
                    help="AVD name to boot (default: first from `emulator -list-avds`)")
    ap.add_argument("--apk", default=_DEFAULT_APK if os.path.exists(_DEFAULT_APK) else None,
                    help="APK to install if the app is missing from the device")
    args = ap.parse_args()

    if args.boot_emulator:
        ensure_emulator(args.avd, args.apk)

    all_rows, visited_codes = load_existing(args.out)
    start_sets = len(visited_codes)
    if visited_codes:
        print(f"resuming from {args.out}: {len(all_rows)} rows, "
              f"{len(visited_codes)} sets already done: {sorted(visited_codes)}", flush=True)

    ensure_library_screen()  # fail loudly now if the app isn't positioned right

    for tab in args.tabs:
        try:
            crawl_tab(tab, all_rows, visited_codes, args.out)
        except KeyboardInterrupt:
            print("\ninterrupted -- saving progress", flush=True)
            break
        except Exception as e:                    # noqa: BLE001
            print(f"=== tab {tab!r} bailed: {type(e).__name__}: {e} -- moving on", flush=True)
            save(all_rows, args.out)
            _safe_recover()

    gained = len(visited_codes) - start_sets
    print(f"collected {len(all_rows)} card rows across {len(visited_codes)} sets "
          f"(+{gained} this run)", flush=True)
    save(all_rows, args.out)
    print(f"wrote {args.out}", flush=True)


if __name__ == "__main__":
    main()
