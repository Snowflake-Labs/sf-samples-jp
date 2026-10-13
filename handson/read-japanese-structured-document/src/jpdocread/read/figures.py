"""P4 — 図の構造化。

変更点：`AI_COMPLETE` の呼び出しは S40（SQL プロシージャ）に移した。このモジュールは
(1) S40 に渡すプロンプト本文と shot 引数を組み立て、(2) 生出力を解析し、(3) 成果物用に
グラフを整える。規則本文・語彙・max_tokens の係数・解析手順は親から変えていない。

領域クロップ 1 枚 → node/edge グラフ JSON。**表とは別のプロンプト・別のスキーマ**（F8）。

**表と共有しない理由：** F4/F8 より、格子スキーマとグラフスキーマを 1 つのプロンプトに
混ぜると壊れる。`tables.py` と重複するコードがあっても分けておく。

**`paths` は LLM に出させない。** グラフから機械的に計算する（§5.5）。
**採点は id ではなくラベルで行う**（F9）ので、id の付け方は自由にさせる。

**予測側のモジュールである。** gold を開いてはならない。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from ..common.paths import CONFIGS, SHOTS, WORK


def _configured_model() -> str:
    """図のモデル名。`configs/pipeline.yaml` の `figure.model` が唯一の出所（W17-E で採用）。"""
    import yaml

    return yaml.safe_load((CONFIGS / "pipeline.yaml").read_text(encoding="utf-8"))["figure"][
        "model"
    ]


MODEL_DEFAULT = _configured_model()
FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.S)


def strip_fence(s: str) -> str:
    """コードフェンスを剥がす。**モデルに関わらず必ず通す**（F19）。"""
    m = FENCE.match(s)
    return m.group(1) if m else s


PROMPT_VERSION = "p4_graph_v2"  # T4：figure_type を先に決めさせ role を型別語彙に限定
# 図の出力量はセル数のような線形の目安が無いので実測で定める（§6.3）。
# **実測（T2）**：`fig_claim_flow`（gold 11 要素）の生出力は 1,516 文字、
# すなわち **約 138 文字/要素**。60 では下限 4,096 に張り付き、
# `fig_structure`（gold 49 要素、必要量 約 6,200 文字）が**切断され**
# JSONDecodeError として現れた（22 件中 5 件）。表で `max_tokens = セル数 × 46`
# が薄すぎたのと**同じ欠陥**である。日本語は 1 文字 ≒ 1 トークンとみて
# 実測 138 に余裕を足す。**切断は「壊れた JSON」として現れ、原因が見えにくい。**
TOKENS_PER_ELEM = 180
MIN_MAX_TOKENS = 4096

# **プロンプト本文に `{` を書かない**（F7）。スキーマは shot の期待 JSON に担わせる。
RULES = (
    "あなたは日本語の保険約款に載る図を読み取る。入力は図 1 つだけを切り出した画像である。"
    "図の構造を JSON で出力せよ。\n"
    "出力の最上位は次の 5 つのキーを持つ object とする："
    "figure_type（下の語彙から 1 つ）、n_nodes（ノード数）、n_edges（辺の数）、"
    "nodes（配列）、edges（配列）。\n"
    "nodes の各要素は次の 4 つのキーを持つ object とする："
    "id（あなたが付ける短い識別子）、label（図に印字されている文字をそのまま写した文字列）、"
    "role（下の語彙から 1 つ）、shape（下の語彙から 1 つ）。\n"
    "edges の各要素は次の 4 つのキーを持つ object とする："
    "from（始点ノードの id）、to（終点ノードの id）、"
    "relation（下の語彙から 1 つ）、label（辺に印字された文字。無ければ null）。\n"
    # T4 の実測：role は 19 値の平坦な語彙ではなく、**図の型ごとに排他的な部分集合**である。
    # 型を先に選ばせ、その型の語彙だけを使わせる。平坦な 9 値を与えていた版は
    # 上限 0.5960 を自分で作っていた（gold に存在しない group を含んでいた）。
    "figure_type の語彙と、その型で使える role：\n"
    "  tree（木・階層図）      : role は tree、note のみ\n"
    "  flow（流れ図）          : role は start、process、decision、end、document のみ\n"
    "  timeline（時系列・帯）  : role は event、span、tick のみ\n"
    "  checklist（手順・確認）  : role は step、ask、doc、detail のみ\n"
    "  form（帳票・記入欄）    : role は field、legend のみ\n"
    "  tablemock（表の模式図） : role は row、col、cell、legend のみ\n"
    "shape の語彙：rect、rounded、diamond、ellipse、arrow、line、none。\n"
    "relation の語彙：child、next、flow、ref、maps_to、spans、at。\n"
    "規則：\n"
    "1. label は図に**実際に印字されている文字だけ**を写す。推測で言葉を足してはならない。\n"
    "2. 矢印や線で結ばれていないノード同士を、位置が近いだけで結んではならない。\n"
    "3. 線が交差している場合、どの端点とどの端点がつながっているかを線の向きに沿って辿る。"
    "交差点で線を乗り換えてはならない。\n"
    "4. 同じ 2 ノードを結ぶ辺を重複して出してはならない。"
    "自分自身に戻る辺を作ってはならない。\n"
    "5. **まず figure_type を 1 つ決め、role はその型に挙げた語だけを使う。**"
    "他の型の語を混ぜてはならない。迷ったら最も多くのノードに当てはまる型を選ぶ。\n"
    "6. 図の外にある注記・凡例は、その型に note か legend があればそれを使う。"
    "無ければノードに含めない。\n"
    "7. n_nodes と n_edges は、実際に出力した nodes と edges の要素数と一致させる。\n"
    "8. 日本語の文字はそのまま写す。全角の括弧・丸数字を半角に置き換えてはならない。\n"
    "9. 出力は JSON のみ。説明文を付けてはならない。コードフェンスも付けてはならない。\n"
    "10. 例と完全に同じキー名・階層・型を使うこと。\n"
    "例1の画像: {0}\n例1の正解: {1}\n例2の画像: {2}\n例2の正解: {3}\n対象画像: {4}"
)

# T4 で測った型→role の対応。採点や検算に使う（プロンプトと同じ表を二重に書かない）。
ROLE_BY_TYPE: dict[str, set[str]] = {
    "tree": {"tree", "note"},
    "flow": {"start", "process", "decision", "end", "document"},
    "timeline": {"event", "span", "tick"},
    "checklist": {"step", "ask", "doc", "detail"},
    "form": {"field", "legend"},
    "tablemock": {"row", "col", "cell", "legend"},
}


@dataclass
class FigureOut:
    region_id: str
    doc_id: str
    rel_path: str
    max_tokens: int
    nodes: list[dict] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)
    n_nodes_decl: int = 0
    n_edges_decl: int = 0
    figure_type: str | None = None  # T4：モデルが宣言した図の型
    n_role_off_vocab: int = 0  # 宣言した型の語彙から外れた role の数
    raw_chars: int = 0
    err: str | None = None
    raw_tail: str | None = None  # parse 失敗時の生出力末尾（切断の判別用）
    query_id: str | None = None


def _infer_type(roles: set[str]) -> str:
    """gold の role 集合から figure_type を決める。**例の型を推測で埋めてはならない。**

    T4 の実測どおり role 集合は型ごとに排他なので、包含する型が一意に決まる。
    決まらない場合は例として使えないので **raise する**。`role or "tree"` の
    ような黙った既定値を置くと、例と規則が食い違ったまま気づけない（F19 の轍）。
    """
    cands = [t for t, vocab in ROLE_BY_TYPE.items() if roles <= vocab]
    if len(cands) == 1:
        return cands[0]
    raise ValueError(
        f"figure_type が一意に決まらない role 集合: {sorted(roles)} → 候補 {cands}。"
        "ROLE_BY_TYPE を gold に合わせて見直すこと（T4 の型表を参照）。"
    )


def _shot_args() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for p in sorted(SHOTS.glob("figure__*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        if not d.get("crop") or not (d.get("graph") or {}).get("nodes"):
            continue
        g = d["graph"]
        roles = {n.get("role") for n in g["nodes"] if n.get("role")}
        if len(roles) != len({n.get("role") for n in g["nodes"]}):
            raise ValueError(f"{p.name}: role が欠けたノードがある。例には使えない")
        expected = {
            "figure_type": _infer_type(roles),
            "n_nodes": len(g["nodes"]),
            "n_edges": len(g.get("edges") or []),
            "nodes": [
                {
                    "id": n.get("id"),
                    "label": n.get("label"),
                    "role": n["role"],
                    "shape": n.get("shape") or "rect",
                }
                for n in g["nodes"]
            ],
            "edges": [
                {
                    "from": e.get("from"),
                    "to": e.get("to"),
                    "relation": e.get("relation") or "flow",
                    "label": e.get("label"),
                }
                for e in (g.get("edges") or [])
            ],
        }
        out.append((d["crop"], json.dumps(expected, ensure_ascii=False, separators=(",", ":"))))
    return out


def max_tokens_for(n_elems: int) -> int:
    return max(MIN_MAX_TOKENS, int(n_elems) * TOKENS_PER_ELEM)


def prompt_spec() -> dict:
    """S40 の SQL に渡すプロンプト本文と shot（例のクロップと期待 JSON）を返す。

    **プロンプト本文に素の `{` を書かない**（F7）。`{0}`〜`{4}` のプレースホルダだけを持つ。
    shot のクロップは S30 が供出元 PDF から作ったものを使う（親と同じ `regions.py` の手順）。
    """
    shots = _shot_args()
    if len(shots) < 2:
        raise RuntimeError("図 shot が 2 件揃っていない（クロップ付きが必要）。")
    body = RULES
    if re.search(r"\{(?!\d\})", body):
        raise ValueError("プロンプト本文にプレースホルダ以外の { がある（F7）")
    return {
        "prompt_version": PROMPT_VERSION,
        "model": MODEL_DEFAULT,
        "rules": body,
        "shot_crops": [shots[0][0], shots[1][0]],
        "shot_jsons": [shots[0][1], shots[1][1]],
    }


def parse_raw(
    rel_path: str,
    raw: str | None,
    max_tokens: int,
    query_id: str | None = None,
    sql_error: str | None = None,
) -> FigureOut:
    """S40 の生出力 1 件を解析する（移植元の `extract_figure` の後半と同じ手順）。"""
    out = FigureOut(
        region_id=rel_path,
        doc_id=rel_path.split("/")[0],
        rel_path=rel_path,
        max_tokens=max_tokens,
        query_id=query_id,
    )
    if sql_error:
        out.err = f"sql_error: {sql_error}"
        return out
    if raw is None:
        out.err = "null_output"
        return out
    out.raw_chars = len(raw)
    try:
        obj = json.loads(strip_fence(raw))
        if isinstance(obj, str):
            obj = json.loads(strip_fence(obj))
    except Exception as e:  # noqa: BLE001
        # **切断は壊れた JSON として現れる。** 生出力の末尾を残す（T2）。
        out.err = f"parse_error: {type(e).__name__}"
        out.raw_tail = raw[-160:]
        return out
    if not isinstance(obj, dict):
        out.err = f"unexpected_type: {type(obj).__name__}"
        return out
    out.nodes = [n for n in (obj.get("nodes") or []) if isinstance(n, dict)]
    out.edges = [e for e in (obj.get("edges") or []) if isinstance(e, dict)]
    out.n_nodes_decl = int(obj.get("n_nodes") or 0)
    out.n_edges_decl = int(obj.get("n_edges") or 0)
    out.figure_type = obj.get("figure_type")
    vocab = ROLE_BY_TYPE.get(out.figure_type or "")
    if vocab is not None:
        out.n_role_off_vocab = sum(1 for n in out.nodes if n.get("role") not in vocab)
    if not out.nodes:
        out.err = "no_nodes"
    return out


def label_edges(nodes: list[dict], edges: list[dict]) -> set[tuple[str, str, str]]:
    """辺を (始点ラベル, 終点ラベル, 辺ラベル) の三つ組に書き換える（F9）。

    モデルは独自 id を発明するので、**id 基準の比較は偽の失敗を報告する**。
    """
    by_id = {n.get("id"): (n.get("label") or "") for n in nodes}
    out = set()
    for e in edges:
        a, b = by_id.get(e.get("from")), by_id.get(e.get("to"))
        if a is None or b is None:
            continue
        out.add((a, b, e.get("label") or ""))
    return out


def paths_from_graph(nodes: list[dict], edges: list[dict], max_depth: int = 8) -> list[list[str]]:
    """根→葉の経路をラベル列として**機械的に**計算する（§5.5：LLM に列挙させない）。"""
    by_id = {n.get("id"): (n.get("label") or "") for n in nodes}
    adj: dict[str, list[str]] = {}
    indeg: dict[str, int] = {i: 0 for i in by_id}
    for e in edges:
        a, b = e.get("from"), e.get("to")
        if a in by_id and b in by_id:
            adj.setdefault(a, []).append(b)
            indeg[b] = indeg.get(b, 0) + 1
    roots = [i for i in by_id if indeg.get(i, 0) == 0]
    out: list[list[str]] = []

    def walk(node: str, acc: list[str], seen: set[str]) -> None:
        if len(acc) > max_depth:
            return
        nxt = [c for c in adj.get(node, []) if c not in seen]
        if not nxt:
            out.append([by_id[n] for n in acc])
            return
        for c in nxt:
            walk(c, acc + [c], seen | {c})

    for r in roots:
        walk(r, [r], {r})
    return out


def out_path(tag: str):
    d = WORK / "figures"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{tag}.json"


def write_figures(results: list[FigureOut], tag: str) -> str:
    p = out_path(tag)
    p.write_text(
        json.dumps([r.__dict__ for r in results], ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return str(p)


# ---------------------------------------------------------------- 保存と成果物化（W17-E・W17-F）

# D-10 = 2 値：`note`・`legend`・`tick` を注記、それ以外を経路のノードとする（W1 T3 と同じ写像）。
NOTE_ROLES = frozenset({"note", "legend", "tick"})


def fold_role(role: str | None) -> str:
    """図ノードの `role` を 2 値（`tree` / `note`）に畳む（D-10）。"""
    return "note" if (role or "") in NOTE_ROLES else "tree"


def read_figures(tag: str) -> dict[str, dict]:
    """`write_figures` で保存した抽出結果を `rel_path` で引く。"""
    p = out_path(tag)
    if not p.exists():
        return {}
    return {r["rel_path"]: r for r in json.loads(p.read_text(encoding="utf-8"))}


def graph_for_out(nodes: list[dict], edges: list[dict]) -> dict:
    """成果物用のグラフ：`role` を 2 値に畳み、注記を除いたノードで経路を機械的に出す。"""
    ns = [{**n, "role": fold_role(n.get("role"))} for n in nodes]
    tree_ids = {n.get("id") for n in ns if n["role"] == "tree"}
    es = [e for e in edges if e.get("from") in tree_ids and e.get("to") in tree_ids]
    return {
        "nodes": ns,
        "edges": list(edges),
        "paths": paths_from_graph([n for n in ns if n["role"] == "tree"], es),
    }
