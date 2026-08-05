#!/usr/bin/env python3
"""Fast, daemon-free negative tests for the functional contract control plane."""

import argparse
import copy
import io
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

import fixturectl
import lifecyclectl
import releasectl
import result as contract_result
import scan_result


IMAGE_ID = "sha256:" + ("a" * 64)


def discover_runtime_closure_workflows(workflow_dir):
    discovered = {}
    workflow_paths = sorted(
        set(workflow_dir.glob("*.yml")) | set(workflow_dir.glob("*.yaml"))
    )
    for path in workflow_paths:
        workflow = path.read_text(encoding="utf-8")
        for line in workflow.splitlines():
            match = re.match(r"^\s*runtime_closure:\s*(.*?)\s*$", line)
            if not match or not match.group(1):
                continue
            if match.group(1) != "true":
                raise AssertionError(
                    f"{path.name}: runtime_closure must be the literal true"
                )
            discovered[path.name] = workflow
    return discovered


def passing_result():
    return {
        "schemaVersion": 1,
        "legId": "redis:7.0:linux/amd64",
        "run": {
            "id": "selftest",
            "project": "dhi-selftest",
            "startedAt": "2026-08-03T00:00:00Z",
            "finishedAt": "2026-08-03T00:00:01Z",
            "durationMs": 1000,
            "timeoutSeconds": 600,
            "buildTimeoutSeconds": 600,
        },
        "contract": {
            "family": "redis",
            "version": "7.0",
            "platform": "linux/amd64",
            "suite": "tests/functional/redis",
            "sutService": "app",
            "testService": "test",
        },
        "image": {
            "requestedRef": "local/redis:test",
            "sourceAlias": "localhost/dhi-functional-source/redis:selftest",
            "expectedId": IMAGE_ID,
            "containerImageId": IMAGE_ID,
            "os": "linux",
            "architecture": "amd64",
            "variant": None,
            "identity": {
                "mode": "exact-container-image",
                "verified": True,
                "sourceLayerCount": 1,
                "containerLayerCount": 1,
                "message": "verified",
            },
        },
        "outcome": {
            "status": "pass",
            "classification": "pass",
            "phase": "complete",
            "exitCode": 0,
            "rawExitCode": 0,
            "message": "passed",
        },
        "services": [
            {
                "name": "app",
                "role": "sut",
                "containerId": "sut-container",
                "containerName": "/dhi-selftest-app-1",
                "image": "local/redis:test",
                "imageId": IMAGE_ID,
                "state": "running",
                "health": None,
                "exitCode": 0,
                "oomKilled": False,
            },
            {
                "name": "test",
                "role": "test",
                "containerId": "test-container",
                "containerName": "/dhi-selftest-test-1",
                "image": "local/harness:test",
                "imageId": "sha256:" + ("b" * 64),
                "state": "exited",
                "health": None,
                "exitCode": 0,
                "oomKilled": False,
            },
        ],
        "cleanup": {"status": "success", "residualResources": []},
        "evidence": dict(contract_result.EVIDENCE_PATHS),
        "secondaryFailures": [],
        "warnings": [],
    }


def passing_scan_report():
    return {
        "SchemaVersion": 2,
        "ArtifactName": "local/redis:test",
        "ArtifactType": "container_image",
        "Metadata": {
            "OS": {"Family": "debian", "Name": "12.11"},
            "ImageID": IMAGE_ID,
        },
        "Results": [
            {
                "Target": "local/redis:test (debian 12.11)",
                "Class": "os-pkgs",
                "Type": "debian",
                "Packages": [
                    {"Name": "base-files", "Version": "12.4+deb12u11"},
                    {"Name": "redis-server", "Version": "5:7.0.15-1"},
                ],
                "Vulnerabilities": None,
            }
        ],
    }


def create_evidence(root):
    for relative_path in contract_result.EVIDENCE_PATHS.values():
        path = root / relative_path
        if relative_path == "containers":
            path.mkdir(parents=True)
        else:
            path.write_text("selftest\n", encoding="utf-8")

    identity = passing_result()["image"]["identity"]
    (root / "identity.json").write_text(
        json.dumps(identity), encoding="utf-8"
    )
    source_image = {
        "Id": IMAGE_ID,
        "Os": "linux",
        "Architecture": "amd64",
        "RootFS": {"Layers": ["sha256:source-layer"]},
        "Config": {"Labels": {}},
    }
    (root / "source-image.inspect.json").write_text(
        json.dumps([source_image]), encoding="utf-8"
    )
    (root / "sut-image.inspect.json").write_text(
        json.dumps([source_image]), encoding="utf-8"
    )
    app_inspect = {
        "Id": "sut-container",
        "Name": "/dhi-selftest-app-1",
        "Image": IMAGE_ID,
        "State": {"Status": "running", "ExitCode": 0, "OOMKilled": False},
    }
    test_inspect = {
        "Id": "test-container",
        "Name": "/dhi-selftest-test-1",
        "Image": "sha256:" + ("b" * 64),
        "State": {"Status": "exited", "ExitCode": 0, "OOMKilled": False},
    }
    (root / "containers" / "app.json").write_text(
        json.dumps([app_inspect]), encoding="utf-8"
    )
    (root / "containers" / "test.json").write_text(
        json.dumps([test_inspect]), encoding="utf-8"
    )
    compose_ps = [
        {
            "Service": "app",
            "ID": "sut-container",
            "Name": "dhi-selftest-app-1",
            "Image": "local/redis:test",
            "State": "running",
            "ExitCode": 0,
        },
        {
            "Service": "test",
            "ID": "test-container",
            "Name": "dhi-selftest-test-1",
            "Image": "local/harness:test",
            "State": "exited",
            "ExitCode": 0,
        },
    ]
    (root / "compose-ps.json").write_text(
        json.dumps(compose_ps), encoding="utf-8"
    )
    source_alias = passing_result()["image"]["sourceAlias"]
    compose_config = {
        "services": {
            "app": {
                "image": source_alias,
                "platform": "linux/amd64",
                "pull_policy": "never",
                "labels": {
                    "io.pesla.dhi.functional.role": "sut",
                    "io.pesla.dhi.functional.identity-mode": "exact-container-image",
                },
            },
            "test": {
                "image": "local/harness:test",
                "pull_policy": "never",
                "labels": {"io.pesla.dhi.functional.role": "test"},
            },
        }
    }
    (root / "compose-config.json").write_text(
        json.dumps(compose_config), encoding="utf-8"
    )
    lock_path = pathlib.Path(__file__).with_name("fixtures.lock.json")
    (root / "fixtures.lock.json").write_text(
        lock_path.read_text(encoding="utf-8"), encoding="utf-8"
    )
    fixture_count = len(json.loads(lock_path.read_text(encoding="utf-8"))["fixtures"])
    (root / "fixture-validation.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "fixtures": fixture_count,
                "online": False,
                "status": "pass",
            }
        ),
        encoding="utf-8",
    )
    assertion_contract = {
        "schemaVersion": 1,
        "family": "redis",
        "suite": "redis",
        "requiredAssertions": ["redis.ready"],
    }
    assertion_summary = {
        "assertions": [{"id": "redis.ready", "status": "pass"}],
        "counts": {"fail": 0, "pass": 1},
        "outcome": "pass",
        "schemaVersion": 1,
        "suite": "redis",
    }
    lifecycle_services = [
        {
            "name": "app",
            "containerId": "sut-container",
            "state": "running",
            "exitCode": 0,
            "oomKilled": False,
        }
    ]
    (root / "assertion-contract.json").write_text(
        json.dumps(assertion_contract), encoding="utf-8"
    )
    (root / "lifecycle.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "contract": {
                    "family": "redis",
                    "version": "7.0",
                    "platform": "linux/amd64",
                    "project": "dhi-selftest",
                    "sutService": "app",
                    "testService": "test",
                },
                "identity": {
                    "sourceImageId": IMAGE_ID,
                    "sutImageId": IMAGE_ID,
                },
                "assertionContract": assertion_contract,
                "phases": {
                    "initial": {
                        "startedAt": "2026-08-03T00:00:00Z",
                        "finishedAt": "2026-08-03T00:00:01Z",
                        "testContainerId": "test-container",
                        "testExitCode": 0,
                        "sutContainerId": "sut-container",
                        "sutState": "running",
                        "assertions": assertion_summary,
                        "services": lifecycle_services,
                    },
                    "shutdown": {
                        "signal": "SIGTERM",
                        "startedAt": "2026-08-03T00:00:01Z",
                        "finishedAt": "2026-08-03T00:00:02Z",
                        "durationMs": 1000,
                        "sutExitCode": 0,
                        "sutState": "exited",
                        "oomKilled": False,
                    },
                    "restart": {
                        "startedAt": "2026-08-03T00:00:02Z",
                        "finishedAt": "2026-08-03T00:00:03Z",
                        "durationMs": 1000,
                        "testExitCode": 0,
                        "sutContainerId": "sut-container",
                        "sutState": "running",
                        "oomKilled": False,
                        "assertions": assertion_summary,
                        "services": lifecycle_services,
                    },
                },
                "outcome": {"status": "pass", "message": "passed"},
                "durationMs": 3000,
            }
        ),
        encoding="utf-8",
    )


class ResultContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temporary.name)
        create_evidence(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def test_canonical_pass_is_accepted(self):
        contract_result.validate_result(passing_result(), self.root)

    def test_fabricated_passes_are_rejected(self):
        mutations = {
            "missing run fields": lambda value: value.__setitem__("run", {}),
            "assertion exit": lambda value: value["services"][1].__setitem__(
                "exitCode", 10
            ),
            "SUT exited after restart": lambda value: value["services"][0].__setitem__(
                "state", "exited"
            ),
            "oom killed": lambda value: value["services"][0].__setitem__(
                "oomKilled", True
            ),
            "swapped role": lambda value: value["services"][0].__setitem__(
                "role", "test"
            ),
            "wrong exact image": lambda value: value["image"].__setitem__(
                "containerImageId", "sha256:" + ("c" * 64)
            ),
            "missing evidence": lambda value: value["evidence"].pop(
                "identityProof"
            ),
            "aliased evidence": lambda value: value["evidence"].__setitem__(
                "identityProof", "compose.log"
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                value = copy.deepcopy(passing_result())
                mutate(value)
                with self.assertRaises(ValueError):
                    contract_result.validate_result(value, self.root)

        fixture_failure = copy.deepcopy(passing_result())
        fixture_failure["services"].append(
            {
                "name": "backend",
                "role": "fixture",
                "containerId": "fixture-container",
                "containerName": "/dhi-selftest-backend-1",
                "image": "local/backend:test",
                "imageId": "sha256:" + ("d" * 64),
                "state": "exited",
                "health": None,
                "exitCode": 1,
                "oomKilled": False,
            }
        )
        with self.assertRaises(ValueError):
            contract_result.validate_result(fixture_failure)

    def test_schema_and_validator_evidence_keys_match(self):
        schema_path = pathlib.Path(__file__).with_name("result.schema.json")
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        evidence_schema = schema["properties"]["evidence"]
        schema_keys = set(evidence_schema["properties"])
        self.assertEqual(schema_keys, set(contract_result.EVIDENCE_PATHS))
        for key, relative_path in contract_result.EVIDENCE_PATHS.items():
            self.assertEqual(
                evidence_schema["properties"][key], {"const": relative_path}
            )
        pass_evidence = set(
            schema["allOf"][0]["then"]["properties"]["evidence"]["required"]
        )
        self.assertEqual(pass_evidence, contract_result.PASS_EVIDENCE)

    def test_empty_evidence_directory_is_rejected(self):
        (self.root / "containers" / "app.json").unlink()
        (self.root / "containers" / "test.json").unlink()
        with self.assertRaises(ValueError):
            contract_result.validate_result(passing_result(), self.root)

    def test_structured_evidence_is_cross_bound(self):
        mutations = {
            "identity": (self.root / "identity.json", {"verified": True}),
            "source inspect": (self.root / "source-image.inspect.json", {}),
            "compose state": (self.root / "compose-ps.json", []),
            "fixture validation": (
                self.root / "fixture-validation.json",
                {"schemaVersion": 1, "fixtures": 6, "online": False, "status": "fail"},
            ),
            "lifecycle": (
                self.root / "lifecycle.json",
                {"schemaVersion": 1, "outcome": {"status": "pass"}},
            ),
        }
        for name, (path, replacement) in mutations.items():
            with self.subTest(name=name):
                original = path.read_text(encoding="utf-8")
                path.write_text(json.dumps(replacement), encoding="utf-8")
                try:
                    with self.assertRaises((ValueError, json.JSONDecodeError)):
                        contract_result.validate_result(passing_result(), self.root)
                finally:
                    path.write_text(original, encoding="utf-8")

    def test_lifecycle_evidence_rejects_unclean_shutdown(self):
        path = self.root / "lifecycle.json"
        original = json.loads(path.read_text(encoding="utf-8"))
        mutations = (
            ("unexpected exit code", "sutExitCode", 137),
            ("still running", "sutState", "running"),
            ("oom killed", "oomKilled", True),
        )
        for name, key, value in mutations:
            with self.subTest(name=name):
                document = copy.deepcopy(original)
                document["phases"]["shutdown"][key] = value
                path.write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaises(ValueError):
                    contract_result.validate_result(passing_result(), self.root)
        path.write_text(json.dumps(original), encoding="utf-8")

    def test_lifecycle_evidence_binds_assertions_and_long_lived_services(self):
        path = self.root / "lifecycle.json"
        original = json.loads(path.read_text(encoding="utf-8"))
        mutations = {
            "missing assertion": lambda value: value["phases"]["restart"][
                "assertions"
            ]["assertions"].clear(),
            "wrong assertion suite": lambda value: value["phases"]["initial"][
                "assertions"
            ].__setitem__("suite", "other"),
            "fixture stopped": lambda value: value["phases"]["restart"][
                "services"
            ][0].__setitem__("state", "exited"),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                document = copy.deepcopy(original)
                mutate(document)
                path.write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaises(ValueError):
                    contract_result.validate_result(passing_result(), self.root)
        path.write_text(json.dumps(original), encoding="utf-8")

    def test_invalid_pass_evidence_emits_terminal_failure(self):
        identity = passing_result()["image"]["identity"]
        (self.root / "identity.json").write_text(
            json.dumps(identity), encoding="utf-8"
        )
        services = passing_result()["services"]
        services[0]["oomKilled"] = True
        environment = {
            "DHI_RESULT_ARTIFACT_DIR": str(self.root),
            "DHI_RESULT_LEG_ID": "redis:7.0:linux/amd64",
            "DHI_RESULT_RUN_ID": "selftest",
            "DHI_RESULT_PROJECT": "dhi-selftest",
            "DHI_RESULT_STARTED_AT": "2026-08-03T00:00:00Z",
            "DHI_RESULT_FINISHED_AT": "2026-08-03T00:00:01Z",
            "DHI_RESULT_DURATION_MS": "1000",
            "DHI_RESULT_TIMEOUT_SECONDS": "600",
            "DHI_RESULT_BUILD_TIMEOUT_SECONDS": "600",
            "DHI_RESULT_FAMILY": "redis",
            "DHI_RESULT_VERSION": "7.0",
            "DHI_RESULT_PLATFORM": "linux/amd64",
            "DHI_RESULT_SUITE": "tests/functional/redis",
            "DHI_RESULT_SUT_SERVICE": "app",
            "DHI_RESULT_TEST_SERVICE": "test",
            "DHI_RESULT_REQUESTED_REF": "local/redis:test",
            "DHI_RESULT_SOURCE_ALIAS": "localhost/dhi-functional-source/redis:selftest",
            "DHI_RESULT_EXPECTED_ID": IMAGE_ID,
            "DHI_RESULT_CONTAINER_IMAGE_ID": IMAGE_ID,
            "DHI_RESULT_IMAGE_OS": "linux",
            "DHI_RESULT_IMAGE_ARCH": "amd64",
            "DHI_RESULT_IMAGE_VARIANT": "",
            "DHI_RESULT_IDENTITY_MODE": "exact-container-image",
            "DHI_RESULT_STATUS": "pass",
            "DHI_RESULT_CLASSIFICATION": "pass",
            "DHI_RESULT_PHASE": "complete",
            "DHI_RESULT_EXIT_CODE": "0",
            "DHI_RESULT_RAW_EXIT_CODE": "0",
            "DHI_RESULT_MESSAGE": "passed",
            "DHI_RESULT_CLEANUP_STATUS": "success",
        }
        output = self.root / "result.json"
        with mock.patch.dict("os.environ", environment, clear=True), mock.patch.object(
            contract_result, "service_results", return_value=services
        ), mock.patch("sys.stderr", io.StringIO()):
            status = contract_result.command_emit(
                types.SimpleNamespace(output=str(output))
            )

        self.assertEqual(status, 15)
        emitted = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(emitted["outcome"]["classification"], "evidence_cleanup_failure")
        self.assertEqual(emitted["outcome"]["exitCode"], 15)
        self.assertTrue(emitted["secondaryFailures"])
        contract_result.validate_result(emitted, self.root)


class LifecycleControllerTests(unittest.TestCase):
    @staticmethod
    def controller(timeout=60):
        with tempfile.TemporaryDirectory() as directory:
            contract_path = pathlib.Path(directory) / "assertions.json"
            contract_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "family": "redis",
                        "suite": "redis",
                        "requiredAssertions": ["redis.ready", "redis.get"],
                    }
                ),
                encoding="utf-8",
            )
            arguments = types.SimpleNamespace(
                compose_file="compose.yaml",
                project="selftest",
                family="redis",
                version="7.0",
                platform="linux/amd64",
                sut_service="app",
                test_service="test",
                source_image_id=IMAGE_ID,
                sut_image_id=IMAGE_ID,
                assertion_contract=contract_path,
                timeout=timeout,
            )
            return lifecyclectl.Controller(arguments)

    def test_allowed_exit_codes_are_strict_and_canonical(self):
        self.assertEqual(lifecyclectl.parse_exit_codes("143,0,143"), [0, 143])
        for invalid in ("", "-1", "256", "zero", "0,"):
            with self.subTest(invalid=invalid):
                    with self.assertRaises(argparse.ArgumentTypeError):
                        lifecyclectl.parse_exit_codes(invalid)

    def test_assertion_summary_requires_the_exact_family_contract(self):
        assertion_contract = {
            "schemaVersion": 1,
            "family": "redis",
            "suite": "redis",
            "requiredAssertions": ["redis.ready", "redis.get"],
        }
        summary = {
            "assertions": [
                {"id": "redis.ready", "status": "pass"},
                {"id": "redis.get", "status": "pass"},
            ],
            "counts": {"fail": 0, "pass": 2},
            "outcome": "pass",
            "schemaVersion": 1,
            "suite": "redis",
        }
        output = "DHI_ASSERTION_SUMMARY " + json.dumps(summary)
        self.assertEqual(
            lifecyclectl.parse_assertion_summary(output, assertion_contract, "initial"),
            summary,
        )
        for name, mutate in {
            "missing": lambda value: value["assertions"].pop(),
            "unexpected": lambda value: value["assertions"].append(
                {"id": "redis.extra", "status": "pass"}
            ),
            "failed": lambda value: value["assertions"][0].__setitem__(
                "status", "fail"
            ),
            "wrong count": lambda value: value["counts"].__setitem__("pass", 1),
        }.items():
            with self.subTest(name=name):
                candidate = copy.deepcopy(summary)
                mutate(candidate)
                with self.assertRaises(lifecyclectl.LifecycleError):
                    lifecyclectl.parse_assertion_summary(
                        "DHI_ASSERTION_SUMMARY " + json.dumps(candidate),
                        assertion_contract,
                        "initial",
                    )
        with self.assertRaises(lifecyclectl.LifecycleError):
            lifecyclectl.parse_assertion_summary("verifier passed", assertion_contract, "initial")

    def test_global_deadline_and_command_timeout_are_distinct(self):
        controller = self.controller()
        controller.deadline = time.monotonic() - 1
        with self.assertRaises(lifecyclectl.LifecycleError) as expired:
            controller.remaining()
        self.assertEqual(expired.exception.exit_code, lifecyclectl.EXIT_TIMEOUT)

        controller.deadline = time.monotonic() + 100
        with mock.patch.object(
            lifecyclectl.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(["docker"], 1),
        ), self.assertRaises(lifecyclectl.LifecycleError) as bounded:
            controller.run(["docker"], maximum=1)
        self.assertEqual(bounded.exception.exit_code, lifecyclectl.EXIT_READINESS)

    def test_outer_watchdog_preserves_controller_timeout_evidence(self):
        runner = pathlib.Path(__file__).with_name("run.sh").read_text(encoding="utf-8")
        self.assertIn(
            "lifecycle_watchdog_seconds=$((timeout_seconds + 30))", runner
        )
        self.assertIn(
            'run_logged "$lifecycle_watchdog_seconds" "$artifact_dir/compose-up.log"',
            runner,
        )
        self.assertIn('--timeout "$timeout_seconds"', runner)

    def test_restart_probe_receives_an_explicit_lifecycle_phase(self):
        controller = pathlib.Path(__file__).with_name("lifecyclectl.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"DHI_LIFECYCLE_PHASE=restart"', controller)

    def test_stateful_persistence_suites_bind_phase_and_record_exact_contract(self):
        functional_root = pathlib.Path(__file__).resolve().parent
        producers = {
            "postgresql": ("verify.sh", r"(?m)^record_assertion ([a-z0-9._-]+)$"),
            "mariadb": ("verify.sh", r"(?m)^record_assertion ([a-z0-9._-]+)$"),
            "mongodb": ("verify.js", r'recordPass\("([a-z0-9._-]+)"\);'),
            "rabbitmq": (
                "verify.py",
                r'assertions\.record_pass\("([a-z0-9._-]+)"\)',
            ),
        }

        for suite, (producer_name, record_pattern) in producers.items():
            suite_root = functional_root / suite
            contract = (suite_root / "contract.yaml").read_text(encoding="utf-8")
            required = set(
                re.findall(r"(?m)^  - ([a-z0-9][a-z0-9._-]*)$", contract)
            )
            compose = (suite_root / "compose.yaml").read_text(encoding="utf-8")
            test_service = compose.split("\n  test:\n", 1)[1].split(
                "\nvolumes:\n", 1
            )[0]
            producer = (suite_root / producer_name).read_text(encoding="utf-8")
            recorded = set(re.findall(record_pattern, producer))

            with self.subTest(suite=suite):
                self.assertTrue(required)
                self.assertIn("DHI_LIFECYCLE_PHASE: initial", test_service)
                self.assertEqual(recorded, required)
                self.assertNotIn("passedAssertionIds = [", producer)
                self.assertNotIn(
                    'DHI_ASSERTION_SUMMARY {"assertions":[{"id":', producer
                )

    def test_stateful_persistence_verifiers_reject_an_undeclared_phase(self):
        functional_root = pathlib.Path(__file__).resolve().parent
        cases = {
            "postgresql": (["/bin/sh", "verify.sh"], 10),
            "mariadb": (["/bin/sh", "verify.sh"], 10),
            "mongodb": (["/bin/sh", "verify.sh"], 12),
            "rabbitmq": ([sys.executable, "verify.py"], 10),
        }
        for suite, (command, expected_exit) in cases.items():
            with self.subTest(suite=suite):
                completed = subprocess.run(
                    command,
                    cwd=functional_root / suite,
                    env={},
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=10,
                    check=False,
                )
                self.assertEqual(completed.returncode, expected_exit)
                self.assertIn("lifecycle phase", completed.stderr)


class ScanResultTests(unittest.TestCase):
    def test_os_package_scan_evidence_is_accepted(self):
        summary = scan_result.validate_report(
            passing_scan_report(),
            "debian",
            "local/redis:test",
            IMAGE_ID,
            {"base-files", "redis-server"},
        )
        self.assertEqual(summary["status"], "pass")
        self.assertEqual(summary["trivySchemaVersion"], 2)
        self.assertEqual(summary["osFamily"], "debian")
        self.assertEqual(summary["packageCount"], 2)

    def test_false_green_scan_reports_are_rejected(self):
        mutations = {
            "old schema": lambda value: value.__setitem__("SchemaVersion", 1),
            "future schema": lambda value: value.__setitem__("SchemaVersion", 3),
            "wrong artifact type": lambda value: value.__setitem__(
                "ArtifactType", "filesystem"
            ),
            "missing metadata": lambda value: value.pop("Metadata"),
            "missing OS metadata": lambda value: value["Metadata"].pop("OS"),
            "unsupported OS": lambda value: value["Metadata"]["OS"].__setitem__(
                "Family", "none"
            ),
            "empty OS version": lambda value: value["Metadata"]["OS"].__setitem__(
                "Name", ""
            ),
            "no OS result": lambda value: value.__setitem__("Results", []),
            "language result only": lambda value: value["Results"][0].__setitem__(
                "Class", "lang-pkgs"
            ),
            "wrong OS result type": lambda value: value["Results"][0].__setitem__(
                "Type", "ubuntu"
            ),
            "no packages": lambda value: value["Results"][0].__setitem__(
                "Packages", []
            ),
            "package without name": lambda value: value["Results"][0][
                "Packages"
            ][0].pop("Name"),
            "package with whitespace name": lambda value: value["Results"][0][
                "Packages"
            ][0].__setitem__("Name", "   "),
            "package without version": lambda value: value["Results"][0][
                "Packages"
            ][0].pop("Version"),
            "package with whitespace version": lambda value: value["Results"][0][
                "Packages"
            ][0].__setitem__("Version", "   "),
            "wrong artifact": lambda value: value.__setitem__(
                "ArtifactName", "local/other:test"
            ),
            "wrong image ID": lambda value: value["Metadata"].__setitem__(
                "ImageID", "sha256:" + ("b" * 64)
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                value = copy.deepcopy(passing_scan_report())
                mutate(value)
                with self.assertRaises(scan_result.ScanResultError):
                    scan_result.validate_report(
                        value,
                        "debian",
                        "local/redis:test",
                        IMAGE_ID,
                    )

    def test_expected_package_separators_are_normalized(self):
        self.assertEqual(
            scan_result.parse_expected_packages(
                "base-files,,redis-server\n redis-tools"
            ),
            {"base-files", "redis-server", "redis-tools"},
        )

    def test_runtime_package_inventory_must_match(self):
        with self.assertRaisesRegex(
            scan_result.ScanResultError,
            "missing=redis-tools.*unexpected=redis-server",
        ):
            scan_result.validate_report(
                passing_scan_report(),
                "debian",
                "local/redis:test",
                IMAGE_ID,
                {"base-files", "redis-tools"},
            )

    def test_scan_result_cli_rejects_missing_or_malformed_reports(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            malformed = temporary / "malformed.json"
            malformed.write_text("{", encoding="utf-8")
            reports = (temporary / "missing.json", malformed)
            for report in reports:
                with self.subTest(report=report.name):
                    completed = subprocess.run(
                        [
                            "python3",
                            "tests/functional/scan_result.py",
                            "--report",
                            str(report),
                            "--expected-family",
                            "debian",
                            "--expected-artifact-name",
                            "local/redis:test",
                            "--expected-image-id",
                            IMAGE_ID,
                        ],
                        cwd=root,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=30,
                        check=False,
                    )
                    self.assertEqual(completed.returncode, 1)
                    self.assertIn("scan_result:", completed.stderr)


class FixtureLockTests(unittest.TestCase):
    def test_lock_is_strict_and_digest_pinned(self):
        fixtures = fixturectl.load_lock()
        self.assertEqual(set(fixtures), fixturectl.EXPECTED_FIXTURES)

    def test_fixture_pull_retries_with_bounded_backoff(self):
        reference = fixturectl.load_lock()["harness-python"]["reference"]
        outcomes = [
            types.SimpleNamespace(returncode=1),
            types.SimpleNamespace(returncode=124),
            types.SimpleNamespace(returncode=0),
        ]
        with mock.patch.object(
            fixturectl.subprocess, "run", side_effect=outcomes
        ) as run, mock.patch.object(
            fixturectl.time, "sleep"
        ) as sleep, mock.patch.object(
            fixturectl.sys, "stderr", new=io.StringIO()
        ):
            fixturectl.pull_fixture(
                "harness-python", reference, "linux/arm64/v8"
            )

        self.assertEqual(run.call_count, 3)
        sleep.assert_has_calls([mock.call(5), mock.call(10)])
        for call in run.call_args_list:
            command = call.args[0]
            self.assertEqual(command[-5:], ["docker", "pull", "--platform", "linux/arm64/v8", reference])
            self.assertIn(str(fixturectl.TIMEOUT_PATH), command)
            self.assertEqual(call.kwargs, {"check": False})

    def test_fixture_pull_exhaustion_is_explicit(self):
        reference = fixturectl.load_lock()["harness-python"]["reference"]
        outcomes = [types.SimpleNamespace(returncode=1)] * 3
        with mock.patch.object(
            fixturectl.subprocess, "run", side_effect=outcomes
        ), mock.patch.object(fixturectl.time, "sleep") as sleep, mock.patch.object(
            fixturectl.sys, "stderr", new=io.StringIO()
        ):
            with self.assertRaisesRegex(
                fixturectl.FixtureError,
                r"harness-python after 3 attempts \(last status 1\)",
            ):
                fixturectl.pull_fixture(
                    "harness-python", reference, "linux/amd64"
                )
        sleep.assert_has_calls([mock.call(5), mock.call(10)])

    def test_fixture_pull_rejects_duplicate_unknown_or_invalid_inputs(self):
        fixtures = fixturectl.load_lock()
        for names, platform, message in (
            (["harness-python", "harness-python"], "linux/amd64", "unique"),
            (["missing"], "linux/amd64", "unknown fixture"),
            (["harness-python"], "windows/amd64", "unsupported"),
        ):
            with self.subTest(names=names, platform=platform):
                with self.assertRaisesRegex(fixturectl.FixtureError, message):
                    fixturectl.command_pull(fixtures, names, platform)

    def test_fixture_pull_uses_only_requested_lock_entries(self):
        fixtures = fixturectl.load_lock()
        with mock.patch.object(fixturectl, "pull_fixture") as pull:
            fixturectl.command_pull(
                fixtures, ["php-nginx"], "linux/arm64/v8"
            )
        pull.assert_called_once_with(
            "php-nginx",
            fixtures["php-nginx"]["reference"],
            "linux/arm64/v8",
        )


class PlannerTests(unittest.TestCase):
    def test_selected_families_cannot_hide_expected_legs(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            results = temporary / "results"
            results.mkdir()
            plan = temporary / "plan.json"
            plan.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "selectedFamilies": ["redis"],
                        "expectedLegIds": [],
                    }
                ),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    "ruby",
                    "tests/functional/contractctl.rb",
                    "aggregate",
                    "--results",
                    str(results),
                    "--plan",
                    str(plan),
                ],
                cwd=root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30,
                check=False,
            )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("does not match selectedFamilies", completed.stderr)


class ReleaseArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temporary.name)
        self.archive = self.root / "image.tar"
        self.archive.write_bytes(b"tested-image-archive")
        self.arguments = types.SimpleNamespace(
            image_name="redis",
            image_version="7.0",
            debian_suite="trixie",
            debian_arch="amd64",
            platform="linux/amd64",
            image_ref="ghcr.io/peslaio/redis",
            repository="peslaio/dhi",
            commit_sha="1" * 40,
            run_id="1234",
            run_attempt="1",
        )
        self.inspected = {
            "id": IMAGE_ID,
            "os": "linux",
            "architecture": "amd64",
            "variant": None,
        }

    def tearDown(self):
        self.temporary.cleanup()

    def test_metadata_binds_exact_tested_archive_and_provenance(self):
        document = releasectl.create_document(
            self.arguments, self.archive, self.inspected
        )
        image = releasectl.validate_document(
            document, self.arguments, self.archive
        )
        self.assertEqual(image["id"], IMAGE_ID)
        self.assertEqual(
            image["architectureTag"], "ghcr.io/peslaio/redis:7.0-trixie-amd64"
        )

    def test_tampered_archive_or_provenance_is_rejected(self):
        document = releasectl.create_document(
            self.arguments, self.archive, self.inspected
        )
        self.archive.write_bytes(b"different-image")
        with self.assertRaises(releasectl.ReleaseArchiveError):
            releasectl.validate_document(document, self.arguments, self.archive)

        self.archive.write_bytes(b"tested-image-archive")
        document = releasectl.create_document(
            self.arguments, self.archive, self.inspected
        )
        document["provenance"]["runId"] = "different-run"
        with self.assertRaises(releasectl.ReleaseArchiveError):
            releasectl.validate_document(document, self.arguments, self.archive)

    def test_export_refuses_a_tag_that_no_longer_matches_tested_id(self):
        arguments = copy.copy(self.arguments)
        arguments.archive = str(self.root / "export.tar")
        arguments.metadata = str(self.root / "release-image.json")
        arguments.expected_image_id = IMAGE_ID
        replacement = dict(self.inspected)
        replacement["id"] = "sha256:" + ("c" * 64)
        with mock.patch.object(
            releasectl,
            "inspect_image",
            side_effect=[self.inspected, replacement],
        ), mock.patch.object(releasectl.subprocess, "run") as run:
            with self.assertRaises(releasectl.ReleaseArchiveError):
                releasectl.command_create(arguments)
        run.assert_not_called()

    def test_registry_push_retries_and_returns_only_validated_digest(self):
        digest = "sha256:" + ("d" * 64)
        outcomes = [
            subprocess.TimeoutExpired(
                ["docker", "push"],
                releasectl.REGISTRY_TRANSFER_TIMEOUT_SECONDS,
                output=b"network stalled\n",
            ),
            types.SimpleNamespace(
                returncode=0,
                stdout=f"candidate: digest: {digest} size: 1234\n",
                stderr="",
            ),
            types.SimpleNamespace(
                returncode=0,
                stdout=f"Name: candidate\nDigest: {digest}\n",
                stderr="",
            ),
        ]
        arguments = types.SimpleNamespace(
            reference="ghcr.io/peslaio/redis:candidate", attempts=2
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.object(
            releasectl.subprocess, "run", side_effect=outcomes
        ) as run, mock.patch.object(
            releasectl.time, "sleep"
        ) as sleep, mock.patch.object(
            releasectl.sys, "stdout", new=stdout
        ), mock.patch.object(
            releasectl.sys, "stderr", new=stderr
        ):
            releasectl.command_registry_push(arguments)

        self.assertEqual(run.call_count, 3)
        sleep.assert_called_once_with(15)
        self.assertEqual(
            [call.kwargs["timeout"] for call in run.call_args_list],
            [300, 300, 60],
        )
        self.assertEqual(stdout.getvalue(), f"{digest}\n")
        self.assertIn("network stalled", stderr.getvalue())
        self.assertIn("timed out after 300s", stderr.getvalue())
        self.assertIn("retrying in 15s", stderr.getvalue())

    def test_registry_push_accepts_digest_reported_only_on_stderr(self):
        digest = "sha256:" + ("d" * 64)
        outcomes = [
            types.SimpleNamespace(
                returncode=0,
                stdout="",
                stderr=f"candidate: digest: {digest} size: 1234\n",
            ),
            types.SimpleNamespace(
                returncode=0,
                stdout=f"Name: candidate\nDigest: {digest}\n",
                stderr="",
            ),
        ]
        arguments = types.SimpleNamespace(
            reference="ghcr.io/peslaio/redis:candidate", attempts=1
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.object(
            releasectl.subprocess, "run", side_effect=outcomes
        ) as run, mock.patch.object(
            releasectl.sys, "stdout", new=stdout
        ), mock.patch.object(
            releasectl.sys, "stderr", new=stderr
        ):
            releasectl.command_registry_push(arguments)

        self.assertEqual(run.call_count, 2)
        self.assertEqual(stdout.getvalue(), f"{digest}\n")
        self.assertIn(f"digest: {digest}", stderr.getvalue())

    def test_registry_login_retries_without_disclosing_password(self):
        password = "registry-secret-value"
        outcomes = [
            types.SimpleNamespace(
                returncode=1,
                stdout=f"temporary denial for {password}\n",
                stderr=f"credential={password}\n",
            ),
            types.SimpleNamespace(
                returncode=0,
                stdout="Login Succeeded\n",
                stderr=f"ignored echo {password}\n",
            ),
        ]
        arguments = types.SimpleNamespace(
            registry="ghcr.io", username="github-user", attempts=2
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.object(
            releasectl.subprocess, "run", side_effect=outcomes
        ) as run, mock.patch.object(
            releasectl.time, "sleep"
        ), mock.patch.object(
            releasectl.sys, "stdin", new=io.StringIO(password)
        ), mock.patch.object(
            releasectl.sys, "stdout", new=stdout
        ), mock.patch.object(
            releasectl.sys, "stderr", new=stderr
        ):
            releasectl.command_registry_login(arguments)

        self.assertEqual(run.call_count, 2)
        self.assertEqual(
            [call.kwargs["timeout"] for call in run.call_args_list],
            [60, 60],
        )
        for call in run.call_args_list:
            self.assertEqual(call.kwargs["input"], password)
            self.assertNotIn(password, call.args[0])
        combined_output = stdout.getvalue() + stderr.getvalue()
        self.assertNotIn(password, combined_output)
        self.assertGreaterEqual(combined_output.count("***"), 2)
        self.assertNotIn("ignored echo", combined_output)
        self.assertNotIn("Login Succeeded", combined_output)
        self.assertIn("Authenticated to ghcr.io", stdout.getvalue())

    def test_registry_push_rejects_conflicting_digests(self):
        first = "sha256:" + ("a" * 64)
        second = "sha256:" + ("b" * 64)
        with self.assertRaisesRegex(
            releasectl.ReleaseArchiveError, "conflicting immutable digests"
        ):
            releasectl.registry_digest_from_push(
                f"candidate: digest: {first}\n",
                f"warning digest: {second}\n",
            )

    def test_registry_digest_retries_stale_success_until_expected_digest(self):
        digest = "sha256:" + ("e" * 64)
        stale_digest = "sha256:" + ("f" * 64)
        outcomes = [
            types.SimpleNamespace(
                returncode=0,
                stdout=f"Name: candidate\nDigest: {stale_digest}\n",
                stderr="",
            ),
            types.SimpleNamespace(
                returncode=0,
                stdout=f"Name: candidate\nDigest: {digest}\n",
                stderr="",
            ),
        ]
        arguments = types.SimpleNamespace(
            reference="ghcr.io/peslaio/redis:candidate",
            expected_digest=digest,
            attempts=2,
        )
        stdout = io.StringIO()
        with mock.patch.object(
            releasectl.subprocess, "run", side_effect=outcomes
        ), mock.patch.object(
            releasectl.time, "sleep"
        ) as sleep, mock.patch.object(
            releasectl.sys, "stdout", new=stdout
        ), mock.patch.object(
            releasectl.sys, "stderr", new=io.StringIO()
        ):
            releasectl.command_registry_digest(arguments)

        sleep.assert_called_once_with(15)
        self.assertEqual(stdout.getvalue(), f"{digest}\n")

    def test_registry_raw_inspect_retries_malformed_json(self):
        outcomes = [
            types.SimpleNamespace(returncode=0, stdout="{", stderr=""),
            types.SimpleNamespace(
                returncode=0,
                stdout='{"schemaVersion":2,"manifests":[]}\n',
                stderr="buildx warning\n",
            ),
        ]
        arguments = types.SimpleNamespace(
            registry_command=[
                "--",
                "docker",
                "buildx",
                "imagetools",
                "inspect",
                "ghcr.io/peslaio/redis:candidate",
                "--raw",
            ],
            attempts=2,
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.object(
            releasectl.subprocess, "run", side_effect=outcomes
        ), mock.patch.object(
            releasectl.time, "sleep"
        ) as sleep, mock.patch.object(
            releasectl.sys, "stdout", new=stdout
        ), mock.patch.object(
            releasectl.sys, "stderr", new=stderr
        ):
            releasectl.command_registry_command(arguments)

        sleep.assert_called_once_with(15)
        self.assertEqual(
            stdout.getvalue(), '{"schemaVersion":2,"manifests":[]}\n'
        )
        self.assertEqual(stderr.getvalue().splitlines()[-1], "buildx warning")

    def test_registry_command_rejects_unsafe_operations(self):
        cases = {
            "non-allowlisted command": (
                ["--", "docker", "image", "rm", "candidate"],
                "only permits",
            ),
            "non-idempotent append": (
                [
                    "--",
                    "docker",
                    "buildx",
                    "imagetools",
                    "create",
                    "--append",
                    "ghcr.io/peslaio/redis:candidate",
                ],
                "non-idempotent",
            ),
            "non-idempotent append value": (
                [
                    "--",
                    "docker",
                    "buildx",
                    "imagetools",
                    "create",
                    "--append=true",
                    "ghcr.io/peslaio/redis:candidate",
                ],
                "non-idempotent",
            ),
        }
        for name, (command, message) in cases.items():
            with self.subTest(name=name), self.assertRaisesRegex(
                releasectl.ReleaseArchiveError, message
            ):
                releasectl.command_registry_command(
                    types.SimpleNamespace(
                        registry_command=command,
                        attempts=1,
                    )
                )

    def test_registry_retry_attempt_count_is_bounded(self):
        for attempts in (0, 11):
            with self.subTest(attempts=attempts), self.assertRaisesRegex(
                releasectl.ReleaseArchiveError, "between 1 and 10"
            ), mock.patch.object(releasectl.subprocess, "run") as run:
                releasectl.registry_retry(
                    ["docker", "pull", "ghcr.io/peslaio/redis:candidate"],
                    "test pull",
                    attempts,
                )
            run.assert_not_called()

    def published_records(self):
        records = {}
        for arch, marker in (("amd64", "d"), ("arm64", "e")):
            arguments = copy.copy(self.arguments)
            arguments.debian_arch = arch
            arguments.platform = f"linux/{arch}"
            inspected = dict(self.inspected)
            inspected["id"] = "sha256:" + (marker * 64)
            inspected["architecture"] = arch
            metadata = releasectl.create_document(arguments, self.archive, inspected)
            records[arch] = releasectl.published_document(
                metadata, "sha256:" + (marker * 64)
            )
        return records

    def manifest_arguments(self):
        return types.SimpleNamespace(
            image_name=self.arguments.image_name,
            image_version=self.arguments.image_version,
            debian_suite=self.arguments.debian_suite,
            debian_arches="amd64 arm64",
            image_ref=self.arguments.image_ref,
            repository=self.arguments.repository,
            commit_sha=self.arguments.commit_sha,
            run_id=self.arguments.run_id,
            run_attempt=self.arguments.run_attempt,
        )

    def test_published_records_produce_ordered_immutable_sources(self):
        sources = releasectl.validate_published_documents(
            self.published_records(), self.manifest_arguments()
        )
        self.assertEqual(
            sources,
            [
                "ghcr.io/peslaio/redis@sha256:" + ("d" * 64),
                "ghcr.io/peslaio/redis@sha256:" + ("e" * 64),
            ],
        )

    def test_invalid_published_record_sets_are_rejected(self):
        mutations = {
            "missing architecture": lambda value: value.pop("arm64"),
            "extra architecture": lambda value: value.__setitem__(
                "s390x", copy.deepcopy(value["amd64"])
            ),
            "wrong provenance": lambda value: value["amd64"]["provenance"].__setitem__(
                "runAttempt", "2"
            ),
            "malformed digest": lambda value: value["amd64"].__setitem__(
                "publishedDigest", "latest"
            ),
            "duplicate digest": lambda value: value["arm64"].__setitem__(
                "publishedDigest", value["amd64"]["publishedDigest"]
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                records = self.published_records()
                mutate(records)
                with self.assertRaises(releasectl.ReleaseArchiveError):
                    releasectl.validate_published_documents(
                        records, self.manifest_arguments()
                    )

    def test_index_member_must_match_accepted_platform_digest(self):
        amd64_digest = "sha256:" + ("d" * 64)
        arm64_digest = "sha256:" + ("e" * 64)
        document = {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.index.v1+json",
            "manifests": [
                {
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "digest": amd64_digest,
                    "platform": {"os": "linux", "architecture": "amd64"},
                },
                {
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "digest": arm64_digest,
                    "platform": {"os": "linux", "architecture": "arm64"},
                },
            ],
        }
        self.assertEqual(
            releasectl.verify_index_member(document, "linux/arm64", arm64_digest),
            arm64_digest,
        )

        mutations = {
            "wrong digest": lambda value: value["manifests"][1].__setitem__(
                "digest", "sha256:" + ("f" * 64)
            ),
            "missing platform": lambda value: value["manifests"].pop(),
            "duplicate platform": lambda value: value["manifests"].append(
                copy.deepcopy(value["manifests"][1])
            ),
            "malformed document": lambda value: value.__setitem__(
                "manifests", "not-an-array"
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                candidate = copy.deepcopy(document)
                mutate(candidate)
                with self.assertRaises(releasectl.ReleaseArchiveError):
                    releasectl.verify_index_member(
                        candidate, "linux/arm64", arm64_digest
                    )

    def test_release_freshness_matches_family_and_common_inputs(self):
        selected = {
            ".github/workflows/redis-image.yml",
            ".github/workflows/redis-image-release.yml",
            ".github/workflows/reusable-build-debian-image.yml",
            "images/redis/7.0/image.yaml",
            "tests/functional/releasectl.py",
            "tests/functional/harness/probe.py",
            "tests/functional/redis/compose.yaml",
        }
        ignored = {
            "README.md",
            ".github/workflows/apache-image.yml",
            "images/apache/2.4/image.yaml",
            "tests/functional/apache/compose.yaml",
        }
        for path in selected:
            with self.subTest(selected=path):
                self.assertTrue(releasectl.release_relevant_path("redis", path))
        for path in ignored:
            with self.subTest(ignored=path):
                self.assertFalse(releasectl.release_relevant_path("redis", path))


class WorkflowPolicyTests(unittest.TestCase):
    CORE_WORKFLOWS = {
        "apache-image.yml",
        "caddy-image.yml",
        "dotnet-aspnet-images.yml",
        "dotnet-runtime-images.yml",
        "haproxy-image.yml",
        "java-jre-image.yml",
        "mariadb-image.yml",
        "memcached-image.yml",
        "mongodb-image.yml",
        "nginx-image.yml",
        "node-image.yml",
        "php-fpm-image.yml",
        "postgresql-image.yml",
        "python-image.yml",
        "rabbitmq-image.yml",
        "redis-image.yml",
    }

    PUBLISHER_WORKFLOWS = {
        "reusable-publish-image-manifest.yml",
        "reusable-publish-tested-image.yml",
    }

    def test_image_spec_owners_are_canonical_strings(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        spec_paths = sorted((root / "images").glob("**/image.yaml"))
        owner_lines = [
            line.strip()
            for path in spec_paths
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip().startswith("owner:")
        ]
        self.assertEqual(len(owner_lines), 65)
        for owner_line in owner_lines:
            with self.subTest(owner=owner_line):
                self.assertRegex(
                    owner_line,
                    r'^owner: "(?:0|[1-9][0-9]*|[a-z_][a-z0-9_-]*):'
                    r'(?:0|[1-9][0-9]*|[a-z_][a-z0-9_-]*)"$',
                )

        validation = subprocess.run(
            ["ruby", "tests/functional/contractctl.rb", "validate"],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(validation.returncode, 0, validation.stderr)

        owner_validation = subprocess.run(
            [
                "ruby",
                "-e",
                """
require "yaml"
require File.expand_path("tests/functional/contractctl", Dir.pwd)

valid = %w[0:0 10001:0 root:0 10001:app app:app _svc:0]
invalid = [
  YAML.safe_load("owner: 10001:0")["owner"],
  10001, "", "10001", ":0", "10001:", "root:0:0", "root: 0",
  "-1:0", "+1:0", "01:0", "root/evil:0", "root;id:0", "$(id):0"
]

valid.each { |value| DhiContracts.owner(value, "owner") }
invalid.each do |value|
  begin
    DhiContracts.owner(value, "owner")
  rescue DhiContracts::ContractError
    next
  end
  abort("invalid owner was accepted: #{value.inspect}")
end
""",
            ],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(owner_validation.returncode, 0, owner_validation.stderr)

    def test_image_spec_runtime_identity_matches_effective_workflow_inputs(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        workflow_dir = root / ".github" / "workflows"
        reusable = (
            workflow_dir / "reusable-build-debian-image.yml"
        ).read_text(encoding="utf-8")

        def input_default(key):
            tail = reusable.split(f"\n      {key}:\n", 1)[1]
            next_input = re.search(r"(?m)^      [a-z_]+:\s*$", tail)
            block = tail[: next_input.start()] if next_input else tail
            match = re.search(r"(?m)^        default:\s*(.*?)\s*$", block)
            self.assertIsNotNone(match, f"missing default for {key}")
            return match.group(1).strip().strip("\"'")

        defaults = {
            key: input_default(key)
            for key in (
                "run_user",
                "runtime_user_name",
                "runtime_home",
                "runtime_shell",
                "run_uid",
                "run_gid",
            )
        }

        def scalar(block, key, default=None):
            match = re.search(
                rf"(?m)^      {re.escape(key)}:\s*(.+?)\s*$", block
            )
            if not match:
                return default
            return match.group(1).strip().strip("\"'")

        workflows = {}
        for workflow_name in self.CORE_WORKFLOWS:
            workflow = (workflow_dir / workflow_name).read_text(encoding="utf-8")
            build_call = workflow.split(
                "uses: ./.github/workflows/reusable-build-debian-image.yml", 1
            )[1].split("\n\n  contract-aggregate:", 1)[0]
            family = scalar(build_call, "image_name")
            self.assertIsNotNone(family)
            runtime_name = scalar(
                build_call, "runtime_user_name", defaults["runtime_user_name"]
            ) or family
            uid = scalar(build_call, "run_uid", defaults["run_uid"])
            gid = scalar(build_call, "run_gid", defaults["run_gid"])
            workflows[family] = {
                "name": runtime_name,
                "uid": int(uid),
                "gid": int(gid),
                "home": scalar(
                    build_call, "runtime_home", defaults["runtime_home"]
                ),
                "shell": scalar(
                    build_call, "runtime_shell", defaults["runtime_shell"]
                ),
            }
            self.assertEqual(
                scalar(build_call, "run_user", defaults["run_user"]),
                f"{uid}:{gid}",
            )

        for spec_path in sorted((root / "images").glob("**/image.yaml")):
            spec = spec_path.read_text(encoding="utf-8")
            family = re.search(r"(?m)^name:\s*(\S+)\s*$", spec).group(1)
            user_block = spec.split("\nuser:\n", 1)[1].split("\npaths:\n", 1)[0]
            values = {
                key: value.strip().strip("\"'")
                for key, value in re.findall(
                    r"(?m)^  (name|uid|gid|home|shell):\s*(.+?)\s*$",
                    user_block,
                )
            }
            values["uid"] = int(values["uid"])
            values["gid"] = int(values["gid"])
            with self.subTest(spec=spec_path.relative_to(root)):
                self.assertEqual(values, workflows[family])

        self.assertIn("Runtime image must contain exactly one passwd entry", reusable)
        self.assertIn("Runtime passwd entry mismatch", reusable)
        for runtime_input in (
            "RUNTIME_USER_NAME",
            "RUNTIME_HOME",
            "RUNTIME_SHELL",
        ):
            self.assertIn(f"{runtime_input}: ${{{{ inputs.", reusable)

    def test_fixture_pulls_are_bounded_before_the_single_compose_build(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        runner = (root / "tests" / "functional" / "run.sh").read_text(
            encoding="utf-8"
        )
        pull = 'python3 "$fixture_helper" pull --platform "$platform"'
        build = '"${compose[@]}" build --pull=false'
        self.assertIn(pull, runner)
        self.assertEqual(runner.count(pull), 1)
        self.assertEqual(runner.count(build), 1)
        self.assertLess(runner.index(pull), runner.index(build))
        for fixture_variable in (
            "fixture_python",
            "fixture_java",
            "fixture_nginx",
            "fixture_dotnet",
        ):
            with self.subTest(fixture=fixture_variable):
                self.assertIn(
                    f'grep -Fq -- "${fixture_variable}" '
                    '"$artifact_dir/compose-config.json"',
                    runner,
                )
        self.assertIn(
            'fail_run "$EXIT_INFRASTRUCTURE" infrastructure_failure fixture-pull',
            runner,
        )

    def test_functional_evidence_is_attempt_scoped_and_immutable(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        workflow_dir = root / ".github" / "workflows"
        build = (workflow_dir / "reusable-build-debian-image.yml").read_text(
            encoding="utf-8"
        )
        upload = build.split(
            "\n      - name: Upload functional contract evidence\n", 1
        )[1].split("\n      - name: Enforce functional application contract\n", 1)[0]
        self.assertIn(
            "name: image-contract-result--${{ inputs.image_name }}--${{ inputs.image_version }}--${{ inputs.debian_arch }}--attempt-${{ github.run_attempt }}",
            upload,
        )
        self.assertNotIn("overwrite:", upload)

        family_aggregate = (
            workflow_dir / "reusable-aggregate-image-contract.yml"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "pattern: image-contract-result--${{ inputs.image_name }}--*--attempt-${{ github.run_attempt }}",
            family_aggregate,
        )
        central_aggregate = (workflow_dir / "image-contracts.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "pattern: image-contract-result--*--attempt-${{ github.run_attempt }}",
            central_aggregate,
        )

    def test_runtime_closure_patterns_are_expanded_only_inside_the_rootfs(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        workflow_dir = root / ".github" / "workflows"
        build_workflow = (
            workflow_dir / "reusable-build-debian-image.yml"
        ).read_text(encoding="utf-8")

        self.assertNotIn(
            "for binary_pattern in $RUNTIME_CLOSURE_BINARIES",
            build_workflow,
        )
        self.assertNotIn(
            "for closure_path in $RUNTIME_CLOSURE_PATHS",
            build_workflow,
        )
        self.assertIn(
            'compgen -G "${rootfs}${binary_pattern}"',
            build_workflow,
        )
        self.assertIn(
            'compgen -G "${rootfs}${closure_path}"',
            build_workflow,
        )
        self.assertIn(
            'readlink -f "$path"',
            build_workflow,
        )
        self.assertIn(
            'sudo cp -a "$rootfs$path/." "$runtime_rootfs$path/"',
            build_workflow,
        )
        self.assertIn("runtime_remove_paths:", build_workflow)
        self.assertIn(
            'resolved_remove_target="$(realpath -m "$runtime_remove_target")"',
            build_workflow,
        )
        self.assertIn('"$final_rootfs"/*)', build_workflow)
        self.assertIn("Runtime removal path does not exist", build_workflow)
        rabbitmq_workflow = (
            workflow_dir / "rabbitmq-image.yml"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "runtime_remove_paths: /var/lib/rabbitmq/.erlang.cookie",
            rabbitmq_workflow,
        )
        self.assertIn(
            'cmd: \'["/usr/lib/rabbitmq/bin/rabbitmq-server"]\'',
            rabbitmq_workflow,
        )
        self.assertIn("smoke_tcp_port: \"5672\"", rabbitmq_workflow)
        self.assertIn(
            "smoke_startup_timeout_seconds: \"120\"",
            rabbitmq_workflow,
        )
        self.assertNotIn('exposed_ports: "5672 15672"', rabbitmq_workflow)

    def test_running_smoke_command_retry_is_deadline_bounded(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        workflow_dir = root / ".github" / "workflows"
        build_workflow = (
            workflow_dir / "reusable-build-debian-image.yml"
        ).read_text(encoding="utf-8")
        running_retry = build_workflow.rsplit(
            'if [ -n "$SMOKE_COMMAND" ]; then', 1
        )[1]

        self.assertIn("smoke_command_deadline=", running_retry)
        self.assertIn(
            'timeout --signal=KILL "$smoke_command_attempt_timeout"',
            running_retry,
        )
        self.assertIn(
            'grep -q "$SMOKE_EXPECTED_OUTPUT" /tmp/dif-smoke-output',
            running_retry,
        )
        self.assertIn(
            'smoke_container_status="$(docker inspect',
            running_retry,
        )
        self.assertIn("Smoke command did not become ready", running_retry)
        self.assertIn(
            "smoke_startup_timeout_seconds must be a positive integer",
            build_workflow,
        )

        rabbitmq_workflow = (
            workflow_dir / "rabbitmq-image.yml"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "smoke_command: /usr/sbin/rabbitmq-diagnostics -q ping --timeout 5",
            rabbitmq_workflow,
        )

    def test_vulnerability_scans_are_coverage_gated(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        workflow_dir = root / ".github" / "workflows"
        build_workflow = (
            workflow_dir / "reusable-build-debian-image.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("/etc/debian_version", build_workflow)
        self.assertIn("/etc/os-release", build_workflow)
        self.assertIn(
            "Runtime closure is missing a readable Debian OS identity",
            build_workflow,
        )
        self.assertIn("Runtime closure package database is empty", build_workflow)
        for post_removal_check in (
            "Runtime closure is missing a readable Debian OS identity",
            "Runtime closure package database is empty",
        ):
            with self.subTest(post_removal_check=post_removal_check):
                self.assertGreater(
                    build_workflow.index(post_removal_check),
                    build_workflow.index('sudo rm -rf -- "$runtime_remove_target"'),
                )
        self.assertIn("format: json", build_workflow)
        self.assertIn("output: artifacts/security/trivy-report.json", build_workflow)
        self.assertIn("list-all-pkgs: true", build_workflow)
        self.assertIn("tests/functional/scan_result.py", build_workflow)

        input_policy_step = build_workflow.split(
            "\n      - name: Validate build policy inputs\n", 1
        )[1].split("\n      - name: Install rootfs build dependencies\n", 1)[0]
        functional_upload_step = build_workflow.split(
            "\n      - name: Upload functional contract evidence\n", 1
        )[1].split("\n      - name: Enforce functional application contract\n", 1)[0]
        scan_step = build_workflow.split(
            "\n      - name: Scan image\n", 1
        )[1].split("\n      - name: Validate vulnerability scan coverage\n", 1)[0]
        coverage_step = build_workflow.split(
            "\n      - name: Validate vulnerability scan coverage\n", 1
        )[1].split("\n      - name: Upload vulnerability scan evidence\n", 1)[0]
        upload_step = build_workflow.split(
            "\n      - name: Upload vulnerability scan evidence\n", 1
        )[1].split("\n      - name: Enforce vulnerability scan\n", 1)[0]
        enforcement_step = build_workflow.split(
            "\n      - name: Enforce vulnerability scan\n", 1
        )[1].split("\n      - name: Export fully tested image for release\n", 1)[0]
        export_step = build_workflow.split(
            "\n      - name: Export fully tested image for release\n", 1
        )[1].split("\n      - name:", 1)[0]

        self.assertIn(
            "runtime_closure=true requires a non-empty allowed_packages inventory",
            input_policy_step,
        )
        self.assertIn('if [ "$EXPORT_IMAGE" = "true" ]', input_policy_step)
        for required_gate in (
            "functional_test",
            "generate_sbom",
            "scan",
            "fail_on_vulnerabilities",
        ):
            with self.subTest(release_gate=required_gate):
                self.assertIn(
                    f"missing_release_gates+=({required_gate})",
                    input_policy_step,
                )
        self.assertIn(
            "if: ${{ always() && inputs.functional_test && "
            "(steps.functional.outcome == 'success' || "
            "hashFiles('artifacts/functional/**') != '') }}",
            functional_upload_step,
        )
        self.assertIn("if-no-files-found: error", functional_upload_step)

        self.assertIn("id: vulnerability-scan", scan_step)
        self.assertIn("if: inputs.scan", scan_step)
        self.assertIn("continue-on-error: true", scan_step)
        self.assertIn("id: vulnerability-coverage", coverage_step)
        self.assertIn("if: ${{ always() && inputs.scan }}", coverage_step)
        self.assertIn("continue-on-error: true", coverage_step)
        self.assertIn('--expected-artifact-name "$PRIMARY_TAG"', coverage_step)
        self.assertIn('--expected-image-id "$TESTED_IMAGE_ID"', coverage_step)
        self.assertIn(
            "if: ${{ always() && inputs.scan && "
            "(steps.vulnerability-coverage.outcome == 'success' || "
            "hashFiles('artifacts/security/trivy-report.json') != '') }}",
            upload_step,
        )
        self.assertIn("if-no-files-found: error", upload_step)
        self.assertIn("if: ${{ always() && inputs.scan }}", enforcement_step)
        self.assertIn(
            "steps.vulnerability-scan.outcome", enforcement_step
        )
        self.assertIn(
            "steps.vulnerability-coverage.outcome", enforcement_step
        )
        self.assertIn(
            "Vulnerability scan coverage outcome: $COVERAGE_OUTCOME",
            enforcement_step,
        )
        self.assertIn("if: inputs.export_image", export_step)
        self.assertNotIn("always()", export_step)
        self.assertNotIn("continue-on-error", export_step)

        closure_workflows = discover_runtime_closure_workflows(workflow_dir)
        self.assertTrue(closure_workflows)
        for workflow_name, workflow in closure_workflows.items():
            with self.subTest(workflow=workflow_name):
                allowed_packages = next(
                    line.partition(":")[2].strip().split(",")
                    for line in workflow.splitlines()
                    if line.strip().startswith("allowed_packages:")
                )
                self.assertIn("base-files", allowed_packages)

    def test_closure_allowlists_match_package_inventory(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        workflow_dir = root / ".github" / "workflows"
        inventory_lines = (
            (root / "docs" / "package-inventory.md")
            .read_text(encoding="utf-8")
            .split("## Runtime-Closure Images", 1)[1]
            .split("## Full-Rootfs Images", 1)[0]
            .splitlines()
        )
        scorecard_measurement_lines = (
            (root / "docs" / "image-quality-scorecard.md")
            .read_text(encoding="utf-8")
            .split("## Measurable Gains Over Regular Images", 1)[1]
            .split("## Strengths That Matter", 1)[0]
            .splitlines()
        )
        closure_workflows = {}
        for workflow_name, workflow in discover_runtime_closure_workflows(
            workflow_dir
        ).items():
            image_name = next(
                line.partition(":")[2].strip()
                for line in workflow.splitlines()
                if line.strip().startswith("image_name:")
            )
            closure_workflows[image_name] = workflow_name

        inventory_rows = {
            columns[0].replace("`", ""): columns
            for line in inventory_lines
            if line.startswith("| `")
            for columns in [
                [column.strip() for column in line.strip("|").split("|")]
            ]
        }
        scorecard_rows = {
            columns[0].replace("`", ""): columns
            for line in scorecard_measurement_lines
            if line.startswith("| `")
            for columns in [
                [column.strip() for column in line.strip("|").split("|")]
            ]
        }
        self.assertEqual(set(inventory_rows), set(closure_workflows))
        self.assertEqual(set(scorecard_rows), set(closure_workflows))

        for image_name, workflow_name in closure_workflows.items():
            with self.subTest(image=image_name):
                workflow_lines = (
                    workflow_dir / workflow_name
                ).read_text(encoding="utf-8").splitlines()
                allowed_line = next(
                    line.strip()
                    for line in workflow_lines
                    if line.strip().startswith("allowed_packages:")
                )
                workflow_packages = allowed_line.partition(":")[2].strip().split(",")

                columns = inventory_rows[image_name]
                inventory_count = int(columns[2])
                inventory_packages = columns[3].replace("`", "").split(", ")
                scorecard_columns = scorecard_rows[image_name]
                scorecard_count = int(scorecard_columns[1])
                upstream_count = int(scorecard_columns[2])
                scorecard_reduction = int(scorecard_columns[3].removesuffix("%"))
                expected_reduction = round(
                    (upstream_count - scorecard_count) * 100 / upstream_count
                )

                self.assertEqual(inventory_count, len(workflow_packages))
                self.assertEqual(inventory_packages, workflow_packages)
                self.assertEqual(scorecard_count, inventory_count)
                self.assertEqual(scorecard_reduction, expected_reduction)

    def test_php_fpm_declares_opcache_lock_tmpfs(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        compose = (
            root / "tests" / "functional" / "php-fpm" / "compose.yaml"
        ).read_text(encoding="utf-8")
        workflow = (
            root / ".github" / "workflows" / "php-fpm-image.yml"
        ).read_text(encoding="utf-8")
        image_spec = (
            root / "images" / "php-fpm" / "image.yaml"
        ).read_text(encoding="utf-8")

        self.assertIn("/tmp:uid=10001,gid=0,mode=1777", compose)
        writable_paths = next(
            line.partition(":")[2].strip().split()
            for line in workflow.splitlines()
            if line.strip().startswith("writable_paths:")
        )
        self.assertIn("/tmp", writable_paths)
        self.assertRegex(
            image_spec,
            r'(?m)^  - path: /tmp\n    owner: "10001:0"\n    mode: "1777"$',
        )

    def test_workflows_use_node24_action_generations(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        workflow_dir = root / ".github" / "workflows"
        workflow_paths = sorted(
            set(workflow_dir.glob("*.yml"))
            | set(workflow_dir.glob("*.yaml"))
        )
        action_refs = {
            match.group(1)
            for path in workflow_paths
            for match in re.finditer(
                r"(?m)^\s*(?:-\s*)?uses:\s*([^\s#]+)",
                path.read_text(encoding="utf-8"),
            )
            if not match.group(1).startswith("./")
        }
        minimum_node24_versions = {
            "actions/checkout": (6, 0, 0),
            "actions/download-artifact": (7, 0, 0),
            "actions/upload-artifact": (6, 0, 0),
            "anchore/sbom-action": (0, 24, 0),
            "azure/setup-helm": (5, 0, 0),
        }
        audited_composite_actions = {
            "aquasecurity/trivy-action",
            "sigstore/cosign-installer",
        }
        action_names = {ref.rpartition("@")[0] for ref in action_refs}
        self.assertEqual(
            action_names,
            set(minimum_node24_versions) | audited_composite_actions,
        )

        for ref in action_refs:
            action_name, separator, version = ref.rpartition("@")
            self.assertEqual(separator, "@", ref)
            if action_name not in minimum_node24_versions:
                continue
            with self.subTest(action=ref):
                match = re.fullmatch(r"v(\d+)(?:\.(\d+))?(?:\.(\d+))?", version)
                self.assertIsNotNone(match, ref)
                parsed_version = tuple(
                    int(component or 0) for component in match.groups()
                )
                self.assertGreaterEqual(
                    parsed_version,
                    minimum_node24_versions[action_name],
                )

    def test_download_artifact_suppresses_only_upstream_buffer_warning(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        workflow_dir = root / ".github" / "workflows"
        workflow_paths = sorted(
            set(workflow_dir.glob("*.yml"))
            | set(workflow_dir.glob("*.yaml"))
        )
        download_steps = []
        for path in workflow_paths:
            lines = path.read_text(encoding="utf-8").splitlines()
            for index, line in enumerate(lines):
                uses_match = re.match(
                    r"^(\s*)(-\s*)?uses:\s*actions/download-artifact@",
                    line,
                )
                if uses_match is None:
                    continue
                if uses_match.group(2):
                    step_indent = len(uses_match.group(1))
                    start = index
                else:
                    step_indent = len(uses_match.group(1)) - 2
                    step_start = re.compile(
                        rf"^ {{{step_indent}}}-\s+(?:name|uses):"
                    )
                    start = next(
                        candidate
                        for candidate in range(index, -1, -1)
                        if step_start.match(lines[candidate])
                    )
                next_step = re.compile(rf"^ {{{step_indent}}}-\s+")
                end = next(
                    (
                        candidate
                        for candidate in range(index + 1, len(lines))
                        if next_step.match(lines[candidate])
                    ),
                    len(lines),
                )
                download_steps.append((path, index + 1, "\n".join(lines[start:end])))

        self.assertTrue(download_steps)
        for path, line_number, step in download_steps:
            with self.subTest(workflow=path.name, line=line_number):
                self.assertIn(
                    "NODE_OPTIONS: --disable-warning=DEP0005",
                    step,
                )
                self.assertIn("actions/download-artifact#484", step)

    def test_release_promotion_requires_native_candidate_acceptance(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        workflow_dir = root / ".github" / "workflows"
        publisher = (
            workflow_dir / "reusable-publish-tested-image.yml"
        ).read_text(encoding="utf-8")

        candidate, architecture_acceptance = publisher.split(
            "\n  accept-candidate-architecture:\n", 1
        )
        architecture_acceptance, accepted_record = (
            architecture_acceptance.split("\n  record-accepted-architecture:\n", 1)
        )
        accepted_record, manifest_call = accepted_record.split(
            "\n  publish-manifest:\n", 1
        )

        self.assertIn(
            "candidate-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}", candidate
        )
        self.assertIn("releasectl.py registry-login", candidate)
        self.assertIn("releasectl.py registry-push", candidate)
        self.assertNotIn("docker/login-action", candidate)
        self.assertNotIn("tests/functional/run.sh", candidate)
        self.assertIn(
            "needs: [prepare, publish-candidate-architecture]",
            architecture_acceptance,
        )
        self.assertIn("packages: read", architecture_acceptance)
        self.assertNotIn("packages: write", architecture_acceptance)
        self.assertIn("ubuntu-24.04-arm", architecture_acceptance)
        self.assertIn('docker pull --platform "${{ matrix.platform }}"', architecture_acceptance)
        self.assertIn("tests/functional/run.sh", architecture_acceptance)
        self.assertIn("Verify candidate architecture signature", architecture_acceptance)
        self.assertIn(
            "--certificate-oidc-issuer https://token.actions.githubusercontent.com",
            architecture_acceptance,
        )
        self.assertIn("--output json", architecture_acceptance)
        self.assertIn("max_attempts=5", architecture_acceptance)
        self.assertIn(
            "needs: [prepare, accept-candidate-architecture]",
            accepted_record,
        )
        self.assertNotIn("packages: write", accepted_record)
        self.assertNotIn("docker push", accepted_record)
        self.assertNotIn("imagetools create", accepted_record)
        self.assertIn("needs: [prepare, record-accepted-architecture]", manifest_call)

        manifest = (
            workflow_dir / "reusable-publish-image-manifest.yml"
        ).read_text(encoding="utf-8")
        index_candidate, index_acceptance = manifest.split(
            "\n  accept-candidate-index:\n", 1
        )
        index_acceptance, index_promotion = index_acceptance.split(
            "\n  promote:\n", 1
        )
        self.assertIn(
            "candidate-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}",
            index_candidate,
        )
        self.assertIn("releasectl.py registry-login", index_candidate)
        self.assertIn("releasectl.py registry-command", index_candidate)
        self.assertIn("releasectl.py registry-digest", index_candidate)
        self.assertNotIn("docker/login-action", manifest)
        self.assertIn(
            "needs: [prepare-platform-matrix, publish-candidate]",
            index_acceptance,
        )
        self.assertIn("packages: read", index_acceptance)
        self.assertNotIn("packages: write", index_acceptance)
        self.assertIn("ubuntu-24.04-arm", index_acceptance)
        self.assertIn('source_ref="${IMAGE_REF}@${INDEX_DIGEST}"', index_acceptance)
        self.assertIn(
            "Download accepted native architecture digest", index_acceptance
        )
        self.assertIn("releasectl.py verify-index", index_acceptance)
        self.assertIn('--expected-digest "$INDEX_DIGEST"', index_acceptance)
        self.assertIn(
            'if [ "$observed_index_digest" != "$INDEX_DIGEST" ]',
            index_acceptance,
        )
        self.assertIn("tests/functional/run.sh", index_acceptance)
        self.assertIn("Verify candidate index signature", index_acceptance)
        self.assertIn(
            "--certificate-oidc-issuer https://token.actions.githubusercontent.com",
            index_acceptance,
        )
        self.assertIn("--output json", index_acceptance)
        self.assertIn("max_attempts=5", index_acceptance)
        self.assertGreaterEqual(index_candidate.count("max_attempts=5"), 1)
        self.assertIn(
            "needs: [publish-candidate, accept-candidate-index]",
            index_promotion,
        )
        self.assertIn("actions: read", index_promotion)
        self.assertIn(
            "Download accepted architecture digests", index_promotion
        )
        self.assertIn(
            'architecture_tag="${IMAGE_REF}:${{ inputs.image_version }}-'
            '${{ inputs.debian_suite }}-${arches[$index]}"',
            index_promotion,
        )
        self.assertIn(
            'docker buildx imagetools create --prefer-index=false '
            '--tag "$architecture_tag" "$source_ref"',
            index_promotion,
        )
        self.assertLess(
            index_promotion.index('architecture_tag="${IMAGE_REF}:'),
            index_promotion.index(
                'docker buildx imagetools create --tag "$PRIMARY_TAG"'
            ),
        )
        self.assertIn(
            'docker buildx imagetools create --tag "$PRIMARY_TAG" '
            '"$IMAGE_REF@$INDEX_DIGEST"',
            index_promotion,
        )
        self.assertIn(
            'if [ "$observed_digest" != "$INDEX_DIGEST" ]',
            index_promotion,
        )
        self.assertGreaterEqual(index_promotion.count("--expected-digest"), 2)

    def test_every_release_registry_boundary_uses_the_retry_controller(self):
        workflow_dir = (
            pathlib.Path(__file__).resolve().parents[2]
            / ".github"
            / "workflows"
        )
        architecture_publisher = (
            workflow_dir / "reusable-publish-tested-image.yml"
        ).read_text(encoding="utf-8")
        manifest_publisher = (
            workflow_dir / "reusable-publish-image-manifest.yml"
        ).read_text(encoding="utf-8")

        self.assertEqual(
            architecture_publisher.count("releasectl.py registry-login"), 2
        )
        self.assertEqual(
            architecture_publisher.count("releasectl.py registry-push"), 1
        )
        self.assertEqual(
            architecture_publisher.count("releasectl.py registry-command"), 1
        )
        self.assertEqual(
            manifest_publisher.count("releasectl.py registry-login"), 3
        )
        self.assertEqual(
            manifest_publisher.count("releasectl.py registry-command"), 5
        )
        self.assertEqual(
            manifest_publisher.count("releasectl.py registry-digest"), 4
        )
        for workflow in (architecture_publisher, manifest_publisher):
            self.assertNotIn("docker/login-action", workflow)
            self.assertNotRegex(workflow, r"(?m)^\s+docker push ")

    def test_every_release_registry_login_has_a_final_logout(self):
        workflow_dir = (
            pathlib.Path(__file__).resolve().parents[2]
            / ".github"
            / "workflows"
        )
        job_pattern = re.compile(
            r"(?ms)^  ([a-z][a-z0-9-]+):\n(.*?)(?=^  [a-z][a-z0-9-]+:\n|\Z)"
        )
        login_pattern = re.compile(
            r"(?m)^      - name: Log in to registry(?: for candidate pull)?\n"
            r"        id: ([a-z][a-z0-9_]*)$"
        )
        logout_pattern = re.compile(
            r"(?m)^      - name: Log out of registry\n"
            r"        if: \$\{\{ always\(\) && steps\.([a-z][a-z0-9_]*)"
            r"\.outcome == 'success' \}\}$"
        )
        paired_login_ids = []

        for workflow_name in self.PUBLISHER_WORKFLOWS:
            workflow = (workflow_dir / workflow_name).read_text(encoding="utf-8")
            for job_name, job in job_pattern.findall(workflow):
                login_calls = job.count("releasectl.py registry-login")
                if login_calls == 0:
                    self.assertNotIn("docker logout", job)
                    continue
                with self.subTest(workflow=workflow_name, job=job_name):
                    login_ids = login_pattern.findall(job)
                    logout_ids = logout_pattern.findall(job)
                    self.assertEqual(login_calls, 1)
                    self.assertEqual(login_ids, logout_ids)
                    self.assertEqual(len(login_ids), 1)
                    self.assertEqual(job.count('docker logout "$REGISTRY"'), 1)
                    self.assertTrue(
                        job.rstrip().endswith('docker logout "$REGISTRY"')
                    )
                    paired_login_ids.extend(login_ids)

        self.assertEqual(
            set(paired_login_ids),
            {
                "candidate_registry_login",
                "architecture_acceptance_registry_login",
                "manifest_candidate_registry_login",
                "index_acceptance_registry_login",
                "promotion_registry_login",
            },
        )
        self.assertEqual(len(paired_login_ids), 5)

    def test_write_permissions_and_operations_are_confined_to_release_graph(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        workflow_dir = root / ".github" / "workflows"
        release_workflows = {
            name.replace(".yml", "-release.yml")
            for name in self.CORE_WORKFLOWS
        }
        write_capable = set()
        for path in workflow_dir.glob("*.yml"):
            content = path.read_text(encoding="utf-8")
            if "id-token: write" in content or "packages: write" in content:
                write_capable.add(path.name)
        self.assertEqual(
            write_capable, release_workflows | self.PUBLISHER_WORKFLOWS
        )

        read_only_graph = self.CORE_WORKFLOWS | {
            "image-contracts.yml",
            "reusable-build-debian-image.yml",
            "reusable-prepare-image-matrix.yml",
            "reusable-aggregate-image-contract.yml",
        }
        for name in read_only_graph:
            with self.subTest(workflow=name):
                content = (workflow_dir / name).read_text(encoding="utf-8")
                self.assertNotIn("id-token: write", content)
                self.assertNotIn("packages: write", content)

        write_operations = (
            "releasectl.py registry-login",
            "releasectl.py registry-push",
            "docker push ",
            "cosign sign ",
            "docker buildx imagetools create ",
        )
        operation_workflows = set()
        for path in workflow_dir.glob("*.yml"):
            content = path.read_text(encoding="utf-8")
            if any(operation in content for operation in write_operations):
                operation_workflows.add(path.name)
        self.assertEqual(operation_workflows, self.PUBLISHER_WORKFLOWS)

        for name in self.CORE_WORKFLOWS:
            with self.subTest(reusable_only=name):
                content = (workflow_dir / name).read_text(encoding="utf-8")
                self.assertNotIn("workflow_dispatch:", content)
                self.assertNotIn("branches:", content)
                self.assertNotIn("reusable-publish", content)
                self.assertIn("export_image:", content)

        build_workflow = (
            workflow_dir / "reusable-build-debian-image.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("Export fully tested image for release", build_workflow)
        self.assertIn("Capture image identity used by tests", build_workflow)
        self.assertIn('--expected-image-id "$TESTED_IMAGE_ID"', build_workflow)
        self.assertIn("actions/upload-artifact@", build_workflow)
        self.assertIn(
            "name: image-release-archive--${{ inputs.image_name }}--${{ inputs.image_version }}--${{ inputs.debian_suite }}--${{ inputs.debian_arch }}--attempt-${{ github.run_attempt }}",
            build_workflow,
        )
        self.assertIn(
            "artifact-name: sbom-${{ inputs.image_name }}-${{ inputs.image_version }}-${{ inputs.debian_suite }}-${{ inputs.debian_arch }}-attempt-${{ github.run_attempt }}",
            build_workflow,
        )
        self.assertNotIn("docker push ", build_workflow)
        self.assertNotIn("cosign sign ", build_workflow)

        publisher = (
            workflow_dir / "reusable-publish-tested-image.yml"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "name: image-release-archive--${{ inputs.image_name }}--${{ matrix.version }}--${{ matrix.debian_suite }}--${{ matrix.debian_arch }}--attempt-${{ github.run_attempt }}",
            publisher,
        )
        self.assertIn(
            "name: image-release-digest--${{ inputs.image_name }}--${{ matrix.version }}--${{ matrix.debian_suite }}--${{ matrix.debian_arch }}--attempt-${{ github.run_attempt }}",
            publisher,
        )
        self.assertIn("Reject newer release inputs on main", publisher)
        self.assertIn("fetch-depth: 0", publisher)
        self.assertIn("git merge-base --is-ancestor", publisher)
        self.assertIn("git log --format= --name-only --no-renames", publisher)
        manifest_call = publisher.split("\n  publish-manifest:", 1)[1]
        self.assertIn("\n      actions: read", manifest_call)
        manifest_publisher = (
            workflow_dir / "reusable-publish-image-manifest.yml"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "Reject newer release inputs on main", manifest_publisher
        )
        self.assertIn("fetch-depth: 0", manifest_publisher)
        self.assertIn("git merge-base --is-ancestor", manifest_publisher)
        self.assertIn(
            "git log --format= --name-only --no-renames", manifest_publisher
        )
        self.assertIn(
            "pattern: image-release-digest--${{ inputs.image_name }}--${{ inputs.image_version }}--${{ inputs.debian_suite }}--*--attempt-${{ github.run_attempt }}",
            manifest_publisher,
        )
        self.assertNotIn("source_tags", manifest_publisher)
        download_step = publisher.split(
            "uses: actions/download-artifact@", 1
        )[1].split("\n      - name:", 1)[0]
        self.assertNotIn("github-token:", download_step)
        self.assertNotIn("repository:", download_step)
        self.assertNotIn("run-id:", download_step)

        for name in release_workflows:
            with self.subTest(release_wrapper=name):
                content = (workflow_dir / name).read_text(encoding="utf-8")
                family = name.removesuffix("-image-release.yml").removesuffix(
                    "-images-release.yml"
                )
                path_lines = content.split("\n    paths:\n", 1)[1].split(
                    "\n  workflow_dispatch:", 1
                )[0]
                release_paths = {
                    line.strip().removeprefix("- ")
                    for line in path_lines.splitlines()
                    if line.strip().startswith("- ")
                }
                common_prefix_paths = {
                    f"{prefix.rstrip('/')}/**"
                    for prefix in releasectl.COMMON_RELEASE_PREFIXES
                }
                expected_paths = releasectl.COMMON_RELEASE_PATHS | common_prefix_paths | {
                    f".github/workflows/{name}",
                    f".github/workflows/{name.replace('-release.yml', '.yml')}",
                    f"images/{family}/**",
                    f"tests/functional/{family}/**",
                }
                self.assertEqual(release_paths, expected_paths)
                release_build, release_publish = content.split(
                    "\n  release_publish:", 1
                )
                release_build = release_build.split("\n  release_build:", 1)[1]
                self.assertIn("export_image: true", release_build)
                self.assertNotIn("id-token: write", release_build)
                self.assertNotIn("packages: write", release_build)
                self.assertIn("id-token: write", release_publish)
                self.assertIn("packages: write", release_publish)
                self.assertNotIn("secrets: inherit", release_publish)
                self.assertIn(
                    "uses: ./.github/workflows/reusable-publish-tested-image.yml",
                    release_publish,
                )

    def test_every_reusable_workflow_call_declares_permissions(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        workflow_dir = root / ".github" / "workflows"
        reusable_calls = 0
        discovered_calls = 0
        for path in workflow_dir.glob("*.yml"):
            content = path.read_text(encoding="utf-8")
            discovered_calls += sum(
                line.startswith("    uses: ./.github/workflows/")
                for line in content.splitlines()
            )
            if "\njobs:\n" not in content:
                continue
            job_lines = content.split("\njobs:\n", 1)[1].splitlines()
            blocks = []
            current = []
            for line in job_lines:
                if line and not line.startswith(" "):
                    break
                if line.startswith("  ") and not line.startswith("    "):
                    if current:
                        blocks.append("\n".join(current))
                    current = [line]
                elif current:
                    current.append(line)
            if current:
                blocks.append("\n".join(current))

            for block in blocks:
                if "\n    uses: ./.github/workflows/" not in block:
                    continue
                reusable_calls += 1
                with self.subTest(workflow=path.name, job=block.split(":", 1)[0].strip()):
                    self.assertIn("\n    permissions:", block)
        self.assertGreater(discovered_calls, 0)
        self.assertEqual(reusable_calls, discovered_calls)


if __name__ == "__main__":
    unittest.main()
