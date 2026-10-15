# HR Intelligence アプリ（hr-app-v2）

Next.js 16 の人事分析アプリ。Snowflake App Runtime にデプロイして動かす（デプロイ先のターゲット名は `v3`）。
データは Snowflake Postgres（OLTP）と Snowflake（Cortex AI / ML 推論結果）から読む。

主な画面: ダッシュボード、社員、評価（横断レビュー・調整会議・AI 定量化）、
マイチーム評価（1stラインマネージャー向けの入力画面）、離職予測、配置シミュレーション。

## 前提

- Snowflake アカウント（Cortex `COMPLETE` で `claude-haiku-4-5` が使えること）
- Snowflake Postgres インスタンス
- `snow` CLI、Node.js 22 以上

## セットアップ

1. DB とデータを用意する: デモのルートにある [README](../README.md) の手順 1〜6 をすべて実行する。
   途中で止めると、アプリは起動しても画面が空になる。
2. ローカル用の環境変数: `cp .env.example .env.local` して値を埋める。
   `SESSION_SECRET` は `openssl rand -hex 32` などで作ったランダム値にする。
3. ローカル起動:
   ```bash
   npm ci
   npm run dev     # http://localhost:3000
   npm test        # ユニットテスト (vitest)
   ```

## デプロイ（Snowflake App Runtime）

`app.yml` は git に入れていない。通信の許可と秘密情報は、ルートの README の手順 7（`sql/setup_app_runtime.sql`）で先に作っておく。
`cp app.yml.example app.yml` して `<YOUR_...>` を自分の環境の値に置き換える。

- `query_warehouse`、`POSTGRES_HOST`、`POSTGRES_USER`
- `external_access_integrations`: Postgres の 5432 とアカウントホストの 443 を許可する EAI
- `secrets`: Postgres パスワードと `SESSION_SECRET` を Snowflake の SECRET として作り、完全修飾名で指定する

```bash
snow app deploy --target v3 --connection <your-connection>
```

`SESSION_SECRET` が設定されていないと、本番ではログインできないようにしている（推測できる既定値で Cookie を偽造されるのを防ぐため）。

## デモ用ログイン

ログイン画面のカードから選ぶ。パスワードなしでロールを切り替えられるデモ用の認証なので、
**実データや社外公開には使わない**こと。

| ユーザー | ロール | 用途 |
|---|---|---|
| admin | HR_ADMIN | 人事管理者（全画面） |
| manager | HR_MANAGER | 部門長 |
| viewer | HR_VIEWER | 閲覧のみ |
| linemgr | LINE_MANAGER | 課長。`/my-team` で自分が評価者の部下だけを入力する |

## ログイン後に最初にすること

- **データ経路:** `admin` でログインし、サイドバーのデータ経路を `snowflake-sdk` に切り替える。既定の pg_lake 経路は、README の手順では作らない `hr_lake` スキーマを読むため、切り替えないとダッシュボードなどがエラーになる。
- **評価期間:** `2025-H2` を選ぶ。デモデータはこの期間に入っている。

