"""Contract tests for the safe, local initialization journey."""

from __future__ import annotations

import io
import json
import os
import tomllib
from pathlib import Path, PurePosixPath

import pytest
from conftest import run_module

from skillroll import cli
from skillroll.commands import doctor, evaluate, initialize
from skillroll.commands.initialize import (
    DEFAULT_API_KEY_ENV,
    DEFAULT_OPENROUTER_BASE_URL,
    DEFAULT_OPENROUTER_MODEL,
    InitOptions,
    run,
)
from skillroll.config import is_safe_inference_url, load_config
from skillroll.initialization import discovery as initial_discovery
from skillroll.initialization import transaction
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
from skillroll.outcomes import Outcome


def make_skill(root: Path, relative: str = "skills/review") -> Path:
    skill = root / relative
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# Review\n", encoding="utf-8")
    return skill


class TerminalOutput(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_missing_or_empty_setup_mascot_does_not_block_init(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class MissingMascot:
        def joinpath(self, *_: str) -> MissingMascot:
            return self

        def read_text(self, *, encoding: str) -> str:
            del encoding
            raise OSError("missing")

    monkeypatch.setattr(cli.resources, "files", lambda _: MissingMascot())
    assert cli._setup_mascot() == ""

    repository = tmp_path / "repository"
    make_skill(repository)
    output = TerminalOutput()
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(cli, "_setup_mascot", lambda: "")

    assert (
        cli.main(
            ["init", "--repo", str(repository), "--skills-path", "skills"],
            stdout=output,
        )
        == 0
    )
    assert output.getvalue().startswith("PASS — SkillRoll is ready.")


def test_fresh_interactive_init_displays_packaged_mascot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repository"
    make_skill(repository)
    output = TerminalOutput()
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)

    assert (
        cli.main(
            ["init", "--repo", str(repository), "--skills-path", "skills"],
            stdout=output,
        )
        == 0
    )
    rendered = output.getvalue()
    assert "\x1b[" in rendered
    assert "SkillRoll is ready" in rendered


def test_setup_mascot_stays_out_of_noninteractive_and_json_output(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    make_skill(repository)
    output = io.StringIO()
    assert (
        cli.main(
            [
                "--output=json",
                "init",
                "--repo",
                str(repository),
                "--skills-path",
                "skills",
            ],
            stdout=output,
        )
        == 0
    )
    assert "\x1b[" not in output.getvalue()
    json.loads(output.getvalue())


def test_root_skills_path_is_a_narrow_valid_config_value(tmp_path: Path) -> None:
    make_skill(tmp_path, "root-skill")
    (tmp_path / "skillroll.toml").write_text(
        'schema_version = 1\nskills_path = "."\n', encoding="utf-8"
    )
    assert load_config(tmp_path).value is not None


def test_init_creates_minimal_local_files_and_templates(tmp_path: Path) -> None:
    repository = tmp_path / "a repo with spaces"
    skill = make_skill(repository)
    result = run(
        repo=str(repository),
        skills_path="skills",
        starter_evals="review",
        environment={"SKILLROLL_API_KEY": "never-read"},
    )
    assert result.outcome is Outcome.PASS
    assert result.data["changed_paths"] == (
        "skillroll.toml",
        ".gitignore",
        "skills/review/evals/first-use.eval.md",
        "skills/review/evals/edge-case.eval.md",
    )
    assert (repository / "skillroll.toml").read_text(encoding="utf-8") == (
        'schema_version = 1\nskills_path = "skills"\n'
    )
    assert (repository / ".gitignore").read_text(
        encoding="utf-8"
    ) == ".skillroll/runs/\n"
    starter = (skill / "evals" / "first-use.eval.md").read_text(encoding="utf-8")
    assert "Write the request or task that triggers the skill" in starter
    assert "Dungeon Master" in starter


def test_init_is_idempotent_and_never_replaces_configuration(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    make_skill(repository)
    assert (
        run(repo=str(repository), skills_path="skills", starter_evals="review").outcome
        is Outcome.PASS
    )
    before = (repository / "skillroll.toml").read_bytes()
    repeat = run(repo=str(repository), skills_path="skills", starter_evals="review")
    assert repeat.outcome is Outcome.PASS
    assert repeat.data["changed_paths"] == ()
    assert (repository / "skillroll.toml").read_bytes() == before


def test_init_requires_explicit_noninteractive_choice_and_yes_uses_default(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    make_skill(repository)
    blocked = run(
        repo=str(repository), input_stream=io.StringIO(), output_stream=io.StringIO()
    )
    assert blocked.outcome is Outcome.ERROR
    assert not (repository / "skillroll.toml").exists()
    allowed = run(
        repo=str(repository),
        yes=True,
        input_stream=io.StringIO(),
        output_stream=io.StringIO(),
    )
    assert allowed.outcome is Outcome.PASS
    configured = load_config(repository).value
    assert configured is not None
    assert configured.inference is None


def test_init_validates_endpoint_pair_and_never_writes_partial_setup(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    make_skill(repository)
    result = run(
        repo=str(repository), skills_path="skills", base_url="https://example.test/v1"
    )
    assert result.outcome is Outcome.ERROR
    assert not (repository / "skillroll.toml").exists()


def test_init_adds_generic_inference_without_accessing_a_key(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    make_skill(repository)
    result = run(
        repo=str(repository),
        skills_path="skills",
        base_url="https://example.test/v1",
        model="vendor/cheap-model",
    )
    assert result.outcome is Outcome.PASS
    content = (repository / "skillroll.toml").read_text(encoding="utf-8")
    assert DEFAULT_API_KEY_ENV in content
    assert "secret" not in content


def test_init_explicitly_adds_openrouter_free_without_accessing_a_key(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    make_skill(repository)
    result = run(
        repo=str(repository),
        skills_path="skills",
        openrouter_free=True,
    )
    assert result.outcome is Outcome.PASS
    configured = load_config(repository).value
    assert configured is not None
    assert configured.inference is not None
    assert configured.inference.base_url == DEFAULT_OPENROUTER_BASE_URL
    assert configured.inference.model == DEFAULT_OPENROUTER_MODEL
    assert configured.inference.api_key_env == DEFAULT_API_KEY_ENV
    custom = tmp_path / "custom-key"
    make_skill(custom)
    custom_result = run(
        repo=str(custom),
        skills_path="skills",
        api_key_env="CUSTOM_OPENROUTER_KEY",
        openrouter_free=True,
    )
    assert custom_result.outcome is Outcome.PASS
    custom_config = load_config(custom).value
    assert custom_config is not None
    assert custom_config.inference is not None
    assert custom_config.inference.api_key_env == "CUSTOM_OPENROUTER_KEY"


def test_init_rejects_openrouter_free_with_custom_endpoint(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    make_skill(repository)
    result = run(
        repo=str(repository),
        skills_path="skills",
        base_url="https://example.test/v1",
        model="example/model",
        openrouter_free=True,
    )
    assert result.outcome is Outcome.ERROR
    assert not (repository / "skillroll.toml").exists()


def test_init_rejects_existing_starter_work_before_changing_anything(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    skill = make_skill(repository)
    (skill / "evals").mkdir()
    target = skill / "evals" / "edge-case.eval.md"
    target.write_text("mine", encoding="utf-8")
    result = run(repo=str(repository), skills_path="skills", starter_evals="review")
    assert result.outcome is Outcome.ERROR
    assert target.read_text(encoding="utf-8") == "mine"
    assert not (repository / "skillroll.toml").exists()


def test_templates_and_suggestion_are_stable_and_portable() -> None:
    skills = (
        InitialSkill(PurePosixPath("plugins/a/SKILL.md")),
        InitialSkill(PurePosixPath("plugins/b/SKILL.md")),
    )
    assert suggest_skills_path(skills).as_posix() == "plugins"
    assert (
        render_config(PurePosixPath(".")) == b'schema_version = 1\nskills_path = "."\n'
    )
    assert render_ignore("# local\r\n") == b"# local\r\n.skillroll/runs/\r\n"
    assert render_ignore(".skillroll/runs/\n") == b".skillroll/runs/\n"
    assert b"Success criteria" in render_starter_case("edge-case")


def test_templates_escape_toml_controls_and_common_root_stops_at_mismatch() -> None:
    content = render_config(
        PurePosixPath("skills"),
        base_url="https://example.test/v1",
        model="quoted\\model\nwith\ttab",
        api_key_env="KEY",
    )
    assert b'model = "quoted\\\\model\\nwith\\ttab"' in content
    assert tomllib.loads(content.decode())["inference"]["model"] == (
        "quoted\\model\nwith\ttab"
    )
    root = suggest_skills_path(
        (
            InitialSkill(PurePosixPath("a/one/shared/SKILL.md")),
            InitialSkill(PurePosixPath("a/two/shared/SKILL.md")),
        )
    )
    assert root == PurePosixPath("a")
    assert suggest_skills_path(
        (
            InitialSkill(PurePosixPath("same/path/SKILL.md")),
            InitialSkill(PurePosixPath("same/path/SECOND.md")),
        )
    ) == PurePosixPath("same/path")


def test_init_json_and_cli_flags_are_machine_readable(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    make_skill(repository)
    completed = run_module(
        "--output=json",
        "init",
        "--repo",
        str(repository),
        "--skills-path",
        "skills",
        "--starter-evals",
        "review",
    )
    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["data"]["skills_path"] == "skills"
    assert completed.stderr == ""


def test_local_command_help_and_missing_inference_explain_the_next_step(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    make_skill(repository)
    assert (
        run(repo=str(repository), skills_path="skills", starter_evals="review").outcome
        is Outcome.PASS
    )
    doctor_result = doctor.run(repo=str(repository), environment={})
    assert doctor_result.outcome is Outcome.ERROR
    assert "setup is complete" in doctor_result.summary
    assert (
        "base_url, api_key_env, and either model or profiles"
        in (doctor_result.diagnostics[0].details[0])
    )
    eval_result = evaluate.run(repo=str(repository), environment={})
    assert eval_result.outcome is Outcome.ERROR
    assert eval_result.diagnostics[0].next_action is not None
    assert "skillroll doctor" in eval_result.diagnostics[0].next_action
    configured = tmp_path / "configured"
    make_skill(configured)
    assert (
        run(
            repo=str(configured),
            skills_path="skills",
            starter_evals="review",
            base_url="https://example.test/v1",
            model="example/model",
            api_key_env="KEY",
        ).outcome
        is Outcome.PASS
    )
    missing_key = evaluate.run(repo=str(configured), environment={})
    assert missing_key.outcome is Outcome.ERROR
    assert missing_key.diagnostics[0].next_action is not None
    assert "CI secret" in missing_key.diagnostics[0].next_action


@pytest.mark.parametrize(
    ("value", "valid"),
    [
        ("https://example.test/v1", True),
        ("http://localhost:8080/v1", True),
        ("http://example.test", False),
        ("https://user@example.test", False),
        ("https://example.test?x=y", False),
    ],
)
def test_endpoint_validation_is_the_same_safe_policy(value: str, valid: bool) -> None:
    assert is_safe_inference_url(value) is valid


def test_prompt_helpers_cover_default_edit_and_noninteractive_choices() -> None:
    out = io.StringIO()
    assert initialize._ask(io.StringIO(" answer \n"), out, "Question?") == "answer"
    assert out.getvalue() == "Question? "
    default = PurePosixPath("skills")
    assert (
        initialize._choose_path(
            InitOptions(skills_path="plugins"),
            default,
            interactive=False,
            input_stream=io.StringIO(),
            output_stream=io.StringIO(),
        )
        == "plugins"
    )
    assert (
        initialize._choose_path(
            InitOptions(yes=True),
            default,
            interactive=False,
            input_stream=io.StringIO(),
            output_stream=io.StringIO(),
        )
        == "skills"
    )


def test_interactive_optional_setup_has_flag_equivalent_choices() -> None:
    skills = (InitialSkill(PurePosixPath("review/SKILL.md")),)
    default = PurePosixPath("skills")
    prompted = initialize._ask_optional_setup(
        InitOptions(),
        skills,
        interactive=True,
        input_stream=io.StringIO(
            "yes\nhttps://example.test/v1\nmodel\n\nyes\nreview\n"
        ),
        output_stream=io.StringIO(),
    )
    assert prompted.base_url == "https://example.test/v1"
    assert prompted.model == "model"
    assert prompted.api_key_env == DEFAULT_API_KEY_ENV
    assert prompted.starter_evals == "review"
    unchanged = initialize._ask_optional_setup(
        InitOptions(yes=True),
        skills,
        interactive=True,
        input_stream=io.StringIO("this must not be read"),
        output_stream=io.StringIO(),
    )
    assert unchanged == InitOptions(yes=True)
    explicit = InitOptions(
        base_url="https://example.test/v1", model="example/model", yes=True
    )
    assert (
        initialize._ask_optional_setup(
            explicit,
            skills,
            interactive=True,
            input_stream=io.StringIO("this must not be read"),
            output_stream=io.StringIO(),
        )
        == explicit
    )
    defaults_output = io.StringIO()
    defaults = initialize._ask_optional_setup(
        InitOptions(starter_evals="review"),
        skills,
        interactive=True,
        input_stream=io.StringIO("\n"),
        output_stream=defaults_output,
    )
    assert defaults == InitOptions(starter_evals="review")
    assert "OpenAI-compatible model" in defaults_output.getvalue()
    assert "OpenRouter" not in defaults_output.getvalue()
    declined = initialize._ask_optional_setup(
        InitOptions(starter_evals="review"),
        skills,
        interactive=True,
        input_stream=io.StringIO("n\n"),
        output_stream=io.StringIO(),
    )
    assert declined == InitOptions(starter_evals="review")
    unclear = initialize._ask_optional_setup(
        InitOptions(starter_evals="review"),
        skills,
        interactive=True,
        input_stream=io.StringIO("maybe\n"),
        output_stream=io.StringIO(),
    )
    assert unclear == InitOptions(starter_evals="review")
    assert (
        initialize._choose_path(
            InitOptions(),
            None,
            interactive=True,
            input_stream=io.StringIO(),
            output_stream=io.StringIO(),
        )
        is None
    )
    assert (
        initialize._choose_path(
            InitOptions(),
            default,
            interactive=False,
            input_stream=io.StringIO(),
            output_stream=io.StringIO(),
        )
        is None
    )
    assert (
        initialize._choose_path(
            InitOptions(),
            default,
            interactive=True,
            input_stream=io.StringIO("other\n"),
            output_stream=io.StringIO(),
        )
        == "other"
    )
    assert (
        initialize._choose_path(
            InitOptions(),
            default,
            interactive=True,
            input_stream=io.StringIO("\n"),
            output_stream=io.StringIO(),
        )
        == "skills"
    )


def test_ignore_and_starter_helpers_reject_unsafe_targets(tmp_path: Path) -> None:
    directory = tmp_path / ".gitignore"
    directory.mkdir()
    assert initialize._read_ignore(directory)[1] is not None
    bad = tmp_path / "bad-ignore"
    bad.write_bytes(b"\xff")
    assert initialize._read_ignore(bad)[1] is not None
    skills = tmp_path / "skills"
    make_skill(tmp_path)
    assert initialize._starter_target(skills, "../no") is None
    assert initialize._starter_target(skills, "missing") is None
    assert initialize._starter_target(skills, "review") == skills / "review"


def test_init_reports_every_safe_early_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert (
        run(repo=str(tmp_path / "missing"), skills_path="skills").outcome
        is Outcome.ERROR
    )
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "skillroll.toml").write_text("not = [toml", encoding="utf-8")
    assert run(repo=str(bad), skills_path="skills").outcome is Outcome.ERROR
    monkeypatch.setattr(
        initialize, "scan_skills", lambda _: (_ for _ in ()).throw(ScanError("bounded"))
    )
    assert run(repo=str(tmp_path), skills_path="skills").outcome is Outcome.ERROR


def test_init_reports_invalid_selected_layout_and_side_effect_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repository"
    make_skill(repository)
    assert run(repo=str(repository), skills_path="../escape").outcome is Outcome.ERROR
    assert run(repo=str(repository), skills_path="missing").outcome is Outcome.ERROR
    assert (
        run(repo=str(repository), skills_path="skills", starter_evals="missing").outcome
        is Outcome.ERROR
    )
    monkeypatch.setattr(
        initialize,
        "commit",
        lambda _, **__: (_ for _ in ()).throw(
            transaction.TransactionError("disk full")
        ),
    )
    assert run(repo=str(repository), skills_path="skills").outcome is Outcome.ERROR


class _TTY(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_init_interactive_scan_and_later_scan_or_ignore_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repository"
    make_skill(repository)
    prompted = run(
        repo=str(repository),
        input_stream=_TTY("\n"),
        output_stream=io.StringIO(),
    )
    assert prompted.outcome is Outcome.PASS
    repository_two = tmp_path / "repository-two"
    make_skill(repository_two)
    original_scan = initialize.scan_skills
    calls = 0

    def fail_on_second(path: Path) -> tuple[InitialSkill, ...]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ScanError("later scan")
        return original_scan(path)

    monkeypatch.setattr(initialize, "scan_skills", fail_on_second)
    assert run(repo=str(repository_two), skills_path="skills").outcome is Outcome.ERROR
    selected_calls = 0

    def empty_on_second(_: Path) -> tuple[InitialSkill, ...]:
        nonlocal selected_calls
        selected_calls += 1
        return (
            (InitialSkill(PurePosixPath("a/SKILL.md")),) if selected_calls == 1 else ()
        )

    monkeypatch.setattr(initialize, "scan_skills", empty_on_second)
    assert run(repo=str(repository_two), skills_path="skills").outcome is Outcome.ERROR
    monkeypatch.undo()
    repository_three = tmp_path / "repository-three"
    make_skill(repository_three)
    (repository_three / ".gitignore").mkdir()
    assert (
        run(repo=str(repository_three), skills_path="skills").outcome is Outcome.ERROR
    )


def test_init_handles_existing_ignore_rule_and_evals_link(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    make_skill(repository)
    (repository / ".gitignore").write_text(".skillroll/runs/\n", encoding="utf-8")
    assert run(repo=str(repository), skills_path="skills").outcome is Outcome.PASS
    assert (repository / ".gitignore").read_text(
        encoding="utf-8"
    ) == ".skillroll/runs/\n"
    repository_two = tmp_path / "repository-two"
    linked_skill = make_skill(repository_two)
    destination = repository_two / "real-evals"
    destination.mkdir()
    try:
        os.symlink(destination, linked_skill / "evals")
    except OSError:
        pytest.skip("This platform does not permit test symlinks")
    result = run(repo=str(repository_two), skills_path="skills", starter_evals="review")
    assert result.outcome is Outcome.ERROR


def test_scan_skips_hidden_and_links_and_has_bounded_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repository"
    make_skill(root, "visible/skill")
    make_skill(root, ".hidden/skill")
    link = root / "linked"
    try:
        os.symlink(root / "visible", link)
    except OSError:
        pytest.skip("This platform does not permit test symlinks")
    assert [item.skill_file.as_posix() for item in scan_skills(root)] == [
        "visible/skill/SKILL.md"
    ]
    monkeypatch.setattr(initial_discovery, "_MAX_ENTRIES", 0)
    with pytest.raises(ScanError, match="10,000"):
        scan_skills(root)
    monkeypatch.setattr(initial_discovery, "_MAX_ENTRIES", 10_000)
    monkeypatch.setattr(initial_discovery, "_MAX_DEPTH", 0)
    with pytest.raises(ScanError, match="deeper"):
        scan_skills(root)


def test_scan_ignores_untrusted_observation_and_suggestion_edges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repository"
    make_skill(root)
    monkeypatch.setattr(initial_discovery, "is_within", lambda *_: False)
    assert scan_skills(root) == ()
    assert suggest_skills_path(()) is None
    assert (
        suggest_skills_path((InitialSkill(PurePosixPath("SKILL.md")),)).as_posix()
        == "."
    )
    split = (
        InitialSkill(PurePosixPath("a/SKILL.md")),
        InitialSkill(PurePosixPath("b/SKILL.md")),
    )
    assert suggest_skills_path(split).as_posix() == "."


def test_scan_reports_impossible_outside_relative_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repository"
    make_skill(root)
    path_type = type(root / "skills" / "review" / "SKILL.md")
    original = path_type.relative_to

    def impossible(self: Path, other: Path) -> Path:
        if self.name == "SKILL.md":
            raise ValueError("outside")
        return original(self, other)

    monkeypatch.setattr(path_type, "relative_to", impossible)
    with pytest.raises(ScanError, match="outside"):
        scan_skills(root)


def test_transaction_writes_replaces_conflicts_and_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fresh = tmp_path / "nested" / "fresh"
    old = tmp_path / "ignore"
    old.write_bytes(b"old")
    result = transaction.commit(
        (
            transaction.PlannedWrite(fresh, b"new"),
            transaction.PlannedWrite(old, b"replacement", replace=True),
        )
    )
    assert result.changed == (fresh, old)
    assert fresh.read_bytes() == b"new"
    assert old.read_bytes() == b"replacement"
    with pytest.raises(transaction.TransactionError, match="will not replace"):
        transaction.commit((transaction.PlannedWrite(fresh, b"no"),))
    first = tmp_path / "first"
    second = tmp_path / "second"
    real = transaction._write_new
    calls = 0

    def fail_second(path: Path, content: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected")
        real(path, content)

    monkeypatch.setattr(transaction, "_write_new", fail_second)
    with pytest.raises(transaction.TransactionError, match="injected"):
        transaction.commit(
            (
                transaction.PlannedWrite(first, b"one"),
                transaction.PlannedWrite(second, b"two"),
            )
        )
    assert not first.exists()
    assert not second.exists()


def test_transaction_restores_replaced_file_and_reports_cleanup_uncertainty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = tmp_path / "old"
    old.write_bytes(b"before")
    late = tmp_path / "late"
    real_new = transaction._write_new

    def fail_late(path: Path, content: bytes) -> None:
        if path == late:
            raise OSError("late failure")
        real_new(path, content)

    writes = 0

    def fail_second(path: Path, content: bytes) -> None:
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError("late failure")
        real_new(path, content)

    monkeypatch.setattr(transaction, "_write_new", fail_late)
    with pytest.raises(transaction.TransactionError, match="late failure"):
        transaction.commit(
            (
                transaction.PlannedWrite(old, b"after", replace=True),
                transaction.PlannedWrite(late, b"no"),
            )
        )
    assert old.read_bytes() == b"before"
    created = tmp_path / "created"
    second = tmp_path / "second"
    monkeypatch.setattr(transaction, "_write_new", fail_second)
    original_unlink = type(created).unlink

    def fail_cleanup(self: Path, *args: object, **kwargs: object) -> None:
        if self == created:
            raise OSError("cannot remove")
        original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(type(created), "unlink", fail_cleanup)
    with pytest.raises(transaction.TransactionError, match="Review these files"):
        transaction.commit(
            (
                transaction.PlannedWrite(created, b"created"),
                transaction.PlannedWrite(second, b"second"),
            )
        )


def test_transaction_rejects_outside_and_symbolic_link_parents_without_writing(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = root / "linked"
    try:
        os.symlink(outside, link)
    except OSError:
        pytest.skip("This platform does not permit test symlinks")
    with pytest.raises(transaction.TransactionError, match="symbolic-link folder"):
        transaction.commit(
            (transaction.PlannedWrite(link / "created", b"no"),), root=root
        )
    assert not (outside / "created").exists()
    with pytest.raises(transaction.TransactionError, match="outside"):
        transaction.commit(
            (transaction.PlannedWrite(outside / "created", b"no"),), root=root
        )
    occupied = root / "existing"
    occupied.write_text("keep", encoding="utf-8")
    with pytest.raises(transaction.TransactionError) as error:
        transaction.commit((transaction.PlannedWrite(occupied, b"no"),), root=root)
    assert str(root) not in str(error.value)


def test_transaction_rejects_invalid_parent_and_link_file_targets(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    not_a_folder = root / "file"
    not_a_folder.write_text("x", encoding="utf-8")
    with pytest.raises(transaction.TransactionError, match="not a folder"):
        transaction.commit(
            (transaction.PlannedWrite(not_a_folder / "child", b"no"),), root=root
        )
    with pytest.raises(transaction.TransactionError, match="regular repository"):
        transaction.commit(
            (transaction.PlannedWrite(root / "new", b"no"),), root=not_a_folder
        )
    linked = root / "linked"
    try:
        os.symlink(not_a_folder, linked)
    except OSError:
        pytest.skip("This platform does not permit test symlinks")
    with pytest.raises(transaction.TransactionError, match="symbolic-link file"):
        transaction.commit(
            (transaction.PlannedWrite(linked, b"no", replace=True),), root=root
        )
