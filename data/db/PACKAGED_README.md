# Gene Ontology reference tables

This folder of the installed `proteomicscopylot` package holds two third-party resources. The
project GPL-3.0 license does not replace their source license.

| File | Purpose | Records | SHA-256 |
| --- | --- | ---: | --- |
| `all_go_terms_genes.csv` | Gene Ontology term-to-gene mapping used by the over-representation analysis, `organism="human"` (default) | 20,941 terms, 19,631 human genes | `b314eda0ae2164a6bdc137899330b7b2fb568b85610d2e5bb99a13fc6e298e21` |
| `all_go_terms_genes_mouse.csv` | The same for `organism="mouse"` | 21,864 terms, 22,002 mouse genes | `9ecf591d37b77bd8132597c8e07fcbb22e97f4aa3faaba4d5a581cf384fc7452` |

Both tables are built from the Gene Ontology Consortium release of 2026-08-05 (`goa_human.gaf.gz`,
`mgi.gaf.gz` and `go-basic.obo`, data-version 2026-07-26): protein and protein-coding-gene
annotations without a `NOT` qualifier, propagated to ancestor terms over `is_a` and `part_of`.
The build script, the committed upstream files and their checksums are in the CoPYlot repository
(`tools/build_reference_databases.py`, `data/reference-sources/`). The tables never update on
their own; a newer release is fetched, rebuilt and committed deliberately.

Gene Ontology Consortium data and data products are distributed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The Consortium's
[citation and license policy](https://geneontology.org/docs/go-citation-policy/) provides the
required attribution, citation guidance, source links, and warranty disclaimer. Copyright
1999-present, Gene Ontology Consortium. Results should cite that release (and may cite the
checksum above).

The data are supplied without warranties by their providers. The repository's
`data/db/README.md` documents all bundled reference resources.
