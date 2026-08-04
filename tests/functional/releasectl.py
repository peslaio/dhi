#!/usr/bin/env python3
"""Create and verify run-scoped archives of functionally tested images."""

import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import time


SCHEMA_VERSION = 1
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
IMAGE_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
COMMON_RELEASE_PATHS = {
    ".github/workflows/reusable-aggregate-image-contract.yml",
    ".github/workflows/reusable-build-debian-image.yml",
    ".github/workflows/reusable-prepare-image-matrix.yml",
    ".github/workflows/reusable-publish-image-manifest.yml",
    ".github/workflows/reusable-publish-tested-image.yml",
    "tests/functional/contractctl.rb",
    "tests/functional/fixturectl.py",
    "tests/functional/fixtures.lock.json",
    "tests/functional/lifecyclectl.py",
    "tests/functional/releasectl.py",
    "tests/functional/result.py",
    "tests/functional/result.schema.json",
    "tests/functional/run.sh",
    "tests/functional/scan_result.py",
    "tests/functional/timeout.py",
}
COMMON_RELEASE_PREFIXES = (
    "tests/functional/harness/",
)
DEFAULT_REGISTRY_ATTEMPTS = 5
MAX_REGISTRY_ATTEMPTS = 10
REGISTRY_RETRY_DELAY_SECONDS = 15
REGISTRY_METADATA_TIMEOUT_SECONDS = 60
REGISTRY_TRANSFER_TIMEOUT_SECONDS = 300


class ReleaseArchiveError(ValueError):
    """Raised when a release archive or its metadata is invalid."""


def require(condition, message):
    if not condition:
        raise ReleaseArchiveError(message)


def require_exact_keys(value, expected, context):
    require(isinstance(value, dict), f"{context} must be an object")
    actual = set(value)
    expected = set(expected)
    require(
        actual == expected,
        f"{context} keys must be exactly {', '.join(sorted(expected))}",
    )


def write_process_output(output, stream):
    if output:
        stream.write(output)
        stream.flush()


def validate_registry_attempts(attempts):
    require(
        isinstance(attempts, int)
        and 1 <= attempts <= MAX_REGISTRY_ATTEMPTS,
        f"registry attempts must be between 1 and {MAX_REGISTRY_ATTEMPTS}",
    )


def text_output(value):
    if not value:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def redact_input(output, input_text):
    if not input_text:
        return output
    secrets = {input_text, input_text.rstrip("\r\n")}
    for secret in sorted(secrets, key=len, reverse=True):
        if secret:
            output = output.replace(secret, "***")
    return output


def registry_retry(
    command,
    operation,
    attempts,
    *,
    timeout_seconds=REGISTRY_METADATA_TIMEOUT_SECONDS,
    input_text=None,
    validator=None,
):
    """Run an idempotent registry operation with bounded linear backoff."""
    validate_registry_attempts(attempts)
    require(command, "registry command must not be empty")
    require(
        isinstance(timeout_seconds, int) and timeout_seconds > 0,
        "registry command timeout must be a positive integer",
    )

    for attempt in range(1, attempts + 1):
        try:
            completed = subprocess.run(
                command,
                input=input_text,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            stdout = text_output(error.stdout)
            stderr = text_output(error.stderr)
            failure = f"timed out after {timeout_seconds}s"
        else:
            stdout = completed.stdout or ""
            stderr = getattr(completed, "stderr", "") or ""
            failure = None
            validated = stdout
            if completed.returncode == 0:
                try:
                    if validator is not None:
                        validated = validator(stdout, stderr)
                except ReleaseArchiveError as error:
                    failure = str(error)
                else:
                    return (
                        validated,
                        redact_input(stdout, input_text),
                        redact_input(stderr, input_text),
                    )
            else:
                failure = f"exit status {completed.returncode}"

        stdout = redact_input(stdout, input_text)
        stderr = redact_input(stderr, input_text)

        write_process_output(stdout, sys.stderr)
        write_process_output(stderr, sys.stderr)
        if attempt == attempts:
            raise ReleaseArchiveError(
                f"{operation} failed after {attempts} attempts ({failure})"
            )
        delay = attempt * REGISTRY_RETRY_DELAY_SECONDS
        print(
            f"{operation} failed on attempt {attempt}/{attempts} ({failure}); "
            f"retrying in {delay}s",
            file=sys.stderr,
        )
        time.sleep(delay)

    raise AssertionError("unreachable registry retry state")


def registry_reference(value, context):
    require(isinstance(value, str) and value, f"{context} must not be empty")
    require(not value.startswith("-"), f"{context} must not start with a dash")
    require(not re.search(r"\s", value), f"{context} must not contain whitespace")
    return value


def registry_digest_from_push(stdout, stderr=""):
    digests = re.findall(
        r"\bdigest:\s*(sha256:[0-9a-f]{64})\b", stdout + "\n" + stderr
    )
    require(digests, "registry push did not report an immutable digest")
    unique_digests = set(digests)
    require(
        len(unique_digests) == 1,
        "registry push reported conflicting immutable digests",
    )
    return digests[0]


def registry_digest_from_inspect(stdout, expected_digest=None):
    digests = re.findall(r"(?m)^Digest:\s*(sha256:[0-9a-f]{64})\s*$", stdout)
    require(len(digests) == 1, "registry inspect did not report exactly one digest")
    if expected_digest is not None:
        require(
            digests[0] == expected_digest,
            f"registry inspect resolved {digests[0]} instead of {expected_digest}",
        )
    return digests[0]


def registry_json_from_inspect(stdout):
    try:
        document = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise ReleaseArchiveError(f"registry inspect returned invalid JSON: {error}") from error
    require(isinstance(document, dict), "registry inspect JSON must be an object")
    return stdout


def command_registry_login(arguments):
    registry = registry_reference(arguments.registry, "registry")
    username = registry_reference(arguments.username, "registry username")
    password = sys.stdin.read()
    require(password, "registry password must not be empty")
    registry_retry(
        [
            "docker",
            "login",
            registry,
            "--username",
            username,
            "--password-stdin",
        ],
        f"registry login to {registry}",
        arguments.attempts,
        input_text=password,
    )
    print(f"Authenticated to {registry}")


def command_registry_push(arguments):
    reference = registry_reference(arguments.reference, "push reference")
    digest, stdout, stderr = registry_retry(
        ["docker", "push", reference],
        f"registry push of {reference}",
        arguments.attempts,
        timeout_seconds=REGISTRY_TRANSFER_TIMEOUT_SECONDS,
        validator=registry_digest_from_push,
    )
    inspected_digest, inspect_stdout, inspect_stderr = registry_retry(
        ["docker", "buildx", "imagetools", "inspect", reference],
        f"registry digest inspection of pushed {reference}",
        arguments.attempts,
        validator=lambda value, _error: registry_digest_from_inspect(
            value, digest
        ),
    )
    require(inspected_digest == digest, "pushed registry digest verification failed")
    write_process_output(stdout, sys.stderr)
    write_process_output(stderr, sys.stderr)
    write_process_output(inspect_stdout, sys.stderr)
    write_process_output(inspect_stderr, sys.stderr)
    print(digest)


def command_registry_digest(arguments):
    reference = registry_reference(arguments.reference, "inspect reference")
    expected_digest = arguments.expected_digest
    if expected_digest is not None:
        require(
            SHA256_RE.fullmatch(expected_digest),
            "expected registry digest is invalid",
        )
    digest, stdout, stderr = registry_retry(
        ["docker", "buildx", "imagetools", "inspect", reference],
        f"registry digest inspection of {reference}",
        arguments.attempts,
        validator=lambda value, _error: registry_digest_from_inspect(
            value, expected_digest
        ),
    )
    write_process_output(stdout, sys.stderr)
    write_process_output(stderr, sys.stderr)
    print(digest)


def command_registry_command(arguments):
    command = list(arguments.registry_command)
    if command and command[0] == "--":
        command.pop(0)
    allowed_prefixes = (
        ("docker", "pull"),
        ("docker", "buildx", "imagetools", "create"),
        ("docker", "buildx", "imagetools", "inspect"),
    )
    require(
        any(tuple(command[: len(prefix)]) == prefix for prefix in allowed_prefixes),
        "registry-command only permits docker pull or buildx imagetools create/inspect",
    )
    is_create = tuple(command[:4]) == (
        "docker",
        "buildx",
        "imagetools",
        "create",
    )
    require(
        not is_create
        or not any(
            argument == "--append" or argument.startswith("--append=")
            for argument in command[4:]
        ),
        "registry-command does not permit non-idempotent imagetools create --append",
    )
    is_pull = tuple(command[:2]) == ("docker", "pull")
    is_raw_inspect = (
        tuple(command[:4]) == ("docker", "buildx", "imagetools", "inspect")
        and "--raw" in command[4:]
    )
    require(
        tuple(command[:4]) != ("docker", "buildx", "imagetools", "inspect")
        or is_raw_inspect,
        "registry-command permits imagetools inspect only with --raw",
    )
    stdout, _, stderr = registry_retry(
        command,
        "docker registry command",
        arguments.attempts,
        timeout_seconds=(
            REGISTRY_TRANSFER_TIMEOUT_SECONDS
            if is_pull
            else REGISTRY_METADATA_TIMEOUT_SECONDS
        ),
        validator=(
            (lambda value, _error: registry_json_from_inspect(value))
            if is_raw_inspect
            else None
        ),
    )
    write_process_output(stdout, sys.stdout)
    write_process_output(stderr, sys.stderr)


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def platform_parts(platform):
    parts = platform.split("/")
    require(len(parts) in (2, 3), f"invalid platform: {platform}")
    require(all(parts), f"invalid platform: {platform}")
    return parts[0], parts[1], parts[2] if len(parts) == 3 else None


def release_relevant_path(image_name, path):
    require(IMAGE_NAME_RE.fullmatch(image_name), f"invalid image name: {image_name}")
    if path in COMMON_RELEASE_PATHS:
        return True
    if path.startswith(COMMON_RELEASE_PREFIXES):
        return True
    if path.startswith(f"images/{image_name}/"):
        return True
    if path.startswith(f"tests/functional/{image_name}/"):
        return True
    if not path.startswith(".github/workflows/"):
        return False
    basename = pathlib.PurePosixPath(path).name
    return basename in {
        f"{image_name}-image.yml",
        f"{image_name}-images.yml",
        f"{image_name}-image-release.yml",
        f"{image_name}-images-release.yml",
    }


def expected_values(arguments):
    os_name, architecture, variant = platform_parts(arguments.platform)
    require(
        arguments.debian_arch == architecture,
        f"Debian architecture {arguments.debian_arch} does not match {arguments.platform}",
    )
    primary_tag = (
        f"{arguments.image_ref}:{arguments.image_version}-{arguments.debian_suite}"
    )
    return {
        "provenance": {
            "repository": arguments.repository,
            "commitSha": arguments.commit_sha,
            "runId": arguments.run_id,
            "runAttempt": arguments.run_attempt,
        },
        "image": {
            "name": arguments.image_name,
            "version": arguments.image_version,
            "debianSuite": arguments.debian_suite,
            "debianArch": arguments.debian_arch,
            "platform": arguments.platform,
            "ref": arguments.image_ref,
            "primaryTag": primary_tag,
            "architectureTag": f"{primary_tag}-{arguments.debian_arch}",
            "os": os_name,
            "architecture": architecture,
            "variant": variant,
        },
    }


def inspect_image(reference):
    completed = subprocess.run(
        ["docker", "image", "inspect", reference],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ReleaseArchiveError(
            f"docker image inspect failed for {reference}: {completed.stderr.strip()}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ReleaseArchiveError(
            f"docker image inspect returned invalid JSON for {reference}: {error}"
        ) from error
    require(
        isinstance(payload, list) and len(payload) == 1 and isinstance(payload[0], dict),
        f"docker image inspect must return exactly one image for {reference}",
    )
    image = payload[0]
    image_id = image.get("Id")
    require(isinstance(image_id, str) and SHA256_RE.fullmatch(image_id), "invalid image ID")
    os_name = image.get("Os")
    architecture = image.get("Architecture")
    variant = image.get("Variant") or None
    require(isinstance(os_name, str) and os_name, "image OS is missing")
    require(isinstance(architecture, str) and architecture, "image architecture is missing")
    require(variant is None or isinstance(variant, str), "image variant is invalid")
    return {
        "id": image_id,
        "os": os_name,
        "architecture": architecture,
        "variant": variant,
    }


def create_document(arguments, archive, inspected):
    expected = expected_values(arguments)
    require(inspected["os"] == expected["image"]["os"], "image OS mismatch")
    require(
        inspected["architecture"] == expected["image"]["architecture"],
        "image architecture mismatch",
    )
    if expected["image"]["variant"] is not None:
        require(inspected["variant"] == expected["image"]["variant"], "image variant mismatch")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "provenance": expected["provenance"],
        "image": {
            **expected["image"],
            "id": inspected["id"],
            "variant": inspected["variant"],
        },
        "archive": {
            "file": archive.name,
            "sha256": sha256_file(archive),
            "sizeBytes": archive.stat().st_size,
        },
    }


def validate_document(document, arguments, archive):
    require_exact_keys(
        document,
        {"schemaVersion", "provenance", "image", "archive"},
        "metadata",
    )
    require(document["schemaVersion"] == SCHEMA_VERSION, "unsupported schemaVersion")
    require_exact_keys(
        document["provenance"],
        {"repository", "commitSha", "runId", "runAttempt"},
        "metadata.provenance",
    )
    require_exact_keys(
        document["image"],
        {
            "name",
            "version",
            "debianSuite",
            "debianArch",
            "platform",
            "ref",
            "primaryTag",
            "architectureTag",
            "id",
            "os",
            "architecture",
            "variant",
        },
        "metadata.image",
    )
    require_exact_keys(
        document["archive"],
        {"file", "sha256", "sizeBytes"},
        "metadata.archive",
    )

    expected = expected_values(arguments)
    require(document["provenance"] == expected["provenance"], "release provenance mismatch")
    for key, value in expected["image"].items():
        if key == "variant" and value is None:
            continue
        require(document["image"].get(key) == value, f"metadata.image.{key} mismatch")

    image_id = document["image"].get("id")
    require(isinstance(image_id, str) and SHA256_RE.fullmatch(image_id), "invalid image ID")
    require(document["archive"]["file"] == archive.name, "archive file name mismatch")
    require(
        isinstance(document["archive"]["sizeBytes"], int)
        and document["archive"]["sizeBytes"] > 0,
        "invalid archive size",
    )
    require(archive.is_file(), f"release archive does not exist: {archive}")
    require(
        archive.stat().st_size == document["archive"]["sizeBytes"],
        "release archive size mismatch",
    )
    require(
        sha256_file(archive) == document["archive"]["sha256"],
        "release archive digest mismatch",
    )
    return document["image"]


def published_document(metadata, digest):
    require(isinstance(digest, str) and SHA256_RE.fullmatch(digest), "invalid published digest")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "provenance": dict(metadata["provenance"]),
        "image": dict(metadata["image"]),
        "archiveSha256": metadata["archive"]["sha256"],
        "publishedDigest": digest,
    }


def validate_published_documents(documents, arguments):
    arches = arguments.debian_arches.split()
    require(arches, "debian architectures must not be empty")
    require(len(arches) == len(set(arches)), "debian architectures must be unique")
    require(all(arch in ("amd64", "arm64") for arch in arches), "unsupported Debian architecture")
    require(set(documents) == set(arches), "published architecture record set mismatch")

    primary_tag = (
        f"{arguments.image_ref}:{arguments.image_version}-{arguments.debian_suite}"
    )
    expected_provenance = {
        "repository": arguments.repository,
        "commitSha": arguments.commit_sha,
        "runId": arguments.run_id,
        "runAttempt": arguments.run_attempt,
    }
    source_refs = []
    digests = set()
    for arch in arches:
        document = documents[arch]
        require_exact_keys(
            document,
            {
                "schemaVersion",
                "provenance",
                "image",
                "archiveSha256",
                "publishedDigest",
            },
            f"published record {arch}",
        )
        require(document["schemaVersion"] == SCHEMA_VERSION, "unsupported published record schemaVersion")
        require_exact_keys(
            document["provenance"],
            {"repository", "commitSha", "runId", "runAttempt"},
            f"published record {arch}.provenance",
        )
        require(document["provenance"] == expected_provenance, f"published record {arch} provenance mismatch")
        require_exact_keys(
            document["image"],
            {
                "name",
                "version",
                "debianSuite",
                "debianArch",
                "platform",
                "ref",
                "primaryTag",
                "architectureTag",
                "id",
                "os",
                "architecture",
                "variant",
            },
            f"published record {arch}.image",
        )
        expected_image = {
            "name": arguments.image_name,
            "version": arguments.image_version,
            "debianSuite": arguments.debian_suite,
            "debianArch": arch,
            "platform": f"linux/{arch}",
            "ref": arguments.image_ref,
            "primaryTag": primary_tag,
            "architectureTag": f"{primary_tag}-{arch}",
            "os": "linux",
            "architecture": arch,
        }
        for key, value in expected_image.items():
            require(document["image"].get(key) == value, f"published record {arch} image {key} mismatch")
        image_id = document["image"].get("id")
        require(isinstance(image_id, str) and SHA256_RE.fullmatch(image_id), f"published record {arch} image ID is invalid")
        variant = document["image"].get("variant")
        require(variant is None or isinstance(variant, str), f"published record {arch} variant is invalid")
        archive_digest = document["archiveSha256"]
        require(
            isinstance(archive_digest, str) and SHA256_RE.fullmatch(archive_digest),
            f"published record {arch} archive digest is invalid",
        )
        digest = document["publishedDigest"]
        require(
            isinstance(digest, str) and SHA256_RE.fullmatch(digest),
            f"published record {arch} registry digest is invalid",
        )
        require(digest not in digests, "published architecture digests must be unique")
        digests.add(digest)
        source_refs.append(f"{arguments.image_ref}@{digest}")
    return source_refs


def load_document(path):
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReleaseArchiveError(f"cannot read release metadata {path}: {error}") from error
    return document


def write_document(path, document):
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def command_create(arguments):
    archive = pathlib.Path(arguments.archive)
    metadata = pathlib.Path(arguments.metadata)
    archive.parent.mkdir(parents=True, exist_ok=True)
    metadata.parent.mkdir(parents=True, exist_ok=True)
    expected = expected_values(arguments)
    require(
        isinstance(arguments.expected_image_id, str)
        and SHA256_RE.fullmatch(arguments.expected_image_id),
        "invalid expected tested image ID",
    )
    primary = inspect_image(expected["image"]["primaryTag"])
    inspected = inspect_image(expected["image"]["architectureTag"])
    require(
        primary["id"] == arguments.expected_image_id,
        "primary tag no longer identifies the image used by tests",
    )
    require(
        inspected["id"] == arguments.expected_image_id,
        "architecture tag no longer identifies the image used by tests",
    )
    subprocess.run(
        [
            "docker",
            "image",
            "save",
            "--output",
            str(archive),
            expected["image"]["architectureTag"],
        ],
        check=True,
    )
    document = create_document(arguments, archive, inspected)
    write_document(metadata, document)
    print(
        f"Exported {document['image']['architectureTag']} "
        f"({document['image']['id']}) to {archive}"
    )


def append_github_output(path, image):
    with path.open("a", encoding="utf-8") as stream:
        stream.write(f"image_ref={image['ref']}\n")
        stream.write(f"architecture_tag={image['architectureTag']}\n")
        stream.write(f"image_id={image['id']}\n")


def command_verify(arguments):
    archive = pathlib.Path(arguments.archive)
    metadata = pathlib.Path(arguments.metadata)
    image = validate_document(load_document(metadata), arguments, archive)
    subprocess.run(["docker", "image", "load", "--input", str(archive)], check=True)
    inspected = inspect_image(image["architectureTag"])
    require(inspected["id"] == image["id"], "loaded image ID does not match tested image ID")
    require(inspected["os"] == image["os"], "loaded image OS mismatch")
    require(inspected["architecture"] == image["architecture"], "loaded image architecture mismatch")
    require(inspected["variant"] == image["variant"], "loaded image variant mismatch")
    append_github_output(pathlib.Path(arguments.github_output), image)
    print(f"Verified tested image {image['architectureTag']} ({image['id']})")


def command_record(arguments):
    archive = pathlib.Path(arguments.archive)
    metadata_path = pathlib.Path(arguments.metadata)
    metadata = load_document(metadata_path)
    validate_document(metadata, arguments, archive)
    document = published_document(metadata, arguments.digest)
    output = pathlib.Path(arguments.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    write_document(output, document)
    print(
        f"Recorded {document['image']['architectureTag']}@"
        f"{document['publishedDigest']} in {output}"
    )


def command_manifest_sources(arguments):
    records = pathlib.Path(arguments.records)
    require(records.is_dir(), f"published record directory does not exist: {records}")
    paths = list(records.glob("*.json"))
    documents = {path.stem: load_document(path) for path in paths}
    require(len(documents) == len(paths), "duplicate published architecture record names")
    source_refs = validate_published_documents(documents, arguments)
    output = pathlib.Path(arguments.github_output)
    with output.open("a", encoding="utf-8") as stream:
        stream.write("source_refs<<DHI_RELEASE_REFS\n")
        for reference in source_refs:
            stream.write(f"{reference}\n")
        stream.write("DHI_RELEASE_REFS\n")
    print(f"Verified {len(source_refs)} immutable architecture digest records")


def verify_index_member(document, platform, expected_digest):
    require(isinstance(document, dict), "OCI index must be an object")
    require(document.get("schemaVersion") == 2, "OCI index schemaVersion must equal 2")
    require(
        document.get("mediaType")
        in {
            "application/vnd.oci.image.index.v1+json",
            "application/vnd.docker.distribution.manifest.list.v2+json",
        },
        "OCI index mediaType is unsupported",
    )
    manifests = document.get("manifests")
    require(isinstance(manifests, list) and manifests, "OCI index has no manifests")
    require(SHA256_RE.fullmatch(expected_digest), "expected platform digest is invalid")
    os_name, architecture, variant = platform_parts(platform)

    matches = []
    for descriptor in manifests:
        require(isinstance(descriptor, dict), "OCI index manifest descriptor must be an object")
        descriptor_platform = descriptor.get("platform")
        if not isinstance(descriptor_platform, dict):
            continue
        if (
            descriptor_platform.get("os") == os_name
            and descriptor_platform.get("architecture") == architecture
            and (variant is None or descriptor_platform.get("variant") == variant)
        ):
            matches.append(descriptor)

    require(len(matches) == 1, f"OCI index must contain exactly one descriptor for {platform}")
    observed_digest = matches[0].get("digest")
    require(
        matches[0].get("mediaType")
        in {
            "application/vnd.oci.image.manifest.v1+json",
            "application/vnd.docker.distribution.manifest.v2+json",
        },
        "OCI index platform descriptor mediaType is unsupported",
    )
    require(SHA256_RE.fullmatch(observed_digest or ""), "OCI index platform digest is invalid")
    require(
        observed_digest == expected_digest,
        f"OCI index {platform} digest {observed_digest} does not match {expected_digest}",
    )
    return observed_digest


def command_verify_index(arguments):
    inspect_path = pathlib.Path(arguments.inspect)
    try:
        with inspect_path.open(encoding="utf-8") as stream:
            document = json.load(stream)
    except json.JSONDecodeError as error:
        raise ReleaseArchiveError(f"OCI index JSON is invalid: {error}") from error
    digest = verify_index_member(document, arguments.platform, arguments.expected_digest)
    print(f"Verified OCI index member {arguments.platform}@{digest}")


def command_guard_current(arguments):
    changed_files = pathlib.Path(arguments.changed_files)
    try:
        paths = [
            line.strip()
            for line in changed_files.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except OSError as error:
        raise ReleaseArchiveError(
            f"cannot read main-branch change list {changed_files}: {error}"
        ) from error
    relevant = [
        path for path in paths if release_relevant_path(arguments.image_name, path)
    ]
    require(
        not relevant,
        "refusing to publish because newer main changed release inputs: "
        + ", ".join(relevant),
    )
    print(
        f"No newer main commit changed release inputs for {arguments.image_name} "
        f"({len(paths)} paths checked)"
    )


def add_identity_arguments(parser):
    parser.add_argument("--image-name", required=True)
    parser.add_argument("--image-version", required=True)
    parser.add_argument("--debian-suite", required=True)
    parser.add_argument("--debian-arch", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--image-ref", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create", help="Export and describe a tested image")
    create.add_argument("--archive", required=True)
    create.add_argument("--metadata", required=True)
    create.add_argument("--expected-image-id", required=True)
    add_identity_arguments(create)
    create.set_defaults(handler=command_create)

    verify = commands.add_parser("verify", help="Verify and load a tested image archive")
    verify.add_argument("--archive", required=True)
    verify.add_argument("--metadata", required=True)
    verify.add_argument("--github-output", required=True)
    add_identity_arguments(verify)
    verify.set_defaults(handler=command_verify)

    record = commands.add_parser("record", help="Record a pushed tested-image digest")
    record.add_argument("--archive", required=True)
    record.add_argument("--metadata", required=True)
    record.add_argument("--output", required=True)
    record.add_argument("--digest", required=True)
    add_identity_arguments(record)
    record.set_defaults(handler=command_record)

    manifest = commands.add_parser(
        "manifest-sources", help="Verify immutable architecture digest records"
    )
    manifest.add_argument("--records", required=True)
    manifest.add_argument("--github-output", required=True)
    manifest.add_argument("--image-name", required=True)
    manifest.add_argument("--image-version", required=True)
    manifest.add_argument("--debian-suite", required=True)
    manifest.add_argument("--debian-arches", required=True)
    manifest.add_argument("--image-ref", required=True)
    manifest.add_argument("--repository", required=True)
    manifest.add_argument("--commit-sha", required=True)
    manifest.add_argument("--run-id", required=True)
    manifest.add_argument("--run-attempt", required=True)
    manifest.set_defaults(handler=command_manifest_sources)

    verify_index = commands.add_parser(
        "verify-index", help="Verify one native platform member of an OCI index"
    )
    verify_index.add_argument("--inspect", required=True)
    verify_index.add_argument("--platform", required=True)
    verify_index.add_argument("--expected-digest", required=True)
    verify_index.set_defaults(handler=command_verify_index)

    guard = commands.add_parser(
        "guard-current", help="Reject a release superseded by relevant main changes"
    )
    guard.add_argument("--image-name", required=True)
    guard.add_argument("--changed-files", required=True)
    guard.set_defaults(handler=command_guard_current)

    registry_login = commands.add_parser(
        "registry-login", help="Log in to a registry with bounded retries"
    )
    registry_login.add_argument("--registry", required=True)
    registry_login.add_argument("--username", required=True)
    registry_login.add_argument(
        "--attempts", type=int, default=DEFAULT_REGISTRY_ATTEMPTS
    )
    registry_login.set_defaults(handler=command_registry_login)

    registry_push = commands.add_parser(
        "registry-push", help="Push an image and return its immutable digest"
    )
    registry_push.add_argument("--reference", required=True)
    registry_push.add_argument(
        "--attempts", type=int, default=DEFAULT_REGISTRY_ATTEMPTS
    )
    registry_push.set_defaults(handler=command_registry_push)

    registry_digest = commands.add_parser(
        "registry-digest", help="Inspect and return an immutable registry digest"
    )
    registry_digest.add_argument("--reference", required=True)
    registry_digest.add_argument("--expected-digest")
    registry_digest.add_argument(
        "--attempts", type=int, default=DEFAULT_REGISTRY_ATTEMPTS
    )
    registry_digest.set_defaults(handler=command_registry_digest)

    registry_command = commands.add_parser(
        "registry-command", help="Run an allowlisted registry command with retries"
    )
    registry_command.add_argument(
        "--attempts", type=int, default=DEFAULT_REGISTRY_ATTEMPTS
    )
    registry_command.add_argument("registry_command", nargs=argparse.REMAINDER)
    registry_command.set_defaults(handler=command_registry_command)
    return root


def main(arguments=None):
    parsed = parser().parse_args(arguments)
    try:
        parsed.handler(parsed)
    except (ReleaseArchiveError, OSError, subprocess.CalledProcessError) as error:
        print(f"release archive error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
