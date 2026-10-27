"""リポジトリ構成・命名・公開安全性の静的テスト（オフライン）。Run: python3 -m pytest tests -q"""
import pathlib
import re
import subprocess
import sys

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
PATTERNS = ["00_common", "01_router_handoff", "02_orchestrator_worker", "03_agent_as_tool",
            "04_verifier_human_in_the_loop", "05_mcp_agent_chaining", "06_skill_composition"]
TEXT_FILES = [p for p in ROOT.rglob("*") if p.is_file() and p.suffix in {".sql", ".sh", ".py", ".md", ".yaml", ".json", ".example"}
              and not {"results", "__pycache__", ".pytest_cache"} & set(p.parts) and p.name not in {"AGENTS.md", "TASK.md"}]
SQL_FILES = sorted(ROOT.glob("0*/sql/*.sql"))
KNOWN_VARS = {"db", "wh", "role", "mcp_db", "skill_db", "wh_size", "wh_suspend"}


def test_generated_agent_sql_is_current():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_agents_sql.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


@pytest.mark.parametrize("pattern", PATTERNS)
def test_each_pattern_has_readme_and_scripts(pattern):
    d = ROOT / pattern
    assert (d / "README.md").exists(), f"{pattern}/README.md is missing"
    assert (d / "setup.sh").exists() and (d / "teardown.sh").exists()
    if pattern != "00_common":
        assert (d / "run.sh").exists()


@pytest.mark.parametrize("path", sorted(ROOT.glob("0*/*.sh")), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_shell_scripts_use_shared_lib(path):
    text = path.read_text()
    assert "scripts/lib.sh" in text and "map_init" in text


@pytest.mark.parametrize("path", sorted(ROOT.glob("*/*.sh")), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_shell_variables_before_non_ascii_are_braced(path):
    # bash 3.2（macOS 標準）は "$VAR（" の全角文字を変数名の一部として読むため、${VAR} と書く
    bad = [line for line in path.read_text().splitlines() if re.search(r"\$[A-Za-z_]\w*[^\x00-\x7f]", line)]
    assert not bad, bad


@pytest.mark.parametrize("path", sorted(ROOT.glob("0*/teardown.sh")), ids=lambda p: p.parent.name)
def test_teardown_requires_confirm(path):
    assert "confirm_or_exit" in path.read_text()


@pytest.mark.parametrize("path", SQL_FILES, ids=lambda p: f"{p.parent.parent.name}/{p.name}")
def test_sql_uses_only_known_template_variables(path):
    text = path.read_text()
    assert "__DB__" not in text and "__WH__" not in text, "use <% var %> templates"
    used = set(re.findall(r"<%\s*(\w+)\s*%>", text))
    assert used <= KNOWN_VARS, used - KNOWN_VARS


@pytest.mark.parametrize("path", SQL_FILES, ids=lambda p: f"{p.parent.parent.name}/{p.name}")
def test_sql_has_no_hardcoded_object_names(path):
    text = path.read_text()
    for name in ("MULTI_AGENT_PATTERNS", "MAP_MCP_CHAIN", "MAP_SKILL_COMPOSITION", "CORTEX_MULTI_AGENT"):
        assert name not in text, f"{name} must come from a template variable"


def test_each_procedure_is_created_by_exactly_one_file():
    owners = {}
    for path in SQL_FILES:
        for name in re.findall(r"CREATE OR REPLACE PROCEDURE\s+(<%\s*\w+\s*%>\.\w+\.\w+)\(", path.read_text()):
            owners.setdefault(name, []).append(str(path.relative_to(ROOT)))
    dup = {k: v for k, v in owners.items() if len(v) > 1}
    assert not dup, f"CREATE OR REPLACE drops grants: define each procedure once {dup}"


def test_each_agent_is_created_by_exactly_one_file():
    owners = {}
    for path in SQL_FILES:
        for name in re.findall(r"CREATE OR REPLACE AGENT\s+(<%\s*\w+\s*%>\.\w+\.\w+)", path.read_text()):
            owners.setdefault(name, []).append(path.name)
    assert all(len(v) == 1 for v in owners.values()), owners


@pytest.mark.parametrize("path", sorted(ROOT.glob("0*/sql/*.sql")), ids=lambda p: f"{p.parent.parent.name}/{p.name}")
def test_every_agent_sets_a_budget(path):
    text = path.read_text()
    for spec in re.findall(r"CREATE OR REPLACE AGENT.*?\$\$(.*?)\$\$;", text, re.S):
        assert "budget:" in yaml.safe_dump(yaml.safe_load(spec.replace("<% ", "").replace(" %>", ""))), path.name


# リポジトリ規約 4: 名前・値に snow / snowflake を含めない。システムオブジェクト参照は例外。
@pytest.mark.parametrize("path", [p for p in TEXT_FILES if p.suffix in {".sql", ".yaml", ".json"}], ids=lambda p: str(p.relative_to(ROOT)))
def test_no_reserved_word_in_identifiers_or_values(path):
    for i, line in enumerate(path.read_text().splitlines(), 1):
        if line.lstrip().startswith("--"):
            continue
        stripped = re.sub(r"SNOWFLAKE\.CORTEX(_USER)?|snowflake\.snowpark(\.files)?|snowflake-snowpark-python|SnowflakeFile|SNOWFLAKE_SAMPLE_DATA", "", line)
        assert not re.search(r"snow", stripped, re.I), f"{path.name}:{i}: {line.strip()}"


def test_shell_and_python_names_avoid_reserved_word():
    for path in [p for p in TEXT_FILES if p.suffix in {".sh", ".py"}]:
        text = path.read_text()
        names = set(re.findall(r"\b([A-Za-z_]\w*)\s*=", text))          # 変数への代入
        names |= set(re.findall(r"\bdef\s+(\w+)", text))                 # Python 関数
        names |= set(re.findall(r"^\s*(\w+)\(\)\s*\{", text, re.M))      # シェル関数
        bad = sorted(n for n in names if "snow" in n.lower())
        assert not bad, f"{path.relative_to(ROOT)}: {bad}"


def test_no_hostnames_or_secrets():
    pat = re.compile(r"[A-Za-z0-9-]+\.snowflakecomputing\.com|BEGIN (RSA )?PRIVATE KEY|password\s*=\s*['\"][^<]", re.I)
    hits = [str(p.relative_to(ROOT)) for p in TEXT_FILES if pat.search(p.read_text())]
    assert not hits, hits


def test_env_example_has_only_placeholders():
    for line in (ROOT / ".env.example").read_text().splitlines():
        if line.startswith("MAP_CONNECTION="):
            assert line.split("=", 1)[1].startswith("<"), line


def test_gitignore_excludes_local_files():
    ignored = (ROOT / ".gitignore").read_text().split()
    for entry in (".env", "results/", "AGENTS.md", "TASK.md", "__pycache__/"):
        assert entry in ignored


def test_sanitizer_removes_identifying_fields():
    sys.path.insert(0, str(ROOT / "scripts"))
    import agent_runner as ar
    nested = '{"content":[{"type":"thinking","thinking":{"text":"x","signature":"S"}}],"thread_id":"1"}\n{"text":"ok","message_id":"2"}'
    raw = {"request_id": "r", "content": [{"type": "tool_result", "tool_result": {"content": [{"json": {"result": nested}}]}}]}
    out = str(ar.sanitize(raw))
    for word in ("signature", "request_id", "thread_id", "message_id", '"S"'):
        assert word not in out


def test_teardown_all_covers_every_pattern_in_dependency_order():
    text = (ROOT / "scripts" / "teardown_all.sh").read_text()
    assert "$CONFIRM ||" in text, "--confirm なしでは何も削除しない"
    code = text[text.index("run_teardown() {"):]
    # 実際に呼んでいる順序（for ループの列挙と run_teardown の呼び出し）だけを見る
    code = "\n".join(l for l in code.splitlines() if l.lstrip().startswith(("for p in", "run_teardown 0")))
    order = ["04_verifier_human_in_the_loop", "03_agent_as_tool", "02_orchestrator_worker", "01_router_handoff",
             "06_skill_composition", "05_mcp_agent_chaining", "00_common"]
    positions = [code.index(p) for p in order]
    assert positions == sorted(positions), "teardown は依存の逆順（04→03→02→01→06→05→00）で行う"
