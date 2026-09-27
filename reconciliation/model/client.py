"""The one interface a model backend must provide to plug into the workflow.

Only `ask` is required. Parallel runs, cancellation fences and cache invalidation
are optional; the helpers below give safe defaults so simple clients (for example
test fakes) work unchanged.
"""

from contextlib import nullcontext
from typing import Protocol, runtime_checkable

# Largest single request the workflow sends: images attached and prompt characters.
MAX_IMAGES, MAX_PROMPT = 40, 100000


@runtime_checkable
class ModelClient(Protocol):
    """Answer one prompt with JSON matching `schema`, optionally reading images."""

    model: str | None

    def ask(self, prompt: str, schema: dict, images=()) -> dict:
        """Return a schema-valid result or raise; never return partial output."""


def supports_parallel(client):
    """Parallel workers need `fork()` so each call keeps its own stage settings."""
    return hasattr(client, "fork")


def worker_for(client, parallel):
    """Return an isolated copy for a parallel call, or the client itself."""
    return client.fork() if parallel else client


def acceptance(client):
    """Return the context that fences checkpoint writes against cancellation."""
    return getattr(client, "acceptance", nullcontext)


def invalidate(client):
    """Drop the client's cached last answer after workflow validation rejects it."""
    if hasattr(client, "invalidate"):
        client.invalidate()
