"""Test package. The bundled Overture extract (server/data/overture_ch.json) is switched off for tests so
that results never depend on real data; tests that need it point overture.DATA_PATH at their own file."""

import os

os.environ.setdefault("OVERTURE_DATA_PATH", os.path.join(os.path.dirname(__file__), "no-overture-data.json"))
