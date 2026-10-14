# Biological reference data

These runtime resources contain third-party biological data. The project GPL-3.0 license does not
replace the source licenses described below.

CoPYlot uses these frozen reference tables without downloading or rebuilding them at runtime.
The construction script is `tools/build_reference_databases.py`; its upstream snapshots and
source URLs, releases, retrieval dates, licences and checksums are in `data/reference-sources/`.
The manifest identifies the inputs and outputs of the current build; `BUILD.log` records past builds.

## Runtime files (this folder)

| File | Runtime purpose | Records | Built from |
| --- | --- | ---: | --- |
| `BioNamesDB.txt.gz` | Identifier translation table (ID Translator page, notebook replay) | 280,689 rows: 172,337 human, 108,352 mouse | UniProt 2026_03 entries of the human and mouse reference proteomes + secondary accessions, HGNC complete set (2026-10-09), MGI marker reports (2026-10-12) |
| `all_go_terms_genes.csv` | Gene Ontology term → human gene symbols, for over-representation analysis and pathway heatmaps (app, pip package, R functions; organism `human`) | 20,941 terms, 19,631 genes | GO release 2026-08-05: `goa_human.gaf.gz` + `go-basic.obo`, symbols from `BioNamesDB` |
| `all_go_terms_genes_mouse.csv` | The same for mouse (organism `mouse` in the ORA and pathway-heatmap organism selectors and in `enrichment_data(organism=)`) | 21,864 terms, 22,002 genes | GO release 2026-08-05: `mgi.gaf.gz` + `go-basic.obo`, symbols from `BioNamesDB` |
| `UP000005640_9606.fasta.gz` | Human reference proteome, canonical sequences, for sequence coverage | 20,652 sequences | UniProt 2026_03 reference proteomes FTP, unchanged |
| `UP000000589_10090.fasta.gz` | Mouse reference proteome, canonical sequences, for sequence coverage | 21,860 sequences | UniProt 2026_03 reference proteomes FTP, unchanged |
| `UP000005640_9606_additional.fasta.gz` | Human reference proteome, additional sequences (isoforms, non-canonical TrEMBL entries), consulted when a selected variant is not among the canonical sequences | 148,999 sequences | UniProt 2026_03 reference proteomes FTP, unchanged; stored here only (41 MB), logged in the manifest like every source (fetched 2026-10-14) |
| `UP000000589_10090_additional.fasta.gz` | The same for mouse | 41,468 sequences | UniProt 2026_03 reference proteomes FTP, unchanged; stored here only (10 MB), logged in the manifest (fetched 2026-10-14) |

The SHA-256 of every file is in `data/reference-sources/manifest.json` (`outputs`) and in
`BUILD.log`. Results should cite the upstream release (and may cite the checksum); the executables
and the Docker image ship this folder, not `data/reference-sources/`.

### Checksums (SHA-256 of the committed files)

| File | SHA-256 |
| --- | --- |
| `BioNamesDB.txt.gz` | `a5968748aca7f88728ffd46494adc9a21469a8bfdb778e420a185b270083c816` |
| `UP000000589_10090.fasta.gz` | `c24568f70ce9ffd7693a1ecd31c23eaa97a1f43d9305e2ff5401bdf30e2a0a93` |
| `UP000005640_9606.fasta.gz` | `64299d01e8f41fb6ef03cdf7ec051d3d4e5f041003b6b0fa75b09d439af79dce` |
| `UP000005640_9606_additional.fasta.gz` | `9cafde8f00cef658388e188392429eb2440cce95031347670492475cb656b11a` |
| `UP000000589_10090_additional.fasta.gz` | `edbde2466111e563b3a12ce4fed9c4b436782acc74ddf9adca4bc253badb8cbf` |
| `all_go_terms_genes.csv` | `b314eda0ae2164a6bdc137899330b7b2fb568b85610d2e5bb99a13fc6e298e21` |
| `all_go_terms_genes_mouse.csv` | `9ecf591d37b77bd8132597c8e07fcbb22e97f4aa3faaba4d5a581cf384fc7452` |

## How the tables are built

**`BioNamesDB.txt.gz`** (tab-separated, one row per protein entry or gene):

- One row per UniProt entry of the human (UP000005640, 147,520 entries) and mouse (UP000000589,
  54,855 entries) reference proteomes, Swiss-Prot and TrEMBL: accession, entry name, reviewed
  (`sp`/`tr`), primary gene, all gene names, protein names, secondary accessions (from UniProt's
  `sec_ac.txt`), sequence length.
- Each human entry is joined to HGNC by UniProt's HGNC cross-reference (146,336 entries), or by
  the primary gene symbol when the cross-reference is missing (89); each mouse entry to MGI by the
  MGI cross-reference (54,484) or symbol (18). The `join` column says which. Entries that match
  neither (1,095 human, 353 mouse, mostly TrEMBL fragments) keep their UniProt columns only.
- HGNC genes without a protein entry (24,817, e.g. non-coding genes) and MGI genes without one
  (53,497) are rows of their own (`join = gene-only`), so symbol ↔ Ensembl/Entrez translations
  work for them too. MGI rows are restricted to markers of type *Gene*.
- Gene-level columns: HGNC id, symbol, name, alias symbols, Ensembl, Entrez, VEGA, ENA, RefSeq,
  CCDS, PubMed, EC, RNAcentral, OMIM, the MGI ortholog HGNC records; MGI id, symbol, name,
  synonyms, feature type. Entrez and RefSeq fall back to UniProt's cross-reference when
  the gene record has none. Ensembl fallbacks accept gene IDs only, never transcript IDs.
  Multiple values are `;`-separated.
- Rows are sorted by species, accession and gene id, so the file is deterministic.

**`all_go_terms_genes*.csv`** (`ontology,term,description,genes`):

- Annotations are read from the GO Consortium release's GAF files, keeping objects of type
  `protein` or `protein_coding_gene` (UniProtKB and MGI objects; no RNAs, no complexes) and
  dropping `NOT`-qualified annotations. The primary taxon must match the selected species.
  Every evidence code is kept, including electronic (IEA).
- Each gene's annotations are propagated to all ancestors of the term over `is_a` and `part_of`
  (the GO Consortium's recommended closure for gene-set construction). `regulates` relations are
  not followed: a regulator of apoptosis is not counted as directly participating in apoptosis.
  See the [GO relation guidance](https://geneontology.org/docs/ontology-relations/).
- Obsolete terms are skipped; `alt_id`s are mapped to their current term. The term's namespace
  is written as BP / MF / CC. A term that has become obsolete since an earlier build is simply no
  longer found (results and notebooks that cite it keep their captured copy of the table).
- The GAF `DB_Object_Symbol` is the gene symbol written to the table. Where UniProt-GOA has no
  symbol it repeats the accession (e.g. `A0A0B4J2F0`); such rows are written under the entry's
  primary gene from `BioNamesDB.txt.gz` when it has one, and dropped otherwise (62 human, 129
  mouse annotation objects in the 2026-08-05 release), so the table contains symbols only.

**FASTA files**: the reference proteome files as published by UniProt, copied unchanged (gzipped).
The peptide-coverage page reads them directly.

## Sources, attribution and terms

| Source | Release used | Licence | Citation / terms |
| --- | --- | --- | --- |
| UniProt reference proteomes and UniProtKB entries | 2026_03 (2 September 2026) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | The UniProt Consortium, *UniProt: the Universal Protein Knowledgebase*, Nucleic Acids Res.; [license](https://www.uniprot.org/help/license) |
| HGNC complete set | file dated 2026-10-09 (HGNC publishes no release number; the file date is the release) | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) | HUGO Gene Nomenclature Committee, EMBL-EBI, www.genenames.org; [licence](https://www.genenames.org/about/license/) |
| MGI marker reports (`MRK_List2`, `MGI_Gene_Model_Coord`, `MRK_SwissProt_TrEMBL`) | files dated 2026-10-12 (MGI's reports are regenerated continuously; the file date is the release) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | Mouse Genome Informatics, The Jackson Laboratory, www.informatics.jax.org; [copyright](https://www.informatics.jax.org/mgihome/other/copyright.shtml) |
| Gene Ontology: `go-basic.obo` (data-version 2026-07-26), `goa_human.gaf`, `mgi.gaf` | GO release 2026-08-05 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | Gene Ontology Consortium, Genetics 224, iyad031 (2023); Ashburner et al., Nat Genet 25, 25–29 (2000); [citation policy](https://geneontology.org/docs/go-citation-policy/). Copyright 1999–present, Gene Ontology Consortium |

All upstream data are supplied without warranties by their respective providers. Users remain
responsible for complying with third-party rights that may apply to individual records.

## Refreshing

Updates can change term membership and analysis results. Refresh only when preparing a reviewed
database update; normal application use needs none of these commands.

```sh
python tools/build_reference_databases.py fetch    # new upstream releases into data/reference-sources/
python tools/build_reference_databases.py build    # regenerate this folder; appends to BUILD.log
python tools/build_reference_databases.py verify   # what the test suite runs
```

Then update the record counts and checksums in this file and in `PACKAGED_README.md` (the pip
package ships the two GO tables with their checksums), run the test suite, and commit the sources,
the manifest, the outputs and `BUILD.log` together. Never edit an output by hand; change the build
script instead.
