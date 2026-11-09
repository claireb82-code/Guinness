"""Test package. The bundled Overture extract (server/data/overture_ch.json) is switched off for tests so
that results never depend on real data; tests that need it point overture.DATA_PATH at their own file."""

import os

os.environ.setdefault("OVERTURE_DATA_PATH", os.path.join(os.path.dirname(__file__), "no-overture-data.json"))

# Overpass: no shared cache between tests, no waiting between retry passes (tests that need them set their own).
os.environ.setdefault("OVERPASS_CACHE_SECONDS", "0")
os.environ.setdefault("OVERPASS_RETRY_PAUSE_SECONDS", "0")
