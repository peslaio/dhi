#!/usr/bin/env ruby
# frozen_string_literal: true

require "json"
require "optparse"
require "yaml"

class RenderAssertionError < StandardError; end

def assert(condition, message)
  raise RenderAssertionError, message unless condition
end

begin
  options = {
    openshift: false,
    network_policy: false
  }

  OptionParser.new do |parser|
    parser.on("--file PATH") { |value| options[:file] = value }
    parser.on("--expected-repository REF") { |value| options[:expected_repository] = value }
    parser.on("--expected-image REF") { |value| options[:expected_image] = value }
    parser.on("--openshift") { options[:openshift] = true }
    parser.on("--network-policy") { options[:network_policy] = true }
  end.parse!

  assert(ARGV.empty?, "unexpected arguments: #{ARGV.join(' ')}")
  assert(options[:file], "--file is required")
  assert(options[:expected_repository] || options[:expected_image], "an expected image or repository is required")
  assert(!(options[:expected_repository] && options[:expected_image]), "expected image and repository are mutually exclusive")

documents = File.read(options[:file]).split(/^---\s*$\n?/).each_with_object([]) do |source, parsed|
  next if source.strip.empty?

  document = YAML.safe_load(
    source,
    permitted_classes: [],
    permitted_symbols: [],
    aliases: false,
    filename: options[:file]
  )
  parsed << document unless document.nil?
end

workloads = documents.select { |document| %w[Deployment StatefulSet].include?(document["kind"]) }
assert(workloads.length == 1, "render must contain exactly one Deployment or StatefulSet")

workload = workloads.first
pod_spec = workload.dig("spec", "template", "spec")
assert(pod_spec.is_a?(Hash), "workload has no Pod spec")
assert(pod_spec["automountServiceAccountToken"] == false, "Pod must disable service-account token automount")

containers = pod_spec["containers"]
assert(containers.is_a?(Array) && !containers.empty?, "Pod must contain at least one container")
container = containers.first
image = container["image"]
assert(image.is_a?(String) && !image.empty?, "primary container image must be non-empty")

if options[:expected_image]
  assert(image == options[:expected_image], "image #{image.inspect} does not equal #{options[:expected_image].inspect}")
else
  prefix = "#{options[:expected_repository]}:"
  assert(image.start_with?(prefix), "image #{image.inspect} is not tagged from #{options[:expected_repository].inspect}")
  assert(!image.include?("@"), "default render must use a tag, not a digest")
end

security_context = container["securityContext"]
assert(security_context.is_a?(Hash), "primary container must declare a security context")
assert(security_context["runAsNonRoot"] == true, "primary container must require non-root execution")
assert(security_context["allowPrivilegeEscalation"] == false, "primary container must disable privilege escalation")
assert(Array(security_context.dig("capabilities", "drop")).include?("ALL"), "primary container must drop all capabilities")

pod_security_context = pod_spec["securityContext"] || {}
assert(pod_security_context.dig("seccompProfile", "type") == "RuntimeDefault", "Pod must use RuntimeDefault seccomp")

if options[:openshift]
  assert(!security_context.key?("runAsUser"), "OpenShift render must not pin runAsUser")
  assert(!security_context.key?("runAsGroup"), "OpenShift render must not pin runAsGroup")
  assert(!pod_security_context.key?("fsGroup"), "OpenShift render must not pin fsGroup")
else
  assert(security_context["runAsUser"] == 10_001, "default render must use UID 10001")
  assert(security_context["runAsGroup"] == 0, "default render must use GID 0")
end

service_accounts = documents.select { |document| document["kind"] == "ServiceAccount" }
service_accounts.each do |service_account|
  assert(service_account["automountServiceAccountToken"] == false, "ServiceAccount must disable token automount")
end

network_policies = documents.select { |document| document["kind"] == "NetworkPolicy" }
if options[:network_policy]
  assert(network_policies.length == 1, "NetworkPolicy render must contain exactly one NetworkPolicy")
else
  assert(network_policies.empty?, "default render must not add an undeclared NetworkPolicy")
end

puts JSON.generate(
  "status" => "pass",
  "workloadKind" => workload["kind"],
  "image" => image,
  "openshift" => options[:openshift],
  "networkPolicy" => options[:network_policy]
)
rescue Errno::ENOENT, Psych::Exception, RenderAssertionError => e
  warn "chart render assertion failed: #{e.message}"
  exit 1
end
