# Biological reference data

These runtime resources contain third-party biological data. The project MIT license does not
replace the source licenses described below.

## Committed snapshots

| File | Runtime purpose | Records | SHA-256 |
| --- | --- | ---: | --- |
| `all_go_terms_genes.csv` | Gene Ontology term-to-gene mapping used by enrichment workflows | 22,074 terms | `a48f37a11bf8c2ba031843c99ba5f042c0943f8ae3bbbb2f8c52519e0a64389a` |
| `BioNamesDB.txt` | Protein/gene identifier translation table | 107,018 mappings | `4e069af7a7fc25970024c723b89e8fd7c379d8a0174a7bcf4e272fcffd3dae1f` |
| `UP000000589_10090.fasta` | Mouse reference proteome used for sequence coverage | 21,803 sequences | `1c9822446a56780dd536396d115dac4803ccc4e96e29b5b69dbaa1b1adde34cc` |
| `UP000005640_9606.fasta` | Human reference proteome used for sequence coverage | 20,663 sequences | `26399c337462bdc4adac02d207374f4eb192bf32c8e57bb6460f82b50e80e12d` |

The files were first committed on 2026-03-20. That date is repository history, not an upstream
release or download date.

An earlier public
[ProteomicsCopilotR commit](https://github.com/JonasMarx3007/ProteomicsCopilotR/commit/8483bf23157a270d52e35a28c0167e1d7dfb0716)
from 2025-07-21 contains SHA-256-identical copies of both FASTA files. A project description in
that commit labels a mouse analysis FASTA
`mus-musculus_uniprotkb_proteome_UP000000589_2024_07_31_C57Bl6J` and says it was from July 2024.
This supports the historical association but does not identify the UniProt release, original
download request, or provenance of the human FASTA.

## Sources, attribution, and terms

`all_go_terms_genes.csv` is a prepared derivative of Gene Ontology terms and human gene
annotations. Gene Ontology Consortium data and data products are distributed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The Consortium's
[citation and license policy](https://geneontology.org/docs/go-citation-policy/) provides the
required attribution, citation guidance, source links, and warranty disclaimer. Copyright
1999-present, Gene Ontology Consortium. The exact GO release, annotation product, and preparation
steps used for this CSV were not recorded.

The two FASTA files identify the UniProt reference proteomes
[UP000000589](https://www.uniprot.org/proteomes/UP000000589) and
[UP000005640](https://www.uniprot.org/proteomes/UP000005640). Copyright UniProt Consortium.
Copyrightable parts of UniProt databases are provided under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); see the official
[UniProt license and disclaimer](https://www.uniprot.org/help/license) and
[citation guidance](https://www.uniprot.org/help/publications). The exact UniProt release and
download options used for these FASTA snapshots were not recorded.

`BioNamesDB.txt` is a prepared merge whose columns contain UniProt and HGNC identifiers and
annotations. The UniProt-derived content is subject to the UniProt attribution and terms above.
HGNC states that its data are available under
[CC0](https://creativecommons.org/publicdomain/zero/1.0/); see the official
[HGNC download documentation](https://hgnc.genenames.org/download/). The exact input snapshots,
source URLs, and merge procedure were not recorded, so the origin of every column cannot currently
be reconstructed.

All upstream data are supplied without warranties by their respective providers. Users remain
responsible for complying with third-party rights that may apply to individual records.

## Reproducibility status

The SHA-256 values above identify the exact bytes used by this release, but the missing upstream
release identifiers and preparation recipes mean these datasets cannot yet be regenerated from
source. Results should cite the committed file checksum and must not claim a specific upstream
database release.

When replacing a resource:

1. Record the upstream release, retrieval date, stable URL or DOI, and download parameters.
2. Preserve the source license, attribution, copyright notice, and disclaimer.
3. Record the deterministic preparation command or script and input checksums.
4. Update the record count and SHA-256 value above.
5. Check the resulting file for credentials, private paths, and unintended local data before
   committing it.
