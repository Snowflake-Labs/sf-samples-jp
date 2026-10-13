from __future__ import annotations

from pathlib import Path

import pytest
from fixtures.configs import make_corpus_cfg

from jpdocread.config import ConfigError
from jpdocread.fetch.sources import (
    FetchError,
    HuggingFaceSource,
    LocalSource,
    make_source,
)


class TestLocalSource:
    def test_fetch_index_copies_manifest_and_sums(self, dataset, tmp_path):
        dest = tmp_path / "dest"
        got = LocalSource(dataset).fetch_index(dest)
        assert got == ["manifest.json", "SHA256SUMS"]
        assert (dest / "manifest.json").read_bytes() == (dataset / "manifest.json").read_bytes()

    def test_fetch_docs_copies_only_requested_files(self, dataset, tmp_path):
        dest = tmp_path / "dest"
        LocalSource(dataset).fetch_docs(dest, ["aaa-0001--style-a"], ["doc.pdf"])
        assert (dest / "aaa-0001--style-a" / "doc.pdf").exists()
        # 予測用だけを頼んだときは正解 JSON を置かない
        assert not (dest / "aaa-0001--style-a" / "answer.json").exists()
        assert not (dest / "aaa-0001--style-b").exists()

    def test_missing_files_are_listed(self, dataset, tmp_path):
        with pytest.raises(FetchError, match="2 件"):
            LocalSource(dataset).fetch_docs(tmp_path, ["nope-1", "nope-2"], ["doc.pdf"])

    def test_missing_root(self, tmp_path):
        with pytest.raises(FetchError, match="ディレクトリが無い"):
            LocalSource(tmp_path / "none").fetch_index(tmp_path / "dest")

    def test_missing_manifest(self, tmp_path):
        (tmp_path / "root").mkdir()
        with pytest.raises(FetchError, match="manifest.json"):
            LocalSource(tmp_path / "root").fetch_index(tmp_path / "dest")


class FakeHub:
    """snapshot_download の代わり。呼ばれた引数を記録し、allow_patterns に合うファイルだけを置く。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls: list[dict] = []

    def __call__(self, **kwargs) -> str:
        self.calls.append(kwargs)
        dest = Path(kwargs["local_dir"])
        for pattern in kwargs["allow_patterns"]:
            src = self.root / pattern
            if src.exists():
                (dest / pattern).parent.mkdir(parents=True, exist_ok=True)
                (dest / pattern).write_bytes(src.read_bytes())
        return str(dest)


class TestHuggingFaceSource:
    def test_requests_only_index_then_named_files(self, dataset, tmp_path):
        hub = FakeHub(dataset)
        src = HuggingFaceSource("org/repo", "abc123", downloader=hub)
        src.fetch_index(tmp_path / "d")
        src.fetch_docs(tmp_path / "d", ["aaa-0001--style-a"], ["doc.pdf", "answer.json"])
        index_call, docs_call = hub.calls
        assert index_call["repo_type"] == "dataset"
        assert index_call["revision"] == "abc123"
        assert index_call["allow_patterns"] == ["manifest.json", "SHA256SUMS"]
        assert docs_call["allow_patterns"] == [
            "aaa-0001--style-a/doc.pdf",
            "aaa-0001--style-a/answer.json",
        ]
        assert (tmp_path / "d" / "aaa-0001--style-a" / "answer.json").exists()

    def test_missing_remote_file_is_an_error(self, dataset, tmp_path):
        src = HuggingFaceSource("org/repo", downloader=FakeHub(dataset))
        with pytest.raises(FetchError, match="1 件"):
            src.fetch_docs(tmp_path / "d", ["nope"], ["doc.pdf"])

    def test_missing_remote_manifest(self, tmp_path):
        (tmp_path / "empty").mkdir()
        src = HuggingFaceSource("org/repo", downloader=FakeHub(tmp_path / "empty"))
        with pytest.raises(FetchError, match="manifest.json"):
            src.fetch_index(tmp_path / "d")


class TestMakeSource:
    def test_local_expands_path(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TEST_ROOT_X", str(tmp_path))
        cfg = make_corpus_cfg(source={"kind": "local", "local": {"path": "${TEST_ROOT_X}"}})
        src = make_source(cfg)
        assert isinstance(src, LocalSource) and src.root == tmp_path

    def test_local_without_path(self):
        cfg = make_corpus_cfg(source={"kind": "local"})
        with pytest.raises(ConfigError, match="path"):
            make_source(cfg)

    def test_huggingface_without_repo_id_is_explicit_error(self):
        cfg = make_corpus_cfg(source={"kind": "huggingface", "huggingface": {"repo_id": None}})
        with pytest.raises(ConfigError, match="repo_id"):
            make_source(cfg)

    def test_huggingface(self):
        cfg = make_corpus_cfg(
            source={
                "kind": "huggingface",
                "huggingface": {
                    "repo_id": "org/repo",
                    "revision": "0123456789abcdef0123456789abcdef01234567",
                },
            }
        )
        src = make_source(cfg, downloader=lambda **k: "")
        assert isinstance(src, HuggingFaceSource)
        assert src.describe() == {
            "kind": "huggingface",
            "repo_id": "org/repo",
            "revision": "0123456789abcdef0123456789abcdef01234567",
        }
        assert src.dir_suffix() == "-hf-0123456789ab"

    @pytest.mark.parametrize(
        "rev", [None, "main", "v1", "0123456789ab", "0123456789ABCDEF0123456789ABCDEF01234567"]
    )
    def test_huggingface_revision_must_be_commit_sha(self, rev):
        # main・タグ・短縮 SHA・null は repo の更新で入力が黙って変わり得るので止める
        cfg = make_corpus_cfg(
            source={"kind": "huggingface", "huggingface": {"repo_id": "org/repo", "revision": rev}}
        )
        with pytest.raises(ConfigError, match="コミット SHA"):
            make_source(cfg, downloader=lambda **k: "")

    @pytest.mark.parametrize("name", ["yakkan", "contract"])
    def test_shipped_configs_use_pinned_hub_without_data_root(self, name, monkeypatch):
        # 公開する設定は HF を既定にし、DATA_ROOT_* も HF_TOKEN も無しで取得元を組み立てられる
        from jpdocread.config import load_corpus_config

        for key in ("DATA_ROOT_YAKKAN", "DATA_ROOT_CONTRACT", "HF_TOKEN"):
            monkeypatch.delenv(key, raising=False)
        cfg = load_corpus_config(name)
        assert cfg.source.kind == "huggingface"
        src = make_source(cfg, downloader=lambda **k: "")
        assert src.describe()["repo_id"].startswith("cvusk/japanese-")
        assert len(src.describe()["revision"]) == 40

    def test_local_keeps_the_existing_layout(self, tmp_path):
        assert LocalSource(tmp_path).dir_suffix() == ""
