"""Fetch, log and rebuild CoPYlot's bundled reference databases.

Three commands, run from the repository root:

    python tools/build_reference_databases.py fetch     # download the upstream releases into data/reference-sources/
    python tools/build_reference_databases.py build     # rebuild data/db/* from those sources, offline
    python tools/build_reference_databases.py verify    # check every source and output against the manifest

`fetch` is the only step that uses the network. It stores upstream files
(gzipped) under `data/reference-sources/`, except unchanged FASTAs stored once
under `data/db/`, and records in `data/reference-sources/manifest.json`
where it came from, which release it is, when it was retrieved, its SHA-256 and
its licence. `build` reads only those files and is deterministic, so anyone
with the repository can regenerate the runtime databases and get the same
bytes; `verify` proves it (and runs in the test suite).

What is built, and from what:

* `BioNamesDB.txt.gz` -- the identifier table behind the ID translator. One row
  per UniProt entry of the human (UP000005640) and mouse (UP000000589)
  reference proteomes, joined to HGNC (human) or MGI (mouse) by the UniProt
  cross-reference, falling back to the gene symbol; plus one row per HGNC/MGI
  gene without a protein entry, so non-coding genes still translate.
* `all_go_terms_genes.csv` (human) and `all_go_terms_genes_mouse.csv` -- Gene
  Ontology term -> gene symbols, from the GO Consortium release's annotation
  files and `go-basic.obo`, with annotations propagated to every ancestor over
  `is_a` and `part_of` (a gene annotated to "nucleus" is counted for
  "intracellular anatomical structure" too). Only protein / protein-coding
  gene objects are used (no RNAs or complexes); NOT-qualified annotations are
  excluded; every evidence code, including electronic (IEA), is kept. A
  protein without a gene symbol in the annotation file is written under the
  symbol the identifier table knows for its accession, or left out.
* `UP000005640_9606.fasta.gz`, `UP000000589_10090.fasta.gz` -- the reference
  proteome FASTA files for sequence coverage, as published (canonical entries).
* `UP000005640_9606_additional.fasta.gz`, `UP000000589_10090_additional.fasta.gz`
  -- the same release's "additional" files (isoforms and the non-canonical
  TrEMBL entries of the proteome), consulted when a search database entry is
  not among the canonical sequences (2026-10-14: A0A140T8R7, a mouse Rcor1
  isoform). They are large (41 MB / 10 MB), so they are stored once, under
  `data/db/` only, and logged in the manifest like every other source.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import io
import json
import re
import shutil
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "db"
SOURCES = ROOT / "data" / "reference-sources"  # not bundled: the executables and the image ship data/db only
MANIFEST = SOURCES / "manifest.json"
BUILD_LOG = DB / "BUILD.log"

UNIPROT_FTP = "https://ftp.uniprot.org/pub/databases/uniprot/current_release"
UNIPROT_FIELDS = ("accession,id,reviewed,protein_name,gene_primary,gene_names,organism_id,length,"
                  "xref_hgnc,xref_mgi,xref_ensembl,xref_geneid,xref_refseq")
GO_RELEASE = "https://current.geneontology.org"

LICENCES = {
    "uniprot": {"licence": "CC BY 4.0", "licence_url": "https://www.uniprot.org/help/license",
                "citation": "The UniProt Consortium. UniProt: the Universal Protein Knowledgebase. Nucleic Acids Res."},
    "hgnc": {"licence": "CC0 1.0", "licence_url": "https://www.genenames.org/about/license/",
             "citation": "HGNC Database, HUGO Gene Nomenclature Committee (HGNC), EMBL-EBI. www.genenames.org"},
    "mgi": {"licence": "CC BY 4.0", "licence_url": "https://www.informatics.jax.org/mgihome/other/copyright.shtml",
            "citation": "Mouse Genome Informatics (MGI), The Jackson Laboratory. www.informatics.jax.org"},
    "go": {"licence": "CC BY 4.0", "licence_url": "https://geneontology.org/docs/go-citation-policy/",
           "citation": "Gene Ontology Consortium. The Gene Ontology knowledgebase in 2023. Genetics 224, iyad031 (2023); "
                       "Ashburner et al. Gene Ontology: tool for the unification of biology. Nat Genet 25, 25-29 (2000)."},
}

# name -> (url, provider, stored file name, already gzipped upstream?)
SOURCE_FILES = {
    "uniprot_human_proteome_fasta": (f"{UNIPROT_FTP}/knowledgebase/reference_proteomes/Eukaryota/UP000005640/UP000005640_9606.fasta.gz",
                                     "uniprot", "UP000005640_9606.fasta.gz", True),
    "uniprot_mouse_proteome_fasta": (f"{UNIPROT_FTP}/knowledgebase/reference_proteomes/Eukaryota/UP000000589/UP000000589_10090.fasta.gz",
                                     "uniprot", "UP000000589_10090.fasta.gz", True),
    "uniprot_human_proteome_fasta_additional": (f"{UNIPROT_FTP}/knowledgebase/reference_proteomes/Eukaryota/UP000005640/UP000005640_9606_additional.fasta.gz",
                                                "uniprot", "UP000005640_9606_additional.fasta.gz", True),
    "uniprot_mouse_proteome_fasta_additional": (f"{UNIPROT_FTP}/knowledgebase/reference_proteomes/Eukaryota/UP000000589/UP000000589_10090_additional.fasta.gz",
                                                "uniprot", "UP000000589_10090_additional.fasta.gz", True),
    "uniprot_human_entries": (f"https://rest.uniprot.org/uniprotkb/stream?query=(proteome:UP000005640)&format=tsv&fields={UNIPROT_FIELDS}&compressed=true",
                              "uniprot", "uniprot_human_UP000005640_entries.tsv.gz", True),
    "uniprot_mouse_entries": (f"https://rest.uniprot.org/uniprotkb/stream?query=(proteome:UP000000589)&format=tsv&fields={UNIPROT_FIELDS}&compressed=true",
                              "uniprot", "uniprot_mouse_UP000000589_entries.tsv.gz", True),
    "uniprot_secondary_accessions": (f"{UNIPROT_FTP}/knowledgebase/complete/docs/sec_ac.txt",
                                     "uniprot", "uniprot_sec_ac.txt.gz", False),
    "hgnc_complete_set": ("https://storage.googleapis.com/public-download-files/hgnc/tsv/tsv/hgnc_complete_set.txt",
                          "hgnc", "hgnc_complete_set.txt.gz", False),
    "mgi_marker_list": ("https://www.informatics.jax.org/downloads/reports/MRK_List2.rpt",
                        "mgi", "mgi_MRK_List2.rpt.gz", False),
    "mgi_gene_model_coord": ("https://www.informatics.jax.org/downloads/reports/MGI_Gene_Model_Coord.rpt",
                             "mgi", "mgi_MGI_Gene_Model_Coord.rpt.gz", False),
    "mgi_uniprot": ("https://www.informatics.jax.org/downloads/reports/MRK_SwissProt_TrEMBL.rpt",
                    "mgi", "mgi_MRK_SwissProt_TrEMBL.rpt.gz", False),
    "go_ontology": (f"{GO_RELEASE}/ontology/go-basic.obo", "go", "go-basic.obo.gz", False),
    "go_annotations_human": (f"{GO_RELEASE}/annotations/goa_human.gaf.gz", "go", "goa_human.gaf.gz", True),
    "go_annotations_mouse": (f"{GO_RELEASE}/annotations/mgi.gaf.gz", "go", "mgi.gaf.gz", True),
}

# GAF rows kept for the term -> gene tables: proteins and protein-coding genes
# (UniProtKB / MGI objects). RNAs and protein complexes (RNAcentral,
# ComplexPortal) are left out: the enrichment background is a proteome.
PROTEIN_OBJECT_TYPES = {"protein", "protein_coding_gene"}

OUTPUTS = ("BioNamesDB.txt.gz", "all_go_terms_genes.csv", "all_go_terms_genes_mouse.csv",
           "UP000005640_9606.fasta.gz", "UP000000589_10090.fasta.gz",
           "UP000005640_9606_additional.fasta.gz", "UP000000589_10090_additional.fasta.gz")

# FASTA sources used unchanged at runtime: stored under
# data/db/ only (fetched there, verified there); `build` copies them to its
# output folder only when that is somewhere else (a rebuild in isolation).
DB_ONLY_SOURCES = {
    "uniprot_human_proteome_fasta", "uniprot_mouse_proteome_fasta",
    "uniprot_human_proteome_fasta_additional", "uniprot_mouse_proteome_fasta_additional",
}
DB_SOURCES = ROOT / "data" / "db"


def source_path(name: str, stored: str) -> Path:
    return (DB_SOURCES if name in DB_ONLY_SOURCES else SOURCES) / stored


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_gz_bytes(path: Path, data: bytes) -> None:
    """Deterministic gzip: no name, mtime 0, so the same bytes give the same file."""
    with path.open("wb") as raw, gzip.GzipFile(filename="", mode="wb", compresslevel=9, fileobj=raw, mtime=0) as handle:
        handle.write(data)


def _write_gz_text(path: Path, text: str) -> None:
    _write_gz_bytes(path, text.encode("utf-8"))


def _get(url: str, timeout: int = 600, attempts: int = 6) -> tuple[bytes, dict[str, str]]:
    """Retry interrupted downloads without combining bytes from changing releases."""
    import http.client
    import time
    for attempt in range(attempts):
        request = urllib.request.Request(url, headers={"User-Agent": "CoPYlot-reference-db-build/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 -- fixed https URLs above
                return response.read(), {k.lower(): v for k, v in response.headers.items()}
        except (http.client.IncompleteRead, ConnectionError, TimeoutError) as exc:
            if attempt == attempts - 1:
                raise
            print(f"  transfer interrupted ({type(exc).__name__}), retrying", flush=True)
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("unreachable")


def _open_text(path: Path):
    return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8", errors="replace")


def _read_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {"sources": {}, "outputs": {}}


def _write_manifest(manifest: dict) -> None:
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


# --------------------------------------------------------------------------- #
# fetch
# --------------------------------------------------------------------------- #

def _uniprot_release() -> tuple[str, str]:
    text, _ = _get(f"{UNIPROT_FTP}/relnotes.txt", timeout=60)
    first = text.decode("utf-8", "replace").splitlines()[0]
    match = re.search(r"Release (\d{4}_\d{2})", first)
    _, headers = _get("https://rest.uniprot.org/uniprotkb/search?query=accession:P04217&format=tsv&fields=accession&size=1", timeout=60)
    return (match.group(1) if match else first.strip()), headers.get("x-uniprot-release-date", "")


def _go_release() -> str:
    text, _ = _get(f"{GO_RELEASE}/metadata/release-date.json", timeout=60)
    match = re.search(r"\d{4}-\d{2}-\d{2}", text.decode("utf-8", "replace"))
    return match.group(0) if match else text.decode("utf-8", "replace").strip()


def fetch(names: list[str] | None = None) -> None:
    unknown = set(names or ()) - SOURCE_FILES.keys()
    if unknown:
        raise ValueError(f"Unknown sources: {', '.join(sorted(unknown))}")
    SOURCES.mkdir(parents=True, exist_ok=True)
    manifest = _read_manifest()
    retrieved = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    uniprot_release, uniprot_release_date = _uniprot_release()
    go_release = _go_release()
    for name, (url, provider, stored, gzipped) in SOURCE_FILES.items():
        if names and name not in names:
            continue
        print(f"fetching {name} ...", flush=True)
        data, headers = _get(url)
        target = source_path(name, stored)
        target.parent.mkdir(parents=True, exist_ok=True)
        if gzipped:
            target.write_bytes(data)
        else:
            _write_gz_bytes(target, data)
        if provider == "uniprot":
            release = uniprot_release
            release_date = uniprot_release_date
        elif provider == "go":
            release = go_release
            release_date = go_release
            if name == "go_ontology":
                version = re.search(rb"data-version: (\S+)", data[:2000])
                release = f"{go_release} (obo data-version {version.group(1).decode()})" if version else go_release
        else:
            release = headers.get("last-modified", "")
            release_date = release
        manifest["sources"][name] = {
            "file": stored, "url": url, "provider": provider,
            "release": release, "release_date": release_date, "retrieved": retrieved,
            "upstream_last_modified": headers.get("last-modified", ""),
            "bytes": target.stat().st_size, "sha256": sha256_of(target), **LICENCES[provider],
        }
        print(f"  {stored}: {target.stat().st_size:,} bytes, release {release}")
        if name in DB_ONLY_SOURCES:
            # Used unchanged, so it is an output too; the log line keeps the fetch in the history.
            manifest.setdefault("outputs", {})[stored] = {"sha256": manifest["sources"][name]["sha256"], "bytes": target.stat().st_size,
                                                          "records": _record_count(target), "built": retrieved}
            manifest.setdefault("build", {}).setdefault("sources_sha256", {})[name] = manifest["sources"][name]["sha256"]
            with BUILD_LOG.open("a", encoding="utf-8", newline="\n") as log:
                log.write(f"\n== fetch {retrieved} (stored under data/db only)\n")
                log.write(f"source  {stored:<45} release {release:<24} sha256 {manifest['sources'][name]['sha256']}\n")
                log.write(f"output  {stored:<45} records {manifest['outputs'][stored]['records']:<9,} sha256 {manifest['sources'][name]['sha256']}\n")
        _write_manifest(manifest)  # after every file, so an interrupted run keeps what it got


# --------------------------------------------------------------------------- #
# build: identifier table
# --------------------------------------------------------------------------- #

def _read_tsv(path: Path, **kwargs):
    import pandas as pd
    with _open_text(path) as handle:
        return pd.read_csv(handle, sep="\t", dtype=str, keep_default_na=False, **kwargs)


def _secondary_accessions(path: Path, primaries: set[str]) -> dict[str, list[str]]:
    """sec_ac.txt: 'secondary primary' pairs after a header block ending in a line of underscores."""
    mapping: dict[str, list[str]] = defaultdict(list)
    started = False
    with _open_text(path) as handle:
        for line in handle:
            if not started:
                if line.startswith("____"):
                    started = True
                continue
            parts = line.split()
            if len(parts) == 2 and parts[1] in primaries:
                mapping[parts[1]].append(parts[0])
    return {k: sorted(v) for k, v in mapping.items()}


def _first(value: str) -> str:
    return value.split(";")[0].strip() if value else ""


def _ensembl_gene_ids(value: str) -> str:
    """Keep gene identifiers; UniProt Ensembl cross-references can be transcripts."""
    genes = {part.strip().split(".")[0] for part in value.split(";")}
    return ";".join(sorted(gene for gene in genes if re.fullmatch(r"ENS(?:MUS)?G\d+", gene)))


def build_bionames() -> "pandas.DataFrame":
    import pandas as pd

    manifest = _read_manifest()["sources"]
    src = lambda key: SOURCES / manifest[key]["file"]  # noqa: E731

    # --- HGNC (human genes) -------------------------------------------------
    hgnc = _read_tsv(src("hgnc_complete_set"))
    hgnc = hgnc.rename(columns={"entrez_id": "entrez_gene_id", "mgd_id": "mgi_ortholog_id"})
    hgnc_cols = ["hgnc_id", "symbol", "name", "alias_symbol", "ensembl_gene_id", "vega_id", "ena",
                 "refseq_accession", "ccds_id", "uniprot_ids", "pubmed_id", "enzyme_id", "rna_central_id",
                 "entrez_gene_id", "omim_id", "mgi_ortholog_id"]
    hgnc = hgnc[[c for c in hgnc_cols if c in hgnc.columns]].copy()
    hgnc["alias_symbol"] = hgnc["alias_symbol"].str.replace("|", ";", regex=False)
    hgnc["ensembl_gene_id"] = hgnc["ensembl_gene_id"].str.replace("|", ";", regex=False)
    for col in ("ena", "refseq_accession", "ccds_id", "uniprot_ids", "pubmed_id", "enzyme_id", "rna_central_id", "omim_id", "mgi_ortholog_id"):
        if col in hgnc.columns:
            hgnc[col] = hgnc[col].str.replace("|", ";", regex=False)

    # --- MGI (mouse genes) ----------------------------------------------------
    markers = _read_tsv(src("mgi_marker_list"))
    markers = markers.rename(columns={
        "MGI Accession ID": "mgi_id", "Marker Symbol": "mgi_symbol", "Marker Name": "mgi_name",
        "Marker Synonyms (pipe-separated)": "mgi_synonym", "Marker Type": "mgi_marker_type", "Feature Type": "mgi_feature_type",
    })
    markers = markers[markers["mgi_marker_type"] == "Gene"][["mgi_id", "mgi_symbol", "mgi_name", "mgi_synonym", "mgi_feature_type"]].copy()
    markers["mgi_synonym"] = markers["mgi_synonym"].str.replace("|", ";", regex=False)
    coords = _read_tsv(src("mgi_gene_model_coord"))
    coords = coords.rename(columns={"1. MGI accession id": "mgi_id", "6. Entrez gene id": "entrez_gene_id",
                                    "11. Ensembl gene id": "ensembl_gene_id"})
    coords = coords[["mgi_id", "entrez_gene_id", "ensembl_gene_id"]].replace("null", "")
    mgi = markers.merge(coords, on="mgi_id", how="left").fillna("")
    mgi_uniprot = _read_tsv(src("mgi_uniprot"), header=None,
                            names=["mgi_id", "mgi_symbol_", "status", "mgi_name_", "cM", "chr", "uniprot_ids"])
    mgi_uniprot = mgi_uniprot[["mgi_id", "uniprot_ids"]].copy()
    mgi_uniprot["uniprot_ids"] = mgi_uniprot["uniprot_ids"].str.replace(" ", ";", regex=False)
    mgi = mgi.merge(mgi_uniprot, on="mgi_id", how="left").fillna("")

    # --- UniProt entries ------------------------------------------------------
    frames = []
    for species, key in (("human", "uniprot_human_entries"), ("mouse", "uniprot_mouse_entries")):
        entries = _read_tsv(src(key))
        entries = entries.rename(columns={
            "Entry": "uniprot_symbol", "Entry Name": "uniprot_name", "Reviewed": "reviewed",
            "Protein names": "uniprot_description", "Gene Names (primary)": "uniprot_gene",
            "Gene Names": "uniprot_gene_names", "Organism (ID)": "taxonomy_id", "Length": "sequence_length",
            "HGNC": "xref_hgnc", "MGI": "xref_mgi", "Ensembl": "xref_ensembl", "GeneID": "xref_geneid", "RefSeq": "xref_refseq",
        })
        entries["species"] = species
        entries["reviewed"] = entries["reviewed"].map({"reviewed": "sp", "unreviewed": "tr"}).fillna(entries["reviewed"])
        frames.append(entries)
    uniprot = pd.concat(frames, ignore_index=True)
    secondary = _secondary_accessions(src("uniprot_secondary_accessions"), set(uniprot["uniprot_symbol"]))
    uniprot["uniprot_alternative"] = uniprot["uniprot_symbol"].map(lambda acc: ";".join(secondary.get(acc, [])))
    uniprot["uniprot_gene_names"] = uniprot["uniprot_gene_names"].str.replace(" ", ";", regex=False)
    uniprot["xref_hgnc"] = uniprot["xref_hgnc"].map(_first)
    uniprot["xref_mgi"] = uniprot["xref_mgi"].map(_first)
    uniprot["xref_geneid"] = uniprot["xref_geneid"].map(_first)
    uniprot["xref_refseq"] = uniprot["xref_refseq"].str.replace(" ", "", regex=False).str.strip(";")
    uniprot["xref_ensembl"] = uniprot["xref_ensembl"].str.replace(" ", "", regex=False).str.strip(";")

    # --- join: human entries -> HGNC by cross-reference, else by symbol -------
    human = uniprot[uniprot["species"] == "human"].copy()
    by_id = hgnc.set_index("hgnc_id")
    by_symbol = hgnc.drop_duplicates("symbol").set_index("symbol")
    key = human["xref_hgnc"].where(human["xref_hgnc"].isin(by_id.index), "")
    key = key.where(key != "", human["uniprot_gene"].map(lambda g: by_symbol.loc[g, "hgnc_id"] if g in by_symbol.index else ""))
    human["hgnc_id"] = key
    human["join"] = human["xref_hgnc"].isin(by_id.index).map({True: "uniprot-xref", False: "symbol"}).where(key != "", "none")
    human = human.merge(hgnc, on="hgnc_id", how="left", suffixes=("", "_hgnc")).fillna("")
    unmatched_hgnc = hgnc[~hgnc["hgnc_id"].isin(set(human["hgnc_id"]))].copy()
    unmatched_hgnc["species"] = "human"
    unmatched_hgnc["join"] = "gene-only"

    # --- join: mouse entries -> MGI by cross-reference, else by symbol --------
    mouse = uniprot[uniprot["species"] == "mouse"].copy()
    mgi_by_id = mgi.set_index("mgi_id")
    mgi_by_symbol = mgi.drop_duplicates("mgi_symbol").set_index("mgi_symbol")
    key = mouse["xref_mgi"].where(mouse["xref_mgi"].isin(mgi_by_id.index), "")
    key = key.where(key != "", mouse["uniprot_gene"].map(lambda g: mgi_by_symbol.loc[g, "mgi_id"] if g in mgi_by_symbol.index else ""))
    mouse["mgi_id"] = key
    mouse["join"] = mouse["xref_mgi"].isin(mgi_by_id.index).map({True: "uniprot-xref", False: "symbol"}).where(key != "", "none")
    mouse = mouse.merge(mgi, on="mgi_id", how="left", suffixes=("", "_mgi")).fillna("")
    unmatched_mgi = mgi[~mgi["mgi_id"].isin(set(mouse["mgi_id"]))].copy()
    unmatched_mgi["species"] = "mouse"
    unmatched_mgi["join"] = "gene-only"

    table = pd.concat([human, unmatched_hgnc, mouse, unmatched_mgi], ignore_index=True).fillna("")
    # one gene-level entrez/ensembl column across species (UniProt's xref fills gaps)
    for col, xref in (("entrez_gene_id", "xref_geneid"), ("ensembl_gene_id", "xref_ensembl")):
        if xref in table.columns:
            fallback = table[xref].map(_ensembl_gene_ids if col == "ensembl_gene_id" else _first)
            table[col] = table[col].where(table[col] != "", fallback)
    if "refseq_accession" in table.columns and "xref_refseq" in table.columns:
        table["refseq_accession"] = table["refseq_accession"].where(table["refseq_accession"] != "", table["xref_refseq"])
    columns = [
        "species", "uniprot_symbol", "uniprot_name", "reviewed", "uniprot_gene", "uniprot_gene_names",
        "uniprot_description", "uniprot_alternative", "sequence_length",
        "hgnc_id", "symbol", "name", "alias_symbol",
        "mgi_id", "mgi_symbol", "mgi_name", "mgi_synonym", "mgi_feature_type", "mgi_ortholog_id",
        "ensembl_gene_id", "entrez_gene_id", "vega_id", "ena", "refseq_accession", "ccds_id", "uniprot_ids",
        "pubmed_id", "enzyme_id", "rna_central_id", "omim_id", "join",
    ]
    for col in columns:
        if col not in table.columns:
            table[col] = ""
    table = table[columns].astype(str)
    table = table.sort_values(["species", "uniprot_symbol", "hgnc_id", "mgi_id"], kind="mergesort").reset_index(drop=True)
    return table


# --------------------------------------------------------------------------- #
# build: Gene Ontology term -> genes
# --------------------------------------------------------------------------- #

def _parse_obo(path: Path) -> tuple[dict[str, tuple[str, str]], dict[str, set[str]], dict[str, str]]:
    """terms (id -> (namespace, name)), parents (id -> is_a/part_of parents), alt_id -> id."""
    terms: dict[str, tuple[str, str]] = {}
    parents: dict[str, set[str]] = defaultdict(set)
    alt: dict[str, str] = {}
    current: dict[str, list[str]] = {}
    in_term = False

    def flush():
        if in_term and "id" in current and "is_obsolete" not in current:
            tid = current["id"][0]
            terms[tid] = (current.get("namespace", [""])[0], current.get("name", [""])[0])
            for p in current.get("is_a", []):
                parents[tid].add(p.split("!")[0].strip())
            for r in current.get("relationship", []):
                kind, target = r.split("!")[0].split()[:2]
                if kind == "part_of":
                    parents[tid].add(target)
            for a in current.get("alt_id", []):
                alt[a] = tid

    with _open_text(path) as handle:
        for raw in handle:
            line = raw.rstrip("\n")
            if line == "[Term]":
                flush(); current = {}; in_term = True
                continue
            if line.startswith("["):
                flush(); current = {}; in_term = False
                continue
            if in_term and ":" in line:
                k, v = line.split(":", 1)
                current.setdefault(k.strip(), []).append(v.strip())
    flush()
    return terms, parents, alt


def _ancestors(term: str, parents: dict[str, set[str]], cache: dict[str, frozenset]) -> frozenset:
    if term in cache:
        return cache[term]
    result: set[str] = set()
    stack = list(parents.get(term, ()))
    while stack:
        p = stack.pop()
        if p in result:
            continue
        result.add(p)
        stack.extend(parents.get(p, ()))
    cache[term] = frozenset(result)
    return cache[term]


def build_go(species: str, gene_symbols: dict[str, str] | None = None) -> "pandas.DataFrame":
    """Term -> gene symbols for one species.

    `gene_symbols` maps a UniProt accession to its gene symbol (from the
    identifier table built in the same run): an annotation whose object has no
    symbol in the GAF (the symbol column then holds the accession) is written
    under the gene symbol when one is known and dropped otherwise, so the
    enrichment universe holds genes, not accessions.
    """
    import pandas as pd

    if species not in {"human", "mouse"}:
        raise ValueError(f"Unsupported species: {species}")
    manifest = _read_manifest()["sources"]
    terms, parents, alt = _parse_obo(SOURCES / manifest["go_ontology"]["file"])
    gaf = SOURCES / manifest["go_annotations_human" if species == "human" else "go_annotations_mouse"]["file"]
    gene_symbols = gene_symbols or {}
    direct: dict[str, set[str]] = defaultdict(set)
    dropped: set[str] = set()
    with _open_text(gaf) as handle:
        for line in handle:
            if line.startswith("!"):
                continue
            cols = line.rstrip("\n").split("\t")
            if len(cols) < 15:
                continue
            accession, symbol, qualifier, go_id, object_type = cols[1], cols[2], cols[3], cols[4], cols[11]
            if cols[12].split("|")[0] != ("taxon:9606" if species == "human" else "taxon:10090"):
                continue
            if "NOT" in qualifier.split("|") or object_type not in PROTEIN_OBJECT_TYPES:
                continue
            if symbol == accession:  # no gene symbol known to the annotation: the accession stands in
                symbol = gene_symbols.get(accession, "")
                if not symbol:
                    dropped.add(accession)
                    continue
            go_id = alt.get(go_id, go_id)
            if go_id in terms and symbol:
                direct[go_id].add(symbol)
    if dropped:
        print(f"GO {species}: {len(dropped):,} annotated proteins without a gene symbol left out")
    cache: dict[str, frozenset] = {}
    genes: dict[str, set[str]] = defaultdict(set)
    for go_id, symbols in direct.items():
        genes[go_id].update(symbols)
        for ancestor in _ancestors(go_id, parents, cache):
            if ancestor in terms:
                genes[ancestor].update(symbols)
    namespace = {"biological_process": "BP", "molecular_function": "MF", "cellular_component": "CC"}
    rows = [(namespace.get(terms[t][0], terms[t][0]), t, terms[t][1], ";".join(sorted(genes[t])))
            for t in sorted(genes) if genes[t]]
    return pd.DataFrame(rows, columns=["ontology", "term", "description", "genes"])


# --------------------------------------------------------------------------- #
# build / verify
# --------------------------------------------------------------------------- #

def build() -> None:
    manifest = _read_manifest()
    missing = [n for n in SOURCE_FILES if n not in manifest["sources"] or not source_path(n, manifest["sources"][n]["file"]).exists()]
    if missing:
        raise SystemExit(f"sources missing, run `fetch` first: {missing}")
    verify(sources_only=True)
    started = dt.datetime.now(dt.timezone.utc)

    table = build_bionames()
    _write_gz_text(DB / "BioNamesDB.txt.gz", table.to_csv(sep="\t", index=False, lineterminator="\n"))
    counts = table["species"].value_counts().to_dict()
    joins = table.groupby(["species", "join"]).size().to_dict()
    print(f"BioNamesDB: {len(table):,} rows {counts}; joins {joins}")

    symbols = {acc: gene for acc, gene in zip(table["uniprot_symbol"], table["uniprot_gene"]) if acc and gene}
    for species, name in (("human", "all_go_terms_genes.csv"), ("mouse", "all_go_terms_genes_mouse.csv")):
        go = build_go(species, symbols)
        (DB / name).write_text(go.to_csv(index=False, quoting=1, lineterminator="\n"), encoding="utf-8", newline="\n")
        print(f"GO {species}: {len(go):,} terms, {len(set(';'.join(go['genes']).split(';'))):,} genes")

    for key in sorted(DB_ONLY_SOURCES):
        source = source_path(key, manifest["sources"][key]["file"])
        if source.resolve() != (DB / source.name).resolve():
            shutil.copyfile(source, DB / source.name)

    manifest["outputs"] = {}
    for name in OUTPUTS:
        path = DB / name
        manifest["outputs"][name] = {"sha256": sha256_of(path), "bytes": path.stat().st_size,
                                     "records": _record_count(path), "built": started.strftime("%Y-%m-%dT%H:%M:%SZ")}
    manifest["build"] = {"script": "tools/build_reference_databases.py", "python": sys.version.split()[0],
                         "pandas": __import__("pandas").__version__,
                         "sources_sha256": {n: s["sha256"] for n, s in manifest["sources"].items()}}
    _write_manifest(manifest)
    with BUILD_LOG.open("a", encoding="utf-8", newline="\n") as log:
        log.write(f"\n== build {started.strftime('%Y-%m-%d %H:%M UTC')}\n")
        for n, s in manifest["sources"].items():
            log.write(f"source  {s['file']:<45} release {s['release']:<24} sha256 {s['sha256']}\n")
        for n, o in manifest["outputs"].items():
            log.write(f"output  {n:<45} records {o['records']:<9,} sha256 {o['sha256']}\n")
    print("manifest and BUILD.log updated")


def _record_count(path: Path) -> int:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as handle:
        if ".fasta" in path.name:
            return sum(1 for line in handle if line.startswith(b">"))
        return max(0, sum(1 for _ in handle) - 1)


def verify(sources_only: bool = False) -> None:
    manifest = _read_manifest()
    problems = []
    if set(manifest.get("sources", {})) != set(SOURCE_FILES):
        problems.append("manifest must list every expected source, and no unknown sources")
    if not sources_only:
        if set(manifest.get("outputs", {})) != set(OUTPUTS):
            problems.append("manifest must list every expected output, and no unknown outputs")
        if manifest.get("build", {}).get("sources_sha256") != {
            name: entry["sha256"] for name, entry in manifest.get("sources", {}).items()
        }:
            problems.append("outputs were not built from the currently recorded sources")
    for name, entry in manifest["sources"].items():
        path = source_path(name, entry["file"])
        if not path.exists():
            problems.append(f"missing source {path.name}")
        elif sha256_of(path) != entry["sha256"]:
            problems.append(f"source {path.name} does not match the manifest")
    if not sources_only:
        for name, entry in manifest.get("outputs", {}).items():
            path = DB / name
            if not path.exists():
                problems.append(f"missing output {name}")
            elif sha256_of(path) != entry["sha256"]:
                problems.append(f"output {name} does not match the manifest")
    if problems:
        raise SystemExit("verify failed:\n  " + "\n  ".join(problems))
    print("verify: every " + ("source" if sources_only else "source and output") + " matches the manifest")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("fetch", help="download the upstream releases (network)")
    f.add_argument("names", nargs="*", help="only these sources (default: all)")
    sub.add_parser("build", help="rebuild the runtime databases from the frozen sources (offline)")
    sub.add_parser("verify", help="check sources and outputs against the manifest")
    args = parser.parse_args()
    if args.command == "fetch":
        fetch(args.names or None)
    elif args.command == "build":
        build()
    else:
        verify()


if __name__ == "__main__":
    main()
