from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
import scripts.release as release_module
from scripts.release import (
    Bump,
    ReleaseMode,
    ReleasePlanError,
    ReleaseRequest,
    Version,
    _read_published_versions,
    _run,
    _write_github_outputs,
    inspect_repository,
    main,
    plan_release,
)

HEAD = "a" * 40


def test_composite_action_keeps_git_auth_header_on_one_line() -> None:
    action = Path(".github/actions/setup-hypercolor/action.yml").read_text(encoding="utf-8")
    assert "base64 | tr -d '\\n'" in action

    environment = {**os.environ, "HYPERCOLOR_TOKEN": "github_pat_" + "x" * 96}
    encoded = subprocess.run(
        [
            "/bin/bash",
            "-c",
            "printf 'x-access-token:%s' \"${HYPERCOLOR_TOKEN}\" | base64 | tr -d '\\n'",
        ],
        check=True,
        capture_output=True,
        env=environment,
        text=True,
    ).stdout

    assert encoded
    assert "\n" not in encoded


def _request(
    *,
    project: str = "1.2.3",
    explicit: str | None = None,
    bump: Bump = Bump.PATCH,
    tags: dict[str, str] | None = None,
    published: set[str] | None = None,
) -> ReleaseRequest:
    return ReleaseRequest(
        project_version=Version.parse(project),
        explicit_version=Version.parse(explicit) if explicit else None,
        bump=bump,
        head_commit=HEAD,
        tag_commits={Version.parse(tag): commit for tag, commit in (tags or {}).items()},
        published_versions=frozenset(Version.parse(tag) for tag in published or set()),
    )


def _write_version_files(root: Path, version: str = "1.2.3") -> None:
    (root / "pyproject.toml").write_text(f'[project]\nversion = "{version}"\n', encoding="utf-8")
    manifest = root / "custom_components" / "hypercolor" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"version": version}), encoding="utf-8")


@pytest.mark.parametrize(
    ("bump", "expected"),
    [
        (Bump.PATCH, "1.2.4"),
        (Bump.MINOR, "1.3.0"),
        (Bump.MAJOR, "2.0.0"),
    ],
)
def test_bumps_latest_tag(bump: Bump, expected: str) -> None:
    plan = plan_release(_request(bump=bump, tags={"1.2.3": "b" * 40}))

    assert str(plan.version) == expected
    assert plan.mode is ReleaseMode.CREATE


@pytest.mark.parametrize(
    ("project", "tags", "expected"),
    [
        ("0.1.0", {}, "0.1.0"),
        ("1.3.0", {"1.2.3": "b" * 40}, "1.3.0"),
    ],
)
def test_uses_project_version_for_first_or_prestamped_release(
    project: str,
    tags: dict[str, str],
    expected: str,
) -> None:
    plan = plan_release(_request(project=project, tags=tags))

    assert str(plan.version) == expected
    assert plan.mode is ReleaseMode.CREATE


def test_explicit_version_overrides_bump() -> None:
    plan = plan_release(_request(explicit="v3.1.4", tags={"1.2.3": "b" * 40}))

    assert str(plan.version) == "3.1.4"


def test_missing_target_tag_creates_release_without_rewriting_version() -> None:
    plan = plan_release(_request(project="1.2.4", explicit="1.2.4", tags={"1.2.3": HEAD}))

    assert plan.mode is ReleaseMode.CREATE
    assert plan.tag_exists is False


def test_matching_unpublished_tag_resumes_release() -> None:
    plan = plan_release(_request(explicit="1.2.3", tags={"1.2.3": HEAD}))

    assert plan.mode is ReleaseMode.RESUME
    assert plan.tag_exists is True


@pytest.mark.parametrize(
    ("release_request", "message"),
    [
        (
            _request(explicit="1.2.3", tags={"1.2.3": "b" * 40}),
            "does not match the current release state",
        ),
        (
            _request(explicit="1.2.3", tags={"1.2.3": HEAD}, published={"1.2.3"}),
            "already exists",
        ),
        (
            _request(explicit="1.2.2", tags={"1.2.3": HEAD}),
            "is not above the latest tag",
        ),
    ],
)
def test_rejects_unsafe_release_state(release_request: ReleaseRequest, message: str) -> None:
    with pytest.raises(ReleasePlanError, match=message):
        plan_release(release_request)


def test_writes_github_action_outputs(tmp_path: Path) -> None:
    output = tmp_path / "github-output"
    plan = plan_release(_request(explicit="1.2.3", tags={"1.2.3": HEAD}))

    _write_github_outputs(output, plan)

    assert output.read_text(encoding="utf-8").splitlines() == [
        "current=1.2.3",
        "latest_tag=v1.2.3",
        "mode=resume",
        "tag=v1.2.3",
        "tag_exists=true",
        "version=1.2.3",
    ]


def test_inspects_repository_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_version_files(tmp_path)

    def fake_run(root: Path, *command: str) -> str:
        assert root == tmp_path
        match command:
            case ("git", "rev-parse", "HEAD"):
                return HEAD
            case ("git", "tag", "--list"):
                return "v1.2.2\n1.2.1\nnot-a-release"
            case ("git", "rev-list", "-n", "1", "v1.2.2"):
                return "b" * 40
            case (
                "gh",
                "release",
                "list",
                "--limit",
                "1000",
                "--json",
                "tagName",
            ):
                return json.dumps([{"tagName": "v1.2.2"}, {"tagName": "nightly"}])
            case _:
                raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(release_module, "_run", fake_run)

    request = inspect_repository(tmp_path, explicit_version="1.2.4", bump=Bump.MINOR)

    assert request == ReleaseRequest(
        project_version=Version.parse("1.2.3"),
        explicit_version=Version.parse("1.2.4"),
        bump=Bump.MINOR,
        head_commit=HEAD,
        tag_commits={Version.parse("1.2.2"): "b" * 40},
        published_versions=frozenset({Version.parse("1.2.2")}),
    )


@pytest.mark.parametrize(("release_count", "fails"), [(999, False), (1000, True)])
def test_github_release_listing_must_be_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    release_count: int,
    fails: bool,
) -> None:
    releases = json.dumps([{"tagName": "v1.2.3"}] * release_count)
    monkeypatch.setattr(release_module, "_run", lambda *_args: releases)

    if fails:
        with pytest.raises(ReleasePlanError, match="cannot prove release state"):
            _read_published_versions(tmp_path)
    else:
        assert _read_published_versions(tmp_path) == frozenset({Version.parse("1.2.3")})


def test_command_failure_is_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.CalledProcessError(7, ["gh", "release"], stderr="denied")

    monkeypatch.setattr(subprocess, "run", fail)

    with pytest.raises(ReleasePlanError, match="gh release failed: denied"):
        _run(tmp_path, "gh", "release")


def test_cli_writes_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    github_output = tmp_path / "github-output"

    def fake_inspection(root: Path, *, explicit_version: str, bump: Bump) -> ReleaseRequest:
        assert root == Path.cwd()
        assert explicit_version == "1.2.4"
        assert bump is Bump.PATCH
        return _request(explicit="1.2.4", tags={"1.2.3": "b" * 40})

    monkeypatch.setattr(release_module, "inspect_repository", fake_inspection)

    result = main(["--version", "1.2.4", "--github-output", str(github_output)])

    assert result == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "create"
    assert "tag=v1.2.4\n" in github_output.read_text(encoding="utf-8")


def test_cli_returns_two_for_unsafe_state(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_inspection(_root: Path, *, explicit_version: str, bump: Bump) -> ReleaseRequest:
        assert explicit_version == "1.2.3"
        assert bump is Bump.PATCH
        return _request(explicit="1.2.3", tags={"1.2.3": "b" * 40})

    monkeypatch.setattr(release_module, "inspect_repository", fake_inspection)

    assert main(["--version", "1.2.3"]) == 2
    assert "does not match the current release state" in capsys.readouterr().err
