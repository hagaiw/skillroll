# Releasing SkillRoll

## Build and eval checks

`CI` runs offline tests on Linux, macOS, and Windows, checks 100% statement and
branch coverage plus function coverage, Ruff, strict mypy, and Action syntax,
and builds and tests the package. `SkillRoll` validates changed evals on PRs.
Owner-authored, same-repository PRs run the affected live cases when the reviewed
impact plan selects cases and `SKILLROLL_LIVE_EVAL=true`, using the
`skillroll-eval` environment. Its manual
workflow can evaluate a reviewed revision. These model-backed runs are separate
from release automation and can spend inference budget.

## Prepare a version

Prepare and review the release candidate in a PR before publishing:

1. Set `src/skillroll/_version.py` to the new `MAJOR.MINOR.PATCH` or
   `MAJOR.MINOR.PATCHrcN` version.
2. Update all `plugins/*/.claude-plugin/plugin.json` versions and exact
   `flow-runner` dependency versions together. Refresh `uv.lock` with `uv lock`.
3. Update checked-in Action references and release documentation as appropriate.
4. Run the installed-wheel live E2E and isolated Claude dependency-install
   checks. Record actual results for this version in `release-gates.toml`.
   Both gates must be `PASS`; do not copy old evidence to a new version.
5. Require/review the PR's CI and relevant live eval results before merging.

Automation publishes the prepared version; it does not choose a bump or invent
external gate evidence. The existing PyPI trusted publisher must allow
`.github/workflows/release.yml` and the `pypi` environment. Keep environment
reviewers and branch protections configured for the desired release policy.

## Release from GitHub

After merging the candidate, open **Actions → Release → Run workflow**:

- Select **main**.
- Enable **publish**.
- Enter the exact prepared **version**, without the `v` prefix.

Leaving **publish** off runs an offline rehearsal only. Rehearsals may run on
other branches. They upload artifacts and readiness evidence without publishing.

## Release on merge

Create a repository label named **release** and apply it to the prepared release
PR before merging into `main`. A merged, labeled PR from this repository starts
publication automatically, using its exact merge commit. An unlabeled PR,
closed-but-unmerged PR, or fork PR does not publish. Adding the label after merge
does not trigger a release; use the manual workflow instead.

## Publication and recovery

Every release builds and tests the selected revision, validates all evals offline,
checks package/plugin version agreement, verifies wheel metadata and checksums,
and checks the version-bound external gates. Offline validation proves structure,
not behavior. As in the existing SkillRoll workflow, `INCOMPLETE` is accepted
when repository-declared commands are deliberately not run. Publishing requests fail if readiness is blocked. Evidence records
the actual checked-out commit.

The workflow attests the built artifacts, publishes those artifacts to PyPI
through the protected `pypi` environment, then creates `vVERSION` and a GitHub
release with generated notes. Release candidates are marked as prereleases.
Publication runs are serialized; a running release is never cancelled by a new
request. Rehearsals and closed PRs that do not publish use separate groups, so
they cannot displace a queued publication. GitHub may replace an older pending run with a newer pending run, so
check the Actions queue when merging multiple release PRs close together.

The GitHub release is created with `GITHUB_TOKEN`, so it does not trigger another
Release or SkillRoll run. Offline eval validation is included in the build for
this reason. Manually publishing a GitHub release still invokes the existing
release-event path, which verifies the tag matches the package version.

Tags are never moved: an existing tag must point at the built commit. Versions
already uploaded to PyPI cannot be overwritten. If publication fails, inspect
the failed job and evidence before retrying. If only GitHub release creation
fails after PyPI succeeds, use **Re-run failed jobs**, not a fresh publication
run. This retries release creation without uploading the package again.
