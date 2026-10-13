"""正解漏れガード。

変更点：供出元の検査をコーパスごとの設定（configs/corpora/*.yaml）と configs/shots/<corpus>/ で行う。
       read/ の場所と禁止名を jpdocread.common.paths から取る。AST の検査ロジックは変えていない。
       read/ の外にある予測経路の入口（jobs.py・worker.py）の検査（4）を足した。

4 つを検査し、1 つでも落ちたら exit 1。

1. `read/` が `eval/` を import していない（AST 走査。文字列 grep より確実）
2. `read/` が正解ファイル名・ページ画像のディレクトリ名を参照していない（docstring は除く）
3. 図の few-shot 供出元が評価から除外され、shot の期待 JSON が供出元のものだけである
4. 予測経路の入口（S30・S50 の `jobs.py`、ローカル読み取りの `worker.py`）が、採点側の関数
   （`cmd_s60`・`_task_eval`）の中でしか `eval` を import していない

**保証の強さ：** これは AST 検査と module 分離による弱い保証である。Snowflake 側はロール分離
（予測ロールは評価 DB を読めない）で補強する（scripts/verify_roles.sh）。強い保証があるふりをしない。
"""

from __future__ import annotations

import ast
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .paths import CONFIGS, FORBIDDEN_DOC_PATHS, FORBIDDEN_GOLD_FILES, HOME

READ_PKG = HOME / "src" / "jpdocread" / "read"
# read/ の外にある予測経路の入口（S30・S50 のジョブと、ローカル読み取りの作業プロセス）。
# 同じモジュールに採点側の入口もあるので、eval を import してよい関数を名前で限る
ENTRY_MODULES: dict[Path, frozenset[str]] = {
    HOME / "src" / "jpdocread" / "jobs.py": frozenset({"cmd_s60"}),
    HOME / "src" / "jpdocread" / "worker.py": frozenset({"_task_eval"}),
}
SHOTS_DIR = CONFIGS / "shots"


@dataclass
class GuardResult:
    violations: list[str] = field(default_factory=list)
    checks_run: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # 違反ではないが、通った理由として知らせること

    @property
    def ok(self) -> bool:
        return not self.violations


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(HOME))
    except ValueError:
        return str(path)


def _iter_read_modules(root: Path | None = None) -> list[Path]:
    root = root or READ_PKG
    if not root.exists():
        return []
    return sorted(root.rglob("*.py"))


def _targets_eval(node: ast.Import | ast.ImportFrom) -> str | None:
    """この import 文が eval パッケージを指しているなら、その表記を返す。

    `import x.eval.y` / `from x.eval import y` / `from ..eval import z` / `from . import eval` を捕まえる。
    組み込みの `eval` 呼び出しは import ではないので対象外。
    """
    if isinstance(node, ast.Import):
        for alias in node.names:
            if "eval" in alias.name.split("."):
                return alias.name
        return None
    module = node.module or ""
    if module and "eval" in module.split("."):
        return f"{'.' * node.level}{module}"
    for alias in node.names:
        if alias.name == "eval":
            return f"{'.' * node.level}{module} :: {alias.name}"
    return None


def check_no_eval_import(res: GuardResult, root: Path | None = None) -> None:
    """read/ が eval/ を import していないこと。AST で判定する。"""
    res.checks_run.append("no_eval_import")
    if not _iter_read_modules(root):
        res.notes.append(
            f"{_rel(root or READ_PKG)} に検査対象が無い（read/ の移植前は検査 1・2 が空で通る）"
        )
    for path in _iter_read_modules(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as e:
            res.violations.append(f"{_rel(path)}: syntax error: {e}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import | ast.ImportFrom):
                hit = _targets_eval(node)
                if hit:
                    res.violations.append(f"{_rel(path)}:{node.lineno} imports eval module: {hit}")


def check_entry_modules(
    res: GuardResult, modules: dict[Path, frozenset[str]] | None = None
) -> None:
    """予測経路の入口のモジュールで、eval の import が採点側の関数の中だけにあること。

    モジュールの先頭で import すると、S30・S50・ローカル読み取りの経路でも eval が読み込まれる。
    """
    res.checks_run.append("entry_modules")
    for path, allowed in (modules if modules is not None else ENTRY_MODULES).items():
        if not path.exists():
            res.violations.append(f"{_rel(path)}: 検査対象のモジュールが無い")
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for top in tree.body:
            name = top.name if isinstance(top, ast.FunctionDef | ast.AsyncFunctionDef) else None
            if name in allowed:
                continue
            for node in ast.walk(top):
                if isinstance(node, ast.Import | ast.ImportFrom):
                    hit = _targets_eval(node)
                    if hit:
                        where = f"関数 {name}" if name else "モジュールの先頭"
                        res.violations.append(
                            f"{_rel(path)}:{node.lineno} {where}で eval を import している: {hit}"
                            f"（許すのは {', '.join(sorted(allowed))} の中だけ）"
                        )


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """docstring として使われている文字列定数の id 集合。

    ガードの目的は正解を *読む* コードを禁じることで、正解の話を *書く* ことではない。
    `#` コメントは AST に現れないので最初から免除されている。docstring だけを同じ扱いにする。
    """
    out: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            out.add(id(first.value))
    return out


def check_no_gold_filenames(res: GuardResult, root: Path | None = None) -> None:
    """read/ のソースに正解ファイル名の文字列リテラルが無いこと（docstring は除く）。"""
    res.checks_run.append("no_gold_filenames")
    for path in _iter_read_modules(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue  # check_no_eval_import で報告済み
        docs = _docstring_nodes(tree)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docs
            ):
                for bad in FORBIDDEN_GOLD_FILES + FORBIDDEN_DOC_PATHS:
                    if bad in node.value:
                        res.violations.append(
                            f"{_rel(path)}:{node.lineno} references gold file {bad!r}"
                        )


def check_donors_excluded(res: GuardResult, shots_dir: Path = SHOTS_DIR) -> None:
    """コーパスごとに、供出元が 2 件で評価除外に入り、shot の期待 JSON が供出元のものだけであること。"""
    from ..config import ConfigError, available_corpora, load_corpus_config

    res.checks_run.append("donors_excluded")
    for name in available_corpora():
        try:
            cfg = load_corpus_config(name)  # 評価除外・pilot との矛盾は設定の検証で落ちる
        except ConfigError as e:
            res.violations.append(str(e))
            continue
        donors = set(cfg.figure_shots)
        if len(donors) != 2:
            res.violations.append(f"{name}: figure_shots が 2 件でない: {sorted(donors)}")
        # shot の文書は JSON の doc_id で判定する（ファイル名 figure__<doc_id>__<figure_id> の分割に頼らない）
        shots = {
            json.loads(p.read_text(encoding="utf-8")).get("doc_id")
            for p in (shots_dir / name).glob("figure__*.json")
        }
        if shots - donors:
            res.violations.append(
                f"{name}: shots に供出元以外の文書がある: {sorted(shots - donors)}"
            )


def run_guard(root: Path | None = None) -> GuardResult:
    res = GuardResult()
    check_no_eval_import(res, root)
    check_no_gold_filenames(res, root)
    check_entry_modules(res)
    check_donors_excluded(res)
    return res


def main(argv: list[str] | None = None) -> int:
    res = run_guard()
    print(f"guard: checks={','.join(res.checks_run)} modules={len(_iter_read_modules())}")
    for note in res.notes:
        print(f"guard: 注意 — {note}")
    if res.ok:
        print("guard: OK — 正解漏れの兆候なし")
        print(
            "guard: 注意 — これは AST 検査と module 分離による弱い保証である。"
            "Snowflake 側はロール分離（予測ロールは評価 DB を読めない）で補強する"
        )
        return 0
    print(f"guard: FAIL — {len(res.violations)} 件の違反", file=sys.stderr)
    for v in res.violations:
        print(f"  - {v}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
