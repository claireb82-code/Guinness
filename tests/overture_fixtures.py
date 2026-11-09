"""A tiny fake of Overture's S3 bucket (list + Range requests) and Parquet files in the real places schema."""

import http.server
import re
import threading
import urllib.parse

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:  # the importer tests skip themselves
    pa = pq = None

RELEASE = "2026-10-21.0"
KEY = f"release/{RELEASE}/theme=places/type=place/part-00000.zstd.parquet"


def place(id, name, hierarchy, lat, lng, country="CH", websites=None, phones=None, confidence=0.9, status="open"):
    return {
        "id": id,
        "names": {"primary": name},
        "taxonomy": {"primary": hierarchy[-1], "hierarchy": hierarchy, "alternates": None},
        "websites": websites,
        "phones": phones,
        "addresses": [{"freeform": "Bahnhofstrasse 1", "locality": "Zürich", "postcode": "8001", "region": None, "country": country}],
        "confidence": confidence,
        "operating_status": status,
        "bbox": {"xmin": lng, "xmax": lng, "ymin": lat, "ymax": lat},
    }


PUB = ["food_and_drink", "alcoholic_beverage_venue", "bar", "pub"]
IRISH_PUB = PUB + ["irish_pub"]
BAR = ["food_and_drink", "alcoholic_beverage_venue", "bar"]
RESTAURANT = ["food_and_drink", "restaurant", "french_restaurant"]
HOTEL = ["lodging", "hotel"]
DENTIST = ["health_care", "dentist"]


def schema():
    return pa.schema(
        [
            ("id", pa.string()),
            ("names", pa.struct([("primary", pa.string())])),
            ("taxonomy", pa.struct([("primary", pa.string()), ("hierarchy", pa.list_(pa.string())), ("alternates", pa.list_(pa.string()))])),
            ("websites", pa.list_(pa.string())),
            ("phones", pa.list_(pa.string())),
            ("addresses", pa.list_(pa.struct([("freeform", pa.string()), ("locality", pa.string()), ("postcode", pa.string()), ("region", pa.string()), ("country", pa.string())]))),
            ("confidence", pa.float64()),
            ("operating_status", pa.string()),
            ("bbox", pa.struct([("xmin", pa.float64()), ("xmax", pa.float64()), ("ymin", pa.float64()), ("ymax", pa.float64())])),
        ]
    )


def write_parquet(path, row_groups, statistics=True):
    """``row_groups``: list of lists of place() dicts; each inner list becomes one Parquet row group."""
    writer = pq.ParquetWriter(path, schema(), write_statistics=statistics)
    for rows in row_groups:
        writer.write_table(pa.Table.from_pylist(rows, schema=schema()))
    writer.close()


class FakeBucket:
    """Serves ``objects`` (key -> bytes) like S3: ?list-type=2 listings and Range GETs."""

    def __init__(self, objects):
        self.objects, self.failures, self.requests = objects, 0, []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                parts = urllib.parse.urlsplit(self.path)
                outer.requests.append(self.path)
                if outer.failures > 0:
                    outer.failures -= 1
                    self.send_response(500)
                    self.end_headers()
                    return
                query = urllib.parse.parse_qs(parts.query)
                if "list-type" in query:
                    return self.listing(query)
                data = outer.objects.get(urllib.parse.unquote(parts.path.lstrip("/")))
                if data is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                rng = self.headers.get("Range")
                if rng:
                    a, b = re.match(r"bytes=(\d+)-(\d+)", rng).groups()
                    body, status = data[int(a) : int(b) + 1], 206
                else:
                    body, status = data, 200
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def listing(self, query):
                prefix = query.get("prefix", [""])[0]
                delimiter = query.get("delimiter", [None])[0]
                xml = '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
                if delimiter:
                    seen = sorted({k[len(prefix):].split(delimiter)[0] for k in outer.objects if k.startswith(prefix)})
                    xml += "".join(f"<CommonPrefixes><Prefix>{prefix}{p}{delimiter}</Prefix></CommonPrefixes>" for p in seen)
                else:
                    xml += "".join(
                        f"<Contents><Key>{k}</Key><Size>{len(v)}</Size></Contents>" for k, v in sorted(outer.objects.items()) if k.startswith(prefix)
                    )
                xml += "</ListBucketResult>"
                body = xml.encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.02), daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
