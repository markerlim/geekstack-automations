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
import sys
import tempfile
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

# adb target. main() replaces this with ["adb", "-s", <serial>] when --serial
# is given, so every _adb() call routes to one specific device/emulator.
ADB: list[str] = ["adb"]

# Set when the orchestrator (crawl_parallel.py) runs several emulators at once:
# the host is under load, uiautomator dumps get slower/flakier, so we widen the
# retry/settle budgets and the per-tab abort thresholds. Solo runs are unaffected.
PARALLEL = os.environ.get("UA_PARALLEL") == "1"


def _adb(*args, **kw):
    """subprocess.run for an adb subcommand, targeting the module ADB device.
    Takes the same kwargs as subprocess.run."""
    return subprocess.run([*ADB, *args], **kw)


class _Budget:
    """Wall-clock stop for the strip/tab navigation loops. They were bounded
    only by iteration count -- fine on a healthy device, but on a degraded
    emulator each `adb_dump` takes seconds, so a 60- or 250-iteration loop
    balloons to 5-40 min with no output ('keeps swiping forever'). A budget
    makes them return best-effort instead, so the caller's retry / _kick_app /
    (orchestrator) reboot can take over."""
    def __init__(self, seconds: float):
        self.deadline = time.monotonic() + seconds
        self.seconds = seconds

    def expired(self) -> bool:
        return time.monotonic() >= self.deadline


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


def _foreground_pkg() -> str:
    """Best-effort package name of the current foreground activity, via
    `dumpsys activity activities`. Empty string if the check itself fails
    (never raises -- this is a diagnostic poll, not a critical path)."""
    try:
        out = _adb("shell", "dumpsys", "activity", "activities", check=False,
                   capture_output=True, timeout=10).stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        return ""
    for line in out.splitlines():
        if "topResumedActivity" in line or "mResumedActivity" in line:
            return line
    return ""


def _relaunch_app(tries: int = 3, settle: float = 2.5) -> bool:
    """Fire the launcher intent and CONFIRM the app actually reached the
    foreground before moving on. A monkey launch fired right after
    force-stop is occasionally silently dropped (the old process is still
    being torn down) -- the caller used to just sleep a fixed time and
    carry on regardless, so a dropped launch stranded the crawl on the home
    screen for the rest of its retry budget with no tab bar to ever find,
    logged only as a repeating, misleading 'card library not visible'."""
    for attempt in range(tries):
        _adb("shell", "monkey", "-p", APP_PKG, "-c",
             "android.intent.category.LAUNCHER", "1", check=False,
             capture_output=True, timeout=15)
        time.sleep(settle)
        if APP_PKG in _foreground_pkg():
            return True
        print(f"    relaunch attempt {attempt + 1}/{tries}: "
              f"app didn't come to foreground", flush=True)
    return False


def _kill_ondevice_uiautomator() -> None:
    """A wedged on-device uiautomator server never recovers on its own and
    hangs every subsequent `dump`. Kill it so the next call re-spawns."""
    _adb("shell", "pkill", "-f", "uiautomator", check=False,
         capture_output=True, timeout=8)


def adb_dump(retries: int | None = None) -> str:
    """uiautomator dump, tolerant of the transient failures that happen
    mid-animation / on error screens. FAILS FAST -- a hung dump used to burn
    ~8 min of retries (× the slow file fallback) and freeze a parallel
    worker; now it's ~2 min worst case, after which the caller force-stops
    and relaunches the app (which resets uiautomator)."""
    if retries is None:
        retries = 3 if PARALLEL else 5
    timeout = 12 if PARALLEL else 20
    last = ""
    for attempt in range(retries):
        try:
            out = _adb(
                "exec-out", "uiautomator", "dump", "/dev/tty",
                capture_output=True, timeout=timeout,
            ).stdout.decode("utf-8", errors="replace")
            xml = _extract_hierarchy(out)
            if xml:
                return xml
            last = out[:120]
        except subprocess.TimeoutExpired:
            last = "<timeout>"
            _kill_ondevice_uiautomator()
        except (subprocess.SubprocessError, OSError) as e:
            last = f"<{type(e).__name__}: {e}>"
        # dump-to-file fallback: only for solo runs -- when the device is
        # healthy it's cheap, and under parallel load it just doubles the
        # time against an already-wedged uiautomator.
        if not PARALLEL:
            try:
                _adb("shell", "uiautomator", "dump", "/sdcard/uidump.xml",
                     capture_output=True, timeout=timeout)
                out = _adb("exec-out", "cat", "/sdcard/uidump.xml",
                           capture_output=True, timeout=timeout
                           ).stdout.decode("utf-8", "replace")
                xml = _extract_hierarchy(out)
                if xml:
                    return xml
            except subprocess.TimeoutExpired:
                pass
        if attempt < retries - 1:
            time.sleep(1.5)
    raise RuntimeError(f"uiautomator dump failed after {retries} tries "
                       f"(last output head: {last!r})")


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
                    _adb("shell", "input", "tap", str(x), str(y), check=False)
                    time.sleep(1.0)
                    return
    except RuntimeError:
        pass
    _adb("shell", "input", "keyevent", "4", check=False)
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


# the app renders one of these when a scrollable list has no more items --
# a definitive "you've seen everything" signal, far better than guessing
# from N idle swipes.
_END_MARKERS = ("- END -", "END", "已经到底了", "已经到底啦", "没有更多了",
                "没有更多", "到底了", "我也是有底线的")


def _list_at_bottom(root: ET.Element) -> bool:
    for n in root.iter("node"):
        t = n.get("text", "").strip()
        if t and (t in _END_MARKERS or t.replace(" ", "") in
                  {m.replace(" ", "") for m in _END_MARKERS}):
            return True
    return False


_TOP_ANCHORS = ("同音字/拼音/首字母/编号", "携战之境UA", "拍照查卡")


def _at_page_top(root: ET.Element) -> bool:
    """True when the real top of the card-library page is on screen (header +
    search bar), not just a pinned strip above a scrolled grid. This view is
    the source of truth for the tab row + set-icon strip."""
    t = {n.get("text", "") for n in root.iter("node")}
    return any(a in t for a in _TOP_ANCHORS)


def recover_to_grid(max_back: int = 4) -> bool:
    """Misclick recovery (the flow the app forces on you):
        stray card tap  ->  card-detail page  ->  login prompt
    BACK to leave the login page, BACK again to leave card-detail, landing
    back on the card grid. Coordinate-free; re-checks after each BACK and
    stops the moment the grid is showing again."""
    dismiss_ad_popup()          # a resume-time promo can't be BACK'd out of
    for _ in range(max_back):
        try:
            if _on_grid_page(get_root(adb_dump())):
                return True
        except RuntimeError:
            pass
        _adb("shell", "input", "keyevent", "4", check=False)
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
    _adb("shell", "input", "tap", str(x), str(y), check=True)


def find_tab_bounds(root: ET.Element, tab_text: str) -> str | None:
    for node in root.iter("node"):
        if node.get("text", "") == tab_text:
            return node.get("bounds")
    return None


_ANY_TAB = ("近期更新", "补充包", "简中版", "构筑", "现场活动", "PR", "其他 & 周边", "分类")


def _rids(root: ET.Element) -> set[str]:
    return {n.get("resource-id", "").rsplit("/", 1)[-1]
            for n in root.iter("node") if n.get("resource-id", "")}


def _on_category_page(root: ET.Element) -> bool:
    """The full-page 分类 browser (title 卡牌库, a vertical kind rail + list).
    It carries the SAME tab labels ('补充包' ...) in its side rail, so
    _library_tabs_visible() used to mistake it for the real library and the
    crawl would strand itself here. Discriminate on resource-ids: the 分类
    page has `kindRv` and no horizontal `packRv` strip / `scroll_view` bar."""
    r = _rids(root)
    return "kindRv" in r and "packRv" not in r and "scroll_view" not in r


def _on_main_library(root: ET.Element) -> bool:
    """The real card-library page the crawl drives: horizontal tab scroller
    (`scroll_view`) + horizontal set-icon strip (`packRv`)."""
    r = _rids(root)
    return "scroll_view" in r and "packRv" in r


# The app's bottom-nav home ("探索" / Discover). Its game-shortcut tiles
# ("18.0", "OP17" ...) match the set-code regex, so find_icon_codes() used to
# fire here and _library_tabs_visible() would wrongly say "we're on the
# library" -- switch_tab() then swiped a phantom tab bar until its budget
# expired. Fingerprint it on the home-only resource-ids and bail out.
_DISCOVER_RIDS = ("vpHome", "trendTv", "shopTv", "warehouseTv", "rateTv", "bottomTab")


def _on_discover_home(root: ET.Element) -> bool:
    r = _rids(root)
    return "packRv" not in r and sum(x in r for x in _DISCOVER_RIDS) >= 2


def _library_tabs_visible(root: ET.Element) -> bool:
    """True only if we're on the REAL card library (not the 分类 browser
    or the Discover home)."""
    if _on_category_page(root) or _on_discover_home(root):
        return False
    return (_on_main_library(root)
            or bool(find_icon_codes(root))
            or any(find_tab_bounds(root, t) for t in _ANY_TAB))


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
    if _find_ad_close_bounds(root) is not None:
        return True             # promo interstitial -- dismiss_blockers() taps its X
    t = _texts(root)
    return (sum(m in t for m in _LOGIN_MARKERS) >= 2
            or any(m in x for x in t for m in _ERROR_MARKERS))


# Promo / "welcome" interstitials the app throws up on launch or resume. They
# float above the library and hide the tab bar, so ensure_library_screen()
# used to just fail. Each has a close (X) control: an ImageView whose
# resource-id ends in a close-ish token, or a node whose text/content-desc is
# a close/skip label. BACK often does NOT dismiss these, so we tap the X.
_AD_CLOSE_RID_TOKENS = ("ivclose", "iv_close", "closeiv", "close_iv", "btnclose",
                        "btn_close", "closebtn", "close_btn", "adclose", "ad_close",
                        "dialogclose", "dialog_close", "imgclose", "img_close",
                        "iconclose", "icon_close", "close")
_AD_CLOSE_LABELS = ("关闭", "跳过", "关闭广告", "close", "skip", "✕", "×", "x")


def _find_ad_close_bounds(root: ET.Element) -> str | None:
    for n in root.iter("node"):
        rid = n.get("resource-id", "").rsplit("/", 1)[-1].lower()
        if rid and any(tok in rid for tok in _AD_CLOSE_RID_TOKENS) \
                and n.get("clickable") == "true" and n.get("bounds"):
            return n.get("bounds")
    for n in root.iter("node"):
        label = (n.get("text", "") or n.get("content-desc", "")).strip().lower()
        if label in _AD_CLOSE_LABELS and n.get("bounds"):
            return n.get("bounds")
    return None


def dismiss_ad_popup(max_tries: int = 4) -> bool:
    """Tap the X on any launch/resume promo interstitial. Returns True if a
    popup was closed (or none was there); False if one is still up."""
    closed_any = False
    for _ in range(max_tries):
        try:
            root = get_root(adb_dump())
        except RuntimeError:
            return closed_any
        b = _find_ad_close_bounds(root)
        if not b:
            return True
        print(f"    ad interstitial -- tapping close {b}", flush=True)
        try:
            tap_bounds(b)
        except Exception:  # noqa: BLE001
            _adb("shell", "input", "keyevent", "4", check=False)
        closed_any = True
        time.sleep(1.4)
    try:
        return _find_ad_close_bounds(get_root(adb_dump())) is None
    except RuntimeError:
        return False


def dismiss_blockers(max_tries: int = 5) -> bool:
    """Back out of a login wall / error page / modal. Escalates:
    BACK a few times, then relaunch the app. Returns True once a normal
    screen shows (or nothing was blocking)."""
    dismiss_ad_popup()          # promo interstitials ignore BACK -- tap their X first
    for i in range(max_tries):
        try:
            if not on_blocker_screen(get_root(adb_dump())):
                return True
        except RuntimeError:
            pass
        if i < 3:
            _adb("shell", "input", "keyevent", "4", check=False)
            time.sleep(1.2)
        else:
            print("    blocker won't dismiss -- relaunching app", flush=True)
            _relaunch_app()
    # as in ensure_library_screen(): a relaunch right after force-stop is a
    # cold start that was observed taking 60-90s under 2-emulator host load
    # before the app actually renders -- give it real time rather than
    # judging off one dump taken the instant the process reappears.
    deadline = time.time() + (90.0 if PARALLEL else 12.0)
    while time.time() < deadline:
        try:
            if not on_blocker_screen(get_root(adb_dump())):
                return True
        except RuntimeError:
            pass
        time.sleep(1.0)
    return False


def _leave_discover_home(max_tries: int = 3) -> bool:
    """If the app is on the bottom-nav Discover home ("探索"), tap the 集换
    nav entry to get onto the card library. Returns True once off the home
    (or if it was never there)."""
    for _ in range(max_tries):
        try:
            root = get_root(adb_dump())
        except RuntimeError:
            return False
        if not _on_discover_home(root):
            return True
        b = find_tab_bounds(root, "集换")
        if not b:
            return False
        print("    on Discover home -- tapping 集换 nav", flush=True)
        try:
            tap_bounds(b)
        except Exception:  # noqa: BLE001
            return False
        time.sleep(2.5)
        if _wait_for_library(3.0):
            return True
    try:
        return not _on_discover_home(get_root(adb_dump()))
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
    # a pulled-down notification shade / quick-settings panel hides everything
    # and swallows taps -- collapse it before anything else.
    _adb("shell", "cmd", "statusbar", "collapse", check=False, capture_output=True)
    dismiss_ad_popup()
    dismiss_blockers()
    _leave_discover_home()
    # A stray tap on 分类 opens the full-page category browser, which the
    # crawl cannot use -- BACK straight out of it before anything else.
    for _ in range(3):
        try:
            if not _on_category_page(get_root(adb_dump())):
                break
        except RuntimeError:
            break
        print("    on the 分类 browser -- backing out", flush=True)
        _adb("shell", "input", "keyevent", "4", check=False)
        time.sleep(1.5)
    # First just wait -- most calls land here right after tap_back() while
    # the library is still repainting; a BACK now would over-navigate.
    if _wait_for_library(3.0):
        return
    for attempt in range(max_back + 1):
        if _library_tabs_visible(get_root(adb_dump())):
            return
        if attempt < max_back:
            _adb("shell", "input", "keyevent", "4", check=False)  # BACK
            time.sleep(1.2)
            if _wait_for_library(2.0):
                return

    print("  card library not visible -- relaunching app", flush=True)
    if not _relaunch_app():
        raise RuntimeError(
            "could not reach the card-library screen (app never came to "
            "foreground after relaunch). Open the 携战之境UA 日文 card "
            "library manually, then re-run."
        )
    # _relaunch_app() only confirms the PROCESS is foregrounded -- right
    # after force-stop that's still just the splash screen, and a cold start
    # under 2-emulator host contention was observed taking 60-90s end to end
    # (logcat: class loading + GC churn + view inflation, not a hang) before
    # the library actually renders. Give it real time instead of judging a
    # still-loading app as "stuck" and clicking around it -- a premature
    # judgement here was the actual cost multiplier: it triggered ANOTHER
    # full force-stop+cold-start cycle on an app that would have come up
    # fine if just left alone a bit longer.
    if _wait_for_library(90.0 if PARALLEL else 25.0):
        return
    dismiss_ad_popup()          # a cold launch almost always shows the promo
    dismiss_blockers()
    _leave_discover_home()
    root = get_root(adb_dump())
    if not _library_tabs_visible(root):
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


def scroll_to_top(max_swipes: int = 25, full: bool = False):
    """Pull-down until the set-icon strip is visible (default) or the REAL
    page top -- header + search bar -- is visible (`full=True`, used before
    enumerating/switching tabs so we read the canonical tab row, not a
    pinned strip above a half-scrolled grid). Raises BlockerError on a
    login / error screen."""
    for _ in range(max_swipes):
        root = get_root(adb_dump())
        if on_blocker_screen(root):
            raise BlockerError("login/error screen while scrolling to strip")
        if _at_page_top(root) if full else find_icon_codes(root):
            return
        # pull-down gesture to reveal the strip at the top of the page
        _adb("shell", "input", "swipe", "540", "700", "540", "1900", "150", check=True)
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
_SETTLE_S = 1.3 if PARALLEL else 0.9

# per-tab abort thresholds -- widened under parallel load (dumps get flakier
# with several emulators competing for the host, so a few extra misses/errors
# in a row are noise, not a dead tab).
_MISS_ABORT = 8 if PARALLEL else 5
_ERROR_ABORT = 5 if PARALLEL else 3

# consecutive dumps with the strip not moving at all -> the RecyclerView has
# stopped responding to `input swipe` (degraded emulator); give up sweeping it.
_STRIP_STALL_LIMIT = 15


def swipe_up_page(frac: float = 1.0):
    dy = int(_SCROLL_STEP * frac)
    _adb("shell", "input", "swipe", "540", str(_SCROLL_TOP_Y),
         "540", str(_SCROLL_TOP_Y - dy), "450", check=True)


def swipe_down_page(frac: float = 0.7):
    dy = int(_SCROLL_STEP * frac)
    _adb("shell", "input", "swipe", "540", str(_SCROLL_TOP_Y - _SCROLL_STEP),
         "540", str(_SCROLL_TOP_Y - _SCROLL_STEP + dy), "450", check=True)


def swipe_strip_left(y: int):
    # Short horizontal step (~2 icons) with ~2 icons of overlap so no set
    # icon slips through un-dumped. Swipe at the icon-label y from
    # find_icon_codes -- the known-good surface. Category-jump is prevented
    # upstream (find_icon_codes returns ONLY the real strip row; open_set
    # re-selects the tab on a miss), so no y-clamp games here.
    _adb("shell", "input", "swipe", "950", str(int(y)), "440", str(int(y)), "400", check=True)


def swipe_strip_right(y: int):
    """Nudge the strip back the other way -- shorter than swipe_strip_left,
    used by the overlap guard to un-skip an icon that flew past."""
    _adb("shell", "input", "swipe", "440", str(int(y)), "820", str(int(y)), "400", check=True)


def _center_strip_icon(code: str, bounds: str, known, band=(140, 940)) -> tuple[str, bool]:
    """If `code`'s icon is sitting half off a screen edge (its centre x is
    outside `band`), nudge the strip a few times to walk it inward and
    return the fresh, fully-tappable bounds. Falls back to the original
    bounds if the icon can't be re-located.

    Returns (bounds, pinned). `pinned` is True when the strip would not
    scroll any further in the needed direction -- it's bottomed out at an
    end and this (tail/head) icon stays clipped against the edge. The
    caller should then tap it where it sits instead of expecting a cleaner
    position or a re-parseable label.
    """
    cx, y = bounds_center(bounds)
    for _ in range(3):
        if band[0] <= cx <= band[1]:
            return bounds, False
        before = bounds
        (swipe_strip_right if cx < band[0] else swipe_strip_left)(y)
        time.sleep(0.5)
        codes = find_icon_codes(get_root(adb_dump()), known)
        nb = next((b for c, b in codes if c == code), None)
        if nb is None:
            break
        if nb == before:
            return nb, True          # swipe didn't move the strip -> at its end
        bounds = nb
        cx, y = bounds_center(bounds)
    return bounds, not (band[0] <= cx <= band[1])


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
    _adb("shell", "input", "swipe", str(x1), str(y), str(x2), str(y), "300", check=True)
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
    try:
        return find_tab_bounds(get_root(adb_dump()), tab_text) or b
    except RuntimeError:
        return b


def _tab_bar_showing(root: ET.Element) -> bool:
    if _on_discover_home(root) or _on_category_page(root):
        return False
    return any(find_tab_bounds(root, t) for t in _ANY_TAB) or bool(find_icon_codes(root))


def _guess_sweep_order(root: ET.Element, tab_text: str) -> list[str]:
    """Which direction to try first when hunting for `tab_text`. _ANY_TAB is
    in real screen left-to-right order; a relaunch/resume can park the bar
    anywhere on it (e.g. back on 现场活动 instead of the default 近期更新),
    not just at the leftmost start -- so a fixed "always sweep left first"
    guess walks AWAY from the target whenever it resumes right of it."""
    target = _ANY_TAB.index(tab_text)
    visible = [_ANY_TAB.index(t) for t in _ANY_TAB if find_tab_bounds(root, t)]
    if visible and max(visible) > target:
        return ["right"] * 8 + ["left"] * 10   # target sits to the left -> reveal it
    return ["left"] * 8 + ["right"] * 10        # default: target sits to the right (or unknown)


def switch_tab(tab_text: str) -> bool:
    """Tap the named tab. First make sure we're actually on the card
    library (a prior set-scrape leaves us buried in a grid), THEN scroll
    the horizontal tab bar to the target. Never blind-swipe at a guessed y
    -- only scroll the bar when a real tab label is visible to anchor it,
    otherwise a horizontal swipe lands on card content and can trip the
    login wall."""
    dismiss_blockers()
    _wait_for_library(3.0)          # let the view settle after a tap_back()
    try:
        scroll_to_top(max_swipes=8, full=True)   # the tab row reads cleanly
    except (RuntimeError, BlockerError):         # only at the real page top
        pass
    # PR is the tab furthest from the default (post-relaunch) leftmost
    # position, so it needs the most dump/swipe round-trips of any tab --
    # under PARALLEL that's also when uiautomator dumps run slowest, so a
    # fixed 120s budget hit PR far more often than any other tab in
    # practice. Widen it here rather than for every tab's easier case. Under
    # PARALLEL a single cold-start recovery inside this loop can itself take
    # up to 90s (observed), so leave headroom above that rather than cutting
    # the budget out from under a relaunch that's about to succeed.
    budget_s = 240 if PARALLEL else 120
    budget = _Budget(budget_s)
    sweep_order: list[str] | None = None
    for i in range(18):
        if budget.expired():
            print(f"    switch_tab({tab_text}): {budget_s}s budget hit", flush=True)
            return False
        try:
            root = get_root(adb_dump())
        except RuntimeError as e:
            # A wedged dump used to propagate straight out of switch_tab(),
            # crashing the whole chunk instead of just this attempt (the
            # PR-tab tracebacks that preceded 'could not reach the
            # card-library screen' in the logs). Treat it like any other
            # transient miss and let the budget above decide when to quit.
            print(f"    switch_tab({tab_text}): dump failed ({e}), retrying",
                  flush=True)
            time.sleep(1.0)
            continue
        if sweep_order is None:
            # Decide direction from wherever the bar actually is (a resumed
            # app can park it anywhere on _ANY_TAB, not just the default
            # leftmost position) rather than assuming a fixed start point.
            sweep_order = _guess_sweep_order(root, tab_text)
        direction = sweep_order[i]
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


def reveal_grid_top(max_down: int | None = None) -> bool:
    """After opening a set: wait for the price grid to render (it can lag,
    especially with several emulators loading at once), scrolling down a
    little if needed, then seat at the top. False only if no grid ever
    shows -- mis-tap / login / a genuinely empty set."""
    if max_down is None:
        max_down = 12 if PARALLEL else 8
    if on_blocker_screen(get_root(adb_dump())):
        return False

    # 1. wait IN PLACE first -- the set page often needs a beat to paint,
    #    and scrolling a half-loaded page can carry us past the grid.
    for _ in range(8 if PARALLEL else 5):
        if parse_price_grid(get_root(adb_dump())):
            return True
        time.sleep(_SETTLE_S)

    # 2. still nothing -> scroll down looking for it
    downs = 0
    while downs < max_down:
        if parse_price_grid(get_root(adb_dump())):
            for _ in range(downs + 1):          # undo, +1 to seat at the top
                swipe_down_page(0.6)
                time.sleep(0.3)
            return True
        swipe_up_page(0.5)                      # finger up = content scrolls DOWN
        downs += 1
        time.sleep(_SETTLE_S)

    # 3. last chance -- sweep all the way back up and re-check once
    for _ in range(downs + 2):
        swipe_down_page(0.7)
        time.sleep(0.25)
    return bool(parse_price_grid(get_root(adb_dump())))


def scrape_current_set_price_grid(set_code: str, max_idle_swipes: int = 8) -> list[CardRow]:
    seen: dict[tuple[str, str], CardRow] = {}
    idle_streak = 0
    stuck_streak = 0
    swipes = 0
    misclicks = 0
    ad_closes = 0
    prev_keys: set[tuple[str, str]] = set()
    hit_bottom = False
    while idle_streak < max_idle_swipes and swipes < 400:
        xml_text = adb_dump()
        root = get_root(xml_text)
        if _find_ad_close_bounds(root) is not None:
            # a promo floated up over the grid on resume -- close it and
            # re-dump this iteration rather than counting it as a misclick.
            ad_closes += 1
            if ad_closes > 5:
                print("    ad keeps reappearing over the grid -- ending set", flush=True)
                break
            print(f"    ad interstitial over the grid -- closing ({ad_closes})", flush=True)
            dismiss_ad_popup()
            time.sleep(_SETTLE_S)
            continue
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

        # definitive stop: the app rendered its end-of-list marker. One more
        # dump already happened above so every row is captured -- no need to
        # burn `max_idle_swipes` guessing.
        if _list_at_bottom(root):
            hit_bottom = True
            print(f"    reached end-of-list marker ({len(seen)} cards)", flush=True)
            break

        idle_streak = idle_streak + 1 if new_count == 0 else 0
        prev_keys = cur_keys
        swipe_up_page()
        swipes += 1
        time.sleep(_SETTLE_S)
    if not hit_bottom and idle_streak >= max_idle_swipes:
        print(f"    stopped on {idle_streak} idle swipes (no end marker seen) "
              f"-- {len(seen)} cards", flush=True)
    return list(seen.values())


def _atomic_write_json(path: str, obj) -> None:
    """Write JSON to `path` via a temp file + os.replace so a concurrent
    reader (or a crash mid-write) never sees a truncated file. Important
    once several workers + a merge step touch the same tree."""
    d = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save(all_rows: list[CardRow], out_path: str):
    _atomic_write_json(out_path, [asdict(r) for r in all_rows])


def _load_rows(path: str) -> list[CardRow]:
    """Card rows from a stored JSON file (any schema); [] if missing /
    unparseable / not a card-row list (e.g. a manifest dict)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    return [_row_from_dict(d) for d in data if isinstance(d, dict)]


def load_existing(out_path: str) -> tuple[list[CardRow], set[str]]:
    rows = _load_rows(out_path)
    codes = {r.jhs_code for r in rows}
    return rows, codes


# de-dup identity for a card row, and a stable sort order for the canonical file
_MERGE_KEY = lambda r: (r.jhs_code, r.cardId, r.rarity)          # noqa: E731
_SORT_KEY = lambda r: (r.booster, r.jhs_code, r.animeCode, r.cardId, r.rarity)  # noqa: E731


def merge_union(inputs: list[str], canonical: str) -> tuple[int, int]:
    """Fold `canonical` + every `inputs` file into `canonical`.

    Dedup on (jhs_code, cardId, rarity). `canonical` is processed first so a
    row present in any fresh worker output overrides the stale canonical copy
    (prices move). Output is sorted deterministically and written atomically.
    Returns (rows_before, rows_after)."""
    before = len(_load_rows(canonical))
    merged: dict = {}
    for path in [canonical, *sorted(inputs)]:
        for row in _load_rows(path):
            merged[_MERGE_KEY(row)] = row
    out = sorted(merged.values(), key=_SORT_KEY)
    _atomic_write_json(canonical, [asdict(r) for r in out])
    return before, len(out)


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


def scroll_strip_to_start(max_swipes: int = 60, min_swipes: int = 6) -> None:
    """Rewind the set-icon strip to its first icon: swipe RIGHT until the
    LEFTMOST visible code stops changing for several dumps in a row.

    Needed because switch_tab(), when we're already on the target tab (the
    common case on a re-run), taps the tab but does NOT reset the strip's
    horizontal scroll -- without this rewind enumerate_strip_codes() starts
    mid-strip and misses every set before that point (the 补充包 tab has a
    long strip and this was silently dropping its first ~25 sets).

    Uses only the leftmost code (not a full bounds signature, which jitters
    on clipped labels and can falsely read as "stable" mid-strip) and
    requires 4 stable dumps + a minimum swipe count before believing it."""
    left = None
    stable = 0
    budget = _Budget(110)
    for i in range(max_swipes):
        if budget.expired():
            print("    scroll_strip_to_start: 110s budget hit", flush=True)
            return
        try:
            codes = find_icon_codes(get_root(adb_dump()))
        except RuntimeError:
            return
        if not codes:
            for _ in range(3):
                try:
                    scroll_to_top()
                    if find_icon_codes(get_root(adb_dump())):
                        break
                except (RuntimeError, BlockerError):
                    return
            continue
        cur_left = codes[0][0]
        if cur_left == left:
            stable += 1
            if stable >= 4 and i >= min_swipes:
                return
        else:
            stable = 0
        left = cur_left
        swipe_strip_right(bounds_center(codes[0][1])[1])
        time.sleep(0.4)


def enumerate_strip_codes(tab_text: str, max_no_new: int = 14) -> list[str]:
    """The ordered, de-duped list of set codes on a tab's icon strip.
    Sweeps the strip left from its start until it stops yielding new codes.

    `no_new` only counts dumps where the strip ACTUALLY MOVED -- a swipe that
    didn't register (adb hiccup / mid-animation) must not push us toward the
    stop condition, or a long strip (补充包 has ~70 icons) gets truncated."""
    if not switch_tab(tab_text):
        return []
    try:
        scroll_to_top(full=True)     # canonical read: header + tab row + strip
    except BlockerError:
        raise
    except RuntimeError:
        scroll_to_top()
    scroll_strip_to_start()
    ordered: list[str] = []
    seen: set[str] = set()
    no_new = 0
    stalls = 0
    iters = 0
    prev_view: frozenset = frozenset()
    budget = _Budget(330)
    last_beat = time.monotonic()
    while no_new < max_no_new and len(ordered) < 300 and iters < 250:
        iters += 1
        if time.monotonic() - last_beat > 30:
            last_beat = time.monotonic()
            print(f"    enumerate_strip_codes({tab_text}): {len(ordered)} codes so far "
                  f"(iter {iters}, {int(budget.deadline - time.monotonic())}s budget left)",
                  flush=True)
        if budget.expired() or stalls >= _STRIP_STALL_LIMIT:
            why = "330s budget" if budget.expired() else f"{stalls} stalls (strip not scrolling)"
            print(f"    enumerate_strip_codes({tab_text}): stopping on {why} -- "
                  f"{len(ordered)} codes", flush=True)
            break
        try:
            codes = find_icon_codes(get_root(adb_dump()))
        except RuntimeError:
            break
        view = frozenset(c for c, _ in codes)
        added = 0
        for c, _ in codes:
            if c not in seen:
                seen.add(c)
                ordered.append(c)
                added += 1

        moved = view != prev_view
        if added:
            no_new = 0
        elif moved:
            no_new += 1
        # if not moved: swipe didn't take -- don't advance no_new, just retry
        stalls = 0 if moved else stalls + 1
        prev_view = view

        if stalls == 2:                       # a stuck strip is often a popup
            dismiss_blockers()                # (ad interstitial / login wall)
        y = _strip_y()
        swipe_strip_left(y)
        if stalls >= 2:                       # kick a stuck strip harder
            time.sleep(0.4)
            swipe_strip_left(y)
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
    disjoint_streak = 0
    end_streak = 0
    empty_streak = 0
    budget = _Budget(150)
    for _ in range(max_swipes):
        if budget.expired():
            print(f"    _sweep_strip_and_tap({code}): 150s budget hit", flush=True)
            return None
        codes = find_icon_codes(get_root(adb_dump()), known)
        cur = {c for c, _ in codes}

        hit = next((b for c, b in codes if c == code), None)
        if hit is not None:
            hit, pinned = _center_strip_icon(code, hit, known)
            if not pinned:
                # RE-CONFIRM right before tapping: the strip is often still
                # settling from the last swipe, so bounds read a moment ago
                # can point at a neighbour by now -> we open the wrong set.
                time.sleep(0.7)
                hit = next((b for c, b in find_icon_codes(get_root(adb_dump()), known)
                            if c == code), None)
                if hit is None:
                    continue                     # icon drifted out of view; re-sweep
            # `pinned` -> strip is bottomed out at an end and this tail/head
            # icon stays clipped against the edge; the re-confirm dump usually
            # can't re-parse the clipped label, so tap it where it sits. This
            # is what lets the last icons on a long strip (e.g. UA04BT/IMS,
            # UA05BT/KMY on 补充包) get opened at all.
            tap_bounds(hit)
            time.sleep(1.5)
            if on_blocker_screen(get_root(adb_dump())):
                raise BlockerError(f"tapping {code} opened a login/error screen")
            return bool(reveal_grid_top())

        if not codes:
            empty_streak += 1
            if empty_streak >= 4:
                return None                  # strip gone / not rendering
            scroll_to_top()
            prev = set()
            continue
        empty_streak = 0

        y = bounds_center(codes[0][1])[1]

        # end of strip: the SAME set of codes several dumps running. (Compare
        # the code SET, not a bounds signature -- clipped labels jitter the
        # bounds so a bounds signature never repeats and the sweep never
        # terminates. A dropped swipe also gives one identical dump, hence 3
        # + the extra kick below before believing it.)
        if cur and cur == prev:
            end_streak += 1
            swipe_strip_left(y)              # kick: maybe the last swipe missed
            time.sleep(0.4)
            if end_streak >= 3:
                return None
            continue
        end_streak = 0

        # a swipe jumped a whole screenful with no overlap -> back up once
        if prev and cur.isdisjoint(prev) and disjoint_streak < 3:
            disjoint_streak += 1
            swipe_strip_right(y)
            time.sleep(0.4)
            prev = cur
            continue
        disjoint_streak = 0

        prev = cur
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
    budget = _Budget(200)          # whole-of-open_set cap: a dead strip fails
                                   # here in ~200s instead of ~600s of retries
    try:
        scroll_to_top()
        got = _sweep_strip_and_tap(code, max_swipes, known_codes)
        if got is not None:
            return got
    except BlockerError:
        raise
    except RuntimeError:
        pass
    if budget.expired():
        print(f"    open_set({code}): 200s cap hit (strip unresponsive)", flush=True)
        return None
    # fall back: explicitly (re)select the tab, rewind the strip, sweep it
    if not switch_tab(tab_text):
        return None
    scroll_to_top()
    scroll_strip_to_start()
    got = _sweep_strip_and_tap(code, max_swipes, known_codes)
    if (got is None and not budget.expired()
            and known_codes and code in known_codes):
        # enumeration proved this code IS on the strip -> the sweep hit a
        # transient stall, not a real miss. Hard-reset and try once more.
        print(f"    {code}: enumerated but sweep missed it -- hard retry", flush=True)
        _safe_recover()
        if not budget.expired() and switch_tab(tab_text):
            try:
                scroll_to_top()
                scroll_strip_to_start()
                got = _sweep_strip_and_tap(code, max_swipes, known_codes)
            except (RuntimeError, BlockerError):
                pass
    return got


def _scrape_one(tab_text: str, code: str, codes: list[str],
                all_rows: list[CardRow], visited_codes: set[str], out_path: str) -> str:
    """Open + scrape one set. Returns an outcome tag:
        'ok'        -> rows captured (or a genuinely empty set), code marked visited
        'no_grid'   -> icon tapped but the price grid never rendered
        'not_found' -> code never appeared on the strip
        'blocker'   -> a login / error wall
        'error'     -> transient adb / dump failure
    Always leaves the app best-effort back on the library."""
    try:
        opened = open_set(tab_text, code, known_codes=codes)
    except BlockerError as e:
        print(f"    !! {code}: {e}", flush=True)
        if not dismiss_blockers():
            print("    !! could not clear the login wall", flush=True)
        _safe_recover()
        return "blocker"
    except RuntimeError as e:
        print(f"    !! {code}: {e} -- recovering", flush=True)
        _safe_recover()
        return "error"

    if not opened:
        _safe_recover()
        return "not_found" if opened is None else "no_grid"

    # Misclick guard: a stale-bounds tap can open a DIFFERENT set on the strip.
    # If the grid that rendered belongs to another enumerated code (its cards'
    # anime prefix matches some *other* `X/YYY` on this tab), back out and let
    # the revisit pass retry -- otherwise those rows get saved under the wrong
    # jhs_code (this is how 27 IMC cards ended up tagged UA21BT/YYH).
    want = code.split("/")[-1] if "/" in code else None
    if want:
        try:
            first = parse_price_grid(get_root(adb_dump()))
        except RuntimeError:
            first = []
        if first:
            got = re.split(r"[-(\[]", first[0].get("number", ""), maxsplit=1)[0].strip()
            others = {c.split("/")[-1] for c in codes if c != code and "/" in c}
            if got and got != want and got in others:
                print(f"    !! {code}: MISCLICK -- opened the {got} set instead; "
                      f"backing out", flush=True)
                tap_back()
                _safe_recover()
                return "no_grid"

    try:
        rows = scrape_current_set_price_grid(code)
    except RuntimeError as e:
        print(f"    !! {code}: {e} during scrape -- recovering", flush=True)
        _safe_recover()
        return "error"

    print(f"    -> {len(rows)} cards", flush=True)
    all_rows.extend(rows)
    visited_codes.add(code)
    save(all_rows, out_path)
    print(f"    (saved, {len(all_rows)} rows so far)", flush=True)
    try:
        scroll_to_top()
    except (RuntimeError, BlockerError):
        _safe_recover()
    return "ok"


def _write_missed(out_path: str, tab_text: str, report: dict) -> None:
    """Record the still-missing sets for a tab next to its output file, so a
    later run / a human can go straight to them. Merges with any prior tabs."""
    p = out_path + ".missed.json"
    data: dict = {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    if report:
        data[tab_text] = report
    else:
        data.pop(tab_text, None)
    _atomic_write_json(p, data)
    print(f"     -> {p}", flush=True)


def enumerate_tab(tab_text: str, out_path: str) -> list[str]:
    """Enumerate a tab's strip with retries + app-kick between tries.
    Writes a LOUD sentinel to the .missed sidecar on total failure and
    returns [] -- never fails silently (a bad enum used to mean the whole
    PR tab produced 0 rows with no trace)."""
    codes: list[str] = []
    for enum_try in range(3):
        codes = enumerate_strip_codes(tab_text)
        if codes:
            return codes
        print(f"  tab {tab_text!r}: strip enumeration empty "
              f"(try {enum_try + 1}/3)", flush=True)
        _kick_app()
        try:
            ensure_library_screen()
        except RuntimeError:
            pass
    print(f"  !! tab {tab_text!r}: strip NEVER enumerated", flush=True)
    _write_missed(out_path, tab_text, {"__strip__": "tab strip not found / not enumerable"})
    return []


def crawl_tab(tab_text: str, all_rows: list[CardRow], visited_codes: set[str],
              out_path: str, revisit_rounds: int = 2,
              preset_codes: list[str] | None = None,
              known_codes: list[str] | None = None):
    """Scrape sets on one tab.

    Default: enumerate the strip, scrape everything not yet visited.
    Set-queue mode (`preset_codes`): skip enumeration, scrape exactly these
    codes (strip order). `known_codes` = the tab's full strip list (from the
    manifest) so open_set sweeps and the misclick check still know every code
    on the strip, not just this chunk."""
    print(f"=== tab: {tab_text} ===", flush=True)
    ensure_library_screen()

    if preset_codes is not None:
        codes = list(known_codes or preset_codes)
        # a single switch_tab() miss used to abandon the whole chunk as
        # tab_unreachable. Escalate first -- kick the app + re-home + retry --
        # the same way enumerate_tab() does, so a transient wedge (notification
        # shade, dead uiautomator, app backgrounded) doesn't cost 8 sets.
        if not switch_tab(tab_text):
            for attempt in range(3):
                print(f"  tab {tab_text!r}: select failed, escalating "
                      f"({attempt + 1}/3)", flush=True)
                _kick_app()
                try:
                    ensure_library_screen()
                except RuntimeError:
                    pass
                if switch_tab(tab_text):
                    break
            else:
                print(f"  !! tab {tab_text!r}: could not select tab after 3 kicks",
                      flush=True)
                _write_missed(out_path, tab_text,
                              {c: "tab_unreachable" for c in preset_codes})
                return
        try:
            scroll_to_top()
        except BlockerError:
            _safe_recover()
        todo = [c for c in preset_codes if c not in visited_codes]
        print(f"  set-queue mode: {len(todo)} of {len(preset_codes)} to scrape: {todo}",
              flush=True)
    else:
        codes = enumerate_tab(tab_text, out_path)
        if not codes:
            return
        todo = [c for c in codes if c not in visited_codes]
        print(f"  {len(codes)} sets on strip, {len(todo)} to scrape: {todo}", flush=True)

    # Enumeration leaves the strip parked at its FAR end. `todo` is in strip
    # order, so rewind once here and each open_set() then only nudges the
    # strip a little further forward -- instead of _sweep_strip_and_tap
    # re-searching the whole strip (wrong direction first) for every code.
    try:
        scroll_strip_to_start()
    except (RuntimeError, BlockerError):
        _safe_recover()

    # main pass. Streak counters only *pause* the main pass -- whatever is
    # left (plus every miss) is handed to the revisit pass, never dropped.
    missed: dict[str, str] = {}
    blocker_hits = miss_streak = error_streak = 0

    for i, code in enumerate(todo):
        if blocker_hits >= 2 or miss_streak >= _MISS_ABORT or error_streak >= _ERROR_ABORT:
            rest = todo[i:]
            print(f"  main pass on {tab_text!r} paused ({blocker_hits} blockers / "
                  f"{miss_streak} misses / {error_streak} errors in a row) -- deferring "
                  f"{len(rest)} set(s) to the revisit pass", flush=True)
            for c in rest:
                missed.setdefault(c, "deferred")
            _safe_recover()
            break

        print(f"  selecting set {code}", flush=True)
        outcome = _scrape_one(tab_text, code, codes, all_rows, visited_codes, out_path)
        if outcome == "ok":
            blocker_hits = miss_streak = error_streak = 0
            missed.pop(code, None)
        elif outcome == "blocker":
            blocker_hits += 1
            missed[code] = "blocker"
        elif outcome == "error":
            error_streak += 1
            missed[code] = "error"
        else:                                    # not_found / no_grid
            miss_streak += 1
            missed[code] = outcome
            print(f"    !! {code}: {outcome} -- queued for revisit", flush=True)

    # revisit pass(es): re-enumerate the strip fresh each round and retry
    # every set that isn't captured yet. Streak aborts do NOT apply here.
    for rnd in range(1, revisit_rounds + 1):
        pending = [c for c in todo if c not in visited_codes]
        if not pending:
            break
        print(f"  --- revisit {rnd}/{revisit_rounds}: {len(pending)} set(s) {pending} ---",
              flush=True)
        _safe_recover()
        if preset_codes is not None:
            # set-queue mode: the manifest already tells us the strip; a full
            # re-enumeration would cost ~4 min for nothing.
            switch_tab(tab_text)
            try:
                scroll_to_top()
                scroll_strip_to_start()
            except (RuntimeError, BlockerError):
                _safe_recover()
            fresh = codes
        else:
            fresh = enumerate_strip_codes(tab_text) or codes
        progressed = False
        for code in pending:
            print(f"  revisiting {code}", flush=True)
            outcome = _scrape_one(tab_text, code, fresh, all_rows, visited_codes, out_path)
            if outcome == "ok":
                progressed = True
                missed.pop(code, None)
            else:
                missed[code] = outcome
        if not progressed:
            print(f"  revisit {rnd} captured nothing new -- stopping revisits", flush=True)
            break

    still = sorted(c for c in todo if c not in visited_codes)
    report = {c: missed.get(c, "unknown") for c in still}
    if still:
        print(f"  !! {tab_text}: {len(still)}/{len(todo)} set(s) STILL MISSING after "
              f"{revisit_rounds} revisit round(s): {report}", flush=True)
    else:
        print(f"  {tab_text}: all {len(todo)} set(s) captured", flush=True)
    _write_missed(out_path, tab_text, report)


def _kick_app() -> None:
    """Hard reset for a wedged UI: force-stop the app + on-device uiautomator,
    relaunch, wait. Used when plain BACK/relaunch recovery can't even get a
    screen dump."""
    print("    kicking the app (force-stop + relaunch)", flush=True)
    _adb("shell", "am", "force-stop", APP_PKG, check=False, capture_output=True, timeout=10)
    _kill_ondevice_uiautomator()
    time.sleep(1.0)
    if not _relaunch_app(tries=3, settle=3.0):
        print("    kick: app still not foregrounded after retries", flush=True)


def _safe_recover():
    """Best-effort return to the card library; never raises. Escalates to a
    force-stop+relaunch if it can't otherwise get there."""
    try:
        dismiss_blockers()
        ensure_library_screen()
        return
    except Exception as e:                       # noqa: BLE001
        print(f"    (recover: {e}) -- escalating", flush=True)
    try:
        _kick_app()
        ensure_library_screen()
    except Exception as e:                       # noqa: BLE001 - last-ditch
        print(f"    (recover still failing: {e})", flush=True)


_DEFAULT_APK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "JHS.apk")


def _find_emulator_bin() -> str | None:
    for base in (os.environ.get("ANDROID_SDK_ROOT"), os.environ.get("ANDROID_HOME"),
                 os.path.expanduser("~/Library/Android/sdk")):
        if base:
            p = os.path.join(base, "emulator", "emulator")
            if os.path.exists(p):
                return p
    return shutil.which("emulator")


def _adb_pfx(serial: str | None) -> list[str]:
    return ["adb"] if not serial else ["adb", "-s", serial]


# console_port -> Popen of the qemu instance we last spawned on it. `adb emu
# kill` needs a live adb transport to deliver the kill command; once a device
# has gone "offline" that transport is dead and the command is a no-op, so
# ensure_emulator_instance()'s "not online -> boot a new one" path used to
# leave the old, un-reachable-but-still-running qemu process behind as an
# orphan on the SAME ports (silently doubling host RAM/CPU load and worsening
# the very stalls that triggered the reboot). Tracked here so kill_emulator()
# can fall back to killing the process directly.
_EMULATOR_PROCS: dict[int, subprocess.Popen] = {}


def kill_emulator(console_port: int, serial: str | None = None) -> None:
    """Best-effort, escalating kill of the qemu instance on `console_port`.
    Safe to call even if nothing is running there."""
    serial = serial or f"emulator-{console_port}"
    subprocess.run([*_adb_pfx(serial), "emu", "kill"], capture_output=True, timeout=20)
    time.sleep(1.5)
    # adb's kill only works over a live transport -- if the instance had
    # already gone offline/hung, fall back to killing the process we spawned.
    proc = _EMULATOR_PROCS.get(console_port)
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:                              # noqa: BLE001
            try:
                proc.kill()
            except Exception:                          # noqa: BLE001
                pass
    # last resort -- a stray instance from an earlier run/process we never
    # held a handle for. Find whatever is still listening on its console
    # port and kill it directly.
    try:
        out = subprocess.run(["lsof", "-ti", f"tcp:{console_port}"],
                             capture_output=True, timeout=10).stdout.decode()
        for pid in out.split():
            subprocess.run(["kill", "-9", pid], capture_output=True, timeout=10)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass


def _device_online(serial: str | None = None) -> bool:
    try:
        if serial:
            out = subprocess.run([*_adb_pfx(serial), "get-state"],
                                 capture_output=True, timeout=10).stdout.decode().strip()
            return out == "device"
        out = subprocess.run(["adb", "devices"], capture_output=True, timeout=10).stdout.decode()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
    return any(ln.split("\t")[-1].strip() == "device" for ln in out.splitlines()[1:] if ln.strip())


def _wait_boot(timeout_s: float, serial: str | None = None) -> bool:
    pfx = _adb_pfx(serial)
    subprocess.run([*pfx, "wait-for-device"], check=False)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            done = subprocess.run([*pfx, "shell", "getprop", "sys.boot_completed"],
                                  capture_output=True, timeout=10).stdout.decode().strip()
        except subprocess.TimeoutExpired:
            done = ""
        if done == "1":
            return True
        time.sleep(2)
    return False


def _install_and_launch(apk: str | None, serial: str | None = None) -> None:
    """Install the app if missing on the target device, then launch it."""
    pfx = _adb_pfx(serial)
    installed = subprocess.run([*pfx, "shell", "pm", "list", "packages", APP_PKG],
                               capture_output=True, timeout=15).stdout.decode()
    if APP_PKG not in installed:
        if not apk or not os.path.exists(apk):
            raise RuntimeError(f"{APP_PKG} not installed and no valid --apk given "
                               f"(try --apk {_DEFAULT_APK}).")
        print(f"[{serial or 'device'}] installing {apk} ...", flush=True)
        r = subprocess.run([*pfx, "install", "-r", "-g", apk], capture_output=True, timeout=600)
        if r.returncode != 0:
            raise RuntimeError(f"adb install failed ({serial or 'device'}): "
                               f"{r.stderr.decode()[:300]}")
    subprocess.run([*pfx, "shell", "monkey", "-p", APP_PKG, "-c",
                    "android.intent.category.LAUNCHER", "1"],
                   check=False, capture_output=True)
    time.sleep(5)


def boot_emulator_instance(avd: str, console_port: int, *, snapshot: str | None = None,
                           no_window: bool = False) -> subprocess.Popen:
    """Launch ONE read-only instance of `avd` on fixed ports. The instance's
    serial is f'emulator-{console_port}' (console port even, adb port = +1).
    -read-only lets several instances share one AVD image; -no-snapshot-save
    keeps exit from writing the shared images."""
    emu = _find_emulator_bin()
    if not emu:
        raise RuntimeError("no `emulator` binary found; set ANDROID_SDK_ROOT.")
    cmd = [emu, "-avd", avd, "-read-only", "-no-snapshot-save",
           "-ports", f"{console_port},{console_port + 1}", "-no-boot-anim",
           # 2nd+ instances routinely fail to inherit host DNS ("网络不翼而飞了" /
           # network unavailable in-app) -- pin public resolvers explicitly.
           "-dns-server", "8.8.8.8,8.8.4.4",
           # feature toggles:
           #  -Vulkan  set-detail pages are WebViews; the guest Vulkan path
           #           falls back to software SwiftShader on Apple Silicon and
           #           those pages render slow / blank -- force hardware GLES.
           #  -Wifi/-VirtioWifi  the emulated Wi-Fi (AndroidWifi + supplicant +
           #           DHCP) is what fails to come up on a 2nd concurrent
           #           instance ("can't establish wifi"). Disable it so the
           #           guest uses the always-up cellular data path for internet.
           "-feature", "-Vulkan,-Wifi,-VirtioWifi"]
    cmd += (["-snapshot", snapshot] if snapshot else ["-no-snapshot-load"])
    if no_window:
        # keep the GPU on the host even headless -- swiftshader would undo the
        # -Vulkan fix above.
        cmd += ["-no-window", "-gpu", "host"]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True)


def _wait_network(serial: str, timeout_s: float = 75) -> bool:
    """Poll until the instance can actually reach the internet. The emulated
    Wi-Fi is disabled at boot (-feature -Wifi), so connectivity rides the
    cellular data interface -- make sure mobile data is on, and give it time
    to attach (a 2nd concurrent instance is slow to register)."""
    pfx = _adb_pfx(serial)

    def sh(*a):
        subprocess.run([*pfx, "shell", *a], check=False, capture_output=True, timeout=10)

    sh("svc", "data", "enable")
    sh("svc", "wifi", "enable")            # harmless if Wi-Fi is gone
    deadline = time.time() + timeout_s
    nudged = False
    while time.time() < deadline:
        try:
            r = subprocess.run([*pfx, "shell", "ping", "-c", "1", "-W", "2", "8.8.8.8"],
                               capture_output=True, timeout=8).stdout.decode()
        except subprocess.TimeoutExpired:
            r = ""
        if " 0% packet loss" in r or "1 received" in r:
            return True
        if not nudged and time.time() > deadline - timeout_s * 0.6:
            # kick a stuck radio: airplane mode off/on, re-enable data
            for v in ("true", "false"):
                sh("cmd", "connectivity", "airplane-mode", v)
            sh("svc", "data", "enable")
            nudged = True
        time.sleep(3)
    return False


def ensure_emulator_instance(avd: str, apk: str | None, console_port: int, *,
                             snapshot: str | None = None, boot_timeout: float = 300,
                             no_window: bool = False, net_retries: int = 1) -> str:
    """Boot (if not already up) one emulator on `console_port`, wait for it +
    for real internet, install+launch the app, and return its adb serial.

    If two instances boot too close together one can come up with a dead NAT
    backend ("网络不翼而飞" in-app); on a no-network boot we kill and re-boot
    that instance up to `net_retries` times."""
    serial = f"emulator-{console_port}"
    if _device_online(serial):
        print(f"[{serial}] already online -- reusing", flush=True)
        _install_and_launch(apk, serial)
        return serial

    # Not "online" per adb -- could be nothing here, or a hung/offline instance
    # from an earlier attempt. Clear the port before booting a fresh instance
    # so a dead-but-still-running qemu process never gets left behind as an
    # orphan (see kill_emulator()).
    kill_emulator(console_port, serial)

    for attempt in range(net_retries + 1):
        print(f"[{serial}] booting @{avd} snapshot={snapshot or '-'} "
              f"(up to {boot_timeout:.0f}s){' [retry]' if attempt else ''} ...", flush=True)
        _EMULATOR_PROCS[console_port] = boot_emulator_instance(
            avd, console_port, snapshot=snapshot, no_window=no_window)
        if not _wait_boot(boot_timeout, serial):
            raise RuntimeError(f"{serial} didn't finish booting in {boot_timeout:.0f}s")
        time.sleep(3)
        subprocess.run([*_adb_pfx(serial), "shell", "input", "keyevent", "82"], check=False)
        if _wait_network(serial):
            print(f"[{serial}] booted, network up", flush=True)
            break
        if attempt < net_retries:
            print(f"[{serial}] booted but NO network -- killing and re-booting", flush=True)
            kill_emulator(console_port, serial)
            time.sleep(5)
        else:
            print(f"[{serial}] still NO network after {net_retries + 1} boots -- "
                  f"this worker will likely scrape nothing", flush=True)

    _install_and_launch(apk, serial)
    return serial


def ensure_emulator(avd: str | None, apk: str | None, boot_timeout: float = 240) -> None:
    """Single-emulator path for --boot-emulator: no-op if any device is
    connected, else cold-boot the first AVD, install the app, launch it.
    Navigating to the JP Union Arena card library is still manual."""
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

    _install_and_launch(apk, None)


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
    ap.add_argument("--serial", default=None,
                    help="adb serial to target, e.g. emulator-5554 (set by crawl_parallel.py)")
    ap.add_argument("--merge", action="store_true",
                    help="merge mode: fold --merge-inputs + --canonical into --canonical, then exit")
    ap.add_argument("--merge-inputs", nargs="*", default=[],
                    help="per-tab JSON files to merge into --canonical")
    ap.add_argument("--canonical", default="union_arena_boosters_all_sets.json",
                    help="canonical output file for --merge mode")
    ap.add_argument("--revisit", type=int, default=2,
                    help="extra passes over sets that failed the main pass (default 2)")
    ap.add_argument("--enumerate-only", action="store_true",
                    help="JOB 1: just enumerate each tab's strip and write "
                         "{tab: [codes]} to --enum-out, no scraping")
    ap.add_argument("--enum-out", default="out/sets_manifest.json",
                    help="manifest file for --enumerate-only (merged, atomic)")
    ap.add_argument("--sets", nargs="*", default=None,
                    help="JOB 2: scrape exactly these set codes on the single "
                         "tab given by --tabs (skips enumeration)")
    ap.add_argument("--manifest", default=None,
                    help="with --sets: manifest file giving the tab's FULL "
                         "strip list, for sweep + misclick context")
    args = ap.parse_args()

    if args.serial:
        global ADB
        ADB = ["adb", "-s", args.serial]

    if args.merge:
        before, after = merge_union(args.merge_inputs, args.canonical)
        print(f"merged {len(args.merge_inputs)} file(s) -> {args.canonical}: "
              f"{before} -> {after} rows", flush=True)
        return

    if args.boot_emulator:
        ensure_emulator(args.avd, args.apk)

    if args.enumerate_only:
        ensure_library_screen()
        try:
            with open(args.enum_out, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            manifest = {}
        for tab in args.tabs:
            codes = enumerate_tab(tab, args.out)
            if codes:
                manifest[tab] = codes
            print(f"[enum] {tab}: {len(codes)} sets", flush=True)
        _atomic_write_json(args.enum_out, manifest)
        print(f"wrote manifest {args.enum_out}", flush=True)
        return

    known_by_tab: dict[str, list[str]] = {}
    if args.manifest:
        try:
            with open(args.manifest, "r", encoding="utf-8") as f:
                known_by_tab = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    if args.sets is not None and len(args.tabs) != 1:
        ap.error("--sets requires exactly one --tabs value")

    all_rows, visited_codes = load_existing(args.out)
    start_sets = len(visited_codes)
    if visited_codes:
        print(f"resuming from {args.out}: {len(all_rows)} rows, "
              f"{len(visited_codes)} sets already done: {sorted(visited_codes)}", flush=True)

    ensure_library_screen()  # fail loudly now if the app isn't positioned right

    for tab in args.tabs:
        try:
            crawl_tab(tab, all_rows, visited_codes, args.out, revisit_rounds=args.revisit,
                      preset_codes=args.sets, known_codes=known_by_tab.get(tab))
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

    try:
        with open(args.out + ".missed.json", "r", encoding="utf-8") as f:
            miss = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        miss = {}
    miss = {t: r for t, r in miss.items() if r}
    if miss:
        total = sum(len(r) for r in miss.values())
        print(f"!! {total} set(s) still missing -> {args.out}.missed.json : {miss}", flush=True)


if __name__ == "__main__":
    main()
