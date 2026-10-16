from __future__ import annotations

import json

import pytest
import yaml
from fixtures.configs import corpus_dict

from jpdocread import cli, config
from jpdocread.common import paths


@pytest.fixture
def isolated(monkeypatch, tmp_path, dataset):
    """設定ディレクトリを一時ディレクトリに差し替え、合成データセットを指すコーパスを置く。"""
    corpora = tmp_path / "corpora"
    corpora.mkdir()
    data = corpus_dict(name="testcorpus", source={"kind": "local", "local": {"path": str(dataset)}})
    (corpora / "testcorpus.yaml").write_text(
        yaml.safe_dump(data, allow_unicode=True), encoding="utf-8"
    )
    monkeypatch.setattr(config, "CORPORA", corpora)
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path / "data")
    orig = config.load_corpus_config
    monkeypatch.setattr(cli, "load_corpus_config", lambda name: orig(name, corpora_dir=corpora))
    monkeypatch.setattr(cli, "available_corpora", lambda: ["testcorpus"])
    return tmp_path


def test_fetch_pilot(isolated, capsys):
    assert cli.main(["fetch", "--corpus", "testcorpus"]) == 0
    out = capsys.readouterr().out
    assert "1 文書" in out and "取得と照合が完了" in out
    assert (isolated / "data" / "testcorpus" / "vtest" / "bbb-0001--style-a" / "doc.pdf").exists()


def test_fetch_dry_run_prints_selection(isolated, capsys):
    assert cli.main(["fetch", "--corpus", "testcorpus", "--slice", "two", "--dry-run"]) == 0
    out = capsys.readouterr().out
    sel = json.loads(out[out.index("{") :])
    assert sel["doc_ids"] == ["aaa-0001--style-a", "bbb-0001--style-a"]
    assert sel["eval_excluded"] == ["aaa-0001--style-a"]
    # --dry-run は data/ に何も残さない
    assert not any((isolated / "data").rglob("*.*"))


def test_all_without_tty_needs_yes(isolated, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert cli.main(["fetch", "--corpus", "testcorpus", "--slice", "all"]) == 1
    assert "--yes" in capsys.readouterr().err
    assert cli.main(["fetch", "--corpus", "testcorpus", "--slice", "all", "--yes"]) == 0


def test_errors_are_reported_without_traceback(isolated, capsys):
    assert cli.main(["fetch", "--corpus", "testcorpus", "--docs", "zzz"]) == 1
    assert "エラー:" in capsys.readouterr().err


def test_names_env_format(capsys):
    assert cli.main(["names"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert "DB=JA_DOC_STRUCTURED_DB" in lines


def test_run_rejects_bad_args_before_connecting(capsys):
    """`run` は引数を検査してから接続する（不正な値は Snowflake に触れずに rc=1）。"""
    assert cli.main(["run", "--corpus", "contract", "--run-id", "bad id"]) == 1
    assert "run_id" in capsys.readouterr().err
    assert cli.main(["run", "--resume", "a", "--watch", "b"]) == 1


def test_every_subcommand_has_help():
    for cmd in ("fetch", "run", "local", "eval", "eval-compare", "export", "job", "guard", "names"):
        with pytest.raises(SystemExit) as e:
            cli.main([cmd, "--help"])
        assert e.value.code == 0
