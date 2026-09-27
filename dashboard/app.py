"""Run the FastAPI dashboard and its bundled Vue frontend in one process."""
import argparse
import secrets
import sys
from pathlib import Path

import uvicorn

WORKSPACE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE))

from dashboard.routes import create_app
from dashboard.services.review import Review, workflow_guide, write_json
from reconciliation.intake.workspace import SourceSelection


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
    app = create_app(review, secrets.token_urlsafe(32), sources)
    display_host = "127.0.0.1" if args.host == "0.0.0.0" else args.host
    print(f"Dashboard: http://{display_host}:{args.port}", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, workers=1, access_log=False)


if __name__ == "__main__":
    main()
