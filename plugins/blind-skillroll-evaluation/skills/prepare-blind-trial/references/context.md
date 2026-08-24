# Preparation context

Use one private temporary directory per target. Keep the source clone, Python
environment, caches, and `.skillroll/runs` isolated from other trials. Do not
run repository-provided setup or cleanup scripts merely to prepare SkillRoll.

## Pin what will be tested

Record:

- canonical target URL and exact checked-out commit;
- active skills root and discovered skill paths;
- exact local SkillRoll commit and whether its worktree was clean;
- whether remote freshness was actually checked;
- generated configuration and workflow paths; and
- commands run, excluding secret values.

Do not fetch, pull, switch branches, stash, or alter the user's SkillRoll
worktree without authorization. A dirty local checkout is not the same thing as
its `main` commit; build the recorded commit in a separate clean tree and
isolated environment, or label the trial non-comparable and stop. Do not install
globally.

## Keep setup inert

Use `skillroll init --skills-path <path> --yes` or the equivalent explicit
configuration. Run offline `validate` during preparation. Unset the inference
credential while running setup and validation; record only its variable name.
Do not call `doctor` or `eval` here.

If advisory CI is requested, use SkillRoll's generated workflow. Never replace
an existing path. Snapshot and recheck any colliding workflow byte-for-byte.
Keep generated CI advisory, review the diff and fork-PR guards, and leave
secrets in the configured environment secret rather than repository files. Do
not commit or push the temporary target.
