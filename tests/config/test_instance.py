from pathlib import Path

import pytest

from nomi.config.instance import (
    DEFAULT_INSTANCE_NAME,
    derive_instance_root,
    list_instance_contexts,
    lookup_instance_context,
    register_instance,
    remove_registered_instance,
    resolve_instance_context,
)


def test_resolve_instance_context_priority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nomi.config.instance.get_default_instance_root",
        lambda: tmp_path / "default-root",
    )
    register_instance("team-a", tmp_path / "registry-root")

    context = resolve_instance_context(
        instance="team-a",
        instance_root=tmp_path / "explicit-root",
        config_path=tmp_path / "cfg-root" / "config.json",
    )

    assert context.root == (tmp_path / "explicit-root").resolve()


def test_register_and_list_instance_contexts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "nomi.config.instance.get_default_instance_root",
        lambda: tmp_path / "default-root",
    )
    monkeypatch.setattr(
        "nomi.config.instance.get_instance_registry_path",
        lambda: tmp_path / "instances.json",
    )

    created = register_instance("team-a", tmp_path / "team-a-root")
    listed = list_instance_contexts()

    assert created.name == "team-a"
    assert lookup_instance_context("team-a").root == (tmp_path / "team-a-root").resolve()
    assert listed[0].name == DEFAULT_INSTANCE_NAME
    assert listed[1].name == "team-a"


def test_default_instance_cannot_be_removed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "nomi.config.instance.get_instance_registry_path",
        lambda: tmp_path / "instances.json",
    )

    with pytest.raises(ValueError, match="default instance cannot be removed"):
        remove_registered_instance(DEFAULT_INSTANCE_NAME)


def test_named_instance_default_root_is_under_instances(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "nomi.config.instance.DEFAULT_NAMED_INSTANCES_ROOT",
        tmp_path / "instances",
    )

    assert derive_instance_root("team-a") == (tmp_path / "instances" / "team-a").resolve()
