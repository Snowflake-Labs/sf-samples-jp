# demo/

POC向けのデモスクリプト・Streamlit アプリ・Notebook などを管理するフォルダです。

---

## ルール

- **各デモは独立したサブフォルダで用意しています。**
- **各サブフォルダに `README.md` を配置しています。**  
  テンプレートは [`README_TEMPLATE.md`](./README_TEMPLATE.md) を使用してください。

## フォルダ命名規則

```
デモ名/
```

例:
```
demo/
├── cortex-analyst-text-to-sql/
│   ├── README.md
│   └── ...
└── streamlit-data-app/
    ├── README.md
    └── ...
```

## 新しいデモを追加するには

1. `デモ名/` の形式でサブフォルダを作成する
2. `README_TEMPLATE.md` をコピーして `README.md` として配置する
3. 必要なファイル（SQL・Python・Notebook など）を追加する
4. PR を作成する（[CONTRIBUTING.md](../CONTRIBUTING.md) 参照）
