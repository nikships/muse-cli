# muse-cli agent notes

## Layout

- `src/muse_cli/` is the package: `cli.py` (commands), `gateway.py` (auth,
  Noise transport), plus `routes.json` and `desc0.bin`/`desc1.bin` data files.
- `pyproject.toml` holds all packaging metadata (hatchling). The version is
  read from `__version__` in `src/muse_cli/__init__.py`; that is the only
  place it lives.
- `.github/workflows/publish.yml` tests, builds, and smoke-tests PRs. Every
  push to `main` automatically bumps the patch version, commits and tags
  the tested version, publishes to PyPI, and creates a GitHub release.
- `scripts/bump_version.py` picks the next patch above the package version
  and existing stable release tags. Its regression tests are in
  `tests/test_release.py`. Run all tests with
  `uv run python -m unittest discover -s tests -v`.

## Cutting a release

Normal releases are automatic: push approved changes to `main`, then watch
the `publish.yml` workflow and verify the published version. Do not manually
bump or tag a routine patch release. Never commit or push without the user's
authorization.

The workflow queues release runs (up to GitHub's 100-pending-run limit),
checks out current `main`, bumps the patch, and validates before atomically
pushing the version commit and tag. PR jobs have read-only permissions.
Bot pushes use `GITHUB_TOKEN`, so they do not start another release.
Publishing runs in the same workflow, not a second tag-triggered run.

If `main` changes during validation, the atomic push fails without publishing
or creating a remote tag. Rerun the failed workflow from the beginning to
validate the latest main. Never force-push to bypass this check.

For an explicit major/minor release, agree on the version first. The
automatic increment is always a patch; setting the source version to
`X.Y.Z` before pushing produces at least `X.Y.(Z+1)`.

Manual `v*` tag pushes remain supported for recovery or explicitly requested
releases. The tag must match `__version__`, be unused on PyPI, and point to
the intended tested source. The workflow publishes it without another bump.
Never push both main and a manual release tag for the same change; that
would schedule two releases. `v0.1.0` is a historical GitHub-only tag; PyPI
releases start at 0.2.0.

After publishing, check the PyPI JSON endpoint and install the exact version
into an isolated environment with `uv` to verify `muse-cli --version` and
`muse-cli chat --help`. PyPI may take a minute to show the new release.
Report the PyPI and GitHub release links when done.

### If something goes wrong

- **Failed before the version/tag push:** nothing was published. Fix the
  problem and rerun the workflow from the beginning.
- **Version/tag pushed, but PyPI failed:** rerun only the failed jobs to
  reuse the tested artifacts. Do not rerun the successful version-commit
  job or delete/re-push the tag.
- **Failed after the PyPI upload succeeded** (for example the GitHub release
  step): the version is live. Don't delete the tag. Fix the workflow, and
  create the missing GitHub release by hand if the user wants it.
- **A bad version reached PyPI:** PyPI never allows re-uploading the same
  version. Fix forward with a new patch version. The user can "yank" the bad
  one on pypi.org; don't try to delete it.

### Don't change without the user's say-so

PyPI trusts this repo through a trusted publisher tied to the workflow file
name `publish.yml` and the GitHub environment `pypi`. Renaming either breaks
publishing until the PyPI settings are updated to match.
