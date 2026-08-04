#!/usr/bin/env ruby
# frozen_string_literal: true

require "json"
require "open3"
require "optparse"
require "set"
require "yaml"

module DhiContracts
  ROOT = File.expand_path("../..", __dir__)
  IMAGES_DIR = File.join(ROOT, "images")
  FUNCTIONAL_DIR = File.join(ROOT, "tests", "functional")
  FIXTURE_CTL = File.join(FUNCTIONAL_DIR, "fixturectl.py")
  FIXTURE_LOCK = File.join(FUNCTIONAL_DIR, "fixtures.lock.json")

  SCHEMA_VERSION = 1
  EXPECTED_SPEC_COUNT = 20
  EXPECTED_SUITE_COUNT = 16
  EXPECTED_LEG_COUNT = 35
  SUPPORTED_ARCHITECTURES = %w[amd64 arm64].freeze
  ARCHITECTURE_ORDER = SUPPORTED_ARCHITECTURES.each_with_index.to_h.freeze
  CONTRACT_KEYS = %w[schemaVersion timeoutSeconds].freeze

  SPEC_KEYS = %w[
    name version profile base repositories packages user paths files environment
    entrypoint cmd ports hardening oci
  ].freeze
  REQUIRED_SPEC_KEYS = %w[name version profile base packages user paths cmd hardening oci].freeze
  BASE_KEYS = %w[distribution suite architectures mirror securityMirror variant].freeze
  REPOSITORY_KEYS = %w[name key source].freeze
  PACKAGE_KEYS = %w[install remove].freeze
  USER_KEYS = %w[name uid gid home shell].freeze
  PATH_KEYS = %w[path owner mode].freeze
  FILE_KEYS = %w[source destination owner mode].freeze
  HARDENING_KEYS = %w[
    removeApt removeDpkg cleanAptCache cleanDocs cleanManPages cleanLogs cleanTmp
    runAsNonRoot openshiftCompatible
  ].freeze
  OCI_KEYS = %w[registry namespace image tag].freeze

  class ContractError < StandardError; end

  module_function

  def assert(condition, message)
    raise ContractError, message unless condition
  end

  def relative(path)
    expanded = File.expand_path(path)
    prefix = ROOT + File::SEPARATOR
    expanded.start_with?(prefix) ? expanded.delete_prefix(prefix) : path
  end

  def read_yaml(path)
    contents = File.read(path)
    YAML.safe_load(
      contents,
      permitted_classes: [],
      permitted_symbols: [],
      aliases: false,
      filename: relative(path)
    )
  rescue Errno::ENOENT => e
    raise ContractError, e.message
  rescue Psych::Exception => e
    raise ContractError, "#{relative(path)} is not valid safe YAML: #{e.message}"
  end

  def strict_mapping(value, context, allowed_keys, required_keys)
    assert(value.is_a?(Hash), "#{context} must be a mapping")
    assert(value.keys.all? { |key| key.is_a?(String) }, "#{context} keys must be strings")

    unknown = value.keys - allowed_keys
    missing = required_keys - value.keys
    assert(unknown.empty?, "#{context} has unknown keys: #{unknown.sort.join(', ')}")
    assert(missing.empty?, "#{context} is missing required keys: #{missing.sort.join(', ')}")
    value
  end

  def string(value, context, allow_empty: false)
    assert(value.is_a?(String), "#{context} must be a string")
    assert(allow_empty || !value.empty?, "#{context} must not be empty")
    value
  end

  def integer(value, context)
    assert(value.is_a?(Integer), "#{context} must be an integer")
    value
  end

  def boolean(value, context)
    assert(value == true || value == false, "#{context} must be a boolean")
    value
  end

  def owner(value, context)
    valid = (value.is_a?(String) && !value.empty?) || (value.is_a?(Integer) && value >= 0)
    assert(valid, "#{context} must be a non-empty owner string or a non-negative integer")
    value
  end

  def string_array(value, context, allow_empty: false)
    assert(value.is_a?(Array), "#{context} must be an array")
    assert(allow_empty || !value.empty?, "#{context} must not be empty")
    value.each_with_index do |item, index|
      string(item, "#{context}[#{index}]")
    end
    value
  end

  def validate_image_spec(path)
    context = relative(path)
    raw = strict_mapping(read_yaml(path), context, SPEC_KEYS, REQUIRED_SPEC_KEYS)

    name = string(raw["name"], "#{context}.name")
    version = string(raw["version"], "#{context}.version")
    profile = string(raw["profile"], "#{context}.profile")
    assert(name.match?(/\A[a-z0-9]+(?:-[a-z0-9]+)*\z/), "#{context}.name is not a canonical family name")
    assert(version.match?(/\A[0-9A-Za-z][0-9A-Za-z._+-]*\z/), "#{context}.version is not canonical")
    assert(profile == "runtime", "#{context}.profile must be runtime")

    base = strict_mapping(raw["base"], "#{context}.base", BASE_KEYS, BASE_KEYS)
    BASE_KEYS.each do |key|
      next if key == "architectures"
      string(base[key], "#{context}.base.#{key}")
    end
    assert(base["distribution"] == "debian", "#{context}.base.distribution must be debian")

    architectures = string_array(base["architectures"], "#{context}.base.architectures")
    assert(architectures.uniq.length == architectures.length, "#{context}.base.architectures contains duplicates")
    unsupported = architectures - SUPPORTED_ARCHITECTURES
    assert(unsupported.empty?, "#{context}.base.architectures has unsupported values: #{unsupported.join(', ')}")

    packages = strict_mapping(raw["packages"], "#{context}.packages", PACKAGE_KEYS, PACKAGE_KEYS)
    string_array(packages["install"], "#{context}.packages.install")
    string_array(packages["remove"], "#{context}.packages.remove", allow_empty: true)

    user = strict_mapping(raw["user"], "#{context}.user", USER_KEYS, USER_KEYS)
    string(user["name"], "#{context}.user.name")
    integer(user["uid"], "#{context}.user.uid")
    integer(user["gid"], "#{context}.user.gid")
    string(user["home"], "#{context}.user.home")
    string(user["shell"], "#{context}.user.shell")

    assert(raw["paths"].is_a?(Array) && !raw["paths"].empty?, "#{context}.paths must be a non-empty array")
    raw["paths"].each_with_index do |item, index|
      item_context = "#{context}.paths[#{index}]"
      path_entry = strict_mapping(item, item_context, PATH_KEYS, PATH_KEYS)
      string(path_entry["path"], "#{item_context}.path")
      owner(path_entry["owner"], "#{item_context}.owner")
      string(path_entry["mode"], "#{item_context}.mode")
    end

    if raw.key?("files")
      assert(raw["files"].is_a?(Array), "#{context}.files must be an array")
      raw["files"].each_with_index do |item, index|
        item_context = "#{context}.files[#{index}]"
        file_entry = strict_mapping(item, item_context, FILE_KEYS, FILE_KEYS)
        string(file_entry["source"], "#{item_context}.source")
        string(file_entry["destination"], "#{item_context}.destination")
        owner(file_entry["owner"], "#{item_context}.owner")
        string(file_entry["mode"], "#{item_context}.mode")
      end
    end

    if raw.key?("repositories")
      assert(raw["repositories"].is_a?(Array), "#{context}.repositories must be an array")
      raw["repositories"].each_with_index do |item, index|
        item_context = "#{context}.repositories[#{index}]"
        repository = strict_mapping(item, item_context, REPOSITORY_KEYS, REPOSITORY_KEYS)
        REPOSITORY_KEYS.each { |key| string(repository[key], "#{item_context}.#{key}") }
      end
    end

    if raw.key?("environment")
      environment = raw["environment"]
      assert(environment.is_a?(Hash), "#{context}.environment must be a mapping")
      environment.each do |key, value|
        string(key, "#{context}.environment key")
        string(value, "#{context}.environment.#{key}")
      end
    end

    %w[entrypoint cmd].each do |key|
      next unless raw.key?(key)
      string_array(raw[key], "#{context}.#{key}")
    end

    if raw.key?("ports")
      assert(raw["ports"].is_a?(Array) && !raw["ports"].empty?, "#{context}.ports must be a non-empty array")
      raw["ports"].each_with_index do |port, index|
        integer(port, "#{context}.ports[#{index}]")
        assert(port.between?(1, 65_535), "#{context}.ports[#{index}] is outside 1..65535")
      end
    end

    hardening = strict_mapping(raw["hardening"], "#{context}.hardening", HARDENING_KEYS, HARDENING_KEYS)
    HARDENING_KEYS.each { |key| boolean(hardening[key], "#{context}.hardening.#{key}") }

    oci = strict_mapping(raw["oci"], "#{context}.oci", OCI_KEYS, OCI_KEYS)
    OCI_KEYS.each do |key|
      string(oci[key], "#{context}.oci.#{key}", allow_empty: key == "namespace")
    end

    suite = base["suite"]
    assert(oci["image"] == name, "#{context}.oci.image must equal name")
    assert(oci["tag"] == "#{version}-#{suite}", "#{context}.oci.tag must equal <version>-<suite>")

    image_relative = path.delete_prefix(IMAGES_DIR + File::SEPARATOR)
    directories = File.dirname(image_relative).split(File::SEPARATOR)
    assert(directories.length.between?(1, 2), "#{context} must be images/<name>/image.yaml or images/<name>/<version>/image.yaml")
    assert(directories.first == name, "#{context} directory must match spec name #{name}")
    if directories.length == 2
      assert(directories.last == version, "#{context} version directory must match spec version #{version}")
    end

    {
      path: path,
      relative_path: context,
      name: name,
      version: version,
      debian_suite: suite,
      architectures: architectures
    }
  end

  def validate_contract(path, family)
    context = relative(path)
    raw = strict_mapping(read_yaml(path), context, CONTRACT_KEYS, CONTRACT_KEYS)
    integer(raw["schemaVersion"], "#{context}.schemaVersion")
    assert(raw["schemaVersion"] == SCHEMA_VERSION, "#{context}.schemaVersion must be #{SCHEMA_VERSION}")
    timeout = integer(raw["timeoutSeconds"], "#{context}.timeoutSeconds")
    assert(timeout.between?(60, 1_800), "#{context}.timeoutSeconds must be between 60 and 1800")

    {
      name: family,
      path: path,
      compose_path: File.join(File.dirname(path), "compose.yaml"),
      timeout_seconds: timeout
    }
  end

  def natural_version_key(version)
    version.scan(/\d+|\D+/).map do |part|
      part.match?(/\A\d+\z/) ? [0, part.to_i] : [1, part]
    end
  end

  def spec_sort_key(spec)
    [spec[:name], natural_version_key(spec[:version]), spec[:debian_suite], spec[:relative_path]]
  end

  def leg_sort_key(leg)
    [
      leg[:name],
      natural_version_key(leg[:version]),
      leg[:debian_suite],
      ARCHITECTURE_ORDER.fetch(leg[:debian_arch])
    ]
  end

  def leg_id(leg)
    "#{leg[:name]}:#{leg[:version]}:#{leg[:platform]}"
  end

  def load_catalog(enforce_counts: true)
    spec_paths = Dir.glob(File.join(IMAGES_DIR, "**", "image.yaml")).sort
    assert(!spec_paths.empty?, "no image specs found below #{relative(IMAGES_DIR)}")
    specs = spec_paths.map { |path| validate_image_spec(path) }.sort_by { |spec| spec_sort_key(spec) }

    spec_keys = Set.new
    specs.each do |spec|
      key = [spec[:name], spec[:version], spec[:debian_suite]]
      assert(spec_keys.add?(key), "duplicate image spec identity: #{key.join(':')}")
    end

    contracts = {}
    contract_paths = Dir.glob(File.join(FUNCTIONAL_DIR, "*", "contract.yaml")).sort
    contract_paths.each do |contract_path|
      family = File.basename(File.dirname(contract_path))
      assert(family.match?(/\A[a-z0-9]+(?:-[a-z0-9]+)*\z/), "invalid functional suite directory name: #{family}")
      compose_path = File.join(FUNCTIONAL_DIR, family, "compose.yaml")
      assert(File.file?(compose_path), "functional suite #{family} is missing #{relative(compose_path)}")
      contracts[family] = validate_contract(contract_path, family)
    end

    families = specs.map { |spec| spec[:name] }.uniq.sort
    missing_contracts = families - contracts.keys
    orphan_contracts = contracts.keys - families
    assert(missing_contracts.empty?, "image families without contracts: #{missing_contracts.join(', ')}")
    assert(orphan_contracts.empty?, "orphan functional contracts: #{orphan_contracts.join(', ')}")

    legs = []
    specs.each do |spec|
      contract = contracts.fetch(spec[:name])
      spec[:architectures].each do |architecture|
        legs << {
          spec: spec[:relative_path],
          name: spec[:name],
          version: spec[:version],
          debian_suite: spec[:debian_suite],
          debian_arch: architecture,
          platform: "linux/#{architecture}",
          timeout_seconds: contract[:timeout_seconds]
        }
      end
    end
    legs.sort_by! { |leg| leg_sort_key(leg) }

    leg_ids = Set.new
    legs.each do |leg|
      id = leg_id(leg)
      assert(leg_ids.add?(id), "duplicate contract leg: #{id}")
    end

    if enforce_counts
      assert(specs.length == EXPECTED_SPEC_COUNT, "expected #{EXPECTED_SPEC_COUNT} image specs, found #{specs.length}")
      assert(contracts.length == EXPECTED_SUITE_COUNT, "expected #{EXPECTED_SUITE_COUNT} functional suites, found #{contracts.length}")
      assert(legs.length == EXPECTED_LEG_COUNT, "expected #{EXPECTED_LEG_COUNT} contract legs, found #{legs.length}")
    end

    { specs: specs, contracts: contracts, legs: legs }
  end

  def safe_tag_component(value)
    value.downcase.gsub(/[^a-z0-9_.-]+/, "-").gsub(/\A[-.]+|[-.]+\z/, "")
  end

  def fixture_references
    @fixture_references ||= begin
      lock = JSON.parse(File.read(FIXTURE_LOCK))
      fixtures = lock["fixtures"]
      assert(fixtures.is_a?(Hash), "fixtures.lock.json has no fixtures mapping")
      fixtures.each_with_object({}) do |(name, fixture), references|
        reference = fixture.is_a?(Hash) ? fixture["reference"] : nil
        assert(reference.is_a?(String) && !reference.empty?, "fixture #{name} has no reference")
        references[name] = reference
      end
    rescue Errno::ENOENT, JSON::ParserError => e
      raise ContractError, "cannot read fixtures.lock.json: #{e.message}"
    end
  end

  def validate_fixture_lock
    stdout, stderr, status = Open3.capture3(
      "python3", FIXTURE_CTL, "validate", chdir: ROOT
    )
    assert(status.success?, "fixture lock validation failed: #{stderr.strip}")
    JSON.parse(stdout)
  rescue JSON::ParserError => e
    raise ContractError, "fixture validator returned invalid JSON: #{e.message}"
  end

  def render_compose(catalog, leg)
    contract = catalog[:contracts].fetch(leg[:name])
    source_tag = [leg[:name], leg[:version], leg[:debian_arch]].map { |value| safe_tag_component(value) }.join("-")
    source_ref = "local/dhi-contract-source:#{source_tag}"
    source_id = "sha256:#{'0' * 64}"
    project = "dhi-contract-#{source_tag}".gsub(/[^a-z0-9_-]+/, "-")
    fixtures = fixture_references
    dotnet_fixture = ""
    if %w[dotnet-aspnet dotnet-runtime].include?(leg[:name])
      dotnet_fixture_name = "dotnet-sdk-#{leg[:version]}"
      assert(fixtures.key?(dotnet_fixture_name), "no pinned fixture exists for #{dotnet_fixture_name}")
      dotnet_fixture = fixtures.fetch(dotnet_fixture_name)
    end
    environment = {
      "DHI_IMAGE_UNDER_TEST" => source_ref,
      "DHI_IMAGE_VERSION" => leg[:version],
      "DHI_PLATFORM" => leg[:platform],
      "DHI_SOURCE_IMAGE_ID" => source_id,
      "DHI_DERIVED_IMAGE" => "local/dhi-contract-derived:#{source_tag}",
      "DHI_FIXTURE_PYTHON_IMAGE" => fixtures.fetch("harness-python"),
      "DHI_FIXTURE_JAVA_BUILDER_IMAGE" => fixtures.fetch("java-builder"),
      "DHI_FIXTURE_NGINX_IMAGE" => fixtures.fetch("php-nginx"),
      "DHI_FIXTURE_DOTNET_SDK_IMAGE" => dotnet_fixture
    }
    command = [
      "docker", "compose",
      "--project-name", project,
      "--file", contract[:compose_path],
      "config", "--format", "json"
    ]
    stdout, stderr, status = Open3.capture3(environment, *command, chdir: ROOT)
    assert(status.success?, "compose render failed for #{leg_id(leg)}: #{stderr.strip}")

    begin
      rendered = JSON.parse(stdout)
    rescue JSON::ParserError => e
      raise ContractError, "compose render returned invalid JSON for #{leg_id(leg)}: #{e.message}"
    end

    services = rendered["services"]
    assert(services.is_a?(Hash), "compose render for #{leg_id(leg)} has no services mapping")
    app = services["app"]
    test = services["test"]
    assert(app.is_a?(Hash), "compose render for #{leg_id(leg)} has no app service")
    assert(test.is_a?(Hash), "compose render for #{leg_id(leg)} has no test service")
    roles = Hash.new { |hash, key| hash[key] = [] }
    services.each do |service_name, service|
      assert(service.is_a?(Hash), "service #{service_name} for #{leg_id(leg)} must be an object")
      assert(service["pull_policy"] == "never", "service #{service_name} for #{leg_id(leg)} must set pull_policy: never")
      labels = service["labels"]
      assert(labels.is_a?(Hash), "service #{service_name} for #{leg_id(leg)} must declare functional role labels")
      role = labels["io.pesla.dhi.functional.role"]
      assert(%w[sut test fixture].include?(role), "service #{service_name} for #{leg_id(leg)} has an invalid functional role")
      roles[role] << service_name
    end
    assert(roles["sut"] == ["app"], "compose for #{leg_id(leg)} must label app as the only sut")
    assert(roles["test"] == ["test"], "compose for #{leg_id(leg)} must label test as the only test service")

    assert(app["platform"] == leg[:platform], "app platform for #{leg_id(leg)} must be #{leg[:platform]}")

    direct_source = app["image"] == source_ref
    build_source = app.dig("build", "args", "RUNTIME_IMAGE") == source_ref
    assert(direct_source || build_source, "app for #{leg_id(leg)} does not consume the exact local source image")
    identity_mode = app.dig("labels", "io.pesla.dhi.functional.identity-mode")
    assert(%w[exact-container-image derived-rootfs-prefix].include?(identity_mode), "app for #{leg_id(leg)} has an invalid identity mode")
    if identity_mode == "exact-container-image"
      assert(direct_source, "app for #{leg_id(leg)} must use the exact source image for exact-container-image identity")
    else
      assert(build_source, "app for #{leg_id(leg)} must pass the source image as RUNTIME_IMAGE for derived-rootfs-prefix identity")
      assert(app.dig("build", "args", "DHI_SOURCE_IMAGE_ID") == source_id, "app for #{leg_id(leg)} must bind DHI_SOURCE_IMAGE_ID for derived identity")
    end

    restart_policy = test["restart"]
    assert(restart_policy.nil? || restart_policy == "no", "test for #{leg_id(leg)} must be a terminating service")
    has_verdict_command = !test["command"].nil? || !test["entrypoint"].nil?
    assert(has_verdict_command, "test for #{leg_id(leg)} must define a terminating command or entrypoint")
  end

  def build_row(leg)
    {
      "name" => leg[:name],
      "version" => leg[:version],
      "debian_suite" => leg[:debian_suite],
      "debian_arch" => leg[:debian_arch],
      "platform" => leg[:platform],
      "timeout_seconds" => leg[:timeout_seconds]
    }
  end

  def command_validate(_arguments)
    catalog = load_catalog
    validate_fixture_lock
    catalog[:legs].each { |leg| render_compose(catalog, leg) }
    puts JSON.generate(
      "schemaVersion" => SCHEMA_VERSION,
      "specs" => catalog[:specs].length,
      "suites" => catalog[:contracts].length,
      "legs" => catalog[:legs].length,
      "status" => "pass"
    )
    true
  end

  def parse_matrix_options(arguments)
    options = {}
    parser = OptionParser.new do |opts|
      opts.on("--name FAMILY") { |value| options[:name] = value }
      opts.on("--kind KIND") { |value| options[:kind] = value }
    end
    parser.parse!(arguments)
    assert(arguments.empty?, "unexpected matrix arguments: #{arguments.join(' ')}")
    assert(options[:name], "matrix requires --name FAMILY")
    assert(%w[build manifest].include?(options[:kind]), "matrix requires --kind build|manifest")
    options
  end

  def command_matrix(arguments)
    options = parse_matrix_options(arguments)
    catalog = load_catalog
    assert(catalog[:contracts].key?(options[:name]), "unknown image family: #{options[:name]}")

    rows = if options[:kind] == "build"
             catalog[:legs].select { |leg| leg[:name] == options[:name] }.map { |leg| build_row(leg) }
           else
             catalog[:specs].select { |spec| spec[:name] == options[:name] }.map do |spec|
               {
                 "name" => spec[:name],
                 "version" => spec[:version],
                 "debian_suite" => spec[:debian_suite],
                 "debian_arches" => spec[:architectures].sort_by { |arch| ARCHITECTURE_ORDER.fetch(arch) }.join(" "),
                 "timeout_seconds" => catalog[:contracts].fetch(spec[:name])[:timeout_seconds]
               }
             end
           end
    puts JSON.generate("include" => rows)
    true
  end

  def parse_resolve_options(arguments)
    options = {}
    parser = OptionParser.new do |opts|
      opts.on("--name NAME") { |value| options[:name] = value }
      opts.on("--version VERSION") { |value| options[:version] = value }
      opts.on("--platform PLATFORM") { |value| options[:platform] = value }
      opts.on("--field FIELD") { |value| options[:field] = value }
    end
    parser.parse!(arguments)
    assert(arguments.empty?, "unexpected resolve arguments: #{arguments.join(' ')}")
    %i[name version platform].each { |key| assert(options[key], "resolve requires --#{key} VALUE") }
    if options[:field]
      assert(options[:field] == "timeout_seconds", "resolve --field only supports timeout_seconds")
    end
    options
  end

  def command_resolve(arguments)
    options = parse_resolve_options(arguments)
    catalog = load_catalog
    matches = catalog[:legs].select do |leg|
      leg[:name] == options[:name] &&
        leg[:version] == options[:version] &&
        leg[:platform] == options[:platform]
    end
    assert(matches.length == 1, "undeclared or ambiguous contract leg: #{options[:name]}:#{options[:version]}:#{options[:platform]}")
    leg = matches.first

    if options[:field]
      puts leg[:timeout_seconds]
    else
      row = { "legId" => leg_id(leg) }.merge(build_row(leg))
      puts JSON.generate(row)
    end
    true
  end

  def normalize_changed_path(path)
    value = path.strip
    value = value.delete_prefix("./")
    expanded = File.expand_path(value, ROOT)
    root_prefix = ROOT + File::SEPARATOR
    expanded.start_with?(root_prefix) ? expanded.delete_prefix(root_prefix) : value
  end

  def read_changed_files(path)
    contents = path == "-" ? $stdin.read : File.read(path)
    contents.lines.map { |line| normalize_changed_path(line) }.reject(&:empty?).uniq
  rescue Errno::ENOENT => e
    raise ContractError, e.message
  end

  def family_for_workflow(path, families)
    basename = File.basename(path)
    families.find do |family|
      ["#{family}-image.yml", "#{family}-image.yaml", "#{family}-images.yml", "#{family}-images.yaml"].include?(basename)
    end
  end

  def documentation_only_path?(path)
    path == ".gitignore" ||
      path == "LICENSE" ||
      path.end_with?(".md") ||
      path.start_with?("docs/") ||
      path.start_with?("charts/")
  end

  def plan_for_files(catalog, paths)
    families = catalog[:contracts].keys.sort
    selected = Set.new
    select_all = false

    paths.each do |path|
      if path.start_with?("images/")
        remainder = path.delete_prefix("images/")
        if !remainder.include?(File::SEPARATOR)
          select_all = true
          next
        end
        family = remainder.split(File::SEPARATOR, 2).first
        assert(families.include?(family), "changed image path references unknown family: #{path}")
        selected.add(family)
      elsif path.start_with?("tests/functional/")
        remainder = path.delete_prefix("tests/functional/")
        if !remainder.include?(File::SEPARATOR)
          select_all = true
          next
        end
        family = remainder.split(File::SEPARATOR, 2).first
        if family == "harness"
          select_all = true
        else
          assert(families.include?(family), "changed functional path references unknown family: #{path}")
          selected.add(family)
        end
      elsif path.start_with?(".github/workflows/")
        workflow_family = family_for_workflow(path, families)
        if workflow_family
          selected.add(workflow_family)
        elsif !%w[helm-charts.yml helm-charts.yaml].include?(File.basename(path))
          select_all = true
        end
      elsif !documentation_only_path?(path)
        select_all = true
      end
    end

    selected = Set.new(families) if select_all
    selected_families = selected.to_a.sort
    expected_ids = catalog[:legs].select { |leg| selected.include?(leg[:name]) }.map { |leg| leg_id(leg) }
    {
      "schemaVersion" => SCHEMA_VERSION,
      "selectedFamilies" => selected_families,
      "expectedLegIds" => expected_ids
    }
  end

  def command_plan(arguments)
    options = {}
    parser = OptionParser.new do |opts|
      opts.on("--files FILE") { |value| options[:files] = value }
    end
    parser.parse!(arguments)
    assert(arguments.empty?, "unexpected plan arguments: #{arguments.join(' ')}")
    assert(options[:files], "plan requires --files FILE")

    catalog = load_catalog
    puts JSON.generate(plan_for_files(catalog, read_changed_files(options[:files])))
    true
  end

  def expected_from_plan(path, catalog)
    data = JSON.parse(File.read(path))
    assert(data.is_a?(Hash), "plan #{path} must be a JSON object")
    expected_keys = %w[expectedLegIds schemaVersion selectedFamilies]
    assert(data.keys.sort == expected_keys, "plan #{path} keys must be exactly #{expected_keys.join(', ')}")
    assert(data["schemaVersion"] == SCHEMA_VERSION, "plan #{path} has unsupported schemaVersion")

    known_families = catalog[:contracts].keys.sort
    selected = data["selectedFamilies"]
    assert(selected.is_a?(Array), "plan #{path}.selectedFamilies must be an array")
    assert(selected.all? { |family| family.is_a?(String) && !family.empty? }, "plan #{path}.selectedFamilies must contain non-empty strings")
    assert(selected.uniq.length == selected.length, "plan #{path}.selectedFamilies contains duplicates")
    assert(selected == selected.sort, "plan #{path}.selectedFamilies must be sorted")
    unknown_families = selected - known_families
    assert(unknown_families.empty?, "plan #{path} selects unknown families: #{unknown_families.join(', ')}")

    expected = data["expectedLegIds"]
    assert(expected.is_a?(Array), "plan #{path}.expectedLegIds must be an array")
    assert(expected.all? { |id| id.is_a?(String) && !id.empty? }, "plan #{path}.expectedLegIds must contain non-empty strings")
    assert(expected.uniq.length == expected.length, "plan #{path}.expectedLegIds contains duplicates")
    recomputed = catalog[:legs].select { |leg| selected.include?(leg[:name]) }.map { |leg| leg_id(leg) }
    assert(expected == recomputed, "plan #{path}.expectedLegIds does not match selectedFamilies")
    expected
  rescue Errno::ENOENT => e
    raise ContractError, e.message
  rescue JSON::ParserError => e
    raise ContractError, "plan #{path} is not valid JSON: #{e.message}"
  end

  def aggregate_results(results_dir, expected_ids)
    errors = []
    records = {}
    result_paths = Dir.glob(File.join(results_dir, "**", "result.json")).sort

    result_paths.each do |path|
      _validator_stdout, validator_stderr, validator_status = Open3.capture3(
        "python3",
        File.join(FUNCTIONAL_DIR, "result.py"),
        "validate",
        path,
        chdir: ROOT
      )
      unless validator_status.success?
        detail = validator_stderr.strip
        detail = "result validator exited #{validator_status.exitstatus}" if detail.empty?
        errors << "#{path}: result validation failed: #{detail}"
      end
      validator_valid = validator_status.success?

      begin
        data = JSON.parse(File.read(path))
      rescue JSON::ParserError => e
        errors << "#{path}: malformed JSON: #{e.message}"
        next
      rescue Errno::ENOENT => e
        errors << "#{path}: #{e.message}"
        next
      end

      unless data.is_a?(Hash)
        errors << "#{path}: result must be a JSON object"
        next
      end

      id = data["legId"]
      unless id.is_a?(String) && !id.empty?
        errors << "#{path}: legId must be a non-empty string"
        next
      end
      if records.key?(id)
        errors << "duplicate result for #{id}: #{records[id][:path]} and #{path}"
        next
      end
      records[id] = { path: path, data: data, validator_valid: validator_valid }

      errors << "#{path}: schemaVersion must be #{SCHEMA_VERSION}" unless data["schemaVersion"] == SCHEMA_VERSION
      id_parts = id.split(":", 3)
      contract_identity = data["contract"]
      if id_parts.length != 3
        errors << "#{path}: legId is not family:version:platform"
      elsif contract_identity.is_a?(Hash)
        expected_identity = {
          "family" => id_parts[0],
          "version" => id_parts[1],
          "platform" => id_parts[2]
        }
        expected_identity.each do |key, value|
          unless contract_identity[key] == value
            errors << "#{path}: contract.#{key} does not match legId"
          end
        end
      end
      outcome = data["outcome"]
      unless outcome.is_a?(Hash)
        errors << "#{path}: outcome must be an object"
        next
      end
      status = outcome["status"]
      classification = outcome["classification"]
      errors << "#{path}: outcome.status must be pass or fail" unless %w[pass fail].include?(status)
      unless classification.is_a?(String) && !classification.empty?
        errors << "#{path}: outcome.classification must be a non-empty string"
      end
    end

    received_ids = records.keys.sort
    missing = expected_ids - received_ids
    extra = received_ids - expected_ids
    errors << "missing results: #{missing.join(', ')}" unless missing.empty?
    errors << "unexpected results: #{extra.join(', ')}" unless extra.empty?

    passed_ids = []
    expected_ids.each do |id|
      next unless records.key?(id)
      next unless records[id][:validator_valid]
      outcome = records[id][:data]["outcome"]
      next unless outcome.is_a?(Hash)
      if outcome["status"] == "pass"
        passed_ids << id
      elsif outcome["status"] == "fail"
        errors << "#{id} failed with classification #{outcome['classification'].inspect}"
      end
    end

    status = errors.empty? && passed_ids.length == expected_ids.length ? "pass" : "fail"
    summary = {
      "schemaVersion" => SCHEMA_VERSION,
      "status" => status,
      "expectedCount" => expected_ids.length,
      "receivedCount" => received_ids.length,
      "passedCount" => passed_ids.length,
      "expectedLegIds" => expected_ids,
      "receivedLegIds" => received_ids,
      "passedLegIds" => passed_ids
    }
    summary["errors"] = errors unless errors.empty?
    [summary, status == "pass"]
  end

  def command_aggregate(arguments)
    options = {}
    parser = OptionParser.new do |opts|
      opts.on("--results DIR") { |value| options[:results] = value }
      opts.on("--plan FILE") { |value| options[:plan] = value }
      opts.on("--name FAMILY") { |value| options[:name] = value }
    end
    parser.parse!(arguments)
    assert(arguments.empty?, "unexpected aggregate arguments: #{arguments.join(' ')}")
    assert(options[:results], "aggregate requires --results DIR")
    assert(!(options[:plan] && options[:name]), "aggregate accepts only one of --plan or --name")
    assert(File.directory?(options[:results]), "aggregate results directory does not exist: #{options[:results]}")

    catalog = load_catalog
    known_ids = catalog[:legs].map { |leg| leg_id(leg) }
    expected_ids = if options[:plan]
                     expected_from_plan(options[:plan], catalog)
                   elsif options[:name]
                     assert(catalog[:contracts].key?(options[:name]), "unknown image family: #{options[:name]}")
                     catalog[:legs].select { |leg| leg[:name] == options[:name] }.map { |leg| leg_id(leg) }
                   else
                     known_ids
                   end

    summary, success = aggregate_results(options[:results], expected_ids)
    puts JSON.generate(summary)
    success
  end

  def dispatch(arguments)
    command = arguments.shift
    case command
    when "validate"
      assert(arguments.empty?, "validate does not accept arguments")
      command_validate(arguments)
    when "matrix"
      command_matrix(arguments)
    when "resolve"
      command_resolve(arguments)
    when "plan"
      command_plan(arguments)
    when "aggregate"
      command_aggregate(arguments)
    else
      raise ContractError, "usage: contractctl.rb validate|matrix|resolve|plan|aggregate"
    end
  end
end

if $PROGRAM_NAME == __FILE__
  begin
    success = DhiContracts.dispatch(ARGV.dup)
    exit 1 unless success
  rescue DhiContracts::ContractError, OptionParser::ParseError => e
    warn "contractctl: #{e.message}"
    exit 1
  end
end
