"""Phase-3 contracts: local skill files, simulated actions, and evidence."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import stat
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

from skillroll.artifacts import store as store_module
from skillroll.artifacts.hashes import classify_bundle_path, hash_bytes, hash_file
from skillroll.artifacts.records import (
    RunFacts,
    canonical_json,
    manifest_bytes,
    report_bytes,
    run_bytes,
    transcript_bytes,
)
from skillroll.artifacts.store import ArtifactError, ArtifactStore
from skillroll.config import load_config
from skillroll.diagnostics import JSONValue
from skillroll.evals import _json_value, _parse_rules, parse_eval_case
from skillroll.inference.profile import (
    InferenceFailure,
    InferenceFailureKind,
    ResolvedInference,
    SecretRedactor,
    SecretValue,
)
from skillroll.inference.transport import (
    ChatRequest,
    ChatResponse,
    ChatTransport,
    ModelUsage,
    ToolCall,
    TransportFailure,
)
from skillroll.models import (
    CaseLimits,
    DeterministicRule,
    EvalCase,
    InferenceLimits,
    Skill,
    effective_limits,
)
from skillroll.runtime.attempt import execute_preliminary, input_hashes
from skillroll.runtime.execution import (
    ExecutionAttempt,
    ExecutionRequest,
    ExecutionResult,
)
from skillroll.world import bundle as bundle_module
from skillroll.world.bundle import (
    MAX_READABLE_BYTES,
    SKILL_WARNING_BYTES,
    BundleError,
    _walk,
    build_bundle,
    bundle_read,
)
from skillroll.world.model import (
    HistoryItem,
    WorldModelError,
    history_view,
    model_action,
    world_request,
)
from skillroll.world.rules import canonical_json as rule_json
from skillroll.world.rules import matching_rule
from skillroll.world.session import (
    MAX_WORLD_ACTIONS_PER_CASE,
    WorldActionError,
    WorldEvent,
    WorldSession,
)


class FakeTransport(ChatTransport):
    def __init__(self, responses: list[ChatResponse | Exception]) -> None:
        self.responses = responses
        self.requests: list[ChatRequest] = []
        self.closed = False

    async def complete(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    async def close(self) -> None:
        self.closed = True


class FakeExecutor:
    def __init__(
        self, action: tuple[str, Mapping[str, JSONValue]] | None = None
    ) -> None:
        self.action = action
        self.requests: list[ExecutionRequest] = []

    async def execute(
        self, request: ExecutionRequest, world_action: object
    ) -> ExecutionAttempt:
        self.requests.append(request)
        if self.action is not None:
            assert callable(world_action)
            await world_action(*self.action)
        return ExecutionAttempt(ExecutionResult("done", 1, (), ()), None)


def profile() -> ResolvedInference:
    return ResolvedInference(
        "https://example.test/v1",
        "cheap-model",
        SecretValue("test-secret/one"),
        InferenceLimits(4, 30, 128),
    )


def skill_at(root: Path) -> Skill:
    root.mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text("Use references/context.md", encoding="utf-8")
    (root / "evals").mkdir(exist_ok=True)
    return Skill(
        "review",
        PurePosixPath("skills/review"),
        root,
        root / "SKILL.md",
        root / "evals",
    )


def source(metadata: str = "schema_version: 1") -> str:
    return f"""# Case

```skillroll
{metadata}
```

## Input

Review this.

## World

The service is available.

## Success criteria

- A useful answer exists.
"""


def parsed_case(tmp_path: Path, metadata: str = "schema_version: 1") -> EvalCase:
    skill = skill_at(tmp_path / "skills" / "review")
    path = skill.evals_directory / "case.eval.md"
    path.write_text(source(metadata), encoding="utf-8")
    value = parse_eval_case(path, skill).value
    assert value is not None
    return value


def event(source: str = "world_model") -> WorldEvent:
    return WorldEvent(0, "Write", {"path": "a.md"}, "done", source)


def test_case_rules_limits_and_effective_restrictions(tmp_path: Path) -> None:
    case = parsed_case(
        tmp_path,
        """schema_version: 1
rules:
  - name: denied write
    tool_name: Write
    arguments: {path: out.md, values: [1, true, null]}
    result: "ERROR: could not write"
limits: {max_turns: 2, timeout_seconds: 5, max_output_tokens: 64}""",
    )
    assert case.rules[0].arguments == {"path": "out.md", "values": (1, True, None)}
    assert case.limits == CaseLimits(2, 5, 64)
    assert effective_limits(
        InferenceLimits(4, 30, 128), case.limits
    ) == InferenceLimits(2, 5, 64)
    assert effective_limits(InferenceLimits(1, 30, 128), case.limits) is None


@pytest.mark.parametrize(
    "metadata",
    [
        "schema_version: 1\nrules: nope",
        "schema_version: 1\nrules: "
        "[{name: x, tool_name: W, arguments: [], result: ok}]",
        "schema_version: 1\nrules: "
        "[{name: '', tool_name: W, arguments: {}, result: ok}]",
        "schema_version: 1\nrules: "
        "[{name: x, tool_name: '', arguments: {}, result: ok}]",
        "schema_version: 1\nrules: "
        "[{name: x, tool_name: W, arguments: {}, result: ''}]",
        "schema_version: 1\nrules: "
        "[{name: x, tool_name: W, arguments: {}, result: ok}, "
        "{name: x, tool_name: Q, arguments: {}, result: ok}]",
        "schema_version: 1\nrules: "
        "[{name: x, tool_name: W, arguments: {a: 1}, result: ok}, "
        "{name: y, tool_name: W, arguments: {a: 1}, result: ok}]",
        "schema_version: 1\nlimits: {}",
        "schema_version: 1\nlimits: {unknown: 1}",
        "schema_version: 1\nlimits: {max_turns: true}",
        "schema_version: 1\nlimits: {timeout_seconds: 601}",
    ],
)
def test_case_metadata_rejects_invalid_phase3_shapes(
    tmp_path: Path, metadata: str
) -> None:
    skill = skill_at(tmp_path / "skill")
    path = skill.evals_directory / "case.eval.md"
    path.write_text(source(metadata), encoding="utf-8")
    assert parse_eval_case(path, skill).value is None


def test_rules_are_exact_and_json_canonical() -> None:
    rule = DeterministicRule("exact", "Write", {"b": 2, "a": [True]}, "blocked")
    assert matching_rule((rule,), "Write", {"a": (True,), "b": 2}) == rule
    assert matching_rule((rule,), "write", {"a": (True,), "b": 2}) is None
    assert matching_rule((rule,), "Write", {"a": (1,), "b": 2}) is None
    assert rule_json({"b": 2, "a": 1}) == '{"a":1,"b":2}'


def test_bundle_indexes_and_only_serves_safe_text(tmp_path: Path) -> None:
    root = tmp_path / "skill"
    skill_at(root)
    (root / "references").mkdir()
    (root / "references" / "context.md").write_text("facts", encoding="utf-8")
    (root / "assets").mkdir()
    (root / "assets" / "image.bin").write_bytes(b"\xff")
    (root / "link").symlink_to(root / "references" / "context.md")
    index = build_bundle(root)
    assert [item.path.as_posix() for item in index.files] == [
        "SKILL.md",
        "assets/image.bin",
        "references/context.md",
    ]
    assert json.loads(
        bundle_read(index, "Read", {"path": "references/context.md"}) or "{}"
    ) == {
        "content": "facts",
        "path": "references/context.md",
        "source": "skill_bundle",
    }
    assert bundle_read(index, "Read", {"file_path": "assets/image.bin"}) is None
    assert bundle_read(index, "read", {"path": "references/context.md"}) is None
    assert bundle_read(index, "Read", {"path": "../outside"}) is None
    assert bundle_read(index, "Read", {"path": "missing"}) is None
    assert bundle_read(index, "Read", {"path": "references"}) is None


def test_external_read_stays_out_of_bundle_and_reaches_world(
    tmp_path: Path,
) -> None:
    selected = tmp_path / "skills" / "selected"
    sibling = tmp_path / "skills" / "other"
    skill_at(selected)
    sibling.mkdir()
    sibling_file = sibling / "reference.md"
    sibling_file.write_text("private sibling content", encoding="utf-8")
    transport = FakeTransport(
        [ChatResponse("simulated sibling result", (), "world", None)]
    )
    session = WorldSession(
        profile(),
        InferenceLimits(2, 30, 128),
        "The sibling reference is represented here by the World author.",
        build_bundle(selected),
        (),
        transport,
    )

    result = asyncio.run(session("Read", {"path": "../other/reference.md"}))

    assert result == "simulated sibling result"
    assert session.events[0].source == "world_model"
    assert "private sibling content" not in (
        transport.requests[0].messages[1].content or ""
    )


def test_bundle_excludes_eval_metadata_hidden_and_generated_dependencies(
    tmp_path: Path,
) -> None:
    root = tmp_path / "skill"
    skill_at(root)
    (root / "evals" / "leak.eval.md").write_text("expected answer", encoding="utf-8")
    (root / ".secret").write_text("private", encoding="utf-8")
    (root / ".hidden").mkdir()
    (root / ".hidden" / "nested.md").write_text("private", encoding="utf-8")
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "cached.pyc").write_bytes(b"bytecode")
    (root / "generated").mkdir()
    (root / "generated" / "output.json").write_text("generated", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "package.js").write_text("dependency", encoding="utf-8")
    (root / "cached.pyc").write_bytes(b"bytecode")

    index = build_bundle(root)
    paths = {item.path.as_posix() for item in index.files}
    assert paths == {"SKILL.md"}
    assert bundle_read(index, "Read", {"path": "evals/leak.eval.md"}) is None
    assert bundle_read(index, "Read", {"path": ".secret"}) is None
    assert bundle_read(index, "Read", {"path": "__pycache__/cached.pyc"}) is None


def test_bundle_keeps_file_count_and_changed_files_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "skill"
    skill_at(root)
    (root / "SKILL.md").write_bytes(b"x" * SKILL_WARNING_BYTES)
    (root / "a").write_bytes(b"abc")
    monkeypatch.setattr(bundle_module, "MAX_FILES", 1)
    with pytest.raises(BundleError, match="files"):
        build_bundle(root)
    monkeypatch.setattr(bundle_module, "MAX_FILES", 512)
    (root / "large.md").write_bytes(b"x" * (4 * 1024 * 1024 + 1))
    (root / "media.bin").write_bytes(b"\x00" + b"x" * (1024 * 1024))
    index = build_bundle(root)
    assert index.file(PurePosixPath("large.md")) is not None
    assert index.file(PurePosixPath("media.bin")) is not None
    assert [(item.path.as_posix(), item.size) for item in index.warnings] == [
        ("SKILL.md", SKILL_WARNING_BYTES)
    ]
    (root / "a").write_bytes(b"changed")
    assert bundle_read(index, "Read", {"path": "a"}) is None
    (root / "a").write_bytes(b"x" * (MAX_READABLE_BYTES + 1))
    assert bundle_read(index, "Read", {"path": "a"}) is None


def test_bundle_indexing_does_not_read_entire_files_at_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "skill"
    skill_at(root)
    (root / "large.md").write_bytes(b"x" * (2 * 1024 * 1024))
    original_read_bytes = Path.read_bytes

    def forbidden_read(path: Path) -> bytes:
        del path
        raise AssertionError("bundle indexing must stream files")

    monkeypatch.setattr(Path, "read_bytes", forbidden_read)
    index = build_bundle(root)
    assert index.file(PurePosixPath("large.md")) is not None
    monkeypatch.setattr(Path, "read_bytes", original_read_bytes)


def test_stream_file_closes_a_non_regular_descriptor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed: list[int] = []

    def fake_open(*_args: object) -> int:
        return 37

    def fake_fstat(_descriptor: int) -> SimpleNamespace:
        return SimpleNamespace(st_mode=stat.S_IFDIR)

    def fake_close(descriptor: int) -> None:
        closed.append(descriptor)

    monkeypatch.setattr(bundle_module.os, "open", fake_open)
    monkeypatch.setattr(bundle_module.os, "fstat", fake_fstat)
    monkeypatch.setattr(bundle_module.os, "close", fake_close)

    with pytest.raises(OSError, match="not a regular file"):
        bundle_module._stream_file(Path("ignored"))

    assert closed == [37]


def test_history_prompt_and_model_response_contract() -> None:
    history = (
        HistoryItem("Write", {"path": "x"}, "created"),
        HistoryItem("Read", {"path": "x"}, "contents"),
    )
    view, omitted = history_view(history)
    assert omitted == 0 and "Action 0" in view and "contents" in view
    request, request_omitted = world_request(
        profile(), 7, "known world", history, "GitHub", {"issue": 2}
    )
    assert request.model == "cheap-model" and request.max_output_tokens == 7
    assert request.temperature == 0.0
    assert request.tools == () and request_omitted == 0
    assert "known world" in (request.messages[1].content or "")
    assert "Success criteria" not in (request.messages[0].content or "")


def test_history_compacts_complete_newest_pairs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("skillroll.world.model.MAX_HISTORY_BYTES", 100)
    items = tuple(HistoryItem(str(index), {}, "x" * 40) for index in range(3))
    view, omitted = history_view(items)
    assert omitted == 2 and "Action 2" in view and "Action 1" not in view


@pytest.mark.parametrize(
    "response,kind",
    [
        (ChatResponse("okay", (), "m", ModelUsage(1, 2, 3)), None),
        (ChatResponse("", (), None, None), InferenceFailureKind.MALFORMED_RESPONSE),
        (
            ChatResponse(" \n\t", (), None, None),
            InferenceFailureKind.MALFORMED_RESPONSE,
        ),
        (
            ChatResponse("x", (ToolCall("id", "x", {}),), None, None),
            InferenceFailureKind.MALFORMED_RESPONSE,
        ),
        (
            ChatResponse("x" * (64 * 1024 + 1), (), None, None),
            InferenceFailureKind.MALFORMED_RESPONSE,
        ),
    ],
)
def test_model_action_validates_responses(
    response: ChatResponse, kind: InferenceFailureKind | None
) -> None:
    transport = FakeTransport([response])
    if kind is None:
        reply = asyncio.run(
            model_action(transport, profile(), 9, "world", (), "Do", {})
        )
        assert reply.result == "okay" and len(transport.requests) == 1
    else:
        with pytest.raises(WorldModelError) as error:
            asyncio.run(model_action(transport, profile(), 9, "world", (), "Do", {}))
        assert error.value.failure.kind == kind


def test_model_action_redacts_failures_and_world_size() -> None:
    failure = InferenceFailure(InferenceFailureKind.TIMEOUT, "timeout")
    transport = FakeTransport([TransportFailure(failure)])
    with pytest.raises(WorldModelError) as error:
        asyncio.run(model_action(transport, profile(), 9, "world", (), "Do", {}))
    assert error.value.failure == failure
    with pytest.raises(WorldModelError, match="World section"):
        world_request(profile(), 9, "x" * (64 * 1024 + 1), (), "Do", {})
    transport = FakeTransport([RuntimeError("test-secret/one failed")])
    with pytest.raises(WorldModelError) as error:
        asyncio.run(model_action(transport, profile(), 9, "world", (), "Do", {}))
    assert "test-secret/one" not in error.value.failure.details[0]


def test_world_session_precedence_history_and_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "skill"
    skill_at(root)
    (root / "context.md").write_text("bundle", encoding="utf-8")
    bundle = build_bundle(root)
    rules = (
        DeterministicRule("write denied", "Write", {"path": "x"}, "ERROR: denied"),
    )
    transport = FakeTransport(
        [ChatResponse("generated", (), "world", None)] * MAX_WORLD_ACTIONS_PER_CASE
    )
    monkeypatch.setattr("skillroll.world.session.MAX_WORLD_ACTIONS_PER_CASE", 3)
    session = WorldSession(
        profile(), InferenceLimits(3, 30, 77), "world", bundle, rules, transport
    )
    assert (
        json.loads(asyncio.run(session("Read", {"path": "context.md"})))["content"]
        == "bundle"
    )
    assert asyncio.run(session("Write", {"path": "x"})) == "ERROR: denied"
    assert asyncio.run(session("Skill", {"name": "child"})) == "generated"
    assert [item.source for item in session.events] == [
        "skill_bundle",
        "rule",
        "world_model",
    ]
    assert transport.requests[0].max_output_tokens == 77
    with pytest.raises(WorldActionError, match="World-action safety limit") as error:
        asyncio.run(session("again", {}))
    assert "3" in error.value.failure.summary and "Skill" in error.value.failure.summary


def test_world_session_invalid_input_and_concurrent_order(tmp_path: Path) -> None:
    bundle = build_bundle(skill_at(tmp_path / "skill").root)
    transport = FakeTransport(
        [ChatResponse("one", (), None, None), ChatResponse("two", (), None, None)]
    )
    session = WorldSession(
        profile(), InferenceLimits(3, 30, 9), "world", bundle, (), transport
    )
    with pytest.raises(WorldActionError, match="tool_name"):
        asyncio.run(session("\n", {}))
    with pytest.raises(WorldActionError, match="16 KiB"):
        asyncio.run(session("Do", {"x": "x" * (16 * 1024)}))

    async def run_two() -> tuple[str, str]:
        return await asyncio.gather(session("A", {}), session("B", {}))

    assert asyncio.run(run_two()) == ["one", "two"]
    assert [item.index for item in session.events] == [0, 1]


def test_hash_records_and_renderers_are_stable(tmp_path: Path) -> None:
    value = hash_bytes(PurePosixPath("a"), "asset", b"abc")
    assert value.sha256 == hashlib.sha256(b"abc").hexdigest()
    path = tmp_path / "x"
    path.write_bytes(b"abc")
    assert hash_file(PurePosixPath("x"), "asset", path).sha256 == value.sha256
    assert [
        classify_bundle_path(PurePosixPath(path))
        for path in ("SKILL.md", "references/a", "scripts/a", "assets/a", "a")
    ] == ["skill_instruction", "reference", "script", "asset", "bundle_file"]
    manifest = manifest_bytes((value,))
    facts = RunFacts(
        "run-id",
        "2026-01-01T00:00:00Z",
        "skill",
        "case",
        None,
        "url",
        "model",
        {"max_turns": 1},
        {"max_turns": 1},
        hashlib.sha256(manifest).hexdigest(),
        "executed",
        (event(),),
    )
    assert json.loads(run_bytes(facts))["repository_root"] == "."
    assert b'"source":"world_model"' in transcript_bytes((event(),))
    assert b"has not been checked" in report_bytes(facts)
    assert canonical_json({"a": 1}).endswith(b"\n")


def test_hash_and_record_error_or_optional_branches(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="could not hash"):
        hash_file(PurePosixPath("missing"), "asset", tmp_path / "missing")
    rule_event = WorldEvent(1, "Write", {}, "no", "rule", "blocked", omitted_history=2)
    assert b'"rule_name":"blocked"' in transcript_bytes((rule_event,))
    manifest = manifest_bytes(())
    facts = RunFacts(
        "id",
        "time",
        "skill",
        "case",
        "title",
        "url",
        "model",
        {},
        {},
        hashlib.sha256(manifest).hexdigest(),
        "error",
        (rule_event,),
        "broken",
        ("network timeout [redacted]",),
    )
    record = json.loads(run_bytes(facts))
    assert record["failure"] == "broken"
    assert record["failure_details"] == ["network timeout [redacted]"]
    rendered = report_bytes(facts)
    assert b"history limit" in rendered and b"Why the run stopped" in rendered
    assert b"Technical details" in rendered
    empty = RunFacts(
        "id", "time", "skill", "case", None, "url", "model", {}, {}, "x", "executed", ()
    )
    assert b"No action completed" in report_bytes(empty)


def test_store_redacts_and_rejects_bad_outputs(tmp_path: Path) -> None:
    store = ArtifactStore(
        tmp_path, SecretRedactor(profile().api_key), lambda: "fixed", lambda: "now"
    )
    run_id, directory, started = store.create()
    manifest = manifest_bytes((hash_bytes(PurePosixPath("a"), "asset", b"a"),))
    facts = RunFacts(
        run_id,
        started,
        "skill",
        "case",
        None,
        "url",
        "test-secret/one",
        {"a": 1},
        {"a": 1},
        hashlib.sha256(manifest).hexdigest(),
        "error",
        (event(),),
        "test-secret/one",
    )
    store.write(directory, facts, manifest, (event(),))
    written = b"".join(item.read_bytes() for item in directory.iterdir())
    assert b"test-secret/one" not in written and b"[redacted]" in written
    with pytest.raises(ArtifactError, match="inconsistent"):
        store.write(directory, facts, b"{}", ())
    with pytest.raises(ArtifactError, match="outside"):
        store.write(tmp_path, facts, manifest, ())


def test_store_handles_collision_and_unsafe_root(tmp_path: Path) -> None:
    first = ArtifactStore(
        tmp_path, SecretRedactor(profile().api_key), lambda: "same", lambda: "now"
    )
    first.create()
    values = iter(("same", "next"))
    second = ArtifactStore(
        tmp_path, SecretRedactor(profile().api_key), lambda: next(values), lambda: "now"
    )
    assert second.create()[0] == "run-next"
    unsafe = tmp_path / "unsafe"
    unsafe.write_text("x", encoding="utf-8")
    with pytest.raises(ArtifactError):
        ArtifactStore(unsafe, SecretRedactor(profile().api_key)).create()


def test_store_rejects_unsafe_subfolders_and_write_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".skillroll").write_text("no", encoding="utf-8")
    with pytest.raises(ArtifactError, match="ordinary"):
        ArtifactStore(tmp_path, SecretRedactor(profile().api_key)).create()
    (tmp_path / ".skillroll").unlink()
    (tmp_path / ".skillroll").mkdir()
    (tmp_path / ".skillroll" / "runs").write_text("no", encoding="utf-8")
    with pytest.raises(ArtifactError, match="ordinary"):
        ArtifactStore(tmp_path, SecretRedactor(profile().api_key)).create()
    (tmp_path / ".skillroll" / "runs").unlink()
    store = ArtifactStore(tmp_path, SecretRedactor(profile().api_key), lambda: "id")
    _, directory, _ = store.create()
    if store_module._descriptor_safety_available():
        directory_fd = store._open_run_directory(directory)
        with pytest.raises(ArtifactError, match="atomically write"):
            monkeypatch.setattr(
                "skillroll.artifacts.store.os.replace",
                lambda *_, **__: (_ for _ in ()).throw(OSError()),
            )
            monkeypatch.setattr(
                "skillroll.artifacts.store.os.unlink",
                lambda *_, **__: (_ for _ in ()).throw(OSError()),
            )
            store._write(directory_fd, "x", b"ok")
        os.close(directory_fd)
        assert list(directory.glob(".x.*.tmp"))
        monkeypatch.undo()
        for temporary in directory.glob(".x.*.tmp"):
            temporary.unlink()
        directory_fd = store._open_run_directory(directory)
        collision = directory / ".collision.fixed.tmp"
        collision.write_bytes(b"already here")

        class FixedToken:
            hex = "fixed"

        monkeypatch.setattr(
            "skillroll.artifacts.store.uuid.uuid4", lambda: FixedToken()
        )
        with pytest.raises(ArtifactError, match="atomically write"):
            store._write(directory_fd, "collision", b"ok")
        os.close(directory_fd)
    assert (
        ArtifactStore(tmp_path, SecretRedactor(profile().api_key))._safe(
            b"test-secret%2Fone"
        )
        == b"[redacted]"
    )


def test_store_exhausts_collision_ids(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path, SecretRedactor(profile().api_key), lambda: "same")
    store.create()
    with pytest.raises(ArtifactError, match="unique"):
        store.create()


def test_experiment_store_contract_and_failure_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unsafe = tmp_path / "unsafe"
    unsafe.write_text("x", encoding="utf-8")
    with pytest.raises(ArtifactError, match="selected repository folder is unsafe"):
        ArtifactStore(unsafe, SecretRedactor(profile().api_key)).create_experiment()

    base_file_root = tmp_path / "base-file"
    base_file_root.mkdir()
    (base_file_root / ".skillroll").write_text("x", encoding="utf-8")
    with pytest.raises(ArtifactError, match="not an ordinary folder"):
        ArtifactStore(
            base_file_root, SecretRedactor(profile().api_key)
        ).create_experiment()

    experiments_file_root = tmp_path / "experiments-file"
    (experiments_file_root / ".skillroll").mkdir(parents=True)
    (experiments_file_root / ".skillroll" / "experiments").write_text(
        "x", encoding="utf-8"
    )
    with pytest.raises(ArtifactError, match="experiments is not an ordinary folder"):
        ArtifactStore(
            experiments_file_root, SecretRedactor(profile().api_key)
        ).create_experiment()

    store = ArtifactStore(tmp_path, SecretRedactor(profile().api_key), lambda: "same")
    _, first = store.create_experiment()
    values = iter(("same", "next"))
    collision_store = ArtifactStore(
        tmp_path, SecretRedactor(profile().api_key), lambda: next(values)
    )
    experiment_id, directory = collision_store.create_experiment()
    assert experiment_id == "experiment-next"
    with pytest.raises(ArtifactError, match="unique"):
        store.create_experiment()

    with pytest.raises(ArtifactError, match="outside"):
        collision_store.write_experiment(tmp_path, b"{}", b"report")
    missing = directory.with_name("experiment-missing")
    with pytest.raises(ArtifactError, match="safely reopen"):
        collision_store.write_experiment(missing, b"{}", b"report")
    first.rmdir()
    first.write_text("x", encoding="utf-8")
    with pytest.raises(ArtifactError, match="not an ordinary folder"):
        store.write_experiment(first, b"{}", b"report")

    original_mkdir = Path.mkdir

    def broken_mkdir(path: Path, *args: object, **kwargs: object) -> None:
        if path.name == "experiments":
            raise OSError("broken")
        original_mkdir(path, *args, **kwargs)

    broken_root = tmp_path / "broken-root"
    broken_root.mkdir()
    monkeypatch.setattr(Path, "mkdir", broken_mkdir)
    with pytest.raises(ArtifactError, match="could not create"):
        ArtifactStore(
            broken_root, SecretRedactor(profile().api_key)
        ).create_experiment()
    monkeypatch.undo()

    original_is_file = Path.is_file

    def changed_file(path: Path) -> bool:
        if path.name.startswith(".result.json"):
            return False
        return original_is_file(path)

    monkeypatch.setattr(Path, "is_file", changed_file)
    with pytest.raises(ArtifactError, match="changed experiment evidence"):
        collision_store.write_experiment(directory, b"{}", b"report")
    monkeypatch.undo()

    monkeypatch.setattr(
        "skillroll.artifacts.store.os.replace",
        lambda *_, **__: (_ for _ in ()).throw(OSError("broken")),
    )
    with pytest.raises(ArtifactError, match="could not atomically write"):
        collision_store.write_experiment(directory, b"{}", b"report")
    assert not list(directory.glob(".*.tmp"))


def test_store_rejects_directory_swap_and_temp_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def facts_for(run_id: str, started: str, manifest: bytes) -> RunFacts:
        return RunFacts(
            run_id,
            started,
            "skill",
            "case",
            None,
            "url",
            "model",
            {},
            {},
            hashlib.sha256(manifest).hexdigest(),
            "executed",
            (),
        )

    manifest = manifest_bytes(())
    store = ArtifactStore(tmp_path, SecretRedactor(profile().api_key), lambda: "swap")
    run_id, directory, started = store.create()
    outside = tmp_path / "outside"
    outside.mkdir()
    moved = directory.with_name("moved")
    directory.rename(moved)
    directory.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ArtifactError, match="run-evidence folder"):
        store.write(directory, facts_for(run_id, started, manifest), manifest, ())
    assert not list(outside.iterdir())

    store = ArtifactStore(tmp_path, SecretRedactor(profile().api_key), lambda: "temp")
    run_id, directory, started = store.create()
    trap = directory / ".inputs.json.trap.tmp"
    trap.symlink_to(outside / "escaped")
    calls = iter(("trap", "safe", "one", "two", "three"))

    class Token:
        def __init__(self, value: str) -> None:
            self.hex = value

    monkeypatch.setattr(
        "skillroll.artifacts.store.uuid.uuid4", lambda: Token(next(calls))
    )
    store.write(directory, facts_for(run_id, started, manifest), manifest, ())
    assert not (outside / "escaped").exists()
    assert (directory / "inputs.json").is_file()


def test_store_fallback_rejects_links_and_exclusive_temp_collisions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def facts_for(run_id: str, started: str, manifest: bytes) -> RunFacts:
        return RunFacts(
            run_id,
            started,
            "skill",
            "case",
            None,
            "url",
            "model",
            {},
            {},
            hashlib.sha256(manifest).hexdigest(),
            "executed",
            (),
        )

    monkeypatch.setattr(
        "skillroll.artifacts.store._descriptor_safety_available", lambda: False
    )
    manifest = manifest_bytes(())
    store = ArtifactStore(
        tmp_path, SecretRedactor(profile().api_key), lambda: "fallback"
    )
    run_id, directory, started = store.create()
    outside = tmp_path / "outside"
    outside.mkdir()
    moved = directory.with_name("moved")
    directory.rename(moved)
    directory.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ArtifactError, match="link"):
        store.write(directory, facts_for(run_id, started, manifest), manifest, ())
    assert not list(outside.iterdir())

    store = ArtifactStore(tmp_path, SecretRedactor(profile().api_key), lambda: "temp")
    run_id, directory, started = store.create()
    trap = directory / ".inputs.json.trap.tmp"
    trap.symlink_to(outside / "escaped")
    values = iter(("trap", "safe", "one", "two", "three"))

    class Token:
        def __init__(self, value: str) -> None:
            self.hex = value

    monkeypatch.setattr(
        "skillroll.artifacts.store.uuid.uuid4", lambda: Token(next(values))
    )
    store.write(directory, facts_for(run_id, started, manifest), manifest, ())
    assert not (outside / "escaped").exists()
    assert (directory / "inputs.json").is_file()


def test_store_fallback_failure_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "skillroll.artifacts.store._descriptor_safety_available", lambda: False
    )
    store = ArtifactStore(
        tmp_path, SecretRedactor(profile().api_key), lambda: "fallback"
    )
    _, directory, _ = store.create()
    directory.rmdir()
    with pytest.raises(ArtifactError, match="safely reopen"):
        store._checked_fallback_directory(directory)

    _, directory, _ = store.create()

    class Token:
        hex = "fixed"

    monkeypatch.setattr("skillroll.artifacts.store.uuid.uuid4", lambda: Token())
    collision = directory / ".collision.fixed.tmp"
    collision.write_bytes(b"exists")
    with pytest.raises(ArtifactError, match="atomically write"):
        store._write_fallback(directory, "collision", b"x")
    collision.unlink()

    original_lstat = Path.lstat

    def missing_lstat(path: Path) -> os.stat_result:
        if path.name.startswith(".missing"):
            raise OSError()
        return original_lstat(path)

    class MissingToken:
        hex = "missing"

    monkeypatch.setattr("skillroll.artifacts.store.uuid.uuid4", lambda: MissingToken())
    monkeypatch.setattr(Path, "lstat", missing_lstat)
    with pytest.raises(ArtifactError, match="temporary evidence"):
        store._write_fallback(directory, "missing", b"x")
    monkeypatch.undo()

    original_lstat = Path.lstat
    recheck_calls = 0

    def recheck_lstat(path: Path) -> os.stat_result:
        nonlocal recheck_calls
        if path.name.startswith(".recheck"):
            recheck_calls += 1
            if recheck_calls == 1:
                raise FileNotFoundError()
            raise OSError()
        return original_lstat(path)

    class RecheckToken:
        hex = "recheck"

    monkeypatch.setattr("skillroll.artifacts.store.uuid.uuid4", lambda: RecheckToken())
    monkeypatch.setattr(Path, "lstat", recheck_lstat)
    with pytest.raises(ArtifactError, match="recheck a temporary evidence"):
        store._write_fallback(directory, "recheck", b"x")
    monkeypatch.undo()

    original_lstat = Path.lstat
    original_open = os.open

    def race_lstat(path: Path) -> os.stat_result:
        if path.name.startswith(".race"):
            raise FileNotFoundError()
        return original_lstat(path)

    def race_open(file: object, *args: object, **kwargs: object) -> int:
        if Path(file).name.startswith(".race"):
            raise FileExistsError()
        return original_open(file, *args, **kwargs)  # type: ignore[arg-type]

    class RaceToken:
        hex = "race"

    monkeypatch.setattr("skillroll.artifacts.store.uuid.uuid4", lambda: RaceToken())
    monkeypatch.setattr(Path, "lstat", race_lstat)
    monkeypatch.setattr("skillroll.artifacts.store.os.open", race_open)
    with pytest.raises(ArtifactError, match="atomically write"):
        store._write_fallback(directory, "race", b"x")
    monkeypatch.undo()

    original_lstat = Path.lstat
    changed_calls = 0

    def linked_lstat(path: Path) -> os.stat_result | SimpleNamespace:
        nonlocal changed_calls
        if path.name.startswith(".changed"):
            changed_calls += 1
            if changed_calls == 1:
                raise FileNotFoundError()
            return SimpleNamespace(st_mode=stat.S_IFLNK)
        return original_lstat(path)

    class ChangedToken:
        hex = "changed"

    monkeypatch.setattr("skillroll.artifacts.store.uuid.uuid4", lambda: ChangedToken())
    monkeypatch.setattr(Path, "lstat", linked_lstat)
    with pytest.raises(ArtifactError, match="changed temporary"):
        store._write_fallback(directory, "changed", b"x")
    monkeypatch.undo()

    class ErrorToken:
        hex = "error"

    monkeypatch.setattr("skillroll.artifacts.store.uuid.uuid4", lambda: ErrorToken())
    monkeypatch.setattr(
        "skillroll.artifacts.store.os.replace",
        lambda *_, **__: (_ for _ in ()).throw(OSError()),
    )
    with pytest.raises(ArtifactError, match="atomically write"):
        store._write_fallback(directory, "error", b"x")
    assert not list(directory.glob(".error.*.tmp"))


def test_preliminary_composition_records_full_inputs(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "skills").mkdir()
    (repo / "skillroll.toml").write_text(
        "schema_version = 1\nskills_path = 'skills'\n[inference]\n"
        "base_url = 'https://example.test/v1'\nmodel = 'cheap-model'\n"
        "api_key_env = 'KEY'\n",
        encoding="utf-8",
    )
    config = load_config(repo).value
    assert config is not None
    case = parsed_case(repo)
    (case.skill.root / ".hidden").write_text("hidden", encoding="utf-8")
    (case.skill.root / "__pycache__").mkdir()
    (case.skill.root / "__pycache__" / "cached.pyc").write_bytes(b"bytecode")
    (case.skill.root / "generated").mkdir()
    (case.skill.root / "generated" / "result.json").write_text(
        "generated", encoding="utf-8"
    )
    # Align this direct test skill with the configured skills root identity.
    bundle = build_bundle(case.skill.root)
    records = input_hashes(config, case, bundle)
    assert {item.kind for item in records} >= {
        "config",
        "eval_case",
        "skill_instruction",
    }
    transport = FakeTransport([ChatResponse("done", (), None, None)])
    store = ArtifactStore(
        repo, SecretRedactor(profile().api_key), lambda: "one", lambda: "time"
    )
    attempt = asyncio.run(
        execute_preliminary(
            config,
            case,
            profile(),
            FakeExecutor(("GitHub", {"issue": 1})),
            transport,
            store,
        )
    )
    assert attempt.failure is None and attempt.artifact_directory is not None
    assert (repo / attempt.artifact_directory / "report.md").is_file()
    manifest = json.loads(
        (repo / attempt.artifact_directory / "inputs.json").read_text(encoding="utf-8")
    )
    identities = {item["identity"] for item in manifest["files"]}
    assert "skills/review/evals/case.eval.md" in identities
    assert all(
        "/evals/" not in identity or identity.endswith("case.eval.md")
        for identity in identities
    )
    assert all("/.hidden" not in identity for identity in identities)
    assert all("__pycache__" not in identity for identity in identities)
    assert all("generated" not in identity for identity in identities)
    assert all(not identity.endswith(".pyc") for identity in identities)


def test_preliminary_rejects_raised_case_limit_before_model(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "skills").mkdir()
    (repo / "skillroll.toml").write_text(
        "schema_version = 1\nskills_path = 'skills'", encoding="utf-8"
    )
    config = load_config(repo).value
    assert config is not None
    case = parsed_case(repo, "schema_version: 1\nlimits: {max_turns: 2}")
    transport = FakeTransport([])
    attempt = asyncio.run(
        execute_preliminary(
            config,
            case,
            ResolvedInference(
                "https://x.test", "m", SecretValue("x"), InferenceLimits(1, 30, 128)
            ),
            FakeExecutor(),
            transport,
            ArtifactStore(repo, SecretRedactor(SecretValue("x"))),
        )
    )
    assert attempt.failure is not None and not transport.requests


def test_preliminary_records_executor_failure_and_store_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "skills").mkdir()
    (repo / "skillroll.toml").write_text(
        "schema_version = 1\nskills_path = 'skills'", encoding="utf-8"
    )
    config = load_config(repo).value
    assert config is not None
    case = parsed_case(repo)

    class FailedExecutor:
        async def execute(self, request: object, action: object) -> ExecutionAttempt:
            return ExecutionAttempt(
                None, InferenceFailure(InferenceFailureKind.TIMEOUT, "timed out")
            )

    names = iter(("failure", "write-failure"))
    store = ArtifactStore(repo, SecretRedactor(profile().api_key), lambda: next(names))
    failed = asyncio.run(
        execute_preliminary(
            config, case, profile(), FailedExecutor(), FakeTransport([]), store
        )
    )
    assert failed.failure is not None
    monkeypatch.setattr(
        store, "write", lambda *_: (_ for _ in ()).throw(ArtifactError("disk"))
    )
    write_failed = asyncio.run(
        execute_preliminary(
            config, case, profile(), FakeExecutor(), FakeTransport([]), store
        )
    )
    assert (
        write_failed.failure is not None and write_failed.artifact_directory is not None
    )


def test_preliminary_handles_setup_and_cancellation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "skills").mkdir()
    (repo / "skillroll.toml").write_text(
        "schema_version = 1\nskills_path = 'skills'", encoding="utf-8"
    )
    config = load_config(repo).value
    assert config is not None
    case = parsed_case(repo)
    store = ArtifactStore(repo, SecretRedactor(profile().api_key))
    monkeypatch.setattr(
        "skillroll.runtime.attempt.build_bundle",
        lambda _: (_ for _ in ()).throw(BundleError("bundle")),
    )
    setup = asyncio.run(
        execute_preliminary(
            config, case, profile(), FakeExecutor(), FakeTransport([]), store
        )
    )
    assert setup.failure is not None and setup.artifact_directory is None

    class CancelledExecutor:
        async def execute(self, request: object, action: object) -> ExecutionAttempt:
            raise asyncio.CancelledError()

    monkeypatch.undo()
    cancelled = asyncio.run(
        execute_preliminary(
            config,
            case,
            profile(),
            CancelledExecutor(),
            FakeTransport([]),
            ArtifactStore(repo, SecretRedactor(profile().api_key), lambda: "cancel"),
        )
    )
    assert cancelled.failure is not None


def test_phase3_remaining_safety_branches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _json_value(float("nan")) is None
    assert _json_value([None, {"x": 2}]) == (None, {"x": 2})
    assert _json_value([object()]) is None
    assert _json_value({1: "bad"}) is None
    errors = _parse_rules(["bad"], tmp_path / "case", 1)[1]
    assert errors
    errors = _parse_rules(
        [
            {
                "name": "x",
                "tool_name": "Do",
                "arguments": {"x": "x" * 16384},
                "result": "ok",
            }
        ],
        tmp_path / "case",
        1,
    )[1]
    assert errors

    with pytest.raises(BundleError, match="open"):
        build_bundle(tmp_path / "missing")
    root = tmp_path / "root"
    root.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(root, target_is_directory=True)
    with pytest.raises(BundleError, match="ordinary"):
        build_bundle(linked)
    (root / "file").write_text("x", encoding="utf-8")
    index = build_bundle(root)
    (root / "file").unlink()
    assert bundle_read(index, "Read", {"path": "file"}) is None
    assert bundle_read(index, "Read", {"path": 1}) is None
    (root / "file").write_text("x", encoding="utf-8")
    index = build_bundle(root)
    monkeypatch.setattr(
        "skillroll.world.bundle.os.open",
        lambda *_: (_ for _ in ()).throw(OSError()),
    )
    assert bundle_read(index, "Read", {"path": "file"}) is None
    monkeypatch.undo()

    missing_entry = root / "gone"
    monkeypatch.setattr(
        "skillroll.world.bundle.sorted_entries", lambda _: (missing_entry,)
    )
    assert _walk(root, root) == ()
    monkeypatch.undo()

    class UnknownEntry:
        def lstat(self) -> object:
            return type("Stat", (), {"st_mode": 0})()

    monkeypatch.setattr(
        "skillroll.world.bundle.sorted_entries",
        lambda _: (UnknownEntry(), root / "file"),
    )
    assert _walk(root, root) == (root / "file",)
    monkeypatch.undo()
    (root / "first").write_text("1", encoding="utf-8")
    (root / "second").write_text("2", encoding="utf-8")
    assert len(build_bundle(root).files) >= 3
    (root / "fault").write_text("x", encoding="utf-8")
    original_stream = bundle_module._stream_file

    def failing_stream(path: Path) -> tuple[int, str]:
        if path.name == "fault":
            raise OSError()
        return original_stream(path)

    monkeypatch.setattr(bundle_module, "_stream_file", failing_stream)
    with pytest.raises(BundleError, match="could not read"):
        build_bundle(root)
    monkeypatch.undo()

    class CancelTransport:
        async def complete(self, request: ChatRequest) -> ChatResponse:
            raise asyncio.CancelledError()

        async def close(self) -> None:
            return None

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            model_action(CancelTransport(), profile(), 9, "world", (), "Do", {})
        )
    session = WorldSession(
        profile(),
        InferenceLimits(1, 30, 9),
        "world",
        build_bundle(root),
        (),
        FakeTransport([ChatResponse("", (), None, None)]),
    )
    with pytest.raises(WorldActionError, match="no action result"):
        asyncio.run(session("Do", {}))
    with pytest.raises(WorldActionError, match="JSON object"):
        asyncio.run(session("Do", {"bad": object()}))  # type: ignore[arg-type]
    cancelled_session = WorldSession(
        profile(),
        InferenceLimits(1, 30, 9),
        "world",
        build_bundle(root),
        (),
        CancelTransport(),
    )
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(cancelled_session("Do", {}))


def test_store_remaining_error_branches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ArtifactStore(tmp_path, SecretRedactor(profile().api_key), lambda: "id")
    monkeypatch.setattr(
        Path, "mkdir", lambda *args, **kwargs: (_ for _ in ()).throw(OSError())
    )
    with pytest.raises(ArtifactError, match="could not create"):
        store.create()
    monkeypatch.undo()

    class UnsafeRedactor:
        secret = SecretValue("x")

        def redact(self, value: str) -> str:
            return value

    raw_store = ArtifactStore(tmp_path, UnsafeRedactor())  # type: ignore[arg-type]
    with pytest.raises(ArtifactError, match="API key"):
        raw_store._safe(b"x")
