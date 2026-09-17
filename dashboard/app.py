"""Local duplicate-review dashboard. Run with Python; no web framework required."""
import argparse
import secrets
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE))

from reconciliation.source_selection import SourceSelection
from dashboard.routes import handler_for
from dashboard.review import Review, workflow_guide, write_json


def main():
    """Start the local dashboard server."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1",
                        help="interface to bind (use 0.0.0.0 in a container)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--manifest", type=Path, default=WORKSPACE / "duplicate-manifest.json")
    parser.add_argument("--data", type=Path, default=Path(__file__).parent / ".data")
    args = parser.parse_args()
    sources = SourceSelection(WORKSPACE, args.data)
    manifest = sources.active_manifest(args.manifest) if args.manifest == WORKSPACE / "duplicate-manifest.json" else args.manifest
    data = manifest.parent / "dashboard-data" if manifest != args.manifest else args.data
    review = Review(manifest, data) if manifest.is_file() else None
    server = ThreadingHTTPServer((args.host, args.port), handler_for(review, secrets.token_urlsafe(32), sources))
    display_host = "127.0.0.1" if args.host == "0.0.0.0" else args.host
    print(f"Dashboard: http://{display_host}:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
