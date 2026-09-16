"""Run a fixed, image-only Terra extraction benchmark through ChatGPT login."""
import hashlib
import json
import time
from pathlib import Path

from PIL import Image, ImageOps
from codex_reviewer import CodexReviewer, object_schema, TEXT, TEXTS

WORK = Path(__file__).parent / "benchmarks" / "terra-benchmark"
SELECTED = [1, 2, 3, 4, 5, 8, 11, 12, 13, 15, 23, 24, 26, 28, 30, 32, 33, 37, 39, 41]
NULLABLE = {"type": ["string", "null"]}
FIELDS = ["supplier", "date", "invoice_number", "currency", "subtotal", "tax", "total"]
ITEM = object_schema({"id": TEXT, "document_type": TEXT,
    **{field: NULLABLE for field in FIELDS}, "other_references": TEXTS, "limitations": TEXTS})
SCHEMA = object_schema({"documents": {"type": "array", "items": ITEM}})
PROMPT = """Extract the attached independent accounting pictures, one result per image.
Use only visible image evidence, never filenames or external knowledge. Return null for
missing/unreadable fields. Supplier means seller/issuer, not customer or reimbursement
claimant; null when no seller/issuer is identifiable. Date is document issue/payment date
in YYYY-MM-DD only when fully shown; null for multiple dates without one document date.
Invoice_number is an explicitly labelled invoice number only; put receipt, order, booking,
tracking and payment identifiers in other_references. Currency is ISO code only when
explicitly shown (RM means MYR); do not assume currency from location or merchant.
Amounts are decimal strings. Subtotal and tax must be explicitly shown, not calculated;
total is the final document amount. Do not sum lists or choose an individual instalment
when no overall total is printed. For tables/screenshots without invoice fields, use null
and describe limitations. Never treat a map, shipping label or QR code as proof of payment.
"""


def save(name, value):
    # Retain readable benchmark evidence and failures in the workspace.
    (WORK / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    # Freeze source hashes and use anonymous image names to prevent filename leakage.
    inventory = json.loads((WORK / "inventory.json").read_text(encoding="utf-8"))
    samples = []
    for number in SELECTED:
        source = Path(inventory[number - 1])
        target = WORK / f"sample-{number:02}.png"
        with Image.open(source) as original:
            picture = ImageOps.exif_transpose(original).convert("RGB")
            picture.save(target)
        samples.append({"id": f"sample-{number:02}", "source": str(source),
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "image": str(target.resolve()), "size": picture.size})
    assert len({s['sha256'] for s in samples}) == 20
    save("samples.json", samples)
    reviewer = CodexReviewer(WORK, model="gpt-5.6-terra", reasoning="low", max_calls=4, timeout=300)
    results = []
    for offset in range(0, len(samples), 5):
        # Separate batches keep context bounded; incomplete calls remain unresolved.
        batch = samples[offset:offset + 5]
        started = time.monotonic()
        record = {"ids": [s["id"] for s in batch], "status": "unresolved"}
        try:
            prompt = PROMPT + "\nImage order: " + ", ".join(record["ids"])
            response = reviewer.ask(prompt, SCHEMA, [s["image"] for s in batch])
            if [r["id"] for r in response["documents"]] != record["ids"]:
                reviewer.invalidate()
                raise ValueError("Response IDs/coverage differ from attached images")
            record.update(status="extracted_unverified", response=response)
        except Exception as error:
            record["error"] = f"{type(error).__name__}: {error}"
        record.update(seconds=round(time.monotonic() - started, 2),
                      evidence=str(reviewer.last_result.parent))
        results.append(record)
        save("results.json", results)
        print(record["ids"], record["status"], record["seconds"], flush=True)


if __name__ == "__main__":
    main()
