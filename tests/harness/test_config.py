"""Tests for the harness.toml and harness/core.toml loader (scripts/harness/config.py)."""

from pathlib import Path

import config
import pytest
from config import ConfigError, Gate
from config_fixtures import write_core, write_pack

VALID = """
[project]
name = "demo"

[packs]
enabled = ["python", "web-ui"]

[secrets]
extra_patterns = [{ name = "demo-token", regex = "demo_[0-9]{8}" }]
exempt_paths = ["docs/"]
safe_values = ["placeholder-value"]

[comments]
include = ["src/**"]
exempt_paths = ["tests/fixtures/"]

[[gates]]
name = "lint"
command = ["python", "-m", "ruff", "check", "."]
hint = "Fix lint."
fast = true
group = "stack"
timeout = 30
requires_glob = "**/*.py"

[[gates]]
name = "tests"
command = ["python", "-m", "pytest"]
hint = "Fix tests."
group = "harness"
"""

CORE = """
[controls]
required_gates = ["secrets"]
required_guards = ["secret_in_write"]

[[gates]]
name = "secrets"
command = ["python", "scripts/harness/check_secrets.py"]
hint = "h"
group = "core"
fast = true
"""


def write(tmp_path: Path, text: str) -> Path:
    write_core(tmp_path)
    for name in ("python", "node", "web-ui"):
        write_pack(tmp_path, name)
    path = tmp_path / "harness.toml"
    path.write_text(text, encoding="utf-8")
    return path


def write_split(tmp_path: Path, project: str) -> Path:
    write_core(tmp_path, CORE)
    for name in ("python", "web-ui"):
        write_pack(tmp_path, name)
    path = tmp_path / "harness.toml"
    path.write_text(project, encoding="utf-8")
    return path


def test_load_valid_config_returns_typed_values(tmp_path: Path) -> None:
    cfg = config.load(write(tmp_path, VALID))

    assert cfg.project_name == "demo"
    assert cfg.packs == ("python", "web-ui")
    assert cfg.exempt_paths == ("docs/",)
    assert cfg.safe_values == ("placeholder-value",)
    assert cfg.comments.include == ("src/**",)
    assert cfg.comments.exempt_paths == ("tests/fixtures/",)
    assert cfg.extra_patterns[0].name == "demo-token"
    assert cfg.extra_patterns[0].regex.search("x demo_12345678 y")
    assert cfg.gates[0] == Gate(
        name="lint",
        command=("python", "-m", "ruff", "check", "."),
        hint="Fix lint.",
        fast=True,
        group="stack",
        timeout=30,
        requires_glob="**/*.py",
    )


def test_gate_defaults_apply_when_optional_keys_are_missing(tmp_path: Path) -> None:
    cfg = config.load(write(tmp_path, VALID))

    assert cfg.gates[1].fast is False
    assert cfg.gates[1].timeout == config.DEFAULT_TIMEOUT
    assert cfg.gates[1].requires_glob == ""


def test_missing_file_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="does not exist"):
        config.load(tmp_path / "missing.toml")


def test_invalid_toml_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not valid TOML"):
        config.load(write(tmp_path, "[[gates]\nname="))


@pytest.mark.parametrize(
    ("gate_body", "message"),
    [
        ('command = ["x"]\nhint = "h"\ngroup = "core"', "missing required key `name`"),
        ('name = "g"\ncommand = "x y"\nhint = "h"\ngroup = "core"', "non-empty list of strings"),
        ('name = "g"\ncommand = []\nhint = "h"\ngroup = "core"', "non-empty list of strings"),
        ('name = "g"\ncommand = ["x"]\nhint = "h"\ngroup = "other"', "group must be one of"),
        ('name = "g"\ncommand = ["x"]\nhint = "h"\ngroup = "core"\ntimeout = 0', "positive"),
        ('name = "g"\ncommand = ["x"]\nhint = "h"\ngroup = "core"\nfast = "yes"', "boolean"),
        (
            'name = "g"\ncommand = ["x"]\nhint = "h"\ngroup = "core"\nrequires_glob = ""',
            "non-empty",
        ),
        ('name = "g"\ncommand = ["x"]\nhint = "h"\ngroup = "core"\nshell = true', "unknown key"),
    ],
)
def test_invalid_gate_is_rejected_with_precise_message(
    tmp_path: Path, gate_body: str, message: str
) -> None:
    with pytest.raises(ConfigError, match=message):
        config.load(write(tmp_path, f"[[gates]]\n{gate_body}\n"))


def test_unsupported_pack_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="unsupported pack `rust`"):
        config.load(write(tmp_path, '[packs]\nenabled = ["rust"]\n'))


def test_duplicate_packs_are_deduplicated_preserving_order(tmp_path: Path) -> None:
    cfg = config.load(write(tmp_path, '[packs]\nenabled = ["python", "node", "python"]\n'))

    assert cfg.packs == ("python", "node")


def test_duplicate_gate_names_are_rejected(tmp_path: Path) -> None:
    gate = '[[gates]]\nname = "g"\ncommand = ["x"]\nhint = "h"\ngroup = "core"\n'

    with pytest.raises(ConfigError, match="duplicate gate name"):
        config.load(write(tmp_path, gate + gate))


def test_unknown_top_level_key_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="unknown key `extras`"):
        config.load(write(tmp_path, "[extras]\nx = 1\n"))


def test_invalid_secret_regex_is_rejected(tmp_path: Path) -> None:
    text = '[secrets]\nextra_patterns = [{ name = "bad", regex = "(" }]\n'

    with pytest.raises(ConfigError, match="invalid regex"):
        config.load(write(tmp_path, text))


def test_untrusted_section_is_parsed(tmp_path: Path) -> None:
    text = '[untrusted]\ninclude = ["docs/**"]\nexempt_paths = ["docs/imported/"]\n'

    cfg = config.load(write(tmp_path, text))

    assert cfg.untrusted.include == ("docs/**",)
    assert cfg.untrusted.exempt_paths == ("docs/imported/",)


def test_untrusted_section_defaults_to_scanning_everything(tmp_path: Path) -> None:
    cfg = config.load(write(tmp_path, VALID))

    assert cfg.untrusted == config.ScanSettings()


def test_unknown_key_in_untrusted_section_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="unknown key `patterns`"):
        config.load(write(tmp_path, "[untrusted]\npatterns = []\n"))


def test_untrusted_include_must_be_a_list_of_strings(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="untrusted.include must be a non-empty list"):
        config.load(write(tmp_path, '[untrusted]\ninclude = "docs/**"\n'))


def test_repository_harness_toml_is_valid() -> None:
    cfg = config.load()

    assert cfg.project_name == "ai-harness"
    assert cfg.gates, "harness.toml must declare gates"


def test_core_gates_run_before_project_gates(tmp_path: Path) -> None:
    cfg = config.load(write_split(tmp_path, VALID))

    assert [g.name for g in cfg.gates] == ["secrets", "lint", "tests"]
    assert cfg.project_name == "demo"


def test_project_cannot_redefine_a_core_gate(tmp_path: Path) -> None:
    project = '[[gates]]\nname = "secrets"\ncommand = ["true"]\nhint = "h"\ngroup = "stack"\n'

    with pytest.raises(ConfigError, match="gate `secrets` is a core gate"):
        config.load(write_split(tmp_path, project))


def test_project_controls_add_to_the_core_baseline(tmp_path: Path) -> None:
    project = '[controls]\nrequired_gates = ["lint"]\nrequired_guards = []\n'

    cfg = config.load(write_split(tmp_path, project))

    assert cfg.controls.required_gates == ("secrets", "lint")
    assert cfg.controls.required_guards == ("secret_in_write",)


def test_missing_core_file_is_a_config_error(tmp_path: Path) -> None:
    path = tmp_path / "harness.toml"
    path.write_text(VALID, encoding="utf-8")

    with pytest.raises(ConfigError, match=r"core\.toml does not exist"):
        config.load(path)


PACK_GATE = """
[[gates]]
name = "py-lint"
command = ["uv", "run", "ruff", "check", "."]
hint = "h"
group = "stack"
fast = true
"""


def test_enabled_pack_gates_run_after_core_and_before_project_gates(tmp_path: Path) -> None:
    write_core(tmp_path, CORE)
    write_pack(tmp_path, "python", PACK_GATE)
    path = tmp_path / "harness.toml"
    path.write_text(
        '[packs]\nenabled = ["python"]\n[[gates]]\nname = "own"\ncommand = ["x"]\n'
        'hint = "h"\ngroup = "stack"\n',
        encoding="utf-8",
    )

    cfg = config.load(path)

    assert [g.name for g in cfg.gates] == ["secrets", "py-lint", "own"]


def test_disabled_pack_gates_are_not_loaded(tmp_path: Path) -> None:
    write_core(tmp_path, CORE)
    write_pack(tmp_path, "python", PACK_GATE)
    path = tmp_path / "harness.toml"
    path.write_text("[packs]\nenabled = []\n", encoding="utf-8")

    assert [g.name for g in config.load(path).gates] == ["secrets"]


def test_enabled_pack_without_manifest_is_a_config_error(tmp_path: Path) -> None:
    write_core(tmp_path)
    path = tmp_path / "harness.toml"
    path.write_text('[packs]\nenabled = ["node"]\n', encoding="utf-8")

    with pytest.raises(ConfigError, match="not installed"):
        config.load(path)


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (PACK_GATE.replace('"stack"', '"harness"'), 'must use group = "stack"'),
        ('[[hooks]]\nevent = "Bogus"\ncommand = "python x.py"\n', "event must be one of"),
        ('[[hooks]]\nevent = "PreToolUse"\ncommand = \'python "x.py"\'\n', "double quotes"),
        ("extra = 1\n", "unknown key `extra`"),
    ],
)
def test_invalid_pack_manifest_is_rejected(tmp_path: Path, body: str, message: str) -> None:
    write_pack(tmp_path, "python", body)

    with pytest.raises(ConfigError, match=message):
        config.load_pack(tmp_path, "python")


def test_pack_name_must_match_its_folder(tmp_path: Path) -> None:
    path = write_pack(tmp_path, "node")
    path.write_text('[pack]\nname = "python"\ndescription = "x"\n', encoding="utf-8")

    with pytest.raises(ConfigError, match="must equal the folder"):
        config.load_pack(tmp_path, "node")


def test_pack_rule_must_exist_inside_the_pack(tmp_path: Path) -> None:
    path = write_pack(tmp_path, "web-ui")
    path.write_text(
        '[pack]\nname = "web-ui"\ndescription = "x"\nrules = ["../escape.md"]\n',
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="escapes the pack folder"):
        config.load_pack(tmp_path, "web-ui")


@pytest.mark.parametrize(
    ("project_gate", "message"),
    [
        ("", "pack `node`: gate `py-lint` already defined in pack `python`"),
        (PACK_GATE, "pack `python`: gate `py-lint` already defined in harness/core.toml"),
    ],
)
def test_pack_gate_name_collision_is_rejected(
    tmp_path: Path, project_gate: str, message: str
) -> None:
    write_core(tmp_path, CORE)
    write_pack(tmp_path, "python", PACK_GATE)
    write_pack(tmp_path, "node", PACK_GATE)
    path = tmp_path / "harness.toml"
    path.write_text('[packs]\nenabled = ["python", "node"]\n' + project_gate, encoding="utf-8")

    with pytest.raises(ConfigError, match=message):
        config.load(path)


def test_pack_hooks_are_parsed_with_defaults(tmp_path: Path) -> None:
    write_pack(
        tmp_path,
        "research-guard",
        '[[hooks]]\nevent = "PreToolUse"\ncommand = "python ../x.py"\n',
    )

    pack = config.load_pack(tmp_path, "research-guard")

    assert pack.hooks == (config.PackHook("PreToolUse", "python ../x.py", 30, ""),)


def test_core_file_with_project_keys_is_rejected(tmp_path: Path) -> None:
    write_core(tmp_path, '[project]\nname = "x"\n')
    path = tmp_path / "harness.toml"
    path.write_text(VALID, encoding="utf-8")

    with pytest.raises(ConfigError, match="core.toml: unknown key `project`"):
        config.load(path)


def test_agents_allow_override_parses_and_rejects_unknown(tmp_path: Path) -> None:
    valid_project = (
        '[project]\nname = "demo"\n[agents]\nallow_override = ["researcher", "implementer"]\n'
    )
    cfg = config.load(write(tmp_path, valid_project))
    assert cfg.agents_allow_override == ("researcher", "implementer")
    assert config.agent_overrides(tmp_path) == ("researcher", "implementer")

    core = config.parse({"gates": []})
    project = config.parse({"agents": {"allow_override": ["researcher"]}})
    merged = config.merge(core, project)
    assert merged.agents_allow_override == ("researcher",)

    t1 = tmp_path / "t1"
    t1.mkdir()
    invalid_key_project = '[project]\nname = "demo"\n[agents]\nunknown_key = true\n'
    with pytest.raises(ConfigError, match="agents: unknown key `unknown_key`"):
        config.load(write(t1, invalid_key_project))

    t2 = tmp_path / "t2"
    t2.mkdir()
    invalid_type_project = '[project]\nname = "demo"\n[agents]\nallow_override = "researcher"\n'
    with pytest.raises(
        ConfigError, match="agents.allow_override must be a non-empty list of strings"
    ):
        config.load(write(t2, invalid_type_project))

    t3 = tmp_path / "t3"
    t3.mkdir()
    unknown_agent_project = (
        '[project]\nname = "demo"\n[agents]\nallow_override = ["unknown-agent"]\n'
    )
    with pytest.raises(ConfigError, match="agents.allow_override: unknown agent `unknown-agent`"):
        config.load(write(t3, unknown_agent_project))


# [init] skip_templates (Requisito 8, specs/kit-adoption-compat).
@pytest.mark.parametrize("name", ["AGENTS", "readme"])
def test_skip_templates_rejects_unknown_name(tmp_path: Path, name: str) -> None:
    text = f'[init]\nskip_templates = ["product", "{name}"]\n'

    with pytest.raises(ConfigError) as excinfo:
        config.load(write(tmp_path, text))

    message = str(excinfo.value)
    assert "[init] skip_templates" in message
    assert f"`{name}`" in message


@pytest.mark.parametrize(
    "value", ['"product"', '["product", 1]'], ids=["string", "list-with-integer"]
)
def test_skip_templates_requires_list_of_strings(tmp_path: Path, value: str) -> None:
    with pytest.raises(ConfigError) as excinfo:
        config.load(write(tmp_path, f"[init]\nskip_templates = {value}\n"))

    assert "[init] skip_templates" in str(excinfo.value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [('["product", "tech"]', ("product", "tech")), ("[]", ())],
    ids=["subset", "empty"],
)
def test_skip_templates_accepts_valid_subset(
    tmp_path: Path, value: str, expected: tuple[str, ...]
) -> None:
    cfg = config.load(write(tmp_path, f"[init]\nskip_templates = {value}\n"))

    assert cfg.init_skip_templates == expected


def test_load_supports_external_harness_root_fallback(tmp_path: Path) -> None:
    harness_root = tmp_path / "shared_harness"
    write_core(harness_root, CORE)
    write_pack(
        harness_root,
        "python",
        '[[gates]]\nname = "lint"\ncommand = ["python", "-m", "ruff"]\n'
        'hint = "h"\ngroup = "stack"\n',
    )

    target_repo = tmp_path / "target_repo"
    target_repo.mkdir()
    ext_cfg = tmp_path / "external-harness.toml"
    ext_cfg.write_text(
        '[project]\nname = "external-target"\n\n[packs]\nenabled = ["python"]\n',
        encoding="utf-8",
    )

    cfg = config.load(ext_cfg, harness_root=harness_root)

    assert cfg.project_name == "external-target"
    assert cfg.packs == ("python",)
    assert [g.name for g in cfg.gates] == ["secrets", "lint"]
