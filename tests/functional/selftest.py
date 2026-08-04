#!/usr/bin/env python3
"""Fast, daemon-free negative tests for the functional contract control plane."""

import copy
import io
import json
import pathlib
import subprocess
import tempfile
import types
import unittest
from unittest import mock

import fixturectl
import result as contract_result


IMAGE_ID = "sha256:" + ("a" * 64)


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
                "state": "exited",
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
        "State": {"Status": "exited", "ExitCode": 0, "OOMKilled": False},
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
            "State": "exited",
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


class FixtureLockTests(unittest.TestCase):
    def test_lock_is_strict_and_digest_pinned(self):
        fixtures = fixturectl.load_lock()
        self.assertEqual(set(fixtures), fixturectl.EXPECTED_FIXTURES)


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


if __name__ == "__main__":
    unittest.main()
