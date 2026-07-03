"""The managed-artifact state library (`convergence/managed_state.py`)."""

import dataclasses
import json

import pytest

from perk import __version__, _resources
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
    desired_state,
    directory_manifest,
    hash_block,
    hash_bytes,
    hash_directory,
    load_managed_state,
    managed_artifacts,
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
