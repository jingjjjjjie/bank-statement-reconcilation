"""Content hashes that bind saved decisions to the exact evidence they were made on."""

import hashlib
import json


def revision(value):
    """Bind saved decisions to the exact evidence and ledger version."""
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
