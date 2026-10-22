# ProteomicsCoPYlot example data

Bundled demonstration data used by `examples/example.ipynb` and `examples/example.R`,
and shipped inside the `proteomicscopylot` distribution.

## License

These data files are released under
[Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/).

You may share and adapt them, including commercially, provided you give appropriate
credit. Cite them as:

> Marx, J. HEK293 wild-type versus GRK whole-proteome and phosphoproteome DIA dataset.
> Bundled example data for Proteomics CoPYlot. CC BY 4.0.

The CC BY 4.0 grant covers these data files only. The software is under the
[GNU GPL version 3](../../LICENSE), and third-party biological reference data under
`data/db/` retain their own upstream terms; see
[Biological reference data](../../data/db/README.md).

## Contents

SHA-256 checksums below refer to the files with LF line endings, enforced by
`.gitattributes` on every platform. Line-ending conversion changes a checksum
even when all table values remain identical.

| File | Content | Dimensions | SHA-256 |
| --- | --- | --- | --- |
| `20260511_144120_20240822_JM_HEK293_WP_Report_PG.tsv` | Whole-proteome protein-group report | 7,490 × 18 | `2daf435ce6719388717adea0911f741a2bb0cb346a59f26df678f72193a47e1b` |
| `20260511_144129_20240822_JM_HEK293_PP_Report_collapsed.tsv` | Phosphoproteome report, collapsed to phosphosites | 11,916 × 15 | `d308f81f768e8445f07532835435ed9dc7e26935c3872161e0998e3d7d55e91a` |
| `phosprot_filtered_data_full.csv` | Phosphosites aggregated to phosphoproteins (`sum_ignore_na`: linear sum over the sites quantified in every sample; proteins without such a site are not listed) | 1,662 × 16 | `0d57b007347c6d324c7120197c7733cc00cfbda07dee17cb7d16975136495636` |
| `protein_metadata_full.csv` | Sample-to-condition map for the protein report | 10 × 2 | `5013126232f2c74186deead21b0baaa2af32a1b1df0b31fbb8352bc63d32b6bf` |
| `phospho_metadata_full.csv` | Sample-to-condition map for the phospho reports | 10 × 2 | `92e28c1d7b608423663be6c63b0a137bf96ffbc41046b0c01ed5f3897b7f0853` |

## Experimental design

HEK293 cells, two conditions with five biological replicates each:

| Condition | n | Meaning |
| --- | ---: | --- |
| `WT` | 5 | Wild type |
| `GRK` | 5 | *(fill in: which GRK, and knockout / knockdown / overexpression)* |

Both the whole-proteome (`WP`) and phosphoproteome (`PP`) arms use the same ten
biological samples. The protein report carries `PG.Log2Quantity`, so its
quantities are already log2-transformed; the tool detects this on upload.

## Provenance

The following is what the file names and column conventions establish:

- Acquired **2024-08-22**, from the `20240822_` run prefix on every sample name.
- Bruker instrumentation: sample names contain `nElute` (nanoElute LC) and `tims1`
  (timsTOF), and raw files carry the Bruker `.d` extension.
- Searched with **Spectronaut**: the reports use Spectronaut's `PG.*`, `EG.*` and
  `PEP.*` column families.
- Report files exported **2026-05-11**, from the `20260511_` export prefix.

The following still needs to be recorded before publication:

- **Repository accession.** These data are not yet deposited. Deposit the raw files
  in [ProteomeXchange / PRIDE](https://www.ebi.ac.uk/pride/) and cite the accession
  here; a software paper should point at the primary data.
- Spectronaut version, search settings, and the FASTA release used.
- Sample preparation, phosphopeptide enrichment method, and LC gradient.
- Which GRK the `GRK` condition refers to and how it was perturbed.

## Purpose and limits

These files exist to make the examples runnable and to exercise the protein,
phosphosite and phosphoprotein workflows end to end. They are a real experiment, not
a simulation, so the numbers are representative, but they are a single dataset from
a single instrument and should not be treated as a benchmark.
