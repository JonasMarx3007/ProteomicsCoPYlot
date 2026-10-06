"""Content-Disposition for downloads whose names can carry any character.

Download names include dataset, package and condition names a user typed. Put
into `filename="..."` as they are, a quote or a line break breaks the header and
anything outside Latin-1 cannot be sent at all. The plain `filename` gets an
ASCII stand-in; the real name travels in `filename*` (RFC 6266 / RFC 5987),
which every current browser prefers.
"""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import quote

_UNSAFE_ASCII = re.compile(r'[^A-Za-z0-9 ._()\[\]+,=@-]+')


def attachment_disposition(filename: str, fallback: str = "download") -> str:
    name = re.sub(r"[\r\n\t]+", " ", str(filename or "")).strip() or fallback
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    ascii_name = _UNSAFE_ASCII.sub("_", ascii_name).strip(" _")
    stem, dot, suffix = ascii_name.rpartition(".")
    if not ascii_name or (dot and not stem.strip(" _.")):
        ascii_name = fallback + (f".{suffix}" if dot and suffix else "")
    header = f'attachment; filename="{ascii_name}"'
    if ascii_name != name:
        header += f"; filename*=UTF-8''{quote(name, safe='')}"
    return header
