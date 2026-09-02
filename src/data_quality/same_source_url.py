"""Pure URL normalization shared by same-source deduplication components."""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def canonicalize_computrabajo_url(url: str) -> str:
    """Return the Computrabajo group identity by removing the URL fragment.

    Args:
        url: Raw Computrabajo URL.

    Returns:
        The URL without its fragment, or the original value if parsing fails.
    """
    if not isinstance(url, str) or not url.strip():
        return url if isinstance(url, str) else ""
    try:
        parts = urlsplit(url)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))
    except (ValueError, AttributeError):
        return url
