"""Local compatibility import for the notebook API.

The pip/package source lives in ``proteomicscopylot.notebook_functions``.
Keeping this shim lets local notebooks continue to use:

    from notebook_functions import *
"""

from proteomicscopylot.notebook_functions import *  # noqa: F401,F403

