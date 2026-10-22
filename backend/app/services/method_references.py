"""The one list of outside method references CoPYlot cites.

The README's "Methods and citations" table, the report's method sentences and
the manual's reference chapter all cite from this list, so a reference is
corrected in one place. `tests/unit/report/test_method_references.py` checks
that the README table carries exactly these entries.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Reference:
    method: str
    used_for: str
    short: str  # "Author et al. (year)", as cited in running text
    doi: str = ""
    detail: str = ""  # journal details when there is no DOI, or an arXiv id

    @property
    def link(self) -> str:
        return f"https://doi.org/{self.doi}" if self.doi else ""

    def cite(self) -> str:
        """In-text form for the report: 'Bolstad et al. 2003, doi:10.1093/...'."""
        name = self.short.replace(" (", " ").replace(")", "")
        return f"{name}, doi:{self.doi}" if self.doi else f"{name}, {self.detail}"


REFERENCES: dict[str, Reference] = {
    "quantile_normalization": Reference(
        "Quantile normalization", "Normalization across samples",
        "Bolstad et al. (2003)", "10.1093/bioinformatics/19.2.185"),
    "vsn": Reference(
        "Variance-stabilizing normalization", "Normalization delegated to Bioconductor vsn",
        "Huber et al. (2002)", "10.1093/bioinformatics/18.suppl_1.S96"),
    "imputation_quantile": Reference(
        "Low-quantile normal imputation (default)",
        "Missing values drawn around a low quantile of the observed values, in the spirit of MinProb",
        "Lazar et al. (2016)", "10.1021/acs.jproteome.5b00981"),
    "imputation_downshift": Reference(
        "Downshifted-normal imputation", "Missing-value imputation, 'numerical' method (Perseus defaults)",
        "Tyanova et al. (2016)", "10.1038/nmeth.3901"),
    "student_t": Reference(
        "Student's t-test", "Pooled-variance and paired volcano tests",
        "Student (1908)", "10.1093/biomet/6.1.1"),
    "welch_t": Reference(
        "Welch's t-test", "Unequal-variance volcano test",
        "Welch (1947)", "10.1093/biomet/34.1-2.28"),
    "limma": Reference(
        "Moderated t-test (limma)", "Empirical-Bayes moderated volcano tests, delegated to Bioconductor limma",
        "Ritchie et al. (2015)", "10.1093/nar/gkv007"),
    "limma_robust": Reference(
        "Robust empirical-Bayes prior (limma)", "The 'robust' variant of the moderated t-test",
        "Phipson et al. (2016)", "10.1214/16-AOAS920"),
    "benjamini_hochberg": Reference(
        "Benjamini-Hochberg false discovery rate", "Multiple-testing correction",
        "Benjamini & Hochberg (1995)", "10.1111/j.2517-6161.1995.tb02031.x"),
    "tukey_kramer": Reference(
        "Tukey HSD post-hoc test (Tukey-Kramer for unequal group sizes)", "Pairwise comparisons after ANOVA",
        "Tukey (1949); Kramer (1956)", "",
        "Biometrics 5:99-114; Biometrics 12:307-310"),
    "hypergeometric_ora": Reference(
        "Hypergeometric over-representation test", "GO over-representation analysis",
        "Rivals et al. (2007)", "10.1093/bioinformatics/btl633"),
    "gene_ontology": Reference(
        "Gene Ontology", "Term annotations for over-representation analysis",
        "Ashburner et al. (2000); Gene Ontology Consortium (2023)", "10.1038/75556",
        "and doi:10.1093/genetics/iyad031"),
    "localization_class_i": Reference(
        "Class I phosphosite localization (probability >= 0.75)", "Phosphosite coverage classes",
        "Olsen et al. (2006)", "10.1016/j.cell.2006.09.026"),
    "kinase_library": Reference(
        "Kinase-substrate specificity atlases", "Kinase Library input preparation and result visualization",
        "Johnson et al. (2023); Yaron-Barir et al. (2024)", "10.1038/s41586-022-05575-3",
        "and doi:10.1038/s41586-024-07407-y"),
    "umap": Reference(
        "UMAP", "Sample embedding (optional)",
        "McInnes et al. (2018)", "", "arXiv:1802.03426"),
    "tsne": Reference(
        "t-SNE", "Sample embedding (optional)",
        "van der Maaten & Hinton (2008)", "", "J. Mach. Learn. Res. 9:2579-2605"),
}


def cite(key: str) -> str:
    """The in-text citation for one method, as the report prints it."""
    reference = REFERENCES[key]
    text = reference.cite()
    if reference.doi and reference.detail.startswith("and "):
        text += f" {reference.detail}"
    return text


def markdown_table() -> str:
    """The README table, generated from this list (the test compares them)."""
    rows = ["| Method | Where it is used | Reference |", "| --- | --- | --- |"]
    for reference in REFERENCES.values():
        if reference.doi:
            cited = f"{reference.short}, [{reference.doi}]({reference.link})"
            if reference.detail:
                extra = reference.detail.removeprefix("and doi:")
                cited += f"; [{extra}](https://doi.org/{extra})" if extra != reference.detail else f"; {reference.detail}"
        else:
            cited = f"{reference.short}, {reference.detail}"
        rows.append(f"| {reference.method} | {reference.used_for} | {cited} |")
    return "\n".join(rows)
