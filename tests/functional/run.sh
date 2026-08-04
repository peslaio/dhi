#!/usr/bin/env bash
set -uo pipefail

readonly EXIT_INVALID=2
readonly EXIT_ASSERTION=10
readonly EXIT_READINESS=11
readonly EXIT_IDENTITY=12
readonly EXIT_TIMEOUT=13
readonly EXIT_INFRASTRUCTURE=14
readonly EXIT_EVIDENCE_CLEANUP=15

if [ "$#" -ne 4 ]; then
  echo "usage: $0 <image-name> <image-ref> <image-version> <platform>" >&2
  exit "$EXIT_INVALID"
fi

image_name="$1"
image_ref="$2"
image_version="$3"
platform="$4"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
result_helper="$script_dir/result.py"
timeout_helper="$script_dir/timeout.py"
fixture_helper="$script_dir/fixturectl.py"
lifecycle_helper="$script_dir/lifecyclectl.py"
suite_relative="tests/functional/${image_name}"

started_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
started_epoch="$(date '+%s')"
run_id="${DHI_RUN_ID:-local-$(date -u '+%Y%m%dT%H%M%SZ')-$$-${RANDOM}}"
run_token_base="$(printf '%s' "$run_id" | tr '[:upper:]' '[:lower:]' | tr -c '[:alnum:]' '-')"
run_token_base="${run_token_base#-}"
run_token_base="${run_token_base%-}"
run_token_base="${run_token_base:0:28}"
[ -n "$run_token_base" ] || run_token_base="run"
run_token="${run_token_base}-$$-${RANDOM}"

artifact_root="${DHI_FUNCTIONAL_ARTIFACT_DIR:-${RUNNER_TEMP:-${TMPDIR:-/tmp}}/dhi-functional}"
if ! mkdir -p "$artifact_root"; then
  echo "Unable to create functional evidence root: $artifact_root" >&2
  exit "$EXIT_INFRASTRUCTURE"
fi
artifact_root="$(cd "$artifact_root" && pwd)"
artifact_dir="$artifact_root/$run_token"
if ! mkdir "$artifact_dir"; then
  echo "Unable to create unique functional evidence directory: $artifact_dir" >&2
  exit "$EXIT_INFRASTRUCTURE"
fi
mkdir -p "$artifact_dir/containers"
rm -f "$artifact_dir/result.json" "$artifact_dir/identity.json"
: >"$artifact_dir/warnings.txt"
: >"$artifact_dir/secondary-failures.txt"
: >"$artifact_dir/cleanup-residuals.txt"
printf '[]\n' >"$artifact_dir/compose-ps.json"

outcome_status="fail"
outcome_classification="infrastructure_failure"
outcome_phase="bootstrap"
outcome_exit_code="$EXIT_INFRASTRUCTURE"
outcome_raw_exit_code=""
outcome_message="functional runner terminated unexpectedly"

project=""
source_tag=""
derived_tag=""
expected_image_id=""
container_image_id=""
image_os=""
image_arch=""
image_variant=""
identity_mode=""
sut_service=""
test_service=""
timeout_seconds=""
build_timeout_seconds="${DHI_FUNCTIONAL_BUILD_TIMEOUT_SECONDS:-600}"
cleanup_timeout_seconds="${DHI_FUNCTIONAL_CLEANUP_TIMEOUT_SECONDS:-30}"
cleanup_status="not-started"
docker_available=false
compose_initialized=false
containers_created=false
evidence_failed=false
cleanup_failed=false
finalizing=false
service_names=()
fixture_names=()
compose=()

warning() {
  printf '%s\n' "$1" >>"$artifact_dir/warnings.txt"
  printf 'warning: %s\n' "$1" >&2
}

secondary_failure() {
  printf '%s\n' "$1" >>"$artifact_dir/secondary-failures.txt"
}

fail_run() {
  outcome_exit_code="$1"
  outcome_classification="$2"
  outcome_phase="$3"
  outcome_message="$4"
  outcome_raw_exit_code="${5:-}"
  outcome_status="fail"
  exit "$outcome_exit_code"
}

run_logged() {
  local deadline="$1"
  local log_file="$2"
  shift 2
  "$timeout_helper" --timeout "$deadline" --kill-after 10 -- "$@" 2>&1 | tee "$log_file"
  local statuses=("${PIPESTATUS[@]}")
  if [ "${statuses[1]}" -ne 0 ]; then
    return 125
  fi
  return "${statuses[0]}"
}

run_bounded() {
  local deadline="$1"
  shift
  "$timeout_helper" --timeout "$deadline" --kill-after 5 -- "$@"
}

run_cleanup_bounded() {
  run_bounded "$cleanup_timeout_seconds" "$@"
}

capture_evidence() {
  [ "$containers_created" = true ] || return 0

  if ! "$timeout_helper" --timeout "$cleanup_timeout_seconds" --kill-after 5 -- \
    "${compose[@]}" logs --no-color --timestamps >"$artifact_dir/compose.log" 2>&1; then
    evidence_failed=true
    secondary_failure "failed to capture Compose logs"
  fi

  if ! "$timeout_helper" --timeout "$cleanup_timeout_seconds" --kill-after 5 -- \
    "${compose[@]}" ps --all --format json >"$artifact_dir/compose-ps.json" 2>"$artifact_dir/compose-ps.error.log"; then
    evidence_failed=true
    secondary_failure "failed to capture Compose service state"
    printf '[]\n' >"$artifact_dir/compose-ps.json"
  fi

  local service container_id
  for service in "${service_names[@]}"; do
    if ! container_id="$(run_cleanup_bounded "${compose[@]}" ps --all --quiet "$service" 2>/dev/null | head -n 1)"; then
      evidence_failed=true
      secondary_failure "failed to resolve service container: $service"
      continue
    fi
    [ -n "$container_id" ] || continue
    if ! run_cleanup_bounded docker inspect "$container_id" >"$artifact_dir/containers/${service}.json" 2>"$artifact_dir/containers/${service}.error.log"; then
      evidence_failed=true
      secondary_failure "failed to inspect service container: $service"
    fi
  done
}

record_residuals() {
  local output resource
  if ! output="$(run_cleanup_bounded docker ps --all --quiet --filter "label=com.docker.compose.project=${project}" 2>>"$artifact_dir/cleanup.log")"; then
    cleanup_failed=true
  else
    while IFS= read -r resource; do
      [ -n "$resource" ] && printf 'container:%s\n' "$resource" >>"$artifact_dir/cleanup-residuals.txt"
    done <<<"$output"
  fi

  if ! output="$(run_cleanup_bounded docker network ls --quiet --filter "label=com.docker.compose.project=${project}" 2>>"$artifact_dir/cleanup.log")"; then
    cleanup_failed=true
  else
    while IFS= read -r resource; do
      [ -n "$resource" ] && printf 'network:%s\n' "$resource" >>"$artifact_dir/cleanup-residuals.txt"
    done <<<"$output"
  fi

  if ! output="$(run_cleanup_bounded docker volume ls --quiet --filter "label=com.docker.compose.project=${project}" 2>>"$artifact_dir/cleanup.log")"; then
    cleanup_failed=true
  else
    while IFS= read -r resource; do
      [ -n "$resource" ] && printf 'volume:%s\n' "$resource" >>"$artifact_dir/cleanup-residuals.txt"
    done <<<"$output"
  fi

  if [ -s "$artifact_dir/cleanup-residuals.txt" ]; then
    cleanup_failed=true
  fi
}

cleanup_resources() {
  [ "$docker_available" = true ] || return 0
  cleanup_status="success"
  : >"$artifact_dir/cleanup.log"

  if [ "$compose_initialized" = true ]; then
    if ! "$timeout_helper" --timeout "$cleanup_timeout_seconds" --kill-after 5 -- \
      "${compose[@]}" down --volumes --remove-orphans --rmi local --timeout 10 \
      >>"$artifact_dir/cleanup.log" 2>&1; then
      cleanup_failed=true
    fi
  fi

  local image_tag remove_status inspect_status inspect_output
  for image_tag in "$derived_tag" "$source_tag"; do
    [ -n "$image_tag" ] || continue
    run_cleanup_bounded docker image rm "$image_tag" >>"$artifact_dir/cleanup.log" 2>&1
    remove_status=$?
    if [ "$remove_status" -eq 0 ]; then
      continue
    elif [ "$remove_status" -eq 124 ]; then
      cleanup_failed=true
      secondary_failure "timed out removing local functional image alias: $image_tag"
      continue
    fi

    inspect_output="$(run_cleanup_bounded docker image inspect "$image_tag" 2>&1)"
    inspect_status=$?
    printf '%s\n' "$inspect_output" >>"$artifact_dir/cleanup.log"
    if [ "$inspect_status" -eq 1 ] && [[ "$inspect_output" =~ [Nn]o[[:space:]]such[[:space:]](image|object) ]]; then
      continue
    elif [ "$inspect_status" -eq 124 ]; then
      cleanup_failed=true
      secondary_failure "timed out verifying removal of local functional image alias: $image_tag"
    else
      cleanup_failed=true
      secondary_failure "failed to remove or verify absence of local functional image alias: $image_tag"
    fi
  done

  if [ -n "$project" ]; then
    record_residuals
  fi
  if [ "$cleanup_failed" = true ]; then
    cleanup_status="failure"
  fi
}

emit_result() {
  local finished_at finished_epoch duration_ms
  finished_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  finished_epoch="$(date '+%s')"
  duration_ms="$(( (finished_epoch - started_epoch) * 1000 ))"

  export DHI_RESULT_ARTIFACT_DIR="$artifact_dir"
  export DHI_RESULT_LEG_ID="${image_name}:${image_version}:${platform}"
  export DHI_RESULT_RUN_ID="$run_id"
  export DHI_RESULT_PROJECT="$project"
  export DHI_RESULT_STARTED_AT="$started_at"
  export DHI_RESULT_FINISHED_AT="$finished_at"
  export DHI_RESULT_DURATION_MS="$duration_ms"
  export DHI_RESULT_TIMEOUT_SECONDS="$timeout_seconds"
  export DHI_RESULT_BUILD_TIMEOUT_SECONDS="$build_timeout_seconds"
  export DHI_RESULT_FAMILY="$image_name"
  export DHI_RESULT_VERSION="$image_version"
  export DHI_RESULT_PLATFORM="$platform"
  export DHI_RESULT_SUITE="$suite_relative"
  export DHI_RESULT_SUT_SERVICE="$sut_service"
  export DHI_RESULT_TEST_SERVICE="$test_service"
  export DHI_RESULT_REQUESTED_REF="$image_ref"
  export DHI_RESULT_SOURCE_ALIAS="$source_tag"
  export DHI_RESULT_EXPECTED_ID="$expected_image_id"
  export DHI_RESULT_CONTAINER_IMAGE_ID="$container_image_id"
  export DHI_RESULT_IMAGE_OS="$image_os"
  export DHI_RESULT_IMAGE_ARCH="$image_arch"
  export DHI_RESULT_IMAGE_VARIANT="$image_variant"
  export DHI_RESULT_IDENTITY_MODE="$identity_mode"
  export DHI_RESULT_STATUS="$outcome_status"
  export DHI_RESULT_CLASSIFICATION="$outcome_classification"
  export DHI_RESULT_PHASE="$outcome_phase"
  export DHI_RESULT_EXIT_CODE="$outcome_exit_code"
  export DHI_RESULT_RAW_EXIT_CODE="$outcome_raw_exit_code"
  export DHI_RESULT_MESSAGE="$outcome_message"
  export DHI_RESULT_CLEANUP_STATUS="$cleanup_status"

  run_bounded "$cleanup_timeout_seconds" \
    python3 "$result_helper" emit --output "$artifact_dir/result.json"
}

finalize() {
  local incoming_exit="$1"
  [ "$finalizing" = false ] || return
  finalizing=true
  trap - EXIT INT TERM
  set +u

  if [ "$outcome_exit_code" -eq "$EXIT_INFRASTRUCTURE" ] && [ "$incoming_exit" -ne 0 ] && [ -z "$outcome_raw_exit_code" ]; then
    outcome_raw_exit_code="$incoming_exit"
  fi

  capture_evidence
  cleanup_resources

  if [ "$evidence_failed" = true ] || [ "$cleanup_failed" = true ]; then
    if [ "$outcome_status" = "pass" ]; then
      outcome_status="fail"
      outcome_classification="evidence_cleanup_failure"
      outcome_phase="cleanup"
      outcome_exit_code="$EXIT_EVIDENCE_CLEANUP"
      outcome_message="functional assertions passed, but evidence capture or cleanup failed"
    else
      secondary_failure "evidence capture or cleanup failed"
    fi
  fi

  emit_result
  emit_status=$?
  if [ ! -f "$artifact_dir/result.json" ]; then
    echo "Failed to emit canonical functional result JSON in $artifact_dir" >&2
    outcome_exit_code="$EXIT_EVIDENCE_CLEANUP"
  elif ! run_bounded "$cleanup_timeout_seconds" \
    python3 "$result_helper" validate "$artifact_dir/result.json"; then
    echo "Emitted functional result is invalid: $artifact_dir/result.json" >&2
    outcome_exit_code="$EXIT_EVIDENCE_CLEANUP"
  else
    if [ "$emit_status" -ne 0 ]; then
      echo "Functional evidence invalidated the candidate result (helper exit $emit_status)" >&2
      outcome_exit_code="$EXIT_EVIDENCE_CLEANUP"
    fi
    echo "Functional result: $artifact_dir/result.json"
  fi
  exit "$outcome_exit_code"
}

on_signal() {
  local signal_code="$1"
  local signal_name="$2"
  outcome_status="fail"
  outcome_classification="interrupted"
  outcome_phase="execution"
  outcome_exit_code="$signal_code"
  outcome_raw_exit_code="$signal_code"
  outcome_message="functional runner interrupted by ${signal_name}"
  exit "$signal_code"
}

if ! command -v python3 >/dev/null 2>&1; then
  fail_run "$EXIT_INFRASTRUCTURE" infrastructure_failure preflight "python3 is required by the functional runner"
fi
if [ ! -f "$result_helper" ] || [ ! -f "$timeout_helper" ] || [ ! -f "$fixture_helper" ] || [ ! -f "$lifecycle_helper" ]; then
  fail_run "$EXIT_INFRASTRUCTURE" infrastructure_failure preflight "functional runner helper files are missing"
fi
if ! [[ "$image_name" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
  fail_run "$EXIT_INVALID" invalid_invocation preflight "invalid image family: $image_name"
fi
if [ -z "$image_ref" ] || [ -z "$image_version" ]; then
  fail_run "$EXIT_INVALID" invalid_invocation preflight "image reference and version must be non-empty"
fi
if ! [[ "$platform" =~ ^linux/(amd64|arm64)(/[^/]+)?$ ]]; then
  fail_run "$EXIT_INVALID" invalid_invocation preflight "unsupported functional-test platform: $platform"
fi
if ! [[ "$build_timeout_seconds" =~ ^[1-9][0-9]*$ ]] || ! [[ "$cleanup_timeout_seconds" =~ ^[1-9][0-9]*$ ]]; then
  fail_run "$EXIT_INVALID" invalid_invocation preflight "functional timeout settings must be positive integers"
fi

suite_dir="$script_dir/$image_name"
compose_file="$suite_dir/compose.yaml"
if [ ! -f "$compose_file" ]; then
  fail_run "$EXIT_INVALID" invalid_invocation preflight "No functional contract exists for ${image_name}: ${suite_relative}/compose.yaml"
fi

trap 'finalize $?' EXIT
trap 'on_signal 130 SIGINT' INT
trap 'on_signal 143 SIGTERM' TERM

if [ -n "${DHI_FUNCTIONAL_EXEC_TIMEOUT_SECONDS:-}" ]; then
  timeout_seconds="$DHI_FUNCTIONAL_EXEC_TIMEOUT_SECONDS"
elif [ -f "$script_dir/contractctl.rb" ]; then
  metadata_output="$artifact_dir/metadata-timeout.txt"
  metadata_error="$artifact_dir/metadata-error.log"
  if ! "$timeout_helper" --timeout 30 --kill-after 5 -- \
    ruby "$script_dir/contractctl.rb" resolve \
    --name "$image_name" --version "$image_version" --platform "$platform" \
    --field timeout_seconds >"$metadata_output" 2>"$metadata_error"; then
    fail_run "$EXIT_INFRASTRUCTURE" infrastructure_failure metadata "contract metadata could not resolve timeout_seconds"
  fi
  timeout_seconds="$(tr -d '[:space:]' <"$metadata_output")"
else
  timeout_seconds=300
  warning "contractctl.rb is unavailable; using the 300s compatibility timeout"
fi
if ! [[ "$timeout_seconds" =~ ^[1-9][0-9]*$ ]] || [ "$timeout_seconds" -gt 3600 ]; then
  timeout_seconds=""
  fail_run "$EXIT_INFRASTRUCTURE" infrastructure_failure metadata "resolved timeout_seconds must be an integer from 1 to 3600"
fi

assertion_contract="$artifact_dir/assertion-contract.json"
assertion_contract_error="$artifact_dir/assertion-contract.error.log"
if [ ! -f "$script_dir/contractctl.rb" ]; then
  fail_run "$EXIT_INFRASTRUCTURE" infrastructure_failure metadata "contractctl.rb is required to resolve the assertion contract"
fi
if ! "$timeout_helper" --timeout 30 --kill-after 5 -- \
  ruby "$script_dir/contractctl.rb" resolve \
  --name "$image_name" --version "$image_version" --platform "$platform" \
  --field assertion_contract >"$assertion_contract" 2>"$assertion_contract_error"; then
  fail_run "$EXIT_INFRASTRUCTURE" infrastructure_failure metadata "contract metadata could not resolve assertion_contract"
fi

if ! python3 "$fixture_helper" validate >"$artifact_dir/fixture-validation.json" 2>"$artifact_dir/fixture-validation.log"; then
  fail_run "$EXIT_INFRASTRUCTURE" infrastructure_failure fixture-metadata "functional fixture lock is invalid"
fi
if ! cp "$script_dir/fixtures.lock.json" "$artifact_dir/fixtures.lock.json"; then
  fail_run "$EXIT_INFRASTRUCTURE" infrastructure_failure fixture-metadata "functional fixture lock could not be copied to evidence"
fi
if ! fixture_python="$(python3 "$fixture_helper" resolve harness-python 2>>"$artifact_dir/fixture-validation.log")" || \
   ! fixture_java="$(python3 "$fixture_helper" resolve java-builder 2>>"$artifact_dir/fixture-validation.log")" || \
   ! fixture_nginx="$(python3 "$fixture_helper" resolve php-nginx 2>>"$artifact_dir/fixture-validation.log")"; then
  fail_run "$EXIT_INFRASTRUCTURE" infrastructure_failure fixture-metadata "functional fixture references could not be resolved"
fi
fixture_dotnet=""
case "$image_name" in
  dotnet-aspnet|dotnet-runtime)
    if ! fixture_dotnet="$(python3 "$fixture_helper" resolve "dotnet-sdk-${image_version}" 2>>"$artifact_dir/fixture-validation.log")"; then
      fail_run "$EXIT_INFRASTRUCTURE" infrastructure_failure fixture-metadata "no pinned .NET SDK fixture exists for ${image_version}"
    fi
    ;;
esac

safe_family="${image_name:0:20}"
project_token="${run_token: -12}"
project_token="${project_token#-}"
project="dhi-${safe_family}-${project_token}"
source_tag="localhost/dhi-functional-source/${image_name}:${run_token}"
derived_tag="localhost/dhi-functional-derived/${image_name}:${run_token}"

if ! command -v docker >/dev/null 2>&1; then
  fail_run "$EXIT_INFRASTRUCTURE" infrastructure_failure preflight "docker is required by the functional runner"
fi
run_bounded 30 docker info >"$artifact_dir/docker-info.log" 2>&1
docker_status=$?
if [ "$docker_status" -eq 124 ]; then
  fail_run "$EXIT_TIMEOUT" timeout preflight "Docker daemon probe exceeded 30s" "$docker_status"
elif [ "$docker_status" -ne 0 ]; then
  fail_run "$EXIT_INFRASTRUCTURE" infrastructure_failure preflight "Docker daemon is unavailable"
fi
docker_available=true
run_bounded 30 docker compose version >"$artifact_dir/compose-version.log" 2>&1
compose_version_status=$?
if [ "$compose_version_status" -eq 124 ]; then
  fail_run "$EXIT_TIMEOUT" timeout preflight "Docker Compose version probe exceeded 30s" "$compose_version_status"
elif [ "$compose_version_status" -ne 0 ]; then
  fail_run "$EXIT_INFRASTRUCTURE" infrastructure_failure preflight "Docker Compose v2 is unavailable"
fi

run_bounded 30 docker image inspect "$image_ref" >"$artifact_dir/source-image.inspect.json" 2>"$artifact_dir/source-image.error.log"
source_inspect_status=$?
if [ "$source_inspect_status" -eq 124 ]; then
  fail_run "$EXIT_TIMEOUT" timeout image-resolution "source image inspection exceeded 30s" "$source_inspect_status"
elif [ "$source_inspect_status" -ne 0 ]; then
  fail_run "$EXIT_INFRASTRUCTURE" infrastructure_failure image-resolution "image reference does not exist in the local Docker image store: $image_ref"
fi
source_info="$(python3 "$result_helper" source-info \
  --inspect "$artifact_dir/source-image.inspect.json" --platform "$platform" \
  2>"$artifact_dir/source-image-validation.log")"
source_info_status=$?
if [ "$source_info_status" -ne 0 ]; then
  fail_run "$EXIT_IDENTITY" identity_failure image-resolution "source image identity or platform is invalid" "$source_info_status"
fi
read -r expected_image_id image_os image_arch image_variant <<<"$source_info"
[ "$image_variant" != "-" ] || image_variant=""

run_bounded 30 docker image tag "$expected_image_id" "$source_tag" >"$artifact_dir/source-tag.log" 2>&1
source_tag_status=$?
if [ "$source_tag_status" -eq 124 ]; then
  fail_run "$EXIT_TIMEOUT" timeout image-resolution "source image alias creation exceeded 30s" "$source_tag_status"
elif [ "$source_tag_status" -ne 0 ]; then
  fail_run "$EXIT_INFRASTRUCTURE" infrastructure_failure image-resolution "failed to create unique local source alias"
fi
alias_id="$(run_bounded 30 docker image inspect "$source_tag" --format '{{.Id}}' 2>>"$artifact_dir/source-tag.log")"
alias_status=$?
if [ "$alias_status" -eq 124 ]; then
  fail_run "$EXIT_TIMEOUT" timeout image-resolution "source alias verification exceeded 30s" "$alias_status"
elif [ "$alias_status" -ne 0 ]; then
  fail_run "$EXIT_INFRASTRUCTURE" infrastructure_failure image-resolution "failed to inspect the local source alias" "$alias_status"
fi
if [ "$alias_id" != "$expected_image_id" ]; then
  fail_run "$EXIT_IDENTITY" identity_failure image-resolution "local source alias does not resolve to the expected image ID"
fi

export DHI_IMAGE_UNDER_TEST="$source_tag"
export DHI_IMAGE_VERSION="$image_version"
export DHI_PLATFORM="$platform"
export DHI_SOURCE_IMAGE_ID="$expected_image_id"
export DHI_DERIVED_IMAGE="$derived_tag"
export DHI_FIXTURE_PYTHON_IMAGE="$fixture_python"
export DHI_FIXTURE_JAVA_BUILDER_IMAGE="$fixture_java"
export DHI_FIXTURE_NGINX_IMAGE="$fixture_nginx"
export DHI_FIXTURE_DOTNET_SDK_IMAGE="$fixture_dotnet"

compose=(docker compose --ansi never --project-name "$project" --file "$compose_file")
compose_initialized=true
run_bounded 30 "${compose[@]}" config >"$artifact_dir/compose-config.yaml" 2>"$artifact_dir/compose-config.error.log"
compose_config_status=$?
if [ "$compose_config_status" -eq 124 ]; then
  fail_run "$EXIT_TIMEOUT" timeout compose-validation "Compose contract rendering exceeded 30s" "$compose_config_status"
elif [ "$compose_config_status" -ne 0 ]; then
  fail_run "$EXIT_INFRASTRUCTURE" infrastructure_failure compose-validation "Compose contract failed to render"
fi
run_bounded 30 "${compose[@]}" config --format json >"$artifact_dir/compose-config.json" 2>>"$artifact_dir/compose-config.error.log"
compose_json_status=$?
if [ "$compose_json_status" -eq 124 ]; then
  fail_run "$EXIT_TIMEOUT" timeout compose-validation "Compose JSON rendering exceeded 30s" "$compose_json_status"
elif [ "$compose_json_status" -ne 0 ]; then
  fail_run "$EXIT_INFRASTRUCTURE" infrastructure_failure compose-validation "Compose contract JSON failed to render"
fi

contract_info="$(python3 "$result_helper" check-compose \
  --config "$artifact_dir/compose-config.json" \
  --source-alias "$source_tag" --expected-id "$expected_image_id" \
  --platform "$platform" 2>"$artifact_dir/compose-policy.log")"
contract_info_status=$?
if [ "$contract_info_status" -ne 0 ]; then
  fail_run "$EXIT_INFRASTRUCTURE" infrastructure_failure compose-validation "Compose contract violates the functional runner policy" "$contract_info_status"
fi
read -r sut_service test_service identity_mode <<<"$contract_info"
service_output="$(run_bounded 30 "${compose[@]}" config --services 2>>"$artifact_dir/compose-config.error.log")"
service_output_status=$?
if [ "$service_output_status" -eq 124 ]; then
  fail_run "$EXIT_TIMEOUT" timeout compose-validation "Compose service discovery exceeded 30s" "$service_output_status"
elif [ "$service_output_status" -ne 0 ]; then
  fail_run "$EXIT_INFRASTRUCTURE" infrastructure_failure compose-validation "Compose service discovery failed" "$service_output_status"
fi
while IFS= read -r service; do
  [ -n "$service" ] && service_names+=("$service")
done <<<"$service_output"

if grep -Fq -- "$fixture_python" "$artifact_dir/compose-config.json"; then
  fixture_names+=(harness-python)
fi
if grep -Fq -- "$fixture_java" "$artifact_dir/compose-config.json"; then
  fixture_names+=(java-builder)
fi
if grep -Fq -- "$fixture_nginx" "$artifact_dir/compose-config.json"; then
  fixture_names+=(php-nginx)
fi
if [ -n "$fixture_dotnet" ] && grep -Fq -- "$fixture_dotnet" "$artifact_dir/compose-config.json"; then
  fixture_names+=("dotnet-sdk-${image_version}")
fi

if [ "${#fixture_names[@]}" -gt 0 ]; then
  python3 "$fixture_helper" pull --platform "$platform" "${fixture_names[@]}" 2>&1 \
    | tee "$artifact_dir/fixture-pull.log"
  fixture_pull_statuses=("${PIPESTATUS[@]}")
  if [ "${fixture_pull_statuses[1]}" -ne 0 ]; then
    fail_run "$EXIT_INFRASTRUCTURE" infrastructure_failure fixture-pull "failed to persist fixture pull output" "${fixture_pull_statuses[1]}"
  elif [ "${fixture_pull_statuses[0]}" -ne 0 ]; then
    fail_run "$EXIT_INFRASTRUCTURE" infrastructure_failure fixture-pull "digest-pinned functional fixture pull failed after bounded retries" "${fixture_pull_statuses[0]}"
  fi
fi

run_logged "$build_timeout_seconds" "$artifact_dir/compose-build.log" \
  "${compose[@]}" build --pull=false
build_status=$?
if [ "$build_status" -eq 124 ]; then
  fail_run "$EXIT_TIMEOUT" timeout build "Compose fixture build exceeded ${build_timeout_seconds}s" "$build_status"
elif [ "$build_status" -eq 125 ]; then
  fail_run "$EXIT_INFRASTRUCTURE" infrastructure_failure build "failed to persist Compose build output" "$build_status"
elif [ "$build_status" -ne 0 ]; then
  fail_run "$EXIT_READINESS" setup_readiness_failure build "Compose fixture or derived SUT build failed" "$build_status"
fi

alias_id="$(run_bounded 30 docker image inspect "$source_tag" --format '{{.Id}}' 2>>"$artifact_dir/source-tag.log")"
alias_status=$?
if [ "$alias_status" -eq 124 ]; then
  fail_run "$EXIT_TIMEOUT" timeout build "post-build source alias verification exceeded 30s" "$alias_status"
elif [ "$alias_status" -ne 0 ]; then
  fail_run "$EXIT_IDENTITY" identity_failure build "source alias disappeared during Compose build" "$alias_status"
fi
if [ "$alias_id" != "$expected_image_id" ]; then
  fail_run "$EXIT_IDENTITY" identity_failure build "source alias changed during Compose build"
fi

containers_created=true
run_logged 120 "$artifact_dir/compose-create.log" \
  "${compose[@]}" create --no-build --pull never --force-recreate
create_status=$?
if [ "$create_status" -eq 124 ]; then
  fail_run "$EXIT_TIMEOUT" timeout create "Compose create exceeded 120s" "$create_status"
elif [ "$create_status" -eq 125 ]; then
  fail_run "$EXIT_INFRASTRUCTURE" infrastructure_failure create "failed to persist Compose create output" "$create_status"
elif [ "$create_status" -ne 0 ]; then
  fail_run "$EXIT_READINESS" setup_readiness_failure create "Compose could not create the functional topology" "$create_status"
fi

sut_container_ids="$(run_bounded 30 "${compose[@]}" ps --all --quiet "$sut_service" 2>"$artifact_dir/sut-container.error.log")"
sut_lookup_status=$?
if [ "$sut_lookup_status" -eq 124 ]; then
  fail_run "$EXIT_TIMEOUT" timeout identity "SUT container lookup exceeded 30s" "$sut_lookup_status"
elif [ "$sut_lookup_status" -ne 0 ]; then
  fail_run "$EXIT_INFRASTRUCTURE" infrastructure_failure identity "failed to query the declared SUT container" "$sut_lookup_status"
fi
sut_container_id="${sut_container_ids%%$'\n'*}"
if [ -z "$sut_container_id" ]; then
  fail_run "$EXIT_INFRASTRUCTURE" infrastructure_failure identity "Compose did not create the declared SUT container"
fi
run_bounded 30 docker inspect "$sut_container_id" >"$artifact_dir/sut-container.inspect.json" 2>>"$artifact_dir/sut-container.error.log"
sut_inspect_status=$?
if [ "$sut_inspect_status" -eq 124 ]; then
  fail_run "$EXIT_TIMEOUT" timeout identity "SUT container inspection exceeded 30s" "$sut_inspect_status"
elif [ "$sut_inspect_status" -ne 0 ]; then
  fail_run "$EXIT_INFRASTRUCTURE" infrastructure_failure identity "failed to inspect the created SUT container"
fi
container_image_id="$(run_bounded 30 docker inspect "$sut_container_id" --format '{{.Image}}' 2>>"$artifact_dir/sut-container.error.log")"
container_image_status=$?
if [ "$container_image_status" -eq 124 ]; then
  fail_run "$EXIT_TIMEOUT" timeout identity "SUT image ID inspection exceeded 30s" "$container_image_status"
elif [ "$container_image_status" -ne 0 ] || [ -z "$container_image_id" ]; then
  fail_run "$EXIT_INFRASTRUCTURE" infrastructure_failure identity "failed to resolve the SUT container image ID" "$container_image_status"
fi
run_bounded 30 docker image inspect "$container_image_id" >"$artifact_dir/sut-image.inspect.json" 2>"$artifact_dir/sut-image.error.log"
sut_image_status=$?
if [ "$sut_image_status" -eq 124 ]; then
  fail_run "$EXIT_TIMEOUT" timeout identity "SUT image inspection exceeded 30s" "$sut_image_status"
elif [ "$sut_image_status" -ne 0 ]; then
  fail_run "$EXIT_INFRASTRUCTURE" infrastructure_failure identity "failed to inspect the SUT container image"
fi
if ! python3 "$result_helper" verify-identity \
  --mode "$identity_mode" --expected-id "$expected_image_id" --platform "$platform" \
  --source-inspect "$artifact_dir/source-image.inspect.json" \
  --container-inspect "$artifact_dir/sut-container.inspect.json" \
  --sut-image-inspect "$artifact_dir/sut-image.inspect.json" \
  --output "$artifact_dir/identity.json" >"$artifact_dir/identity.log" 2>&1; then
  fail_run "$EXIT_IDENTITY" identity_failure identity "created SUT failed image identity proof"
fi

lifecycle_watchdog_seconds=$((timeout_seconds + 30))
run_logged "$lifecycle_watchdog_seconds" "$artifact_dir/compose-up.log" \
  python3 "$lifecycle_helper" \
  --compose-file "$compose_file" \
  --project "$project" \
  --family "$image_name" \
  --version "$image_version" \
  --platform "$platform" \
  --sut-service "$sut_service" \
  --test-service "$test_service" \
  --source-image-id "$expected_image_id" \
  --sut-image-id "$container_image_id" \
  --assertion-contract "$assertion_contract" \
  --timeout "$timeout_seconds" \
  --output "$artifact_dir/lifecycle.json"
compose_status=$?
outcome_raw_exit_code="$compose_status"
if [ "$compose_status" -eq 13 ] || [ "$compose_status" -eq 124 ]; then
  fail_run "$EXIT_TIMEOUT" timeout execution "functional contract exceeded ${timeout_seconds}s" "$compose_status"
elif [ "$compose_status" -eq 125 ]; then
  fail_run "$EXIT_INFRASTRUCTURE" infrastructure_failure execution "failed to persist Compose execution output" "$compose_status"
fi

test_container_ids="$(run_bounded 30 "${compose[@]}" ps --all --quiet "$test_service" 2>>"$artifact_dir/compose-ps.error.log")"
test_lookup_status=$?
if [ "$test_lookup_status" -eq 124 ]; then
  fail_run "$EXIT_TIMEOUT" timeout execution "test container lookup exceeded 30s" "$test_lookup_status"
elif [ "$test_lookup_status" -ne 0 ]; then
  fail_run "$EXIT_INFRASTRUCTURE" infrastructure_failure execution "failed to query the test container" "$test_lookup_status"
fi
test_container_id="${test_container_ids%%$'\n'*}"
test_state=""
test_exit_code=""
if [ -n "$test_container_id" ]; then
  test_state_record="$(run_bounded 30 docker inspect "$test_container_id" --format '{{.State.Status}} {{.State.ExitCode}}' 2>>"$artifact_dir/compose-ps.error.log")"
  test_inspect_status=$?
  if [ "$test_inspect_status" -eq 124 ]; then
    fail_run "$EXIT_TIMEOUT" timeout execution "test result inspection exceeded 30s" "$test_inspect_status"
  elif [ "$test_inspect_status" -ne 0 ]; then
    fail_run "$EXIT_INFRASTRUCTURE" infrastructure_failure execution "failed to inspect the test result" "$test_inspect_status"
  fi
  read -r test_state test_exit_code <<<"$test_state_record"
fi

if [ "$test_state" != "exited" ]; then
  fail_run "$EXIT_READINESS" setup_readiness_failure execution "test container did not terminate normally (state: ${test_state:-unavailable})" "$compose_status"
fi

alias_id="$(run_bounded 30 docker image inspect "$source_tag" --format '{{.Id}}' 2>>"$artifact_dir/source-tag.log")"
alias_status=$?
if [ "$alias_status" -eq 124 ]; then
  fail_run "$EXIT_TIMEOUT" timeout execution "post-execution source alias verification exceeded 30s" "$alias_status"
elif [ "$alias_status" -ne 0 ]; then
  fail_run "$EXIT_IDENTITY" identity_failure execution "source alias disappeared during contract execution" "$alias_status"
fi
if [ "$alias_id" != "$expected_image_id" ]; then
  fail_run "$EXIT_IDENTITY" identity_failure execution "source alias changed during contract execution" "$compose_status"
fi

case "$test_exit_code" in
  0)
    case "$compose_status" in
      0) ;;
      10)
        fail_run "$EXIT_ASSERTION" assertion_failure lifecycle "application or restart assertion failed" "$compose_status"
        ;;
      11)
        fail_run "$EXIT_READINESS" setup_readiness_failure lifecycle "SUT lifecycle or restart readiness failed" "$compose_status"
        ;;
      13)
        fail_run "$EXIT_TIMEOUT" timeout lifecycle "functional lifecycle exceeded ${timeout_seconds}s" "$compose_status"
        ;;
      14)
        fail_run "$EXIT_INFRASTRUCTURE" infrastructure_failure lifecycle "functional lifecycle controller failed" "$compose_status"
        ;;
      *)
        fail_run "$EXIT_INFRASTRUCTURE" infrastructure_failure lifecycle "functional lifecycle returned an unexpected status" "$compose_status"
        ;;
    esac
    ;;
  1|10)
    fail_run "$EXIT_ASSERTION" assertion_failure execution "application contract assertion failed" "$test_exit_code"
    ;;
  11|126|127)
    fail_run "$EXIT_READINESS" setup_readiness_failure execution "SUT setup or readiness failed" "$test_exit_code"
    ;;
  14)
    fail_run "$EXIT_INFRASTRUCTURE" infrastructure_failure execution "functional verifier infrastructure failed" "$test_exit_code"
    ;;
  "")
    fail_run "$EXIT_INFRASTRUCTURE" infrastructure_failure execution "test container state is unavailable" "$compose_status"
    ;;
  *)
    fail_run "$EXIT_READINESS" setup_readiness_failure execution "functional topology terminated before a valid verifier result" "$test_exit_code"
    ;;
esac

outcome_status="pass"
outcome_classification="pass"
outcome_phase="complete"
outcome_exit_code=0
outcome_raw_exit_code=0
outcome_message="Functional contract passed: ${image_name} ${image_version} ${platform}"
echo "$outcome_message"
exit 0
