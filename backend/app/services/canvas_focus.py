"""Resolve feature scope before a canvas is changed; never substitute data levels."""
import json
import re

from app.schemas.assistant import CanvasFocusRequest, ContextMode
from app.services.functions import select_matrix


class CanvasIdentifierCandidate(ValueError):
    def __init__(self, query: str):
        super().__init__(f"Please confirm the exact uploaded identifier: {query}")
        self.query = query


def resolve_canvas_focus(request: CanvasFocusRequest, mode: ContextMode | None, *, message: str = "") -> dict:
    if request.allSites and request.kind != "phospho":
        raise ValueError("All-sites requests require phosphosite data.")
    context = dict(mode or {})
    if context.get("tiles") and context.get("kind") != request.kind:
        raise ValueError("The canvas contains another data level. Use an empty canvas at the requested level; existing tiles were not changed.")
    try:
        _, frame, metadata = select_matrix(request.kind, "data")
    except ValueError as exc:
        raise ValueError("The requested data level is not available. No other level will be substituted.") from exc
    key = {"protein": "ProteinNames", "phospho": "PTM_Collapse_key", "phosprot": "Phosphoprotein"}[request.kind]
    if key not in frame:
        raise ValueError("The requested data level has no usable feature identifiers.")
    query = request.query.strip().casefold()
    if not query:
        raise ValueError("Please provide an exact feature identifier.")
    columns = [key] if request.kind == "phospho" and not request.allSites else [
        *([] if request.allSites else [key]), "ProteinNames", "Protein_group", "GeneNames", "Gene_group", "ProteinAccessions",
    ]
    matches = []
    for _, row in frame.iterrows():
        matched = any(column in frame and isinstance(row[column], str) and (
            row[column].strip().casefold() == query or
            (column != "PTM_Collapse_key" and query in [token.strip().casefold() for token in row[column].split(";")])
        ) for column in columns)
        if matched and isinstance(row[key], str) and row[key] not in matches:
            matches.append(row[key])
    if not matches:
        candidate = request.query.strip().rstrip(".,!?")
        quoted = any(f"{left}{request.query.strip()}{right}".casefold() in message.casefold() for left, right in
                     [('"', '"'), ("'", "'"), ("`", "`"), ("“", "”"), ("‘", "’")])
        if (candidate and candidate != request.query.strip() and not quoted
                and re.search(r"(?<![\w.])" + re.escape(candidate) + r"(?!\w)", message, re.I)):
            resolve_canvas_focus(request.model_copy(update={"query": candidate}), mode)
            raise CanvasIdentifierCandidate(candidate)
        raise ValueError("No exact match exists at the requested data level. Please provide its uploaded identifier.")
    if len(matches) > 1 and not request.allSites:
        choices = ", ".join(json.dumps(match, ensure_ascii=False) for match in matches[:5])
        more = " Showing the first 5; narrow the request if needed." if len(matches) > 5 else ""
        raise ValueError(f"The identifier matches multiple features at this level ({len(matches)} matches): {choices}. "
                         f"Please choose an exact uploaded feature.{more} No canvas changes were made.")
    if len(matches) > 20:
        raise ValueError("More than 20 sites match. Please narrow the request before creating individual site plots.")
    available = metadata["condition"].dropna().astype(str).drop_duplicates().tolist()
    conditions = request.conditions
    if not conditions:
        tiles = context.get("tileEvidence", [])
        for tile in sorted(tiles, key=lambda item: item.get("id") != context.get("linkedVolcanoId")):
            settings = tile.get("settings", {})
            pair = [settings.get("condition1"), settings.get("condition2")]
            if tile.get("type") in {"volcano", "volcanoControl"} and len(set(pair)) == 2 and all(item in available for item in pair):
                conditions = pair
                break
        if not conditions and len(available) == 2:
            conditions = available
    if len(conditions) != 2 or len(set(conditions)) != 2 or any(item not in available for item in conditions):
        raise ValueError("Please specify two distinct conditions for the volcano comparison. Available: " + ", ".join(available))
    return {"kind": request.kind, "features": matches, "conditions": conditions, "allSites": request.allSites}


_FEATURE_KEYS = {"protein": "ProteinNames", "phospho": "PTM_Collapse_key", "phosprot": "Phosphoprotein"}
_PARENT_COLUMNS = ("ProteinNames", "Protein_group", "GeneNames", "Gene_group", "ProteinAccessions")


def feature_candidates(kind: str, *, prefix: str = "", parent: str = "") -> list[str]:
    """Uploaded feature identifiers at one data level, by prefix or by parent protein.

    Read from the data, not from the select's option list: the list the browser
    advertises is capped at 40 and filtered by the words of the question, so it
    can miss K70-K79 when the question says K7. Parent matching is exact per
    ';'-separated token, like the canvas focus -- "P1" never matches "P10".
    """
    key = _FEATURE_KEYS.get(kind)
    if key is None:
        raise ValueError("Choose a protein, phosphosite or phosphoprotein data level first.")
    try:
        _, frame, _ = select_matrix(kind, "data")
    except ValueError as exc:
        raise ValueError("The requested data level is not available. No other level will be substituted.") from exc
    if key not in frame:
        raise ValueError("The requested data level has no usable feature identifiers.")
    found: list[str] = []
    seen: set[str] = set()
    wanted_prefix = prefix.strip().casefold()
    wanted_parent = parent.strip().casefold()
    for _, row in frame.iterrows():
        feature = row[key]
        if not isinstance(feature, str) or feature in seen:
            continue
        if wanted_prefix and feature.strip().casefold().startswith(wanted_prefix):
            found.append(feature)
            seen.add(feature)
        elif wanted_parent and any(
            column in frame and isinstance(row[column], str)
            and wanted_parent in [token.strip().casefold() for token in row[column].split(";")]
            for column in _PARENT_COLUMNS if column != key
        ):
            found.append(feature)
            seen.add(feature)
    return found
