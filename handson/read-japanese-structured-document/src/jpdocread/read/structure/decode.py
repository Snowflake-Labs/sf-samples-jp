"""大域デコード（T9・D1）。

候補とスコアから**見出しの採用集合を全体最適で決める**。

目的関数：`Σ s_i − λ_gap·(番号の飛び) − λ_toc·(目次の未照合) − λ_nest·(入れ子違反)`

**逐次法に対する本質的な改善点は、1 つの見出しの誤読が以降の全段落に伝播せず、
局所的なペナルティとして吸収されること**である。

制約（§5.6(5)）：

- 同一レベルの番号はスコープ内で単調増加（枝番と「第○条 削除」の穴は許容）
- リセットは親境界が開いた直後のみ
- レベル ℓ は開いている ℓ−1 の下のみ

**`greedy` を必ず並走させる**（E7b）。差が消えるなら制約が効いていないので、
祝わずに原因を調べる。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .candidates import Candidate

# レベル：1=編 2=章 3=節 4=条。0 は根（別表・特約）で番号制約を持たない。
MAX_LEVEL = 4

# λ。**P20 で調整し PILOT で報告する**（T10）。
#
# `nest` のみ W3 A4 で 1.5 → 0.8 に変更した。**手続きは T10 と同じ**：
# 非 PILOT の 29 文書で走査し、PILOT を held-out として報告する。
# 調整集合は 0.8 を選び、**held-out でも改善が再現した**
# （段落 recall 0.5000 → 0.5735、条 recall 0.6752 → 0.6785）。
# T10 で調整が転移しなかったのは `nest` の意味が壊れていたためで
# （すべての章に孤児の罰が課されていた・`_accept_cost` 参照）、
# **欠陥を直してから調整すると転移する**。順序が逆だと平坦な目的関数を
# 走査して「調整は効かない」と誤結論する。
LAMBDA = {
    "gap": 0.6,  # 番号が飛んだぶん 1 つあたり
    "toc": 2.0,  # 目次にあるのに採用されなかった項目 1 つあたり（目次の適合率は 1.0 なので重い）
    "nest": 0.8,  # 入れ子違反 1 件あたり（上記のとおり held-out で確認）
    "reset": 0.8,  # 親境界の直後でないリセット 1 件あたり
}


@dataclass(frozen=True)
class State:
    """開いている各レベルの最後の番号。0 は「まだ開いていない」。

    **不変にしておく**（DP の辞書のキーにするため）。
    """

    nums: tuple[int, ...] = (0,) * (MAX_LEVEL + 1)
    just_opened: int = 0  # 直前に開いたレベル（リセットの合法性判定に使う）

    def with_accept(self, level: int, num: int) -> State:
        n = list(self.nums)
        n[level] = num
        for deeper in range(level + 1, MAX_LEVEL + 1):
            n[deeper] = 0  # 親が進んだら子はリセットされる
        return State(tuple(n), just_opened=level)


@dataclass
class Decision:
    cand: Candidate
    accepted: bool
    penalty: float = 0.0
    reason: str = ""


@dataclass
class DecodeResult:
    accepted: list[Candidate]
    total_score: float
    n_gap: int = 0
    n_nest: int = 0
    n_reset: int = 0
    n_toc_unmatched: int = 0
    trace: list[Decision] = field(default_factory=list)

    @property
    def accepted_keys(self) -> set[tuple[str, int, int]]:
        return {(c.kind, c.num, c.page) for c in self.accepted if c.num is not None}


def _accept_cost(
    st: State,
    level: int,
    num: int,
    lam: dict[str, float],
    levels_in_use: frozenset[int] = frozenset({1, 2, 3, 4}),
) -> tuple[float, str, int]:
    """この候補を採用したときの罰と、飛んだ番号の数を返す。

    **採用を禁止しない。** 罰として表現する。禁止すると、読み落としがあったときに
    デコーダが正しい列を組めなくなる（§1.10：番号を整えない、とも整合する）。

    `levels_in_use` は**その文書が実際に使っているレベル**。既定は全レベル。
    """
    pen = 0.0
    reason = ""
    gaps = 0
    # **レベルの飛ばしを罰してはならない。**
    #
    # §5.6(5) の「レベル ℓ は開いている ℓ−1 の下のみ」は、全レベルが存在する文書を
    # 前提にした書き方である。実在の版式はレベルを飛ばす。`auto-0001` の第 1〜4 章は
    # **節を持たず、章の直下に条**が来る（第 5 章だけが節を持つ）。
    #
    # 直前の実装は条（レベル 4）に節（レベル 3）を要求した。その結果、章を採用すると
    # 以降のすべての条に入れ子違反 1.5 が課され、**DP は「章を全部捨てる」方が
    # 得だと判断した**。実測：gold の章 1〜4 が丸ごと落ち、再現が 1.000 → 0.750 に
    # 下がった（λ=0 では 1.000 に戻ったので、罰そのものが原因だと分かった）。
    #
    # よって罰するのは「**どの上位レベルも開いていない**のに深いレベルが来た」場合
    # だけにする。飛ばし自体は正常な版式である。
    #
    # **さらに W3 A4 で 2 つめの同型の誤りを見つけた。** 上の修正でもまだ
    # 「その文書に存在しないレベル」を要求していた。`golf` と `auto` は編を持たない
    # ので、章（レベル 2）には常に `nums[1] == 0`（編が開いていない）が成り立ち、
    # **すべての章に孤児の罰 1.5 が課されていた**。DP は章を捨てるほうが得だと判断し、
    # `golf` の章は 10 候補中 2 件しか採用されず、条 recall が 0.862 → 0.172 に落ちた。
    # 罰の対象は「**その文書が実際に使っているより浅いレベル**が 1 つも開いていない」
    # 場合だけである。最上位のレベルは定義上どこにも属さない。
    shallower = {lv for lv in levels_in_use if lv < level}
    if shallower and not any(st.nums[lv] for lv in shallower):
        pen += lam["nest"]
        reason += "orphan "
    last = st.nums[level]
    if last == 0:
        # リセット（新しくこのレベルを開く）。番号 1 で始まるのが正常。
        if num != 1:
            pen += lam["reset"]
            reason += "reset "
        # 親境界の直後でないリセットも罰する（§5.6(5)）。
        # **ここも飛ばしを許す。** 章の直下に条が来る版式では `just_opened` は 2
        # だが `level - 1` は 3 なので、厳密に比べると正常な版式を罰してしまう。
        # 「直前に開いたのが自分より浅いレベルであればよい」とする。
        if level >= 2 and not (0 <= st.just_opened < level):
            pen += lam["reset"]
            reason += "reset_pos "
    elif num <= last:
        pen += lam["nest"]
        reason += "nonmono "
    else:
        gaps = num - last - 1
        if gaps > 0:
            pen += lam["gap"] * gaps
            reason += f"gap{gaps} "
    return pen, reason.strip(), gaps


def decode_global(
    cands: list[Candidate],
    toc=None,
    lam: dict[str, float] | None = None,
    beam: int = 24,
) -> DecodeResult:
    """位置順のビーム DP。**位置は候補の `pos` 昇順。**

    ビーム幅は 24。候補数は 1 文書あたり数十〜数百なので厳密解も可能だが、
    状態が `(編, 章, 節, 条)` の 4 次元になるためビームで十分である。
    """
    lam = lam or LAMBDA
    numbered = [c for c in cands if c.num is not None and 1 <= c.level <= MAX_LEVEL]
    roots = [c for c in cands if c.num is None or c.level == 0]
    # **その文書が実際に使っているレベル。** 存在しないレベルを親として要求しないため
    # （`_accept_cost` の孤児判定）。候補から採るので gold は使わない。
    levels = frozenset(c.level for c in numbered) or frozenset({1, 2, 3, 4})

    # ビーム：state -> (累積スコア, 採用列, 集計)
    Beam = dict[State, tuple[float, list[Candidate], tuple[int, int, int]]]
    beams: Beam = {State(): (0.0, [], (0, 0, 0))}

    for c in sorted(numbered, key=lambda x: x.pos):
        nxt: Beam = {}

        def put(st: State, sc: float, acc: list[Candidate], agg, _nxt=nxt):
            cur = _nxt.get(st)
            if cur is None or sc > cur[0]:
                _nxt[st] = (sc, acc, agg)

        for st, (sc, acc, agg) in beams.items():
            # 却下：スコアも罰も加えない。**却下は無料である。**
            # （無料にしないと「全部採用」に偏る。候補の適合率は 0.957 だが
            #   残り 4.3% を捨てられる余地を残す。）
            put(st, sc, acc, agg)
            # 採用
            pen, _reason, gaps = _accept_cost(st, c.level, c.num, lam, levels)
            nest_inc = 1 if ("orphan" in _reason or "nonmono" in _reason) else 0
            reset_inc = 1 if "reset" in _reason else 0
            put(
                st.with_accept(c.level, c.num),
                sc + c.score - pen,
                [*acc, c],
                (agg[0] + gaps, agg[1] + nest_inc, agg[2] + reset_inc),
            )
        beams = dict(sorted(nxt.items(), key=lambda kv: -kv[1][0])[:beam])

    best_st, (best_sc, best_acc, agg) = max(beams.items(), key=lambda kv: kv[1][0])

    # 目次の未照合を最後に一括で罰する（**採用集合が決まってからでないと数えられない**）。
    n_unmatched = 0
    if toc is not None and toc.entries:
        have = {(c.kind, c.num) for c in best_acc}
        for e in toc.entries:
            if e.num is None or e.kind not in ("part", "chapter", "section", "article"):
                continue
            if (e.kind, e.num) not in have:
                n_unmatched += 1
        best_sc -= lam["toc"] * n_unmatched

    return DecodeResult(
        accepted=[*best_acc, *roots],
        total_score=best_sc,
        n_gap=agg[0],
        n_nest=agg[1],
        n_reset=agg[2],
        n_toc_unmatched=n_unmatched,
    )


def decode_greedy(
    cands: list[Candidate], toc=None, threshold: float = 0.0, lam: dict[str, float] | None = None
) -> DecodeResult:
    """対照（E7b）。**位置順に、制約を見ずに、スコアが閾値以上なら採る。**

    これが大域デコードと同じ答えを出すなら、制約は効いていない。
    """
    lam = lam or LAMBDA
    acc = [c for c in cands if c.num is None or c.score >= threshold]
    levels = frozenset(
        c.level for c in cands if c.num is not None and 1 <= c.level <= MAX_LEVEL
    ) or frozenset({1, 2, 3, 4})
    st = State()
    n_gap = n_nest = n_reset = 0
    for c in sorted([x for x in acc if x.num is not None], key=lambda x: x.pos):
        if not (1 <= c.level <= MAX_LEVEL):
            continue
        _pen, reason, gaps = _accept_cost(st, c.level, c.num, lam, levels)
        n_gap += gaps
        n_nest += 1 if ("orphan" in reason or "nonmono" in reason) else 0
        n_reset += 1 if "reset" in reason else 0
        st = st.with_accept(c.level, c.num)
    n_unmatched = 0
    if toc is not None and toc.entries:
        have = {(c.kind, c.num) for c in acc if c.num is not None}
        n_unmatched = sum(
            1
            for e in toc.entries
            if e.num is not None
            and e.kind in ("part", "chapter", "section", "article")
            and (e.kind, e.num) not in have
        )
    return DecodeResult(
        accepted=acc,
        total_score=sum(c.score for c in acc),
        n_gap=n_gap,
        n_nest=n_nest,
        n_reset=n_reset,
        n_toc_unmatched=n_unmatched,
    )


def decode_for_doc(
    doc_id: str,
    mode: str = "global",
    lam: dict[str, float] | None = None,
    extra_cut: dict[int, int] | None = None,
):
    from .candidates import candidates_for_doc
    from .toc import build_toc

    cands = candidates_for_doc(doc_id, extra_cut=extra_cut)
    toc = build_toc(doc_id)
    if mode == "greedy":
        return decode_greedy(cands, toc, lam=lam)
    return decode_global(cands, toc, lam=lam)
