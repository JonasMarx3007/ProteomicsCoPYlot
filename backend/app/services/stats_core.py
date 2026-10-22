"""The arithmetic every differential test in the backend shares.

Benjamini-Hochberg, the pooled two-sample standard error, Welch-Satterthwaite
for a sum of independent group means, and the two-sided t p-value, verified
against scipy/statsmodels in tests/reference/test_stats_core.py. They live in
`proteomicscopylot/_core.py`, the one copy the app and the pip package share.
"""
from __future__ import annotations

# <shared-core>
from app.services.copylot_core import (
    bh_adjust, match_sites_to_proteins, pooled_se_df, protein_corrected_site_changes, satterthwaite,
    split_tokens, two_sided_t_pvalues,
)
# </shared-core>

__all__ = ["bh_adjust", "match_sites_to_proteins", "pooled_se_df", "protein_corrected_site_changes",
           "satterthwaite", "split_tokens", "two_sided_t_pvalues"]
