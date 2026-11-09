# Overture Maps attribution

`overture_ch.json` is an extract of the **places** theme of the [Overture Maps Foundation](https://overturemaps.org)
dataset (Swiss hospitality venues that list a website), produced by `scripts/import_overture.py`.
The release and generation time are recorded in the file's header (`release`, `generatedAt`).

- **Data:** © Overture Maps Foundation. The places theme is published under the
  [Community Data License Agreement – Permissive, Version 2.0 (CDLA-Permissive-2.0)](https://cdla.dev/permissive-2-0/).
  Overture's places combine several contributors' data (for example Meta, Microsoft and others, listed per
  record in the source `sources` field, which this extract does not keep). Check the current licence terms at
  <https://docs.overturemaps.org/> before redistributing the file.
- **How the app uses it:** only to fill in a missing website (and phone number) for a venue that was found through
  OpenStreetMap, when the same venue (similar name, within ~75 m) is in this extract. Such venues are marked
  `websiteSource: "overture"` and the venue panel says so.
- **Refreshing:** `pip install pyarrow && python3 scripts/import_overture.py` downloads the latest release
  (a few hundred MB of range requests, not the whole multi-GB dataset) and rewrites the file.
- OpenStreetMap data is © OpenStreetMap contributors (ODbL).
