# Campaign context

Use a narrow artifact at each boundary:

1. Selection returns canonical repositories, immutable target SHAs, skills
   roots, active skill counts, rationale, and freshness limitations.
2. Preparation adds the exact clean local SkillRoll-main SHA, isolated paths,
   generated files, and offline validation evidence.
3. Blind authoring returns frozen case paths and hashes without prior outcomes.
4. Live running returns immutable run evidence and classifications.

In the SkillRoll repository, select the `blind-live` model profile for these
multi-step cases. In an adopter repository, use an equivalently reviewed named
stable model rather than a free or changing route.

Parallelize independent targets when the platform and authorization allow it.
Do not share one target's outcomes with another target's authoring worker. The
coordinator may receive all completed artifacts for final synthesis.

## Final report

Name every target and exact revision, active skill scope, selected cases, live
model, and SkillRoll revision. Give exact `PASS`/`FAIL`/`ERROR` totals and link
or identify run artifacts. Separate:

- setup or case-authoring hiccups and corrected reruns;
- genuine target-skill behavior failures;
- provider or timeout errors; and
- isolated SkillRoll product defects and any verified fix.

Say what did not run. Never call offline validation a live trial, a single pass
coverage, a corrected rerun a replacement for the original, or a mixed campaign
green. Keep CI advisory until repeated evidence supports a stronger gate.
