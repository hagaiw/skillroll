"""The deliberately local, no-overwrite ``skillroll init`` command."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import TextIO

from skillroll.config import is_safe_inference_url, load_config, parse_skills_path
from skillroll.diagnostics import CommandResult, Diagnostic
from skillroll.github_workflow import (
    DEFAULT_ACTION_REF,
    render_workflow,
    valid_action_ref,
)
from skillroll.initialization.discovery import (
    InitialSkill,
    ScanError,
    scan_skills,
    suggest_skills_path,
)
from skillroll.initialization.templates import (
    render_config,
    render_ignore,
    render_starter_case,
)
from skillroll.initialization.transaction import PlannedWrite, TransactionError, commit
from skillroll.outcomes import Outcome
from skillroll.paths import resolve_child
from skillroll.repository_io import current_directory

_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# OpenRouter's free router is an explicit setup check, not a provider-specific
# runtime adapter or a stable evaluation model.
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_OPENROUTER_MODEL = "openrouter/free"
DEFAULT_API_KEY_ENV = "SKILLROLL_API_KEY"


@dataclass(frozen=True, slots=True)
class InitOptions:
    """All CLI choices, kept separate from scanning and writes."""

    repo: str | None = None
    skills_path: str | None = None
    base_url: str | None = None
    model: str | None = None
    api_key_env: str | None = None
    openrouter_free: bool = False
    starter_evals: str | None = None
    github_workflow: bool = False
    action_ref: str | None = None
    yes: bool = False


def _error(summary: str, action: str, *, affected: str | None = None) -> CommandResult:
    return CommandResult(
        Outcome.ERROR,
        summary,
        (Diagnostic("SCI1001", summary, affected=affected, next_action=action),),
    )


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _ask(input_stream: TextIO, output_stream: TextIO, question: str) -> str:
    output_stream.write(question + " ")
    output_stream.flush()
    return input_stream.readline().strip()


def _choose_path(
    options: InitOptions,
    suggestion: PurePosixPath | None,
    *,
    interactive: bool,
    input_stream: TextIO,
    output_stream: TextIO,
) -> str | None:
    if options.skills_path is not None:
        return options.skills_path
    if suggestion is None:
        return None
    if options.yes:
        return suggestion.as_posix()
    if not interactive:
        return None
    answer = _ask(
        input_stream,
        output_stream,
        f"Use {suggestion.as_posix()!r} as the skills folder? "
        "Press Enter to accept, or enter another relative path:",
    )
    return answer or suggestion.as_posix()


def _read_ignore(path: Path) -> tuple[str | None, CommandResult | None]:
    if not path.exists():
        return None, None
    if path.is_symlink() or path.is_dir():
        return None, _error(
            "SkillRoll cannot safely update .gitignore because it is not an "
            "ordinary file.",
            "Replace .gitignore with a regular UTF-8 text file, then run "
            "skillroll init again.",
            affected=".gitignore",
        )
    try:
        # ``Path.read_text`` applies universal-newline translation.  Preserve
        # the user's original line-ending convention before render_ignore
        # decides how to append the one owned rule.
        return path.read_bytes().decode("utf-8"), None
    except (OSError, UnicodeDecodeError):
        return None, _error(
            "SkillRoll cannot safely read .gitignore as UTF-8 text.",
            "Repair .gitignore as UTF-8 text, then run skillroll init again.",
            affected=".gitignore",
        )


def _ask_optional_setup(
    options: InitOptions,
    skills: tuple[InitialSkill, ...],
    *,
    interactive: bool,
    input_stream: TextIO,
    output_stream: TextIO,
) -> InitOptions:
    """Ask only a terminal user about the choices that flags did not supply."""
    if options.openrouter_free:
        return replace(
            options,
            base_url=DEFAULT_OPENROUTER_BASE_URL,
            model=DEFAULT_OPENROUTER_MODEL,
            api_key_env=options.api_key_env or DEFAULT_API_KEY_ENV,
        )
    if options.yes:
        return options
    if not interactive:
        return options
    chosen = options
    if (
        chosen.base_url is None
        and chosen.model is None
        and chosen.api_key_env is None
        and _ask(
            input_stream,
            output_stream,
            "Connect an OpenAI-compatible model now? [y/N]",
        ).lower()
        in {"y", "yes"}
    ):
        base_url = _ask(
            input_stream,
            output_stream,
            "Endpoint URL:",
        )
        model = _ask(
            input_stream,
            output_stream,
            "Model name:",
        )
        chosen = replace(
            chosen,
            base_url=base_url,
            model=model,
            api_key_env=(
                _ask(
                    input_stream,
                    output_stream,
                    f"API-key environment-variable name [{DEFAULT_API_KEY_ENV}]:",
                )
                or DEFAULT_API_KEY_ENV
            ),
        )
    if chosen.starter_evals is None and (
        _ask(input_stream, output_stream, "Create two starter evals? [y/N]").lower()
        in {"y", "yes"}
    ):
        locations = ", ".join(skill.directory.as_posix() for skill in skills)
        chosen = replace(
            chosen,
            starter_evals=_ask(
                input_stream,
                output_stream,
                f"Which skill should receive them? Available: {locations}",
            ),
        )
    return chosen


def _starter_target(skills_root: Path, value: str) -> Path | None:
    selected = parse_skills_path(value)
    if selected is None:
        return None
    target = resolve_child(skills_root, selected)
    if (
        target is None
        or not target.is_dir()
        or target.is_symlink()
        or not (target / "SKILL.md").is_file()
    ):
        return None
    return target


def run(
    *,
    repo: str | None = None,
    skills_path: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    api_key_env: str | None = None,
    openrouter_free: bool = False,
    starter_evals: str | None = None,
    github_workflow: bool = False,
    action_ref: str | None = None,
    yes: bool = False,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
    environment: Mapping[str, str] | None = None,
) -> CommandResult:
    """Set up config/templates; it never reads keys, runs code, or uses network."""
    del environment  # Explicit seam: setup must not inspect a credential.
    import sys

    options = InitOptions(
        repo=repo,
        skills_path=skills_path,
        base_url=base_url,
        model=model,
        api_key_env=api_key_env,
        openrouter_free=openrouter_free,
        starter_evals=starter_evals,
        github_workflow=github_workflow,
        action_ref=action_ref,
        yes=yes,
    )
    root = current_directory() if repo is None else Path(repo)
    if not root.is_dir() or root.is_symlink():
        return _error(
            "The selected repository directory does not exist or is not a "
            "regular directory.",
            "Choose an existing repository directory and run skillroll init again.",
        )
    root = root.resolve()
    if openrouter_free and (base_url is not None or model is not None):
        return _error(
            "OpenRouter free defaults cannot be combined with --base-url or --model.",
            "Use --openrouter-free by itself, or remove it and supply a custom "
            "--base-url/--model pair.",
        )
    config_path = root / "skillroll.toml"
    if config_path.exists():
        parsed = load_config(root)
        if parsed.value is not None:
            ignore_text, ignore_error = _read_ignore(root / ".gitignore")
            if ignore_error is not None:
                return ignore_error
            rendered_ignore = render_ignore(ignore_text)
            ignore_writes: tuple[PlannedWrite, ...] = ()
            if ignore_text is None or rendered_ignore != ignore_text.encode():
                ignore_writes = (
                    PlannedWrite(
                        root / ".gitignore",
                        rendered_ignore,
                        replace=ignore_text is not None,
                    ),
                )
            if options.github_workflow:
                selected_ref = (
                    DEFAULT_ACTION_REF
                    if options.action_ref is None
                    else options.action_ref
                )
                if not valid_action_ref(selected_ref):
                    return _error(
                        "The GitHub Action reference must look like "
                        "owner/repository@tag.",
                        "Use a released Action reference such as hagaiw/skillroll@v0.",
                        affected=selected_ref,
                    )
                workflow = root / ".github" / "workflows" / "skillroll.yml"
                try:
                    result = commit(
                        ignore_writes
                        + (
                            PlannedWrite(
                                workflow,
                                render_workflow(
                                    selected_ref,
                                    None
                                    if parsed.value.inference is None
                                    else parsed.value.inference.api_key_env,
                                ),
                            ),
                        ),
                        root=root,
                    )
                except TransactionError as error:
                    return _error(
                        str(error),
                        "Review the named workflow file, then run skillroll init "
                        "--github-workflow again.",
                    )
                return CommandResult(
                    Outcome.PASS,
                    "Added .github/workflows/skillroll.yml. Add the configured API "
                    "key as a repository secret before running evals.",
                    data={
                        "repository_root": ".",
                        "changed_paths": tuple(
                            _relative(root, path) for path in result.changed
                        ),
                        "action_ref": selected_ref,
                    },
                )
            if ignore_writes:
                try:
                    result = commit(ignore_writes, root=root)
                except TransactionError as error:
                    return _error(
                        str(error),
                        "Review .gitignore, then run skillroll init again.",
                    )
                return CommandResult(
                    Outcome.PASS,
                    "Updated .gitignore for private SkillRoll artifacts.",
                    data={
                        "repository_root": ".",
                        "changed_paths": tuple(
                            _relative(root, path) for path in result.changed
                        ),
                    },
                )
            return CommandResult(
                Outcome.PASS,
                "SkillRoll is already set up. No files changed.",
                data={"repository_root": ".", "changed_paths": ()},
            )
        return CommandResult(
            Outcome.ERROR,
            "SkillRoll will not edit an existing invalid configuration.",
            parsed.diagnostics,
        )
    try:
        found = scan_skills(root)
    except ScanError as error:
        return _error(
            str(error), "Choose a narrower --skills-path and run skillroll init again."
        )
    if not found:
        return _error(
            "SkillRoll did not find any SKILL.md files in this repository.",
            "Add a skill folder with SKILL.md, or select the correct "
            "repository with --repo.",
        )
    source_input = sys.stdin if input_stream is None else input_stream
    source_output = sys.stdout if output_stream is None else output_stream
    interactive = bool(getattr(source_input, "isatty", lambda: False)())
    if interactive:
        source_output.write(
            "SkillRoll found these skills:\n"
            + "".join(f"  - {item.skill_file.as_posix()}\n" for item in found)
        )
    requested_path = _choose_path(
        options,
        suggest_skills_path(found),
        interactive=interactive,
        input_stream=source_input,
        output_stream=source_output,
    )
    if requested_path is None:
        return _error(
            "SkillRoll needs the one folder that contains your skills "
            "before it can create local setup files.",
            "Use --skills-path PATH, or run skillroll init from an "
            "interactive terminal; use --yes only when the displayed default "
            "is suitable.",
        )
    parsed_path = parse_skills_path(requested_path)
    if parsed_path is None:
        return _error(
            "The skills path must be a portable relative path inside this repository.",
            "Use a path such as skills, plugins, or . for root-level skills.",
            affected=requested_path,
        )
    selected_root = resolve_child(root, parsed_path)
    if (
        selected_root is None
        or not selected_root.is_dir()
        or selected_root.is_symlink()
    ):
        return _error(
            "The selected skills folder is not a regular directory inside "
            "this repository.",
            "Choose an existing non-symlink folder with --skills-path.",
            affected=requested_path,
        )
    try:
        selected_skills = scan_skills(selected_root)
    except ScanError as error:
        return _error(
            str(error), "Choose a narrower --skills-path and run skillroll init again."
        )
    if not selected_skills:
        return _error(
            "The selected skills folder does not contain a regular SKILL.md file.",
            "Choose the folder that contains your skill folders with --skills-path.",
            affected=requested_path,
        )
    options = _ask_optional_setup(
        options,
        selected_skills,
        interactive=interactive,
        input_stream=source_input,
        output_stream=source_output,
    )
    base_url = options.base_url
    model = options.model
    api_key_env = options.api_key_env
    starter_evals = options.starter_evals
    has_endpoint = base_url is not None or model is not None or api_key_env is not None
    if has_endpoint and (
        not base_url
        or not model
        or not is_safe_inference_url(base_url)
        or not (api_key_env is None or _ENVIRONMENT_NAME.fullmatch(api_key_env))
    ):
        return _error(
            "Model endpoint settings need both a safe endpoint URL and a model name.",
            "Supply --base-url HTTPS_URL --model MODEL; optionally add "
            "--api-key-env SAFE_NAME.",
        )
    key_name = api_key_env or (DEFAULT_API_KEY_ENV if has_endpoint else None)
    if options.action_ref is not None and not options.github_workflow:
        return _error(
            "An Action reference is only used when creating the GitHub workflow.",
            "Add --github-workflow, or remove --action-ref.",
            affected=options.action_ref,
        )
    selected_ref = (
        DEFAULT_ACTION_REF if options.action_ref is None else options.action_ref
    )
    if options.github_workflow and not valid_action_ref(selected_ref):
        return _error(
            "The GitHub Action reference must look like owner/repository@tag.",
            "Use a released Action reference such as hagaiw/skillroll@v0.",
            affected=selected_ref,
        )
    ignore_text, ignore_error = _read_ignore(root / ".gitignore")
    if ignore_error is not None:
        return ignore_error
    writes = [
        PlannedWrite(
            config_path,
            render_config(
                parsed_path, base_url=base_url, model=model, api_key_env=key_name
            ),
        )
    ]
    rendered_ignore = render_ignore(ignore_text)
    ignore_path = root / ".gitignore"
    if ignore_text is None or rendered_ignore != ignore_text.encode():
        writes.append(
            PlannedWrite(ignore_path, rendered_ignore, replace=ignore_text is not None)
        )
    generated: list[Path] = []
    if starter_evals is not None:
        target = _starter_target(selected_root, starter_evals)
        if target is None:
            return _error(
                "Starter cases must name one existing skill relative to skills_path.",
                "Use --starter-evals with a skill folder such as review.",
                affected=starter_evals,
            )
        evals = target / "evals"
        if evals.is_symlink():
            return _error(
                "SkillRoll will not create starter cases through a "
                "symbolic-link evals folder.",
                "Replace that link with an ordinary evals folder, then run init again.",
                affected=_relative(root, evals),
            )
        for name in ("first-use", "edge-case"):
            path = evals / f"{name}.eval.md"
            writes.append(PlannedWrite(path, render_starter_case(name)))
            generated.append(path)
    if options.github_workflow:
        writes.append(
            PlannedWrite(
                root / ".github" / "workflows" / "skillroll.yml",
                render_workflow(selected_ref, key_name),
            )
        )
    try:
        result = commit(tuple(writes), root=root)
    except TransactionError as error:
        return _error(
            str(error),
            "Review the named files, then correct the issue and run "
            "skillroll init again.",
        )
    changed = tuple(_relative(root, path) for path in result.changed)
    return CommandResult(
        Outcome.PASS,
        "SkillRoll is ready. No model or repository command was run.",
        data={
            "repository_root": ".",
            "skills_path": parsed_path.as_posix(),
            "inference_configured": has_endpoint,
            "generated_case_paths": tuple(_relative(root, path) for path in generated),
            "changed_paths": changed,
            "github_workflow": options.github_workflow,
        },
    )
