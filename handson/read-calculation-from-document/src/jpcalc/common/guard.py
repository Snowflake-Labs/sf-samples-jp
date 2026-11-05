"""正解漏れガード（正解の隔離の 2 層目。1 層目は入力口、3・4 層目はステージマウントとロール分離）。

src/jpcalc/ のうち eval/ を除くすべてのモジュール（予測側）を AST で読み、次を検査する。新しく足したモジュールも
既定で対象になる。禁止名の正本は configs/guard.yaml で、ここには名前を書かない。

1. 評価側のモジュール（`forbidden_imports`。既定 `jpcalc.eval`）を import していない。
   入口のモジュールでは、EVAL_LAUNCHERS に挙げた関数の中だけで import してよい。
2. 動的な import（`importlib`・`__import__`）を使っていない（文字列で eval を指す抜け道を塞ぐ）。
3. docstring 以外の文字列・bytes のリテラルに、正解のファイル名・ディレクトリと、評価側のモジュール名が無い。
   照合は大文字小文字を区別せず、`\\` を `/` とみなし、境界つきにする：
   - ファイル名：前が文字列の先頭か `/`、後ろが文字列の末尾か英数字・`_`・`.` 以外のとき一致
     （`public_index.jsonl` は `index.json` に一致しない）。
   - `strict_dir_names`（calc・answers・views）：文字列全体がその名前か、`name/` で始まるか、`/name/`・`/name`
     を含むとき一致（`Path(root) / "calc"` を捕まえる）。
   - `boundary_dir_parts`（tests/・programs/・pages/）：`x/` で始まるか `/x/` を含むときだけ一致
     （語としての tests は通す）。

**保証の強さ：** AST 検査による弱い保証である。文字列の連結・f-string・設定から組み立てたパスなど、
実行時に作った文字列は検出できない。予測ジョブのステージマウントとロール分離で補強する。
"""

from __future__ import annotations

import ast
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .paths import GUARD_YAML, HOME, SRC

EVAL_PACKAGE = "eval"
# 評価を起動する入口の関数（モジュールの SRC からの相対パス → 関数名）。ここでだけ jpcalc.eval の import を許す
EVAL_LAUNCHERS: dict[str, frozenset[str]] = {
    "cli.py": frozenset(
        {
            "_cmd_index",
            "_cmd_fetch_gold",
            "_cmd_read_score",
            "_cmd_make_shots",
            "_cmd_eval",
            "_cmd_eval_job",
            "_cmd_upload_gold",
            "_cmd_export_results",
            "_eval_report",
        }
    ),
}
_DYNAMIC_IMPORT_MODULES = ("importlib",)
_DYNAMIC_IMPORT_CALLS = ("__import__", "import_module")


@dataclass
class GuardResult:
    violations: list[str] = field(default_factory=list)
    checks_run: list[str] = field(default_factory=list)
    modules: int = 0

    @property
    def ok(self) -> bool:
        return not self.violations


@dataclass(frozen=True)
class GuardRules:
    forbidden_names: tuple[str, ...]
    strict_dir_names: tuple[str, ...]
    boundary_dir_parts: tuple[str, ...]
    forbidden_imports: tuple[str, ...]

    @classmethod
    def load(cls, path: Path = GUARD_YAML) -> GuardRules:
        from ..config import load_guard_config

        g = load_guard_config(path)
        return cls(g.forbidden_names, g.strict_dir_names, g.boundary_dir_parts, g.forbidden_imports)


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(HOME))
    except ValueError:
        return str(path)


def predict_modules(src: Path = SRC) -> list[Path]:
    """予測側のモジュール：src 配下の全 .py から eval/ の下を除いたもの。"""
    return sorted(p for p in src.rglob("*.py") if p.relative_to(src).parts[0] != EVAL_PACKAGE)


def _parse(res: GuardResult, path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as e:
        res.violations.append(f"{_rel(path)}: 構文エラー: {e}")
        return None


# ---- 1・2. import ----------------------------------------------------------------------------


def _module_pkg(path: Path, src: Path) -> str:
    """相対 import の基準になるパッケージ名（src の名前を最上位にする）。"""
    parts = [src.name, *path.relative_to(src).with_suffix("").parts]
    return ".".join(parts[:-1])


def _resolve(node: ast.Import | ast.ImportFrom, module_pkg: str) -> list[str]:
    """import 文が指すモジュール名（絶対名）の一覧。相対 import は module_pkg を基準に解決する。"""
    if isinstance(node, ast.Import):
        return [a.name for a in node.names]
    base = node.module or ""
    if node.level:
        parts = module_pkg.split(".")
        parent = parts[: len(parts) - (node.level - 1)]
        base = ".".join([*parent, base] if base else parent)
    return [base, *(f"{base}.{a.name}" for a in node.names)]


def _hits_forbidden(names: Iterable[str], forbidden: tuple[str, ...]) -> str | None:
    for n in names:
        for f in forbidden:
            if n == f or n.startswith(f + "."):
                return n
    return None


def _is_dynamic_import(node: ast.AST, pkg: str) -> str | None:
    if isinstance(node, ast.Import | ast.ImportFrom):
        names = _resolve(node, pkg)
        hit = _hits_forbidden(names, _DYNAMIC_IMPORT_MODULES)
        return hit
    if isinstance(node, ast.Call):
        f = node.func
        name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
        if name in _DYNAMIC_IMPORT_CALLS:
            return f"{name}(...)"
    return None


def check_imports(res: GuardResult, rules: GuardRules, src: Path = SRC) -> None:
    res.checks_run += ["no_eval_import", "no_dynamic_import"]
    for path in predict_modules(src):
        tree = _parse(res, path)
        if tree is None:
            continue
        pkg = _module_pkg(path, src)
        allowed = EVAL_LAUNCHERS.get(str(path.relative_to(src)), frozenset())
        for top in tree.body:
            fname = top.name if isinstance(top, ast.FunctionDef | ast.AsyncFunctionDef) else None
            where = f"関数 {fname}" if fname else "モジュールの先頭"
            for node in ast.walk(top):
                dyn = _is_dynamic_import(node, pkg)
                if dyn:
                    res.violations.append(
                        f"{_rel(path)}:{node.lineno} {where}で動的な import を使っている: {dyn}"
                    )
                if fname in allowed:
                    continue
                if isinstance(node, ast.Import | ast.ImportFrom):
                    hit = _hits_forbidden(_resolve(node, pkg), rules.forbidden_imports)
                    if hit:
                        res.violations.append(
                            f"{_rel(path)}:{node.lineno} {where}で評価側を import している: {hit}"
                        )


# ---- 3. 文字列 -------------------------------------------------------------------------------


def _patterns(rules: GuardRules) -> list[tuple[str, re.Pattern[str]]]:
    out = [
        (n, re.compile(r"(?:^|/)" + re.escape(n.lower()) + r"(?![a-z0-9_.])"))
        for n in rules.forbidden_names
    ]
    out += [
        (d, re.compile(r"(?:^|/)" + re.escape(d.lower()) + r"(?:/|$)"))
        for d in rules.strict_dir_names
    ]
    out += [(p, re.compile(r"(?:^|/)" + re.escape(p.lower()))) for p in rules.boundary_dir_parts]
    out += [
        (m, re.compile(r"(?:^|[^a-z0-9_])" + re.escape(m.lower()) + r"(?![a-z0-9_])"))
        for m in rules.forbidden_imports
    ]
    return out


def find_forbidden(text: str, rules: GuardRules) -> list[str]:
    """文字列に含まれる禁止名・禁止ディレクトリ・評価側のモジュール名（境界つき）。"""
    norm = text.replace("\\", "/").lower()
    return [label for label, rx in _patterns(rules) if rx.search(norm)]


def _docstrings(tree: ast.AST) -> set[int]:
    """docstring として使われている文字列定数の id（正解の話を *書く* ことは禁じない）。"""
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                out.add(id(body[0].value))
    return out


def check_strings(res: GuardResult, rules: GuardRules, src: Path = SRC) -> None:
    res.checks_run.append("no_gold_names")
    for path in predict_modules(src):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue  # check_imports で報告済み
        docs = _docstrings(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or id(node) in docs:
                continue
            value = node.value
            if isinstance(value, bytes):
                value = value.decode("utf-8", errors="ignore")
            if not isinstance(value, str):
                continue
            for bad in find_forbidden(value, rules):
                res.violations.append(
                    f"{_rel(path)}:{node.lineno} 正解側の名前を参照している: {bad!r}"
                )


def run_guard(src: Path = SRC, rules: GuardRules | None = None) -> GuardResult:
    rules = rules or GuardRules.load()
    res = GuardResult(modules=len(predict_modules(src)))
    check_imports(res, rules, src)
    check_strings(res, rules, src)
    return res


def main(argv: list[str] | None = None) -> int:
    res = run_guard()
    print(f"guard: checks={','.join(res.checks_run)} modules={res.modules}")
    if res.ok:
        print("guard: OK — 正解漏れの兆候なし（AST 検査による弱い保証。ロール分離で補強する）")
        return 0
    print(f"guard: FAIL — {len(res.violations)} 件の違反", file=sys.stderr)
    for v in res.violations:
        print(f"  - {v}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
