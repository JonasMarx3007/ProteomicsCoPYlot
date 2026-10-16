# Beta 1 structure review

Reviewed on 2026-10-16 against main commit `5687ec6a` plus the pending Beta 1
version changes, using the local Graphify checkout (extractor cache v0.9.82).

## Map and reproduction

The fresh local map is `local/beta-structure/graphify-out/STRUCTURE.html`;
the same folder contains `graph.json` and `GRAPH_REPORT.md`. These generated
artifacts stay under ignored `local/`; the public architecture-map generator and
its GitHub Pages workflow remain the maintained public view.

Run with the Python environment installed in the Graphify checkout:

```powershell
C:\PythonProject\graphify\.venv\Scripts\python.exe -m graphify extract . --code-only --max-workers 2 --out local/beta-structure --no-cluster
C:\PythonProject\graphify\.venv\Scripts\python.exe -m graphify cluster-only . --graph local/beta-structure/graphify-out/graph.json --no-label --no-viz
C:\PythonProject\graphify\.venv\Scripts\python.exe -m graphify tree --graph local/beta-structure/graphify-out/graph.json --output local/beta-structure/graphify-out/STRUCTURE.html --root . --label "ProteomicsCoPYlot 1.0.0 Beta 1"
```

The scan covered 647 code files and produced 9,787 nodes and 29,743 raw edges.
Clustering produced 28,794 edges and 296 communities. Edge counts differ because
the clustering representation collapses some same-endpoint relationships; these
counts are navigation aids, not a complete dependency or cycle proof.
No semantic API calls were used. Tests are included, so node degrees include test
references as well as runtime relationships.

## Findings

| Area | Evidence | Recommendation |
| --- | --- | --- |
| Assistant orchestration | `AssistantRequest` has 218 incident edges and `_assistant_step()` has 81 in the clustered graph; `scientific_assistant.py` has 2,865 lines. | Review task dispatch and evidence assembly for extraction into focused modules when changing assistant behavior. Preserve the existing schema and safety boundaries; a high degree alone does not justify a rewrite. |
| Session and annotation access | `get_session_id()` has 191 edges and `get_annotation()` has 174. Source files are 133 and 447 lines respectively. | Keep these shared access points centralized. Their broad use is expected; changes should retain session-isolation and cache-invalidation tests. |
| Shared scientific core | `services/copylot_core.py` loads the checkout's `proteomicscopylot/_core.py`, including its frozen-build path. | Preserve the shared core and notebook export design. Moving files would affect frozen builds and reproducible notebook exports. |
| Release metadata | Several packaging ecosystems require equivalent version strings; existing tests previously required literal equality. | Compare normalized versions, include the generated OpenAPI snapshot in consistency checks, and cover beta counters beyond 9. Implemented in this branch. |

The current frontend/API/schema/service/package boundaries remain useful. This
review found no structural change necessary before Beta 1. Assistant decomposition
is a follow-up candidate, not a release blocker or a verified defect.

## Limitations

Graphify partially parsed `frontend/src/components/AssistantFields.tsx` at its inline
TypeScript import type. The TypeScript production build passed; this is an extractor
limitation. It also reported 24 code files without symbols and 44 graph nodes
without a source-file field (including external R package nodes). Dynamic imports,
runtime routing and generated notebook source require source/test verification.
The graph is a snapshot of a working tree; its recorded base commit does not
capture uncommitted changes. Regenerate it when reviewing future changes.
