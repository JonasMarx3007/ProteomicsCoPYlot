# Release versioning and distribution

The next release is **1.0.0 Beta 1**. It is not yet published.

| Surface | Beta 1 version |
| --- | --- |
| GitHub tag | `v1.0.0-beta.1` |
| Frontend package and lockfile | `1.0.0-beta.1` |
| Python project/package, backend, OpenAPI, citation | `1.0.0b1` |
| Python artifact directory | `release/python/1.0.0-beta.1/` |
| Python wheel | `proteomicscopylot-1.0.0b1-py3-none-any.whl` |
| Python source archive | `proteomicscopylot-1.0.0b1.tar.gz` |

Python's PEP 440 spelling and the frontend's SemVer spelling describe the same
release. The `v` prefix belongs only to the Git tag. Increment the beta counter
for each published beta (`beta.2`, `beta.3`, and so on, with Python `b2`, `b3`).
Stable releases omit the suffix: `v1.0.0`, then patch releases such as `v1.0.1`,
compatible feature releases such as `v1.1.0`, and incompatible changes as `v2.0.0`.

## Prepare and publish

1. Update `pyproject.toml`, `proteomicscopylot/_version.py`,
   `backend/app/app_version.py`, `CITATION.cff`, `frontend/package.json`, and both
   root version fields in `frontend/package-lock.json`. Regenerate the OpenAPI
   snapshot with `tools/export_openapi.py`. Update this page and the changelog.
2. Run the repository version/release tests and the frontend production build.
   Review and merge the version pull request into `main`.
3. Fetch the merged `main` and build from a clean checkout of that exact commit.
   Follow [the build instructions](INSTALLATION.md) for Python and executable
   packages. Record the source commit and build environments.
4. Use `ProteomicsCoPYlot-1.0.0-beta.1-Windows.zip` and
   `ProteomicsCoPYlotAI-1.0.0-beta.1-Windows.zip` for Windows bundles, and the
   corresponding `-Linux-x86_64.zip` names for Linux. Distribute complete bundles
   with their source, build requirements, manifests and licence notices.
5. Verify archive integrity, manifest versions/revision/hashes, startup and health
   checks, and the standard versus AI-enabled endpoints. Generate `SHA256SUMS.txt`
   from the final ZIP, wheel and source archive files.
6. Create a draft GitHub release with tag `v1.0.0-beta.1` targeting the built
   commit. Mark it as a prerelease and attach the verified files and checksums.
   Describe platform requirements, AI variants and known limitations, then publish.

Old `pre1.0.0`/RC artifacts are historical builds. Renaming them does not update
their embedded version or source; rebuild them before distributing Beta 1.
Never move a published tag to a different commit or silently replace a published
build; increment the release version instead.
