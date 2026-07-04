"""The managed-artifact state library (`convergence/managed_state.py`)."""

import dataclasses
import json

import pytest

from perk import __version__, _resources
from perk.convergence.init import run_init
from perk.convergence.init.agents import PERK_AGENTS
from perk.convergence.init.blocks import GITIGNORE_BODY, _agents_inner, _apply_managed_block
from perk.convergence.init.settings import BORROWED_PACKAGES
from perk.convergence.init.skills import _desired_skills_manifest
from perk.convergence.init.version_pin import render_version_pin
from perk.convergence.managed_state import (
    ArtifactState,
    ManagedState,
    ManagedStateError,
    ManagedStateFileModel,
    block_inner,
    classify_artifact,
    desired_state,
    directory_manifest,
    hash_block,
    hash_bytes,
    hash_directory,
    load_managed_state,
    managed_artifacts,
    record_managed_state,
    render_managed_state,
    save_managed_state,
)
from perk.run.workflow_artifacts import PERK_RUN_WORKFLOW
from perk.substrate import paths


def _descriptor(key: str):
    matches = [d for d in managed_artifacts() if d.key == key]
    assert len(matches) == 1
    return matches[0]


class TestHashFunctions:
    def test_hash_bytes_is_prefixed_lowercase_hex(self):
        digest = hash_bytes(b"payload")
        assert digest.startswith("sha256:")
        hex_part = digest.removeprefix("sha256:")
        assert len(hex_part) == 64
        assert hex_part == hex_part.lower()
        assert all(c in "0123456789abcdef" for c in hex_part)

    def test_hash_bytes_deterministic_and_input_sensitive(self):
        assert hash_bytes(b"same") == hash_bytes(b"same")
        assert hash_bytes(b"one") != hash_bytes(b"two")

    def test_hash_directory_is_insertion_order_independent(self):
        forward = {"a.md": b"alpha", "b.md": b"beta"}
        backward = {"b.md": b"beta", "a.md": b"alpha"}
        assert hash_directory(forward) == hash_directory(backward)

    def test_hash_directory_sensitive_to_rename_content_and_membership(self):
        base = {"a.md": b"alpha", "b.md": b"beta"}
        renamed = {"a2.md": b"alpha", "b.md": b"beta"}
        changed = {"a.md": b"alpha!", "b.md": b"beta"}
        added = {**base, "c.md": b"gamma"}
        removed = {"a.md": b"alpha"}
        digests = {hash_directory(d) for d in (base, renamed, changed, added, removed)}
        assert len(digests) == 5

    def test_hash_block_ignores_trailing_newlines_only(self):
        assert hash_block("x") == hash_block("x\n") == hash_block("x\n\n")
        assert hash_block("x") != hash_block("y")
        assert hash_block("x") != hash_block("\nx")

    def test_block_inner_extracts_between_markers(self):
        text = "before\n<!-- B -->\ninner line\n<!-- E -->\nafter\n"
        assert block_inner(text, begin="<!-- B -->", end="<!-- E -->") == "inner line\n"

    def test_block_inner_returns_none_when_a_marker_is_absent(self):
        assert block_inner("no markers here", begin="<!-- B -->", end="<!-- E -->") is None
        assert block_inner("<!-- B -->\nx\n", begin="<!-- B -->", end="<!-- E -->") is None
        assert block_inner("x\n<!-- E -->\n", begin="<!-- B -->", end="<!-- E -->") is None

    def test_block_inner_round_trips_with_the_real_embedding(self, tmp_path):
        inner = "line one\nline two\n\n"
        target = tmp_path / "AGENTS.md"
        _apply_managed_block(
            target,
            begin="<!-- BEGIN test -->",
            end="<!-- END test -->",
            inner=inner,
            label="AGENTS.md",
        )
        extracted = block_inner(
            target.read_text(encoding="utf-8"),
            begin="<!-- BEGIN test -->",
            end="<!-- END test -->",
        )
        assert extracted is not None
        assert hash_block(extracted) == hash_block(inner)


# The pinned registry table: key -> (path, kind, scope).
EXPECTED_ARTIFACTS = {
    "settings-wiring": (".pi/settings.json", "block", "both"),
    "runner-workflow": (".github/workflows/perk-run.yml", "file", "both"),
    "remote-setup-action": (".github/actions/perk-remote-setup/action.yml", "file", "both"),
    "subagent-agents": (".pi/agents/perk/", "directory", "both"),
    "skills-manifest": (".agents/manifest.d/perk.yaml", "file", "both"),
    "gitignore-block": (".gitignore", "block", "both"),
    "agents-block": ("AGENTS.md", "block", "both"),
    "required-perk-version": (".perk/required-perk-version", "file", "both"),
}


class TestDescriptorRegistry:
    def test_exactly_the_pinned_keys_unique(self):
        keys = [d.key for d in managed_artifacts()]
        assert len(keys) == len(set(keys))
        assert set(keys) == set(EXPECTED_ARTIFACTS)

    def test_each_path_kind_scope_matches_the_pinned_table(self):
        for descriptor in managed_artifacts():
            assert (descriptor.path, descriptor.kind, descriptor.scope) == EXPECTED_ARTIFACTS[
                descriptor.key
            ]

    def test_state_file_is_excluded_from_its_own_artifact_set(self):
        """The no-recursive-churn pin: no descriptor names the state file."""
        for descriptor in managed_artifacts():
            assert "managed-state" not in descriptor.key
            assert "managed-state" not in descriptor.path


class TestDesiredPayloads:
    def test_required_perk_version_payload(self, tmp_path):
        payload = _descriptor("required-perk-version").desired_payload(tmp_path, self_repo=False)
        assert payload == render_version_pin().encode("utf-8")

    def test_runner_workflow_payload(self, tmp_path):
        payload = _descriptor("runner-workflow").desired_payload(tmp_path, self_repo=False)
        assert payload == PERK_RUN_WORKFLOW.encode("utf-8")

    def test_remote_setup_action_differs_self_vs_consumer(self, tmp_path):
        descriptor = _descriptor("remote-setup-action")
        assert descriptor.desired_payload(tmp_path, self_repo=True) != descriptor.desired_payload(
            tmp_path, self_repo=False
        )

    def test_skills_manifest_payload(self, tmp_path):
        for self_repo in (True, False):
            payload = _descriptor("skills-manifest").desired_payload(tmp_path, self_repo=self_repo)
            assert payload == _desired_skills_manifest(self_repo).encode("utf-8")

    def test_block_hashes_match_hash_block(self, tmp_path):
        gitignore = _descriptor("gitignore-block").desired_hash(tmp_path, self_repo=False)
        agents = _descriptor("agents-block").desired_hash(tmp_path, self_repo=False)
        assert gitignore == hash_block(GITIGNORE_BODY)
        assert agents == hash_block(_agents_inner())

    def test_subagent_agents_payload_is_the_directory_manifest(self, tmp_path):
        source_dir = _resources.agents_dir()
        files = {f"{name}.md": (source_dir / f"{name}.md").read_bytes() for name in PERK_AGENTS}
        payload = _descriptor("subagent-agents").desired_payload(tmp_path, self_repo=False)
        assert payload == directory_manifest(files)

    def test_settings_consumer_payload_pins_perk_and_borrowed_set(self, tmp_path):
        payload = _descriptor("settings-wiring").desired_payload(tmp_path, self_repo=False)
        portion = json.loads(payload)
        assert f"npm:@mgiles/perk@{__version__}" in portion["packages"]
        for borrowed in BORROWED_PACKAGES:
            assert borrowed in portion["packages"]

    def test_settings_self_payload_wires_the_local_package(self, tmp_path):
        payload = _descriptor("settings-wiring").desired_payload(tmp_path, self_repo=True)
        assert ".." in json.loads(payload)["packages"]

    def test_settings_hash_moves_with_the_committed_config(self, tmp_path):
        descriptor = _descriptor("settings-wiring")
        before = descriptor.desired_hash(tmp_path, self_repo=False)
        config = paths.config_file(tmp_path)
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text('[issues]\nbackend = "linear"\n', encoding="utf-8")
        after = descriptor.desired_hash(tmp_path, self_repo=False)
        assert before != after


class TestDesiredState:
    def test_stamps_version_sorts_and_hashes(self, tmp_path):
        state = desired_state(tmp_path, self_repo=False)
        assert state.version == __version__
        keys = [a.key for a in state.artifacts]
        assert keys == sorted(keys)
        assert set(keys) == set(EXPECTED_ARTIFACTS)
        by_key = {d.key: d for d in managed_artifacts()}
        for artifact in state.artifacts:
            assert artifact.version == __version__
            assert artifact.hash == by_key[artifact.key].desired_hash(tmp_path, self_repo=False)


class TestRoundTrip:
    def test_save_then_load_round_trips(self, tmp_path):
        state = desired_state(tmp_path, self_repo=False)
        save_managed_state(tmp_path, state)
        loaded = load_managed_state(tmp_path)
        assert loaded == state

    def test_render_load_render_is_a_byte_identity(self, tmp_path):
        state = desired_state(tmp_path, self_repo=True)
        save_managed_state(tmp_path, state)
        text = paths.managed_state_file(tmp_path).read_text(encoding="utf-8")
        loaded = load_managed_state(tmp_path)
        assert loaded is not None
        assert render_managed_state(loaded) == text

    def test_missing_file_returns_none(self, tmp_path):
        assert load_managed_state(tmp_path) is None

    def test_malformed_toml_raises(self, tmp_path):
        state_file = paths.managed_state_file(tmp_path)
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text("not = [valid", encoding="utf-8")
        with pytest.raises(ManagedStateError):
            load_managed_state(tmp_path)

    def test_wrong_typed_field_raises_translated_error(self, tmp_path):
        state_file = paths.managed_state_file(tmp_path)
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(
            "[managed]\n"
            'version = "1.0.0"\n'
            "[managed.artifacts.agents-block]\n"
            'path = "AGENTS.md"\n'
            'kind = "block"\n'
            "version = 1\n"  # TOML integer where a string is required — no str <- int coercion
            'hash = "sha256:00"\n',
            encoding="utf-8",
        )
        with pytest.raises(ManagedStateError, match=r"managed-state\.toml"):
            load_managed_state(tmp_path)

    def test_unknown_sibling_keys_are_ignored(self, tmp_path):
        state_file = paths.managed_state_file(tmp_path)
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(
            "future-top-level = true\n"
            "[managed]\n"
            'version = "9.9.9"\n'
            "future-key = 3\n"
            "[managed.artifacts.agents-block]\n"
            'path = "AGENTS.md"\n'
            'kind = "block"\n'
            'version = "9.9.9"\n'
            'hash = "sha256:00"\n'
            "future-field = false\n",
            encoding="utf-8",
        )
        state = load_managed_state(tmp_path)
        assert state == ManagedState(
            version="9.9.9",
            artifacts=(
                ArtifactState(
                    key="agents-block",
                    path="AGENTS.md",
                    kind="block",
                    version="9.9.9",
                    hash="sha256:00",
                ),
            ),
        )

    def test_unknown_kind_loads_verbatim(self, tmp_path):
        state_file = paths.managed_state_file(tmp_path)
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(
            "[managed]\n"
            'version = "9.9.9"\n'
            "[managed.artifacts.future-artifact]\n"
            'path = "future.txt"\n'
            'kind = "hologram"\n'
            'version = "9.9.9"\n'
            'hash = "sha256:00"\n',
            encoding="utf-8",
        )
        state = load_managed_state(tmp_path)
        assert state is not None
        assert state.artifacts[0].kind == "hologram"

    def test_wrong_typed_field_rejected_at_the_model(self):
        """The lenient model still rejects a wrong-typed scalar (drive via model_validate)."""
        with pytest.raises(ValueError):
            ManagedStateFileModel.model_validate({"managed": {"version": 1}})

    def test_domain_is_frozen(self):
        artifact = ArtifactState(
            key="agents-block", path="AGENTS.md", kind="block", version="1", hash="sha256:00"
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            artifact.kind = "file"  # ty: ignore[invalid-assignment]


class TestClassifyArtifact:
    """The pure five-status classification matrix (first match wins)."""

    def test_not_installed_wins_even_with_no_recorded_row(self):
        assert classify_artifact(observed=None, desired="sha256:aa", recorded=None) == (
            "not-installed"
        )
        assert classify_artifact(observed=None, desired="sha256:aa", recorded="sha256:bb") == (
            "not-installed"
        )

    def test_up_to_date_regardless_of_recorded(self):
        # A stale/absent recorded row never demotes a converged artifact.
        for recorded in (None, "sha256:aa", "sha256:stale"):
            assert (
                classify_artifact(observed="sha256:aa", desired="sha256:aa", recorded=recorded)
                == "up-to-date"
            )

    def test_drift_without_recorded_is_state_missing(self):
        assert classify_artifact(observed="sha256:bb", desired="sha256:aa", recorded=None) == (
            "state-missing"
        )

    def test_drift_matching_recorded_is_changed_upstream(self):
        assert classify_artifact(
            observed="sha256:bb", desired="sha256:aa", recorded="sha256:bb"
        ) == ("changed-upstream")

    def test_drift_not_matching_recorded_is_locally_modified(self):
        assert classify_artifact(
            observed="sha256:cc", desired="sha256:aa", recorded="sha256:bb"
        ) == ("locally-modified")


class TestObservedPayloads:
    def test_file_present_and_absent(self, tmp_path):
        descriptor = _descriptor("required-perk-version")
        assert descriptor.observed_payload(tmp_path) is None
        target = tmp_path / ".perk" / "required-perk-version"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"1.2.3\n")
        assert descriptor.observed_payload(tmp_path) == b"1.2.3\n"

    def test_directory_missing_and_empty_are_not_installed(self, tmp_path):
        descriptor = _descriptor("subagent-agents")
        assert descriptor.observed_payload(tmp_path) is None
        agents = tmp_path / ".pi" / "agents" / "perk"
        agents.mkdir(parents=True)
        assert descriptor.observed_payload(tmp_path) is None  # zero .md files
        (agents / "stray.txt").write_bytes(b"not md")
        assert descriptor.observed_payload(tmp_path) is None  # non-md invisible

    def test_directory_manifest_and_stray_md_sensitivity(self, tmp_path):
        descriptor = _descriptor("subagent-agents")
        agents = tmp_path / ".pi" / "agents" / "perk"
        agents.mkdir(parents=True)
        (agents / "a.md").write_bytes(b"alpha")
        base = descriptor.observed_hash(tmp_path)
        assert base == hash_directory({"a.md": b"alpha"})
        (agents / "stray.md").write_bytes(b"extra")
        assert descriptor.observed_hash(tmp_path) != base  # a stray .md changes the hash
        (agents / "stray.txt").write_bytes(b"noise")  # ...but a non-md file does not
        assert descriptor.observed_hash(tmp_path) == hash_directory(
            {"a.md": b"alpha", "stray.md": b"extra"}
        )

    def test_block_round_trips_with_the_real_embedding(self, tmp_path):
        descriptor = _descriptor("agents-block")
        assert descriptor.observed_payload(tmp_path) is None  # missing file
        target = tmp_path / "AGENTS.md"
        target.write_text("# AGENTS\n\nno markers\n", encoding="utf-8")
        assert descriptor.observed_payload(tmp_path) is None  # markers absent
        _apply_managed_block(
            target,
            begin="<!-- BEGIN perk managed -->",
            end="<!-- END perk managed -->",
            inner=_agents_inner(),
            label="AGENTS.md",
        )
        assert descriptor.observed_hash(tmp_path) == descriptor.desired_hash(
            tmp_path, self_repo=False
        )

    def test_block_trailing_newline_canonicalization(self, tmp_path):
        descriptor = _descriptor("gitignore-block")
        target = tmp_path / ".gitignore"
        target.write_text(
            f"# BEGIN perk managed\n{GITIGNORE_BODY}\n# END perk managed\n", encoding="utf-8"
        )
        base = descriptor.observed_hash(tmp_path)
        target.write_text(
            f"# BEGIN perk managed\n{GITIGNORE_BODY}\n\n\n# END perk managed\n", encoding="utf-8"
        )
        assert descriptor.observed_hash(tmp_path) == base

    def test_settings_absent_and_malformed_are_not_installed(self, tmp_path):
        descriptor = _descriptor("settings-wiring")
        assert descriptor.observed_payload(tmp_path) is None
        settings = tmp_path / ".pi" / "settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text("{not json", encoding="utf-8")
        assert descriptor.observed_payload(tmp_path) is None
        settings.write_text('["a list, not an object"]', encoding="utf-8")
        assert descriptor.observed_payload(tmp_path) is None

    def test_settings_converged_repo_observes_equal_to_desired(self, tmp_path):
        assert run_init(tmp_path, verify=False).ok
        descriptor = _descriptor("settings-wiring")
        assert descriptor.observed_hash(tmp_path) == descriptor.desired_hash(
            tmp_path, self_repo=False
        )

    def test_settings_foreign_package_is_invisible(self, tmp_path):
        assert run_init(tmp_path, verify=False).ok
        descriptor = _descriptor("settings-wiring")
        base = descriptor.observed_hash(tmp_path)
        settings_path = tmp_path / ".pi" / "settings.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        settings["packages"].append("npm:some-users-own-package")
        settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        assert descriptor.observed_hash(tmp_path) == base

    def test_settings_edited_borrowed_entry_changes_the_hash(self, tmp_path):
        assert run_init(tmp_path, verify=False).ok
        descriptor = _descriptor("settings-wiring")
        base = descriptor.observed_hash(tmp_path)
        settings_path = tmp_path / ".pi" / "settings.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        settings["packages"] = [
            "npm:pi-subagents@0.0.1" if p == "npm:pi-subagents" else p for p in settings["packages"]
        ]
        settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        assert descriptor.observed_hash(tmp_path) != base

    def test_settings_order_permutation_is_invisible(self, tmp_path):
        """The canonical-order proof: permuting perk-managed entries leaves the hash unchanged."""
        assert run_init(tmp_path, verify=False).ok
        descriptor = _descriptor("settings-wiring")
        base = descriptor.observed_hash(tmp_path)
        settings_path = tmp_path / ".pi" / "settings.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        settings["packages"] = list(reversed(settings["packages"]))
        settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        assert descriptor.observed_hash(tmp_path) == base


class TestConvergenceObservationRoundTrip:
    def test_every_descriptor_observes_its_desired_payload_after_init(self, tmp_path):
        """The standing guard against extraction/convergence twin drift."""
        assert run_init(tmp_path, verify=False).ok
        for descriptor in managed_artifacts():
            assert descriptor.observed_hash(tmp_path) == descriptor.desired_hash(
                tmp_path, self_repo=False
            ), f"observed != desired for {descriptor.key} on a freshly converged repo"


class TestRecordManagedState:
    def test_creates_then_no_ops_then_records_again(self, tmp_path):
        assert record_managed_state(tmp_path, self_repo=False) == (
            ".perk/managed-state.toml: recorded"
        )
        assert load_managed_state(tmp_path) == desired_state(tmp_path, self_repo=False)
        assert record_managed_state(tmp_path, self_repo=False) is None  # content-gated no-op
        paths.managed_state_file(tmp_path).unlink()
        assert record_managed_state(tmp_path, self_repo=False) == (
            ".perk/managed-state.toml: recorded"
        )

    def test_rewrites_a_corrupted_file_as_updated(self, tmp_path):
        record_managed_state(tmp_path, self_repo=False)
        paths.managed_state_file(tmp_path).write_text("not = [valid", encoding="utf-8")
        assert record_managed_state(tmp_path, self_repo=False) == (
            ".perk/managed-state.toml: updated"
        )
        assert load_managed_state(tmp_path) == desired_state(tmp_path, self_repo=False)
