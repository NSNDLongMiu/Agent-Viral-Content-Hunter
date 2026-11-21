"""Deterministic URL and title normalization for collected items."""

import re
from ipaddress import IPv6Address, ip_address
from unicodedata import normalize
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import TypeAdapter, ValidationError

from hunter.models.common import PublicUrl

_PUBLIC_URL = TypeAdapter(PublicUrl)
_TRACKING_PARAMS = {"fbclid", "gclid", "igshid", "si", "ref", "ref_src", "mc_cid", "mc_eid"}
_HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0002fa1f\U00030000-\U000323af]")
_VIETNAMESE = re.compile(r"[đăơưảạằắẳẵặầấẩẫậẻẽẹềếểễệỉĩịỏọồốổỗộờớởỡợủũụừứửữựỳỷỹỵ]")
_WORD = re.compile(r"[^\W_]+")
_STOP_WORDS = {"a", "an", "and", "of", "or", "the", "to"}


def canonical_url(url: str) -> str:
    try:
        parts = urlsplit(str(_PUBLIC_URL.validate_python(url)))
    except ValidationError:
        raise ValueError("A public HTTP(S) URL without embedded credentials is required") from None

    host = (parts.hostname or "").lower().rstrip(".")
    try:
        address = ip_address(host)
    except ValueError:
        if "." not in host or host.endswith((".localhost", ".local")):
            raise ValueError("Local hostnames are not allowed") from None
    else:
        if isinstance(address, IPv6Address) and address.ipv4_mapped is not None:
            address = address.ipv4_mapped
        if not address.is_global or address.is_multicast:
            raise ValueError("Non-public IP addresses are not allowed")

    query = [
        (name, value) for name, value in parse_qsl(parts.query, keep_blank_values=True, errors="surrogateescape")
        if not name.lower().startswith("utm_") and name.lower() not in _TRACKING_PARAMS
    ]
    # HttpUrl already removes the scheme's default port and formats IPv6 authorities.
    return urlunsplit((
        parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/") or "/",
        urlencode(sorted(query), errors="surrogateescape"), "",
    ))


def normalize_title(text: str) -> str:
    return " ".join(normalize("NFKC", text).split())


def _words(text: str, *, split_han: bool = False) -> list[str]:
    text = normalize_title(text).casefold()
    if split_han:
        # Han text often has no word separators. Split it for query phrase matching.
        text = _HAN.sub(r" \g<0> ", text)
    return _WORD.findall(text)


def title_tokens(text: str) -> list[str]:
    return [word for word in _words(text) if word not in _STOP_WORDS]


def detect_language(text: str) -> str:
    text = normalize_title(text).casefold()
    if _HAN.search(text):
        return "zh"
    if _VIETNAMESE.search(text):
        return "vi"
    letters = [char for char in text if char.isalpha()]
    return "en" if letters and all(char.isascii() for char in letters) else "und"
