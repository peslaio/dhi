#!/usr/bin/env python3
"""Create, validate, and support DHI functional-contract result documents."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import sys
import tempfile
from collections.abc import Mapping
from typing import Any, Optional


CLASSIFICATIONS = {
    "pass",
    "invalid_invocation",
    "assertion_failure",
    "setup_readiness_failure",
    "identity_failure",
    "timeout",
    "infrastructure_failure",
    "evidence_cleanup_failure",
    "interrupted",
}

EVIDENCE_PATHS = {
    "cleanupLog": "cleanup.log",
    "composeBuildLog": "compose-build.log",
    "composeConfig": "compose-config.yaml",
    "composeConfigJson": "compose-config.json",
    "composeCreateLog": "compose-create.log",
    "composeLog": "compose.log",
    "composePs": "compose-ps.json",
    "composeUpLog": "compose-up.log",
    "containerInspects": "containers",
    "fixtureLock": "fixtures.lock.json",
    "fixtureValidation": "fixture-validation.json",
    "identityProof": "identity.json",
    "sourceImageInspect": "source-image.inspect.json",
    "sutImageInspect": "sut-image.inspect.json",
}
PASS_EVIDENCE = set(EVIDENCE_PATHS)


def evidence_path_present(path: pathlib.Path) -> bool:
    """Return true only for evidence that survives artifact transport."""
    if path.is_dir():
        return any(candidate.is_file() for candidate in path.rglob("*"))
    return path.is_file()


def load_json(path: pathlib.Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def load_docker_object(path: pathlib.Path) -> dict[str, Any]:
    value = load_json(path)
    if isinstance(value, list):
        if len(value) != 1 or not isinstance(value[0], dict):
            raise ValueError(f"expected one Docker object in {path}")
        return value[0]
    if not isinstance(value, dict):
        raise ValueError(f"expected a Docker object in {path}")
    return value


def atomic_json_write(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def parse_platform(platform: str) -> tuple[str, str, Optional[str]]:
    parts = platform.split("/")
    if len(parts) not in (2, 3) or not all(parts):
        raise ValueError(f"invalid platform: {platform}")
    return parts[0], parts[1], parts[2] if len(parts) == 3 else None


def image_platform(image: dict[str, Any]) -> tuple[str, str, Optional[str]]:
    return (
        image.get("Os", ""),
        image.get("Architecture", ""),
        image.get("Variant") or None,
    )


def platform_matches(
    actual: tuple[str, str, Optional[str]],
    requested: tuple[str, str, Optional[str]],
) -> bool:
    actual_os, actual_arch, actual_variant = actual
    requested_os, requested_arch, requested_variant = requested
    return (
        actual_os == requested_os
        and actual_arch == requested_arch
        and (requested_variant is None or actual_variant == requested_variant)
    )


def command_source_info(args: argparse.Namespace) -> int:
    image = load_docker_object(pathlib.Path(args.inspect))
    requested = parse_platform(args.platform)
    actual = image_platform(image)
    if not platform_matches(actual, requested):
        raise ValueError(
            f"source platform mismatch: requested {args.platform}, "
            f"found {actual[0]}/{actual[1]}"
            + (f"/{actual[2]}" if actual[2] else "")
        )
    image_id = image.get("Id")
    if not isinstance(image_id, str) or not image_id.startswith("sha256:"):
        raise ValueError("source image has no canonical sha256 image ID")
    print(image_id, actual[0], actual[1], actual[2] or "-")
    return 0


def normalize_labels(service: dict[str, Any]) -> dict[str, str]:
    labels = service.get("labels", {})
    if isinstance(labels, dict):
        return {str(key): str(value) for key, value in labels.items()}
    if isinstance(labels, list):
        result: dict[str, str] = {}
        for item in labels:
            key, _, value = str(item).partition("=")
            result[key] = value
        return result
    return {}


def check_compose_config(
    config: Any,
    source_alias: str,
    expected_id: str,
    platform: str,
) -> tuple[str, str, str]:
    services = config.get("services") if isinstance(config, dict) else None
    if not isinstance(services, dict) or not services:
        raise ValueError("rendered Compose configuration has no services")

    roles: dict[str, list[str]] = {"sut": [], "test": [], "fixture": []}
    identity_mode = ""
    for name, service in services.items():
        if not isinstance(service, dict):
            raise ValueError(f"service {name} is not an object")
        labels = normalize_labels(service)
        role = labels.get("io.pesla.dhi.functional.role", "")
        if role not in roles:
            raise ValueError(f"service {name} has invalid or missing functional role")
        roles[role].append(name)
        if service.get("pull_policy") != "never":
            raise ValueError(f"service {name} must declare pull_policy: never")
        if role == "sut":
            identity_mode = labels.get(
                "io.pesla.dhi.functional.identity-mode", ""
            )

    if len(roles["sut"]) != 1 or len(roles["test"]) != 1:
        raise ValueError("Compose contract must have exactly one sut and one test role")
    if identity_mode not in ("exact-container-image", "derived-rootfs-prefix"):
        raise ValueError(f"unsupported SUT identity mode: {identity_mode}")

    sut_name = roles["sut"][0]
    test_name = roles["test"][0]
    sut = services[sut_name]
    if sut.get("platform") != platform:
        raise ValueError(
            f"SUT platform mismatch: expected {platform}, got {sut.get('platform')}"
        )

    if identity_mode == "exact-container-image":
        if sut.get("image") != source_alias:
            raise ValueError("exact SUT does not use the unique local source alias")
    else:
        build = sut.get("build")
        build_args = build.get("args", {}) if isinstance(build, dict) else {}
        if build_args.get("RUNTIME_IMAGE") != source_alias:
            raise ValueError("derived SUT build does not use the local source alias")
        if build_args.get("DHI_SOURCE_IMAGE_ID") != expected_id:
            raise ValueError("derived SUT build does not bind the expected source ID")

    return sut_name, test_name, identity_mode


def command_check_compose(args: argparse.Namespace) -> int:
    config = load_json(pathlib.Path(args.config))
    sut_name, test_name, identity_mode = check_compose_config(
        config, args.source_alias, args.expected_id, args.platform
    )

    print(sut_name, test_name, identity_mode)
    return 0


def command_verify_identity(args: argparse.Namespace) -> int:
    output_path = pathlib.Path(args.output)
    proof: dict[str, Any] = {
        "mode": args.mode,
        "verified": False,
        "sourceLayerCount": None,
        "containerLayerCount": None,
        "message": "identity verification did not complete",
    }
    try:
        source = load_docker_object(pathlib.Path(args.source_inspect))
        container = load_docker_object(pathlib.Path(args.container_inspect))
        sut_image = load_docker_object(pathlib.Path(args.sut_image_inspect))
        source_id = source.get("Id")
        container_image_id = container.get("Image")
        sut_image_id = sut_image.get("Id")

        if source_id != args.expected_id:
            raise ValueError("source inspect ID changed after resolution")
        if container_image_id != sut_image_id:
            raise ValueError("created SUT container does not reference inspected SUT image")
        requested = parse_platform(args.platform)
        if not platform_matches(image_platform(source), requested):
            raise ValueError("source image platform changed or does not match the leg")
        if not platform_matches(image_platform(sut_image), requested):
            raise ValueError("created SUT image platform does not match the leg")

        source_layers = source.get("RootFS", {}).get("Layers", [])
        sut_layers = sut_image.get("RootFS", {}).get("Layers", [])
        if not isinstance(source_layers, list) or not isinstance(sut_layers, list):
            raise ValueError("Docker image inspect omitted RootFS layer lists")
        proof["sourceLayerCount"] = len(source_layers)
        proof["containerLayerCount"] = len(sut_layers)

        if args.mode == "exact-container-image":
            if container_image_id != args.expected_id:
                raise ValueError("SUT container image ID is not the expected source image ID")
        elif args.mode == "derived-rootfs-prefix":
            labels = sut_image.get("Config", {}).get("Labels") or {}
            label_id = labels.get("io.pesla.dhi.functional.source-image-id")
            if label_id != args.expected_id:
                raise ValueError("derived SUT source-image-id label does not match")
            if sut_layers[: len(source_layers)] != source_layers:
                raise ValueError("source image layers are not a prefix of derived SUT layers")
        else:
            raise ValueError(f"unsupported identity mode: {args.mode}")

        proof["verified"] = True
        proof["message"] = "SUT image identity verified"
        atomic_json_write(output_path, proof)
        return 0
    except Exception as exc:
        proof["message"] = str(exc)
        atomic_json_write(output_path, proof)
        print(f"identity verification failed: {exc}", file=sys.stderr)
        return 1


def parse_compose_ps(path: pathlib.Path) -> list[dict[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    try:
        value = json.loads(text)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            return [value]
    except json.JSONDecodeError:
        pass
    result = []
    for line in text.splitlines():
        value = json.loads(line)
        if isinstance(value, dict):
            result.append(value)
    return result


def nullable(value: Optional[str]) -> Optional[str]:
    return value if value else None


def integer(value: Optional[str], default: Optional[int] = None) -> Optional[int]:
    if value in (None, ""):
        return default
    return int(value)


def read_lines(path: pathlib.Path) -> list[str]:
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line]


def service_results(
    ps_path: pathlib.Path,
    inspect_dir: pathlib.Path,
    sut_service: str,
    test_service: str,
) -> list[dict[str, Any]]:
    records = parse_compose_ps(ps_path)
    by_service = {str(record.get("Service", "")): record for record in records}
    names = set(by_service)
    for expected_name in (sut_service, test_service):
        if expected_name and (inspect_dir / f"{expected_name}.json").exists():
            names.add(expected_name)
    results = []
    for name in sorted(names):
        record = by_service.get(name, {})
        inspect_path = inspect_dir / f"{name}.json"
        inspected: dict[str, Any] = {}
        if inspect_path.exists():
            try:
                inspected = load_docker_object(inspect_path)
            except (ValueError, json.JSONDecodeError):
                inspected = {}
        state = inspected.get("State", {}) if isinstance(inspected, dict) else {}
        exit_code = state.get("ExitCode")
        if exit_code is None:
            exit_code = record.get("ExitCode")
        role = "fixture"
        if name == sut_service:
            role = "sut"
        elif name == test_service:
            role = "test"
        results.append(
            {
                "name": name,
                "role": role,
                "containerId": nullable(inspected.get("Id") or record.get("ID")),
                "containerName": nullable(inspected.get("Name") or record.get("Name")),
                "image": nullable(record.get("Image")),
                "imageId": nullable(inspected.get("Image")),
                "state": nullable(state.get("Status") or record.get("State")),
                "health": nullable(
                    (state.get("Health") or {}).get("Status") or record.get("Health")
                ),
                "exitCode": integer(exit_code),
                "oomKilled": bool(state.get("OOMKilled", False)),
            }
        )
    return results


def exact_object(value: Any, path: str, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    missing = keys - set(value)
    extra = set(value) - keys
    if missing or extra:
        raise ValueError(
            f"{path} keys mismatch; missing={sorted(missing)}, extra={sorted(extra)}"
        )
    return value


def string_value(value: Any, path: str, nullable: bool = False) -> Optional[str]:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"{path} must be a non-empty string")
    return value


def integer_value(
    value: Any,
    path: str,
    minimum: Optional[int] = None,
    maximum: Optional[int] = None,
    nullable: bool = False,
) -> Optional[int]:
    if value is None and nullable:
        return None
    if type(value) is not int:
        raise ValueError(f"{path} must be an integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{path} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{path} must be at most {maximum}")
    return value


def string_array(value: Any, path: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{path} must be an array of strings")
    return value


def timestamp(value: Any, path: str) -> str:
    text = string_value(value, path)
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{path} must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{path} must include a timezone")
    return text


def rootfs_layers(image: dict[str, Any], path: str) -> list[str]:
    rootfs = image.get("RootFS")
    if not isinstance(rootfs, dict):
        raise ValueError(f"{path}.RootFS must be an object")
    layers = rootfs.get("Layers")
    if not isinstance(layers, list) or not all(
        isinstance(layer, str) and layer for layer in layers
    ):
        raise ValueError(f"{path}.RootFS.Layers must be an array of strings")
    return layers


def validate_pass_evidence(result: dict[str, Any], artifact_dir: pathlib.Path) -> None:
    """Parse and cross-bind structured pass evidence to the result envelope."""
    evidence = result["evidence"]
    image = result["image"]
    identity = image["identity"]
    contract = result["contract"]

    identity_proof = load_json(artifact_dir / evidence["identityProof"])
    if identity_proof != identity:
        raise ValueError("identity.json does not match image.identity")

    source = load_docker_object(artifact_dir / evidence["sourceImageInspect"])
    sut_image = load_docker_object(artifact_dir / evidence["sutImageInspect"])
    if source.get("Id") != image["expectedId"]:
        raise ValueError("source image inspect ID does not match image.expectedId")
    if sut_image.get("Id") != image["containerImageId"]:
        raise ValueError("SUT image inspect ID does not match image.containerImageId")

    recorded_platform = (image["os"], image["architecture"], image["variant"])
    if image_platform(source) != recorded_platform:
        raise ValueError("source image inspect platform does not match result image")
    if image_platform(sut_image) != recorded_platform:
        raise ValueError("SUT image inspect platform does not match result image")

    source_layers = rootfs_layers(source, "source image inspect")
    sut_layers = rootfs_layers(sut_image, "SUT image inspect")
    if len(source_layers) != identity["sourceLayerCount"]:
        raise ValueError("source image layer count does not match identity proof")
    if len(sut_layers) != identity["containerLayerCount"]:
        raise ValueError("SUT image layer count does not match identity proof")
    if identity["mode"] == "exact-container-image":
        if source_layers != sut_layers:
            raise ValueError("exact image evidence has different rootfs layers")
    else:
        config = sut_image.get("Config")
        labels = config.get("Labels") if isinstance(config, dict) else None
        if not isinstance(labels, dict) or labels.get(
            "io.pesla.dhi.functional.source-image-id"
        ) != image["expectedId"]:
            raise ValueError("derived SUT inspect is missing the expected source ID label")
        if sut_layers[: len(source_layers)] != source_layers:
            raise ValueError("source rootfs layers are not a prefix of the derived SUT")

    compose_config = load_json(artifact_dir / evidence["composeConfigJson"])
    sut_name, test_name, identity_mode = check_compose_config(
        compose_config,
        image["sourceAlias"],
        image["expectedId"],
        contract["platform"],
    )
    if (sut_name, test_name, identity_mode) != (
        contract["sutService"],
        contract["testService"],
        identity["mode"],
    ):
        raise ValueError("rendered Compose roles do not match the result contract")
    configured_services = compose_config.get("services", {})
    if set(configured_services) != {service["name"] for service in result["services"]}:
        raise ValueError("rendered Compose services do not match result services")

    reconstructed_services = service_results(
        artifact_dir / evidence["composePs"],
        artifact_dir / evidence["containerInspects"],
        contract["sutService"],
        contract["testService"],
    )
    if reconstructed_services != result["services"]:
        raise ValueError("Compose/container evidence does not match result services")

    fixture_lock = load_json(artifact_dir / evidence["fixtureLock"])
    repository_lock_path = pathlib.Path(__file__).with_name("fixtures.lock.json")
    if fixture_lock != load_json(repository_lock_path):
        raise ValueError("fixture lock evidence does not match the repository lock")
    fixtures = fixture_lock.get("fixtures") if isinstance(fixture_lock, dict) else None
    if not isinstance(fixtures, dict):
        raise ValueError("fixture lock evidence has no fixture map")
    fixture_validation = exact_object(
        load_json(artifact_dir / evidence["fixtureValidation"]),
        "fixture validation evidence",
        {"schemaVersion", "fixtures", "online", "status"},
    )
    if (
        fixture_validation["schemaVersion"] != 1
        or fixture_validation["fixtures"] != len(fixtures)
        or type(fixture_validation["online"]) is not bool
        or fixture_validation["status"] != "pass"
    ):
        raise ValueError("fixture validation evidence is not a passing lock validation")


def validate_result(result: Any, artifact_dir: Optional[pathlib.Path] = None) -> None:
    top_keys = {
        "schemaVersion",
        "legId",
        "run",
        "contract",
        "image",
        "outcome",
        "services",
        "cleanup",
        "evidence",
        "secondaryFailures",
        "warnings",
    }
    result = exact_object(result, "result", top_keys)
    if result["schemaVersion"] != 1:
        raise ValueError("schemaVersion must equal 1")
    leg_id = string_value(result["legId"], "legId")

    run = exact_object(
        result["run"],
        "run",
        {
            "id",
            "project",
            "startedAt",
            "finishedAt",
            "durationMs",
            "timeoutSeconds",
            "buildTimeoutSeconds",
        },
    )
    string_value(run["id"], "run.id")
    string_value(run["project"], "run.project", nullable=True)
    timestamp(run["startedAt"], "run.startedAt")
    timestamp(run["finishedAt"], "run.finishedAt")
    integer_value(run["durationMs"], "run.durationMs", minimum=0)
    integer_value(run["timeoutSeconds"], "run.timeoutSeconds", minimum=1, nullable=True)
    integer_value(
        run["buildTimeoutSeconds"], "run.buildTimeoutSeconds", minimum=1, nullable=True
    )

    contract = exact_object(
        result["contract"],
        "contract",
        {"family", "version", "platform", "suite", "sutService", "testService"},
    )
    for key in ("family", "version", "platform", "suite"):
        string_value(contract[key], f"contract.{key}")
    if not re.fullmatch(r"linux/(amd64|arm64)(/[^/]+)?", contract["platform"]):
        raise ValueError("contract.platform is unsupported")
    string_value(contract["sutService"], "contract.sutService", nullable=True)
    string_value(contract["testService"], "contract.testService", nullable=True)
    expected_leg_id = (
        f"{contract['family']}:{contract['version']}:{contract['platform']}"
    )
    if leg_id != expected_leg_id:
        raise ValueError("legId does not match the contract family/version/platform")

    image = exact_object(
        result["image"],
        "image",
        {
            "requestedRef",
            "sourceAlias",
            "expectedId",
            "containerImageId",
            "os",
            "architecture",
            "variant",
            "identity",
        },
    )
    string_value(image["requestedRef"], "image.requestedRef")
    for key in (
        "sourceAlias",
        "expectedId",
        "containerImageId",
        "os",
        "architecture",
        "variant",
    ):
        string_value(image[key], f"image.{key}", nullable=True)
    identity = exact_object(
        image["identity"],
        "image.identity",
        {"mode", "verified", "sourceLayerCount", "containerLayerCount", "message"},
    )
    if identity["mode"] not in (
        None,
        "exact-container-image",
        "derived-rootfs-prefix",
    ):
        raise ValueError("image.identity.mode is unsupported")
    if type(identity["verified"]) is not bool:
        raise ValueError("image.identity.verified must be a boolean")
    integer_value(
        identity["sourceLayerCount"],
        "image.identity.sourceLayerCount",
        minimum=0,
        nullable=True,
    )
    integer_value(
        identity["containerLayerCount"],
        "image.identity.containerLayerCount",
        minimum=0,
        nullable=True,
    )
    if not isinstance(identity["message"], str):
        raise ValueError("image.identity.message must be a string")

    outcome = exact_object(
        result["outcome"],
        "outcome",
        {"status", "classification", "phase", "exitCode", "rawExitCode", "message"},
    )
    if outcome["status"] not in ("pass", "fail"):
        raise ValueError("outcome.status must be pass or fail")
    if outcome["classification"] not in CLASSIFICATIONS:
        raise ValueError("outcome.classification is unsupported")
    string_value(outcome["phase"], "outcome.phase")
    integer_value(outcome["exitCode"], "outcome.exitCode", minimum=0, maximum=255)
    integer_value(outcome["rawExitCode"], "outcome.rawExitCode", nullable=True)
    if not isinstance(outcome["message"], str):
        raise ValueError("outcome.message must be a string")

    if not isinstance(result["services"], list):
        raise ValueError("services must be an array")
    service_keys = {
        "name",
        "role",
        "containerId",
        "containerName",
        "image",
        "imageId",
        "state",
        "health",
        "exitCode",
        "oomKilled",
    }
    roles = []
    service_names = []
    for index, service_value in enumerate(result["services"]):
        service = exact_object(service_value, f"services[{index}]", service_keys)
        service_names.append(string_value(service["name"], f"services[{index}].name"))
        if service["role"] not in ("sut", "test", "fixture"):
            raise ValueError(f"services[{index}].role is unsupported")
        roles.append(service["role"])
        for key in ("containerId", "containerName", "image", "imageId", "state", "health"):
            string_value(service[key], f"services[{index}].{key}", nullable=True)
        integer_value(service["exitCode"], f"services[{index}].exitCode", nullable=True)
        if type(service["oomKilled"]) is not bool:
            raise ValueError(f"services[{index}].oomKilled must be a boolean")
    if len(service_names) != len(set(service_names)):
        raise ValueError("service names must be unique")

    cleanup = exact_object(
        result["cleanup"], "cleanup", {"status", "residualResources"}
    )
    if cleanup["status"] not in ("success", "failure", "not-started"):
        raise ValueError("cleanup.status is unsupported")
    string_array(cleanup["residualResources"], "cleanup.residualResources")
    string_array(result["secondaryFailures"], "secondaryFailures")
    string_array(result["warnings"], "warnings")

    evidence = result["evidence"]
    if not isinstance(evidence, dict):
        raise ValueError("evidence must be an object")
    unknown_evidence = set(evidence) - set(EVIDENCE_PATHS)
    if unknown_evidence:
        raise ValueError(f"evidence has unknown keys: {sorted(unknown_evidence)}")
    for key, relative_path in evidence.items():
        string_value(relative_path, f"evidence.{key}")
        if relative_path != EVIDENCE_PATHS[key]:
            raise ValueError(
                f"evidence.{key} must equal canonical path {EVIDENCE_PATHS[key]}"
            )

    if outcome["status"] == "pass":
        if outcome["classification"] != "pass" or outcome["exitCode"] != 0:
            raise ValueError("passing results must have pass classification and exit 0")
        if outcome["rawExitCode"] != 0 or outcome["phase"] != "complete":
            raise ValueError("passing results require raw exit 0 and complete phase")
        if identity["verified"] is not True or identity["mode"] is None:
            raise ValueError("passing results require verified image identity")
        if cleanup["status"] != "success" or cleanup["residualResources"]:
            raise ValueError("passing results require successful cleanup without residuals")
        if result["secondaryFailures"]:
            raise ValueError("passing results cannot contain secondary failures")
        for key in ("project", "timeoutSeconds", "buildTimeoutSeconds"):
            if run[key] is None:
                raise ValueError(f"passing results require run.{key}")
        for key in (
            "sourceAlias",
            "expectedId",
            "containerImageId",
            "os",
            "architecture",
        ):
            if image[key] is None:
                raise ValueError(f"passing results require image.{key}")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image["expectedId"]):
            raise ValueError("passing results require a canonical expected image ID")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image["containerImageId"]):
            raise ValueError("passing results require a canonical container image ID")
        if image["os"] != "linux" or image["architecture"] != contract["platform"].split("/")[1]:
            raise ValueError("passing result image platform does not match contract")
        if identity["sourceLayerCount"] is None or identity["containerLayerCount"] is None:
            raise ValueError("passing results require identity layer counts")
        if identity["sourceLayerCount"] > identity["containerLayerCount"]:
            raise ValueError("source layer count exceeds container layer count")
        if identity["mode"] == "exact-container-image" and image["expectedId"] != image["containerImageId"]:
            raise ValueError("exact identity requires matching image IDs")
        if identity["mode"] == "exact-container-image" and identity["sourceLayerCount"] != identity["containerLayerCount"]:
            raise ValueError("exact identity requires matching layer counts")
        if not contract["sutService"] or not contract["testService"]:
            raise ValueError("passing results require SUT and test service names")
        if roles.count("sut") != 1 or roles.count("test") != 1:
            raise ValueError("passing results require exactly one SUT and one test service")
        if contract["sutService"] not in service_names or contract["testService"] not in service_names:
            raise ValueError("passing result service inventory is incomplete")
        services_by_name = {
            service["name"]: service for service in result["services"]
        }
        sut_record = services_by_name[contract["sutService"]]
        test_record = services_by_name[contract["testService"]]
        if sut_record["role"] != "sut" or test_record["role"] != "test":
            raise ValueError("contract service names do not match recorded service roles")
        if test_record["exitCode"] != 0:
            raise ValueError("passing results require test service exit code 0")
        if test_record["state"] != "exited":
            raise ValueError("passing results require the test service to be exited")
        for service in result["services"]:
            for key in ("containerId", "containerName", "image", "imageId", "state"):
                if service[key] is None:
                    raise ValueError(f"passing results require services.{service['name']}.{key}")
        if any(service["oomKilled"] for service in result["services"]):
            raise ValueError("passing results cannot contain an OOM-killed service")
        if sut_record["imageId"] != image["containerImageId"]:
            raise ValueError("SUT service image ID does not match identity evidence")
        missing = PASS_EVIDENCE - set(evidence)
        if missing:
            raise ValueError(
                "passing results are missing evidence: " + ", ".join(sorted(missing))
            )
        if artifact_dir is not None:
            validate_pass_evidence(result, artifact_dir.resolve())
    elif outcome["classification"] == "pass" or outcome["exitCode"] == 0:
        raise ValueError("failed results require a failure classification and exit code")

    if artifact_dir is not None:
        root = artifact_dir.resolve()
        for key, relative_path in evidence.items():
            candidate = (root / relative_path).resolve()
            if root != candidate and root not in candidate.parents:
                raise ValueError(f"evidence path escapes artifact directory: {key}")
            if not evidence_path_present(candidate):
                raise ValueError(f"evidence path does not exist: {key}={relative_path}")


def command_validate(args: argparse.Namespace) -> int:
    result_path = pathlib.Path(args.result)
    validate_result(load_json(result_path), result_path.parent)
    return 0


def result_from_environment(
    env: Mapping[str, str],
    artifact_dir: pathlib.Path,
    identity: dict[str, Any],
    services: list[dict[str, Any]],
) -> dict[str, Any]:
    """Assemble a result from runner-owned environment and captured evidence."""
    residuals = read_lines(artifact_dir / "cleanup-residuals.txt")
    warnings = read_lines(artifact_dir / "warnings.txt")
    secondary_failures = read_lines(artifact_dir / "secondary-failures.txt")
    sut_container_image_id = nullable(env.get("DHI_RESULT_CONTAINER_IMAGE_ID"))

    evidence = {
        key: relative_path
        for key, relative_path in EVIDENCE_PATHS.items()
        if evidence_path_present(artifact_dir / relative_path)
    }

    return {
        "schemaVersion": 1,
        "legId": env["DHI_RESULT_LEG_ID"],
        "run": {
            "id": env["DHI_RESULT_RUN_ID"],
            "project": nullable(env.get("DHI_RESULT_PROJECT")),
            "startedAt": env["DHI_RESULT_STARTED_AT"],
            "finishedAt": env["DHI_RESULT_FINISHED_AT"],
            "durationMs": int(env["DHI_RESULT_DURATION_MS"]),
            "timeoutSeconds": integer(env.get("DHI_RESULT_TIMEOUT_SECONDS")),
            "buildTimeoutSeconds": integer(
                env.get("DHI_RESULT_BUILD_TIMEOUT_SECONDS")
            ),
        },
        "contract": {
            "family": env["DHI_RESULT_FAMILY"],
            "version": env["DHI_RESULT_VERSION"],
            "platform": env["DHI_RESULT_PLATFORM"],
            "suite": env["DHI_RESULT_SUITE"],
            "sutService": nullable(env.get("DHI_RESULT_SUT_SERVICE")),
            "testService": nullable(env.get("DHI_RESULT_TEST_SERVICE")),
        },
        "image": {
            "requestedRef": env["DHI_RESULT_REQUESTED_REF"],
            "sourceAlias": nullable(env.get("DHI_RESULT_SOURCE_ALIAS")),
            "expectedId": nullable(env.get("DHI_RESULT_EXPECTED_ID")),
            "containerImageId": sut_container_image_id,
            "os": nullable(env.get("DHI_RESULT_IMAGE_OS")),
            "architecture": nullable(env.get("DHI_RESULT_IMAGE_ARCH")),
            "variant": nullable(env.get("DHI_RESULT_IMAGE_VARIANT")),
            "identity": identity,
        },
        "outcome": {
            "status": env["DHI_RESULT_STATUS"],
            "classification": env["DHI_RESULT_CLASSIFICATION"],
            "phase": env["DHI_RESULT_PHASE"],
            "exitCode": int(env["DHI_RESULT_EXIT_CODE"]),
            "rawExitCode": integer(env.get("DHI_RESULT_RAW_EXIT_CODE")),
            "message": env["DHI_RESULT_MESSAGE"],
        },
        "services": services,
        "cleanup": {
            "status": env["DHI_RESULT_CLEANUP_STATUS"],
            "residualResources": residuals,
        },
        "evidence": evidence,
        "secondaryFailures": secondary_failures,
        "warnings": warnings,
    }


def command_emit(args: argparse.Namespace) -> int:
    env = os.environ
    artifact_dir = pathlib.Path(env["DHI_RESULT_ARTIFACT_DIR"])
    identity_path = artifact_dir / "identity.json"
    try:
        if identity_path.exists():
            identity = load_json(identity_path)
        else:
            identity = {
                "mode": nullable(env.get("DHI_RESULT_IDENTITY_MODE")),
                "verified": False,
                "sourceLayerCount": None,
                "containerLayerCount": None,
                "message": "identity evidence is unavailable",
            }
        services = service_results(
            artifact_dir / "compose-ps.json",
            artifact_dir / "containers",
            env.get("DHI_RESULT_SUT_SERVICE", ""),
            env.get("DHI_RESULT_TEST_SERVICE", ""),
        )
        result = result_from_environment(env, artifact_dir, identity, services)
        validate_result(result, artifact_dir)
    except Exception as exc:
        reason = f"canonical evidence validation failed: {type(exc).__name__}: {exc}"
        fallback_identity = {
            "mode": nullable(env.get("DHI_RESULT_IDENTITY_MODE")),
            "verified": False,
            "sourceLayerCount": None,
            "containerLayerCount": None,
            "message": "identity evidence was invalidated during result emission",
        }
        result = result_from_environment(env, artifact_dir, fallback_identity, [])
        original_failure = (
            result["outcome"]["status"] == "fail"
            and result["outcome"]["classification"] in CLASSIFICATIONS - {"pass"}
            and result["outcome"]["exitCode"] != 0
        )
        result["secondaryFailures"].append(reason)
        if not original_failure:
            result["outcome"] = {
                "status": "fail",
                "classification": "evidence_cleanup_failure",
                "phase": "evidence",
                "exitCode": 15,
                "rawExitCode": result["outcome"]["rawExitCode"],
                "message": "functional assertions could not be represented by canonical evidence",
            }
        validate_result(result, artifact_dir)
        atomic_json_write(pathlib.Path(args.output), result)
        print(reason, file=sys.stderr)
        return 0 if original_failure else 15

    atomic_json_write(pathlib.Path(args.output), result)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    source = commands.add_parser("source-info")
    source.add_argument("--inspect", required=True)
    source.add_argument("--platform", required=True)
    source.set_defaults(handler=command_source_info)

    compose = commands.add_parser("check-compose")
    compose.add_argument("--config", required=True)
    compose.add_argument("--source-alias", required=True)
    compose.add_argument("--expected-id", required=True)
    compose.add_argument("--platform", required=True)
    compose.set_defaults(handler=command_check_compose)

    identity = commands.add_parser("verify-identity")
    identity.add_argument("--mode", required=True)
    identity.add_argument("--expected-id", required=True)
    identity.add_argument("--platform", required=True)
    identity.add_argument("--source-inspect", required=True)
    identity.add_argument("--container-inspect", required=True)
    identity.add_argument("--sut-image-inspect", required=True)
    identity.add_argument("--output", required=True)
    identity.set_defaults(handler=command_verify_identity)

    emit = commands.add_parser("emit")
    emit.add_argument("--output", required=True)
    emit.set_defaults(handler=command_emit)

    validate = commands.add_parser("validate")
    validate.add_argument("result")
    validate.set_defaults(handler=command_validate)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return args.handler(args)
    except (KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"result helper failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
