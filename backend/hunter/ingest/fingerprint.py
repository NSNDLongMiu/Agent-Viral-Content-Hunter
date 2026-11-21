"""Exact deduplication keys stored in the foundation fingerprint table."""

from hashlib import sha256

from hunter.models import RawItem

from .normalize import title_tokens


def exact_fingerprints(item: RawItem, url: str) -> list[tuple[str, str]]:
    """Hash the canonical URL and any usable identifiers on a normalized item."""
    keys = [("url", url)]
    if item.external_id is not None:
        keys.append(("external", f"{item.source_id}|{item.external_id}"))
    if item.title is not None and len(title_tokens(item.title)) >= 3:
        keys.append(("title", item.title.casefold()))
    return [(kind, sha256(value.encode("utf-8")).hexdigest()) for kind, value in keys]
