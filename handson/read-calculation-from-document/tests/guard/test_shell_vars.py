"""シェルスクリプトで、`$変数` の直後に ASCII 以外の文字（全角の括弧など）を続けない。

bash は直後の多バイト文字の先頭のバイトまで変数名として読むので、`set -u` のスクリプトでは
存在しない変数の参照になって止まる（その行を通るまで気付かない）。`${変数}` と囲む。
"""

from __future__ import annotations

import re

from jpcalc.common.paths import HOME

BAD = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*(?=[^\x00-\x7f])")


def _violations(text: str) -> list[int]:
    return [i for i, line in enumerate(text.splitlines(), 1) if BAD.search(line)]


def test_scripts_brace_vars_before_non_ascii():
    bad = {
        p.name: _violations(p.read_text(encoding="utf-8"))
        for p in sorted((HOME / "scripts").glob("*.sh"))
    }
    assert not {k: v for k, v in bad.items() if v}


def test_detector():
    assert _violations('die "失敗: $s（上"') == [1]
    assert _violations('die "失敗: ${s}（上"') == []
    assert _violations('echo "$a b"') == []
