from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Self

VERSION_PATTERN = re.compile(
    r"^(?:v)?(?P<major>0|[1-9][0-9]*)\.(?P<minor>0|[1-9][0-9]*)\.(?P<patch>0|[1-9][0-9]*)$"
)


class ReleasePlanError(ValueError):
    pass


class Bump(StrEnum):
    PATCH = "patch"
    MINOR = "minor"
    MAJOR = "major"


class ReleaseMode(StrEnum):
    CREATE = "create"
    RESUME = "resume"


@dataclass(frozen=True, order=True)
class Version:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, value: str) -> Self:
        match = VERSION_PATTERN.fullmatch(value)
        if match is None:
            raise ReleasePlanError(f"invalid version {value!r}; expected X.Y.Z")
        return cls(*(int(match[group]) for group in ("major", "minor", "patch")))

    def bump(self, bump: Bump) -> Version:
        match bump:
            case Bump.MAJOR:
                return Version(self.major + 1, 0, 0)
            case Bump.MINOR:
                return Version(self.major, self.minor + 1, 0)
            case Bump.PATCH:
                return Version(self.major, self.minor, self.patch + 1)

    @property
    def tag(self) -> str:
        return f"v{self}"

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True)
class ReleaseRequest:
    project_version: Version
    explicit_version: Version | None
    bump: Bump
    head_commit: str
    tag_commits: Mapping[Version, str]
    published_versions: frozenset[Version]


@dataclass(frozen=True)
class ReleasePlan:
    current_version: Version
    version: Version
    latest_version: Version | None
    mode: ReleaseMode

    @property
    def tag_exists(self) -> bool:
        return self.mode is ReleaseMode.RESUME

    def github_outputs(self) -> dict[str, str]:
        return {
            "current": str(self.current_version),
            "latest_tag": self.latest_version.tag if self.latest_version else "",
            "mode": self.mode.value,
            "tag": self.version.tag,
            "tag_exists": str(self.tag_exists).lower(),
            "version": str(self.version),
        }


def plan_release(request: ReleaseRequest) -> ReleasePlan:
    latest = max(request.tag_commits, default=None)
    target = _target_version(request, latest)
    tag_commit = request.tag_commits.get(target)

    if target in request.published_versions:
        raise ReleasePlanError(f"GitHub release {target.tag} already exists")

    if tag_commit is not None:
        if target != request.project_version or tag_commit != request.head_commit:
            raise ReleasePlanError(
                f"tag {target.tag} exists but does not match the current release state"
            )
        mode = ReleaseMode.RESUME
    else:
        if latest is not None and target <= latest:
            raise ReleasePlanError(f"version {target} is not above the latest tag {latest.tag}")
        mode = ReleaseMode.CREATE

    return ReleasePlan(
        current_version=request.project_version,
        version=target,
        latest_version=latest,
        mode=mode,
    )


def _target_version(request: ReleaseRequest, latest: Version | None) -> Version:
    if request.explicit_version is not None:
        return request.explicit_version
    if latest is None or request.project_version > latest:
        return request.project_version
    return latest.bump(request.bump)


def inspect_repository(root: Path, *, explicit_version: str, bump: Bump) -> ReleaseRequest:
    project_version = _read_project_version(root / "pyproject.toml")
    manifest_version = _read_manifest_version(
        root / "custom_components" / "hypercolor" / "manifest.json"
    )
    if project_version != manifest_version:
        raise ReleasePlanError(
            f"project version {project_version} does not match manifest {manifest_version}"
        )

    return ReleaseRequest(
        project_version=project_version,
        explicit_version=Version.parse(explicit_version) if explicit_version else None,
        bump=bump,
        head_commit=_run(root, "git", "rev-parse", "HEAD"),
        tag_commits=_read_tag_commits(root),
        published_versions=_read_published_versions(root),
    )


def _read_project_version(path: Path) -> Version:
    with path.open("rb") as file:
        document = tomllib.load(file)
    return Version.parse(document["project"]["version"])


def _read_manifest_version(path: Path) -> Version:
    document = json.loads(path.read_text(encoding="utf-8"))
    return Version.parse(document["version"])


def _read_tag_commits(root: Path) -> dict[Version, str]:
    tags: dict[Version, str] = {}
    for tag in _run(root, "git", "tag", "--list").splitlines():
        if not tag.startswith("v") or VERSION_PATTERN.fullmatch(tag) is None:
            continue
        version = Version.parse(tag)
        tags[version] = _run(root, "git", "rev-list", "-n", "1", tag)
    return tags


def _read_published_versions(root: Path) -> frozenset[Version]:
    raw = _run(root, "gh", "release", "list", "--limit", "1000", "--json", "tagName")
    releases = json.loads(raw)
    if len(releases) == 1000:
        raise ReleasePlanError("cannot prove release state because GitHub returned 1000 releases")

    versions = set()
    for release in releases:
        tag = release.get("tagName")
        if isinstance(tag, str) and tag.startswith("v") and VERSION_PATTERN.fullmatch(tag):
            versions.add(Version.parse(tag))
    return frozenset(versions)


def _run(root: Path, *command: str) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as error:
        raise ReleasePlanError(f"required command not found: {command[0]}") from error
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() or error.stdout.strip() or f"exit {error.returncode}"
        raise ReleasePlanError(f"{' '.join(command)} failed: {detail}") from error
    return result.stdout.strip()


def _write_github_outputs(path: Path, plan: ReleasePlan) -> None:
    with path.open("a", encoding="utf-8") as file:
        for name, value in plan.github_outputs().items():
            file.write(f"{name}={value}\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan a safe Hypercolor HASS release.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--version", default="")
    parser.add_argument("--bump", type=Bump, choices=tuple(Bump), default=Bump.PATCH)
    parser.add_argument(
        "--github-output",
        type=Path,
        default=Path(os.environ["GITHUB_OUTPUT"]) if "GITHUB_OUTPUT" in os.environ else None,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        request = inspect_repository(
            args.root.resolve(),
            explicit_version=args.version,
            bump=args.bump,
        )
        plan = plan_release(request)
        if args.github_output is not None:
            _write_github_outputs(args.github_output, plan)
        print(json.dumps(plan.github_outputs(), sort_keys=True))
    except (KeyError, json.JSONDecodeError, ReleasePlanError) as error:
        print(f"release plan failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
