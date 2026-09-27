"""Fixture: build assembled receipt records for multi-page documents."""


def piece(units, total="45.00"):
    """Build a receipt spanning named source units with one printed total."""
    return {
        "location": "pages " + ", ".join(map(str, units)),
        "document_type": "receipt",
        "invoice_numbers": ["INV-1"],
        "brief_description": "Supplies",
        "total": total,
        "currency": "MYR",
        "limitations": [],
        "source_units": units,
    }
