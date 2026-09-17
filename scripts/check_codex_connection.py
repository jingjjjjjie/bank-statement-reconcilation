"""Explicit live smoke test: one synthetic receipt, no customer documents."""
import json
import argparse
from pathlib import Path
from reconciliation.paths import WORKSPACE

from PIL import Image, ImageDraw
from reconciliation.codex_reviewer import CodexReviewer, EXTRACTION


def main():
    # Verify subscription-authenticated image input and structured output together.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model")
    parser.add_argument("--reasoning", default="default")
    args = parser.parse_args()
    work = (WORKSPACE / "review") / "connection-test"
    work.mkdir(parents=True, exist_ok=True)
    image = work / "synthetic-receipt.png"
    picture = Image.new("RGB", (1000, 500), "white")
    ImageDraw.Draw(picture).text((40, 40), "SYNTHETIC TEST RECEIPT\nReference: TEST-001\nTotal: MYR 123.45", fill="black", font_size=38)
    picture.save(image)
    result = CodexReviewer(work, model=args.model, reasoning=args.reasoning, max_calls=1).ask(
        "Extract this synthetic receipt image. This is a connection test, not real accounting evidence.",
        EXTRACTION, [image])
    assert result["readable"], result
    assert "123.45" in json.dumps(result), result
    print("PASS: codex exec read the image and returned schema-validated JSON through ChatGPT login.")


if __name__ == "__main__":
    main()
