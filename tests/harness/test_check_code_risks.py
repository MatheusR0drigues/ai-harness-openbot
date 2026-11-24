"""Tests for the generated-code risk sensor (scripts/harness/check_code_risks.py)."""

from __future__ import annotations

from pathlib import Path

import check_code_risks
import pytest
from config_fixtures import write_core

RISKY = [
    ("a.py", 'cur.execute("SELECT * FROM t WHERE id = " + user_id)', "sql-concatenation"),
    ("a.py", 'cur.execute(f"SELECT * FROM t WHERE id = {user_id}")', "sql-concatenation"),
    ("a.py", 'subprocess.run(f"ls {path}", shell=True)', "shell-injection"),
    ("a.py", 'os.system(f"rm {path}")', "shell-injection"),
    ("a.py", "value = eval(payload)", "dynamic-evaluation"),
    ("a.py", "exec(source)", "dynamic-evaluation"),
    ("a.py", "data = pickle.loads(blob)", "unsafe-deserialization"),
    ("a.py", "data = yaml.load(blob)", "unsafe-deserialization"),
    ("a.py", "token = random.choice(alphabet)", "weak-randomness"),
    ("a.py", "digest = hashlib.md5(password).hexdigest()", "broken-hash"),
    ("a.py", "digest = hashlib.sha1(secret).hexdigest()", "broken-hash"),
    ("a.py", "response = requests.get(url)", "missing-timeout"),
    ("a.py", "requests.get(url, verify=False, timeout=5)", "tls-verification-disabled"),
    ("a.js", "element.innerHTML = userInput;", "dom-injection"),
    ("a.tsx", "<div dangerouslySetInnerHTML={{ __html: body }} />", "dom-injection"),
    ("a.js", "db.query(`SELECT * FROM t WHERE id = ${id}`)", "sql-concatenation"),
    ("a.ts", "execSync(`tar -xf ${archive}`)", "shell-injection"),
    ("a.js", "const fn = new Function(body);", "dynamic-evaluation"),
    ("a.js", 'crypto.createHash("md5").update(password)', "broken-hash"),
    ("a.js", "const token = Math.random().toString(36);", "weak-randomness"),
    ("a.js", "https.request({ rejectUnauthorized: false });", "tls-verification-disabled"),
]

CLEAN = [
    ("a.py", 'cur.execute("SELECT * FROM t WHERE id = ?", (user_id,))'),
    ("a.py", 'subprocess.run(["ls", path], check=True)'),
    ("a.py", "data = yaml.safe_load(blob)"),
    ("a.py", "data = yaml.load(blob, Loader=yaml.SafeLoader)"),
    ("a.py", "token = secrets.token_hex(32)"),
    ("a.py", "digest = hashlib.sha256(payload).hexdigest()"),
    ("a.py", "response = requests.get(url, timeout=10)"),
    ("a.py", 'print("delete it and re-run the select from the menu")'),
    ("a.js", "element.textContent = userInput;"),
    ("a.js", "db.query('SELECT * FROM t WHERE id = $1', [id]);"),
]


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def configure(root: Path, include: str) -> Path:
    write_core(root)
    return write(root, "harness.toml", f"[code_risks]\ninclude = [{include}]\n")


@pytest.mark.parametrize(("name", "code", "rule"), RISKY)
def test_scan_text_reports_the_expected_rule(name: str, code: str, rule: str) -> None:
    findings = check_code_risks.scan_text(code, name, check_code_risks.rules_for(name))

    assert rule in {finding.rule for finding in findings}, findings


@pytest.mark.parametrize(("name", "code"), CLEAN)
def test_scan_text_leaves_safe_code_alone(name: str, code: str) -> None:
    findings = check_code_risks.scan_text(code, name, check_code_risks.rules_for(name))

    assert findings == []


def test_one_finding_per_rule_per_line() -> None:
    code = "eval(a) or eval(b)\nsafe = 1\nexec(c)\n"

    findings = check_code_risks.scan_text(code, "a.py", check_code_risks.rules_for("a.py"))

    assert [(f.line, f.rule) for f in findings] == [
        (1, "dynamic-evaluation"),
        (3, "dynamic-evaluation"),
    ]
    assert findings[0].render() == "a.py:1: [dynamic-evaluation]"


def test_allow_marker_accepts_a_proven_false_positive() -> None:
    code = f"value = eval(payload)  # {check_code_risks.ALLOW_MARKER}"

    assert check_code_risks.scan_text(code, "a.py", check_code_risks.rules_for("a.py")) == []


def test_python_rules_do_not_apply_to_javascript() -> None:
    names = {rule.name for rule in check_code_risks.rules_for("a.js")}

    assert "missing-timeout" not in names
    assert "dom-injection" in names


def test_files_without_rules_are_not_scanned() -> None:
    assert check_code_risks.rules_for("notes.md") == ()


def test_sensor_is_inert_when_no_code_path_is_configured(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path, "a.py", "value = eval(payload)\n")
    cfg = configure(tmp_path, "")

    code = check_code_risks.main([], root=tmp_path, config_path=cfg)

    assert code == 0
    assert "WARNING: no code paths configured" in capsys.readouterr().out


def test_configured_include_restricts_and_reports(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path, "src/a.py", "value = eval(payload)\n")
    write(tmp_path, "b.py", "value = eval(payload)\n")
    cfg = configure(tmp_path, '"src/**"')

    code = check_code_risks.main([], root=tmp_path, config_path=cfg)
    out = capsys.readouterr().out

    assert code == 1
    assert "CODE RISK SCAN FAILED: 1 finding(s)" in out
    assert "  src/a.py:1: [dynamic-evaluation]" in out
    assert "  b.py:1" not in out
    assert "--- fix hint ---" in out


def test_exempt_paths_are_skipped(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(tmp_path, "src/vendor/a.py", "value = eval(payload)\n")
    write_core(tmp_path)
    cfg = write(
        tmp_path,
        "harness.toml",
        '[code_risks]\ninclude = ["src/**"]\nexempt_paths = ["src/vendor/"]\n',
    )

    code = check_code_risks.main([], root=tmp_path, config_path=cfg)

    assert code == 0
    assert "CODE RISK SCAN PASSED" in capsys.readouterr().out


def test_explicit_arguments_scan_files_and_directories(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path, "lib/deep/a.py", "data = pickle.loads(blob)\n")
    write(tmp_path, "one.py", "requests.get(url)\n")
    cfg = configure(tmp_path, "")

    code = check_code_risks.main(["lib", "one.py"], root=tmp_path, config_path=cfg)
    out = capsys.readouterr().out

    assert code == 1
    assert "lib/deep/a.py:1: [unsafe-deserialization]" in out
    assert "one.py:1: [missing-timeout]" in out


def test_missing_config_keeps_the_sensor_inert(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path, "a.py", "value = eval(payload)\n")

    code = check_code_risks.main([], root=tmp_path, config_path=tmp_path / "missing.toml")

    assert code == 0
    assert "WARNING" in capsys.readouterr().out


def test_invalid_config_is_reported_instead_of_crashing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = write(tmp_path, "harness.toml", "[[gates]\n")

    code = check_code_risks.main([], root=tmp_path, config_path=cfg)

    assert code == 1
    assert "HARNESS CONFIG INVALID" in capsys.readouterr().out


def test_load_settings_reads_the_code_risks_table(tmp_path: Path) -> None:
    cfg = configure(tmp_path, '"scripts/**", "tools/**"')

    settings = check_code_risks.load_settings(cfg)

    assert settings.include == ("scripts/**", "tools/**")
    assert settings.exempt_paths == ()


def test_harness_own_sources_are_clean() -> None:
    sources = sorted((check_code_risks.REPO_ROOT / "scripts" / "harness").glob("*.py"))

    findings = check_code_risks.scan_files(sources, check_code_risks.REPO_ROOT, include=("**",))

    assert findings == [], findings


def test_repository_is_clean_under_the_real_configuration() -> None:
    assert check_code_risks.main([]) == 0
