# sf-samples-jp

Snowflake Japan が提供する、日本向けのサンプルコード・デモ・ハンズオン資材のリポジトリです。

---
> [!IMPORTANT]
>
> **Disclaimer / 免責事項**
>
> This application is not part of the Snowflake Service and is governed by the terms in LICENSE, unless expressly agreed to in writing. You use this application at your own risk, and Snowflake has no obligation to support your use of this application.
>
> （参考訳）本アプリケーションは Snowflake Service の一部ではなく、書面による明示的な合意がない限り LICENSE の条件に従います。本アプリケーションの利用はご自身の責任で行うものとし、Snowflake は本アプリケーションの利用に関していかなるサポート義務も負いません。
> **※ この日本語訳は参考であり、必ず英文を確認してください。**
>
> [Read more](./LEGAL.md)

---

## 目的

このリポジトリは、Snowflake の機能をわかりやすく伝えるための日本語コンテンツを集約・管理することを目的としています。  
デモスクリプト、イベント資材、ハンズオンコンテンツなどを収録しています。

---

## フォルダ構成

```
sf-samples-jp/
├── events/     # イベント・勉強会・カンファレンス向けコンテンツ
├── demo/       # POC向けデモスクリプト・Streamlitアプリ
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
