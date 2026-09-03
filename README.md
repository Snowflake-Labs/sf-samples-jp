# sf-samples-jp

Snowflake Japan が提供する、日本向けのサンプルコード・デモ・ハンズオン資材のリポジトリです。

---

> **Disclaimer / 免責事項**
>
> **[EN]** All code and content in this repository is provided for **demonstration and educational purposes only**.
> It is **not intended for production use**. No warranty is provided, and Snowflake is not responsible for any issues arising from the use of this code in production environments. Always review and test thoroughly before using in any production system.
>
> **[JA]** このリポジトリ内のすべてのコード・コンテンツは、**デモおよび学習目的のみ** を意図して提供されています。
> **本番環境での使用を想定したものではありません。** いかなる保証も提供されず、本コードを本番環境で使用したことによって生じた問題について Snowflake は責任を負いません。本番環境で利用する際は、必ず十分なレビューとテストを行ってください。

---

## 目的

このリポジトリは、Snowflake の機能をわかりやすく伝えるための日本語コンテンツを集約・管理することを目的としています。  
Sales Engineer が作成したデモスクリプト、イベント資材、ハンズオンコンテンツなどを収録しています。

---

## フォルダ構成

```
sf-samples-jp/
├── events/     # イベント・勉強会・カンファレンス向けコンテンツ
├── demo/       # 商談・POC向けデモスクリプト・Streamlitアプリ
└── handson/    # ハンズオンワークショップ向けSQL・手順書
```

| フォルダ | 説明 |
|---------|------|
| [`events/`](./events/) | Snowday Japan などのイベントごとのコンテンツ。イベント名のサブフォルダで管理します |
| [`demo/`](./demo/) | 商談・POCで使用するデモスクリプト、Streamlit アプリ、Notebook など |
| [`handson/`](./handson/) | ハンズオンワークショップ向けの SQL スクリプトや手順書 |

将来的には以下のフォルダ追加を予定しています:

- `use-cases/` — 業種別ユースケースサンプル
- `templates/` — 汎用 SQL テンプレート集
- `quickstarts/` — 機能別クイックスタートガイド

---

## 使い方

1. 目的のフォルダを開く
2. 各フォルダ内の `README.md` で前提条件・実行手順を確認する
3. SQL スクリプトは Snowflake の Worksheets または SnowSQL で実行する
4. Python / Notebook は各フォルダの `requirements.txt` に従って環境を準備する

---

## コントリビューション

このリポジトリへの貢献を歓迎します。  
詳細は [CONTRIBUTING.md](./CONTRIBUTING.md) をご覧ください。

---

## ライセンス

[Apache License 2.0](./LICENSE)
