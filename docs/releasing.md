# Releasing SkillRoll

## Release from GitHub

Open **Actions → Release new version → Run workflow**, select **main**, and run.
The default is a patch release. Choose `minor` or `major`, or enter an explicit
new stable `MAJOR.MINOR.PATCH` version without `v`.

The complete workflow rejects prerelease versions before changing candidate files.
Python's `rcN` format is incompatible with Claude's dependency constraints;
prerelease automation requires an explicit Python-to-SemVer mapping first.

The workflow prepares synchronized package and plugin versions, updates pinned
references, runs the offline quality gates, and builds the wheel and source
archive. It then tests that exact wheel with a live adoption eval and checks
Claude's isolated dependency installation. Only passing, non-skipped results
produce fresh release evidence. It commits the prepared version and evidence,
atomically creates the package and plugin tags, and automatically starts the
**Release** publisher at the immutable version tag. The publisher verifies the
original checked artifacts, attests them, publishes to PyPI, and creates the
GitHub release. The first workflow waits for that publication result.

No separate version-preparation PR or manually edited PASS record is needed.
Configured environment reviewers may still require approval. Live checks spend
inference budget. Enable **dry_run** to prepare and check the build without live
checks, remote writes, tags, or publication; its gates remain blocked.

## One-time configuration

- In **release-write**, configure `RELEASE_TOKEN` for this repository with
  **Contents**, **Workflows**, and **Actions** write permissions. Use a dedicated
  account/token allowed to make the release commit under your existing branch
  rules. The built-in token cannot update pinned workflow references or start
  the publisher this way. The workflow does not disable branch protection.
- In **skillroll-eval**, configure `SKILLROLL_API_KEY` for the installed-wheel
  live adoption test. The isolated Claude install check does not require a
  Claude inference key.
- Keep the PyPI trusted publisher configured for `.github/workflows/release.yml`
  and the **pypi** environment. Keep any desired environment reviewers and tag
  policies configured. Allow the publisher to run at version tags.

The release write credential is checked before live inference. Repository code
runs in separate jobs without that credential; the write job only persists the
verified Git bundle and dispatches publication. The PyPI job has its own OIDC
permission and executes no repository code.

## Release on merge

Create the **release** label and apply it to a same-repository PR before merging
into `main`. Its merge triggers the same complete flow with a patch increment.
Unlabeled, unmerged, or fork PRs do not release. Adding a label after merging does
not trigger a release; use **Run workflow** instead. Use the manual form for a
minor, major, or explicit release candidate version.

## Checks and concurrency

Every new release runs the complete offline quality gates and both release
integration checks. It validates all eval structure without executing declared
repository commands; `INCOMPLETE` is accepted for those commands. Structural
validation does not prove model behavior. Release integration checks are bounded
checks, rather than the full live repository eval suite.

The installed package is imported from a clean environment. Its bytes are
carried unchanged into publication, with wheel digests, test reports, and the
final tagged source SHA recorded in release evidence. A checksum manifest frozen
before the integration checks is compared with the complete artifact inventory
before either gate can be marked PASS. The final evidence-only
commit changes a file excluded from both distributions. Publication runs are
serialized and are never cancelled by a new release. GitHub can replace older
pending runs, so inspect the queue before requesting several releases together.

Normal PR CI remains separate. Main pushes run CI, while the package and plugin
tag pushes do not duplicate the offline CI matrix.

## Recovery and advanced publication

Failures before persistence leave main, tags, and PyPI unchanged. If main moves
while the checks run, persistence fails; start a new run against the updated
main. Atomic persistence never moves an existing release tag and checks that
main still matches the selected base. Repository rules can reject the push.

Git and PyPI publication are separate operations. If dispatch or publication
fails after persistence, the version commit and tags remain. Inspect the linked
run and its evidence before retrying. Re-run failed jobs when the publisher has
already started. Re-running the entire parent release is not a general recovery
mechanism: uploads and release creation cannot safely be repeated indiscriminately.
If only GitHub release creation failed, this retries that job
without uploading to PyPI again. PyPI versions cannot be overwritten; a partial
upload needs investigation rather than blindly repeating publication.

If dispatch itself failed, the advanced **Release → Run workflow** form can
publish the existing version tag: enable `publish`, enter its exact `version`,
and enter the successful preparation run ID as `candidate_run`. This verifies
that run's successful preparation/gate jobs, matching evidence, source SHA, and
artifact hashes before using its artifacts. Artifacts must still be retained.

The advanced form also retains offline rehearsal (`publish` off) and publication
of a separately prepared version from main with version-bound PASS evidence.
Manually publishing a GitHub release invokes the release-event path and checks
that the tag matches the canonical package version. These are recovery and
advanced paths; **Release new version** is the normal complete release entry.
