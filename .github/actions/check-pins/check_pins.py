#!/usr/bin/env python3
"""Fail if any `uses:` in the given workflow directories is not pinned to an
immutable reference.

Mirrors the DARC SY-1.05 rubric:

  local                 `./path`                     nothing to pin
  sha_pinned            `owner/action@<40-hex-sha>`  immutable
  first_party_exact_tag `actions/x@v1.2.3`           immutable by policy
  docker_digest         `docker://img@sha256:<64>`   immutable
  third_party_exact_tag `other/x@v1.2.3`             needs a human attestation
                                                     (verified-creator action)
  mutable               anything else                REPOINTABLE -> fail

Exits 1 on any mutable reference, and 1 on a third-party exact-SemVer tag
unless it is listed in VERIFIED_CREATORS below (the attestation, in code).
"""

import re
import sys
from pathlib import Path

import yaml

FIRST_PARTY_OWNERS = {"actions"}
# Verified-creator actions that publish immutable releases may be pinned by an
# exact SemVer release tag. Add an owner here only with evidence; everything
# else must carry a commit SHA.
VERIFIED_CREATORS: set[str] = set()

FULL_COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$", re.I)
EXACT_SEMVER_TAG = re.compile(r"^v?\d+\.\d+\.\d+$")
DOCKER_IMAGE_DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$", re.I)
ACTION_PATH = re.compile(
    r"^[a-z\d](?:[a-z\d]|-(?=[a-z\d]))*/[\w.-]+(?:/[\w./-]+)?$", re.I
)


def classify(ref: str) -> str:
    if ref.startswith("./"):
        return "local"
    if ref.startswith("docker://"):
        return "docker_digest" if DOCKER_IMAGE_DIGEST.search(ref) else "mutable"
    slash, at = ref.find("/"), ref.rfind("@")
    if slash == -1 or at <= slash:
        return "mutable"
    if not ACTION_PATH.match(ref[:at]):
        return "mutable"
    version = ref[at + 1 :]
    if FULL_COMMIT_SHA.match(version):
        return "sha_pinned"
    if EXACT_SEMVER_TAG.match(version):
        owner = ref[:slash].lower()
        if owner in FIRST_PARTY_OWNERS:
            return "first_party_exact_tag"
        return (
            "verified_creator_exact_tag"
            if owner in VERIFIED_CREATORS
            else "third_party_exact_tag"
        )
    return "mutable"


def uses_refs(node):
    """Yield every `uses:` value in the parsed workflow, at any depth."""
    if isinstance(node, list):
        for item in node:
            yield from uses_refs(item)
    elif isinstance(node, dict):
        for key, value in node.items():
            if key == "uses" and isinstance(value, str):
                yield value.strip()
            else:
                yield from uses_refs(value)


def main(argv: list[str]) -> int:
    paths = [
        path
        for directory in (argv or [".github/workflows"])
        for path in sorted(Path(directory).glob("*.y*ml"))
    ]
    if not paths:
        print("no workflow files found")
        return 0

    problems, pinned = [], 0
    for path in paths:
        workflow = yaml.safe_load(path.read_text())
        for ref in uses_refs(workflow):
            kind = classify(ref)
            if kind in ("mutable", "third_party_exact_tag"):
                problems.append((path, ref, kind))
            else:
                pinned += 1
                print(f"ok   {path}: {ref} ({kind})")

    for path, ref, kind in problems:
        reason = (
            "not pinned to an immutable ref"
            if kind == "mutable"
            else "third-party action pinned by tag, not a commit SHA"
        )
        print(f"FAIL {path}: {ref} — {reason}", file=sys.stderr)

    if problems:
        print(
            f"\n{len(problems)} unpinned action reference(s) — see DARC SY-1.05.",
            file=sys.stderr,
        )
        return 1

    print(f"\nall {pinned} action reference(s) are pinned to immutable refs.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
