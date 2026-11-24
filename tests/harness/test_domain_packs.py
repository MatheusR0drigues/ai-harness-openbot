"""Testes unitarios para os packs de dominio data-engineering e bi-pbip."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import config
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_script(rel_path: str, module_name: str) -> ModuleType:
    path = REPO_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


spark_mod = _load_script(
    "harness/packs/data-engineering/scripts/check_spark_antipatterns.py",
    "check_spark_antipatterns",
)
pbip_mod = _load_script(
    "harness/packs/bi-pbip/scripts/check_pbip_sanity.py",
    "check_pbip_sanity",
)


def test_spark_flags_to_pandas_and_collect_without_limit() -> None:
    code = (
        "rows = df.toPandas()\n"
        "items = spark.table('silver.orders').filter('active = true').collect()\n"
        "raw = orders_df.collect()\n"
    )
    findings = spark_mod.check_source(code, "job.py")
    assert len(findings) == 3
    assert ".toPandas()" in findings[0][1]
    assert ".collect()" in findings[1][1]
    assert ".collect()" in findings[2][1]


def test_spark_flags_python_udfs() -> None:
    code = (
        "from pyspark.sql.functions import udf\n"
        "@udf('string')\n"
        "def norm(x):\n"
        "    return x.strip()\n"
        "fn = udf(lambda v: v)\n"
        "spark.udf.register('norm_sql', lambda v: v)\n"
    )
    findings = spark_mod.check_source(code, "udfs.py")
    lines = [line for line, _ in findings]
    assert lines == [2, 5, 6]


def test_spark_allows_safe_patterns_and_marker() -> None:
    code = (
        "sample = df.filter('ok = true').limit(100).toPandas()\n"
        "head = spark.table('gold.kpi').limit(5).collect()\n"
        "local_items = collector.collect()\n"
        "@pandas_udf('double')\n"
        "def vec(s):\n"
        "    return s * 2\n"
        "approved = df.toPandas()  # spark-antipatterns: allow\n"
    )
    findings = spark_mod.check_source(code, "clean.py")
    assert findings == []


def test_spark_cli_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = tmp_path / "src"
    src.mkdir()
    bad = src / "pipeline.py"
    bad.write_text("df.toPandas()\n", encoding="utf-8")

    assert spark_mod.main(["--root", str(tmp_path)]) == 1
    assert "[spark-antipatterns] src/pipeline.py:1:" in capsys.readouterr().err

    bad.write_text("df.limit(10).toPandas()\n", encoding="utf-8")
    assert spark_mod.main(["--root", str(tmp_path)]) == 0
    assert "SPARK ANTIPATTERNS CHECK PASSED" in capsys.readouterr().out


def test_pbip_flags_space_indentation_and_allows_tabs() -> None:
    bad_tmdl = "table Sales\n measure Total = SUM(Sales[Amount])\n"
    findings = pbip_mod.check_tmdl_text(bad_tmdl)
    assert len(findings) == 1
    assert findings[0][0] == 2

    allowed_tmdl = (
        "table Sales\n\tmeasure Total = 1\n\t\t // alinhamento\n"
        " measure X = 2 # pbip-sanity: allow\n"
    )
    assert pbip_mod.check_tmdl_text(allowed_tmdl) == []


def test_pbip_flags_pii_literals_only_in_filter_blocks() -> None:
    synthetic_email = "ana.silva" + "@exemplo.com"
    synthetic_cpf = "123.456.789" + "-01"
    report_json = (
        '{"config": "layout", "filters": [{"expression": "\''
        + synthetic_email
        + '\'"}], "visualFilter": {"Literal": {"Value": "'
        + synthetic_cpf
        + '"}}, "title": "'
        + synthetic_email
        + '"}'
    )
    findings = pbip_mod.check_report_json_text(report_json)
    assert len(findings) == 2
    assert "e-mail" in findings[0]
    assert "CPF" in findings[1]


def test_pbip_allows_marked_filters_and_flags_bad_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    synthetic_digits = "987654321" + "00"
    clean_visual = tmp_path / "visual.json"
    clean_visual.write_text(
        '{"filters": [{"note": "pbip-sanity: allow", "value": "' + synthetic_digits + '"}]}',
        encoding="utf-8",
    )
    model_tmdl = tmp_path / "model.tmdl"
    model_tmdl.write_text("model Model\n\tculture: pt-BR\n", encoding="utf-8")

    assert pbip_mod.main(["--root", str(tmp_path)]) == 0
    assert "PBIP SANITY CHECK PASSED" in capsys.readouterr().out

    bad_page = tmp_path / "page.json"
    bad_page.write_text("{invalido", encoding="utf-8")
    assert pbip_mod.main(["--root", str(tmp_path)]) == 1
    assert "page.json: JSON invalido" in capsys.readouterr().err


def test_domain_pack_rules_cover_required_directives() -> None:
    de_rule = (
        REPO_ROOT / "harness" / "packs" / "data-engineering" / "rules" / "data-engineering.md"
    ).read_text(encoding="utf-8")
    assert "count(entrada) == count(limpos) + count(quarentena)" in de_rule
    assert "IS DISTINCT FROM" in de_rule

    bi_rule = (REPO_ROOT / "harness" / "packs" / "bi-pbip" / "rules" / "bi-pbip.md").read_text(
        encoding="utf-8"
    )
    assert ".tmdl" in bi_rule
    assert '"filter"' in bi_rule


def test_utf8_bom_handled_by_domain_pack_scripts(tmp_path: Path) -> None:
    py_file = tmp_path / "bom_job.py"
    py_file.write_text("\ufeffdf.toPandas()\n", encoding="utf-8")
    spark_findings = spark_mod.check_paths(tmp_path)
    assert len(spark_findings) == 1
    assert "bom_job.py:1:" in spark_findings[0]

    synthetic_email = "carlos" + "@exemplo.com"
    report_file = tmp_path / "report.json"
    report_file.write_text(
        '\ufeff{"filters": [{"value": "' + synthetic_email + '"}]}',
        encoding="utf-8",
    )
    pbip_findings = pbip_mod.check_paths(tmp_path)
    assert len(pbip_findings) == 1
    assert "e-mail" in pbip_findings[0]


def test_pbip_marker_scope_bookmark_json_and_root_containment(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    outside = tmp_path / "outside.tmdl"
    outside.write_text("table X\n  measure A = 1\n", encoding="utf-8")

    synthetic_email = "diana" + "@exemplo.com"
    report = root / "report.json"
    report.write_text(
        '{"note": "pbip-sanity: allow", "filterConfig": {"note": "pbip-sanity: allow",'
        ' "filters": [{"value": "' + synthetic_email + '"}]}}',
        encoding="utf-8",
    )
    bookmark = root / "sales.bookmark.json"
    bookmark.write_text(
        '{"filters": [{"value": "' + synthetic_email + '"}]}',
        encoding="utf-8",
    )

    findings = pbip_mod.check_paths(root)
    assert len(findings) == 2
    assert any(item.startswith("report.json:") for item in findings)
    assert any(item.startswith("sales.bookmark.json:") for item in findings)
    assert pbip_mod.check_paths(root, [outside]) == []


def test_bi_pbip_gate_runs_on_thin_pbir_without_tmdl(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pack = config.load_pack(REPO_ROOT, "bi-pbip")
    assert len(pack.gates) == 1
    assert pack.gates[0].requires_glob == ""

    synthetic_email = "eva" + "@exemplo.com"
    visual = tmp_path / "visual.json"
    visual.write_text('{"filters": [{"value": "' + synthetic_email + '"}]}', encoding="utf-8")

    assert pbip_mod.main(["--root", str(tmp_path)]) == 1
    assert "visual.json:" in capsys.readouterr().err


PACK_SCRIPTS = [
    pytest.param("data-engineering", "check_spark_antipatterns.py", id="spark-antipatterns"),
    pytest.param("bi-pbip", "check_pbip_sanity.py", id="pbip-sanity"),
]


@pytest.mark.parametrize(("pack", "script"), PACK_SCRIPTS)
def test_pack_scanner_fails_without_harness_runtime(tmp_path: Path, pack: str, script: str) -> None:
    target = tmp_path / "harness" / "packs" / pack / "scripts" / script
    target.parent.mkdir(parents=True)
    shutil.copyfile(REPO_ROOT / "harness" / "packs" / pack / "scripts" / script, target)

    result = subprocess.run(
        [sys.executable, "-B", str(target), "--root", str(tmp_path)],
        cwd=tmp_path,
        timeout=60,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "harness runtime not found (scripts/harness/check_secrets.py)" in (
        result.stdout + result.stderr
    )


PROJECTED_FINDINGS = [
    pytest.param(
        "data-engineering",
        "check_spark_antipatterns.py",
        "pkg/job.py",
        "rows = df.toPandas()\n",
        id="spark-antipatterns",
    ),
    pytest.param(
        "bi-pbip",
        "check_pbip_sanity.py",
        "Vendas.SemanticModel/definition/tables/t.tmdl",
        "table T\n measure Total = 1\n",
        id="pbip-sanity",
    ),
]


@pytest.mark.parametrize(("pack", "script", "rel", "content"), PROJECTED_FINDINGS)
def test_pack_scanner_runs_with_projected_harness_runtime(
    tmp_path: Path, pack: str, script: str, rel: str, content: str
) -> None:
    # Subprocess in an `init`-like layout: proves the pack resolves `<root>/scripts/harness` (D10).
    target = tmp_path / "harness" / "packs" / pack / "scripts" / script
    target.parent.mkdir(parents=True)
    shutil.copyfile(REPO_ROOT / "harness" / "packs" / pack / "scripts" / script, target)
    runtime = tmp_path / "scripts" / "harness"
    runtime.mkdir(parents=True)
    shutil.copyfile(
        REPO_ROOT / "scripts" / "harness" / "check_secrets.py", runtime / "check_secrets.py"
    )
    (tmp_path / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    for folder in ("", "ignored/"):
        finding = tmp_path / (folder + rel)
        finding.parent.mkdir(parents=True, exist_ok=True)
        finding.write_text(content, encoding="utf-8")
    git_argv = ["git", "-c", "core.fsmonitor=false", "-C", str(tmp_path)]
    subprocess.run([*git_argv, "init", "-q"], timeout=60, capture_output=True, check=True)
    subprocess.run([*git_argv, "add", "-A"], timeout=60, capture_output=True, check=True)

    result = subprocess.run(
        [sys.executable, "-B", str(target), "--root", str(tmp_path)],
        cwd=tmp_path,
        timeout=60,
        capture_output=True,
        text=True,
        check=False,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert rel in output
    assert "ignored/" not in output


SYNTHETIC_FILTER_EMAIL = "teste" + "@" + "exemplo.invalid"
BINARY_CASES = [
    pytest.param(spark_mod, "src/blob.py", b"rows = df.toPandas()\n", id="spark-antipatterns"),
    pytest.param(
        pbip_mod,
        "Vendas.Report/definition/visual.json",
        ('{"filters": [{"value": "' + SYNTHETIC_FILTER_EMAIL + '"}]}').encode(),
        id="pbip-sanity",
    ),
]


@pytest.mark.parametrize(("module", "rel", "offending"), BINARY_CASES)
def test_pack_binary_files_skipped(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    module: ModuleType,
    rel: str,
    offending: bytes,
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True, timeout=60)
    target = tmp_path / rel
    target.parent.mkdir(parents=True)
    target.write_bytes(b"\n" * 4096 + b"\x00\n" + offending)
    subprocess.run(["git", "add", rel], cwd=tmp_path, check=True, capture_output=True, timeout=60)

    code = module.main(["--root", str(tmp_path)])
    captured = capsys.readouterr()

    assert code == 0
    assert rel not in captured.out + captured.err


SYNTHETIC_CPF_DIGITS = "123" + "45678901"
PBIR_FIELD = {
    "Column": {
        "Expression": {"SourceRef": {"Entity": "Vendas"}},
        "Property": "Regiao",
    }
}


def _filter_block_report(filter_item: dict[str, object]) -> str:
    return json.dumps({"filterConfig": {"filters": [filter_item]}})


def _literal_filter_item(literal_value: str) -> dict[str, object]:
    return {
        "field": PBIR_FIELD,
        "type": "Categorical",
        "filter": {
            "Where": [{"Condition": {"In": {"Values": [[{"Literal": {"Value": literal_value}}]]}}}]
        },
    }


def test_pbip_hex_filter_name_not_cpf() -> None:
    hex_name = "a" + SYNTHETIC_CPF_DIGITS + "bcdef012"
    report = _filter_block_report({"name": hex_name, "field": PBIR_FIELD, "type": "Categorical"})

    assert pbip_mod.check_report_json_text(report) == []


@pytest.mark.parametrize("key", ["queryRef", "nativeQueryRef"])
def test_pbip_query_refs_not_cpf(key: str) -> None:
    report = _filter_block_report(
        {key: "Vendas.Coluna" + SYNTHETIC_CPF_DIGITS, "field": PBIR_FIELD, "type": "Categorical"}
    )

    assert pbip_mod.check_report_json_text(report) == []


def test_pbip_literal_digits_reported() -> None:
    report = _filter_block_report(_literal_filter_item("'" + SYNTHETIC_CPF_DIGITS + "'"))

    findings = pbip_mod.check_report_json_text(report)

    assert len(findings) == 1
    assert "CPF" in findings[0]


def test_pbip_literal_email_reported() -> None:
    report = _filter_block_report(_literal_filter_item("'" + SYNTHETIC_FILTER_EMAIL + "'"))

    findings = pbip_mod.check_report_json_text(report)

    assert len(findings) == 1
    assert "e-mail" in findings[0]


def test_pbip_name_outside_filter_block_reported() -> None:
    report = json.dumps({"filter": {"name": SYNTHETIC_CPF_DIGITS}})

    findings = pbip_mod.check_report_json_text(report)

    assert len(findings) == 1
    assert "CPF" in findings[0]


def test_pbip_cpf_regex_unchanged() -> None:
    assert pbip_mod.CPF_DIGITS_RE.pattern == r"(?<!\d)\d{11}(?!\d)"


def test_pbip_nested_object_under_query_ref_scanned() -> None:
    report = _filter_block_report(
        {"queryRef": {"x": SYNTHETIC_CPF_DIGITS}, "field": PBIR_FIELD, "type": "Categorical"}
    )

    findings = pbip_mod.check_report_json_text(report)

    assert len(findings) == 1
    assert "CPF" in findings[0]
    assert "filterConfig.filters[0].queryRef.x" in findings[0]
