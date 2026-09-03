---
layout: default
title: SkillRoll documentation
---

# Documentation

SkillRoll is a drop-in eval harness for skills repositories. Start with the
[README](https://github.com/hagaiw/skillroll#readme) to install it and run one
Markdown case.

Then follow the part of the loop you need:

1. [Write or improve an eval](writing-evals.md): describe one behavior and the
   World around it, then keep a supported prompt fix covered.
2. [Configure a model](configuration.md): connect an endpoint and understand
   cost.
3. [Read a result](results.md): inspect the evidence, fix the prompt, and rerun.
4. [Add GitHub Actions](github-actions.md): keep useful cases as advisory
   regression checks.
5. [Review the security model](security.md): understand what each model stage,
   command, and artifact can access.

For a short real-world walkthrough, read
[Testing an AI Helper Before It Deploys to the Wrong Place](https://hagaiw.github.io/skillroll/case-study-testing-skill-decisions/).

Project policies live in
[CONTRIBUTING.md](https://github.com/hagaiw/skillroll/blob/main/.github/CONTRIBUTING.md),
[SECURITY.md](https://github.com/hagaiw/skillroll/blob/main/.github/SECURITY.md),
[SUPPORT.md](https://github.com/hagaiw/skillroll/blob/main/.github/SUPPORT.md),
and
[GOVERNANCE.md](https://github.com/hagaiw/skillroll/blob/main/.github/GOVERNANCE.md).
