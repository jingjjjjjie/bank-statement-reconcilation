"""Explicit live smoke test: one synthetic receipt, no customer documents."""
import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw

from reconciliation.core.paths import WORKSPACE
from reconciliation.core.prompts import load_prompt
from reconciliation.extraction.pieces import EXTRACTION
from reconciliation.model.codex import CodexReviewer


def main():
    # Verify subscription-authenticated image input and structured output together.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model")
    parser.add_argument("--reasoning", default="default")
    parser.add_argument("--pdf", action="store_true", help="Render a synthetic PDF through the app's extraction path")
    args = parser.parse_args()
    work = (WORKSPACE / "review") / ("pdf-connection-test" if args.pdf else "connection-test")
    work.mkdir(parents=True, exist_ok=True)
    image = work / "synthetic-receipt.png"
    picture = Image.new("RGB", (1000, 500), "white")
    ImageDraw.Draw(picture).text((40, 40), "SYNTHETIC TEST RECEIPT\nReference: TEST-001\nTotal: MYR 123.45", fill="black", font_size=38)
    picture.save(image)
    if args.pdf:
        from reconciliation.core.settings import load_config
        from reconciliation.extraction.reader import extract
        pdf = work / "synthetic-receipt.pdf"
        picture.save(pdf, "PDF")
        units = extract(pdf, work / "rendered", load_config())
        assert len(units) == 1 and not units[0]["blocked"] and units[0]["image"], units
        image = Path(units[0]["image"])
    reviewer = CodexReviewer(work, model=args.model, reasoning=args.reasoning, max_calls=1)
    reviewer.stage = "pdf_connection_test" if args.pdf else "image_connection_test"
    result = reviewer.ask(
        load_prompt("shared/connection_test"),
        EXTRACTION, [image])
    assert result["readable"], result
    assert "123.45" in json.dumps(result), result
    print("PASS: codex exec read the " + ("rendered PDF" if args.pdf else "image")
          + " and returned schema-validated JSON through ChatGPT login.")


if __name__ == "__main__":
    main()
