# geekstack-automations -- job runner
#
#   make help            list targets
#
# JHS (jihuanshe) price scrape -- needs the Pixel_3a_API_34 emulator with the
# `jp_library` snapshot sitting on the logged-in card-library screen.
#
#   make jhs-daily       full re-scrape -> dated snapshot -> merge canonical.
#                        Auto-retries stragglers (up to RETRIES passes, default 2)
#                        with no intervention; only merges on a clean finish.
#   make jhs-retry       re-scrape only the sets that failed in the latest run
#   make jhs-resume      continue an interrupted --daily run
#   make jhs-sets SETS="UA56BT UA55BT" CAT=booster    re-scrape exact set codes
#   make jhs-incremental new set codes only, no price refresh
#   make jhs-coverage    print the latest run's missing / still-missing lists
#   make jhs-refresh-apk bake a new jihuanshe APK into the jp_library snapshot
#                        (needed whenever the app nags an in-app update --
#                        put the new file at jihuanshe/JHS.apk, or pass APK=path)
#
#   tuning (any jhs-* target):  WORKERS=3  CHUNK=4  RETRIES=3
#     WORKERS  concurrent emulators (default 2; 3 needs ~6 GB free RAM)
#     CHUNK    sets per worker assignment (default 8; try 4-5 with WORKERS=3)
#     RETRIES  auto-retry passes after the main run (default 2)
#
# Price pipeline (YYT + JHS -> normalise -> MongoDB price_jhs / price_yyt)
#
#   make prices          full chain: YYT scrape + JHS --daily + normalise + upload
#   make prices-resume   resume an interrupted JHS step, then normalise + upload
#   make prices-nodb     scrape + normalise, skip the DB upload
#   make prices-refresh  re-normalise + re-upload from data already on disk
#   make yyt             YYT scrape only (writes dated backup, no legacy cardprices_yyt write)

PY      := $(CURDIR)/venv/bin/python3
GAME    ?= union_arena
CAT     ?=
SETS    ?=
WORKERS ?=
CHUNK   ?=
RETRIES ?=
APK     ?=
RUNS    := $(CURDIR)/jihuanshe/runs/$(GAME)

# optional passthroughs: `make jhs-daily WORKERS=3 CHUNK=4`, `make jhs-retry CAT=promo`
_workers = $(if $(WORKERS),--workers $(WORKERS),)
_chunk   = $(if $(CHUNK),--chunk $(CHUNK),)
_retries = $(if $(RETRIES),--retries $(RETRIES),)
_cat     = $(if $(CAT),--categories $(CAT),)
_tune    = $(_workers) $(_chunk) $(_retries)

.PHONY: help \
        jhs-daily jhs-retry jhs-resume jhs-sets jhs-incremental jhs-coverage jhs-refresh-apk \
        prices prices-resume prices-nodb prices-refresh yyt

help:
	@awk '/^#/{sub(/^# ?/,"");print;next}{exit}' $(firstword $(MAKEFILE_LIST))

# ----------------------------------------------------------------------------- #
# JHS
# ----------------------------------------------------------------------------- #
jhs-daily:
	$(PY) jihuanshe/main.py $(GAME) --daily $(_tune)

jhs-retry:
	$(PY) jihuanshe/main.py $(GAME) --retry $(_cat) $(_tune)

jhs-resume:
	$(PY) jihuanshe/main.py $(GAME) --resume $(_tune)

jhs-sets:
	@test -n "$(SETS)" || { echo 'usage: make jhs-sets SETS="CODE CODE" CAT=<category>'; exit 2; }
	@test -n "$(CAT)"  || { echo 'usage: make jhs-sets SETS="CODE CODE" CAT=<category>'; exit 2; }
	$(PY) jihuanshe/main.py $(GAME) --sets $(SETS) --categories $(CAT) $(_tune)

jhs-incremental:
	$(PY) jihuanshe/main.py $(GAME) $(_cat) $(_tune)

jhs-coverage:
	@d=$$(ls -1d $(RUNS)/20* 2>/dev/null | tail -1); \
	 test -n "$$d" || { echo "no runs under $(RUNS)/"; exit 1; }; \
	 echo "latest run: $$d"; \
	 if [ -f "$$d/missed.json" ]; then echo "-- still missing after revisits --"; cat "$$d/missed.json"; echo; fi; \
	 if [ -f "$$d/coverage_missing.txt" ]; then \
	   echo "-- coverage_missing.txt ($$(wc -l < "$$d/coverage_missing.txt" | tr -d ' ') rows) --"; \
	   head -40 "$$d/coverage_missing.txt"; \
	 fi

jhs-refresh-apk:
	$(PY) jihuanshe/refresh_apk_snapshot.py $(if $(APK),--apk $(APK),) --force-kill

# ----------------------------------------------------------------------------- #
# price pipeline
# ----------------------------------------------------------------------------- #
prices:
	$(PY) pricescraper/run.py

prices-resume:
	$(PY) pricescraper/run.py --jhs-args="$(GAME) --resume"

prices-nodb:
	$(PY) pricescraper/run.py --skip upload

prices-refresh:
	$(PY) pricescraper/run.py --only normalise upload

yyt:
	$(PY) pricescraper/run.py --only yyt
