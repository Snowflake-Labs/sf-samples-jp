# HR Intelligence 業務フロー設計書

> 本文書はHR Intelligenceアプリの業務フローを定義する。画面の操作は `operation_guide.md` を参照。

## 1. アプリ全体の業務フローマップ

```mermaid
graph TB
  subgraph analyze ["分析フェーズ"]
    dash["ダッシュボード"]
    attrition["離職予測"]
    wf_ov["異動ダッシュボード"]
    agent["AIエージェント"]
  end

  subgraph plan ["計画フェーズ"]
    sim["異動シナリオ作成 /simulation"]
    chain["玉突き人事 /chain-simulation"]
  end

  subgraph review_phase ["レビューフェーズ"]
    review["異動案レビュー /review"]
  end

  subgraph confirm_phase ["確定フェーズ"]
    snap["確定済み異動 /snapshots"]
    csv["CSV出力"]
    external["勤怠・給与システム"]
  end

  subgraph master ["マスタ管理"]
    emp["社員管理"]
    eval_mgmt["評価管理"]
    gov["ガバナンス"]
  end

  dash -->|"リスク高社員を確認"| attrition
  attrition -->|"異動検討対象を特定"| sim
  wf_ov -->|"Watch List → 異動検討"| sim
  agent -->|"自然言語で分析"| dash

  sim -->|"レビュー依頼"| review
  chain -->|"レビュー依頼"| review
  review -->|"承認"| snap
  review -->|"差し戻し"| sim
  review -->|"差し戻し"| chain
  snap -->|"CSV出力"| csv
  csv -->|"データ連携"| external

  emp -->|"社員データ参照"| sim
  eval_mgmt -->|"評価データ参照"| sim
```

## 2. 社員情報管理フロー

### 2.1 社員登録・編集

```mermaid
sequenceDiagram
  actor HR as 人事担当者
  participant App as HR Intelligence
  participant PG as Postgres

  HR->>App: /employees/new で新規登録
  App->>PG: INSERT INTO hr.employees
  PG-->>App: employee_id 返却
  App-->>HR: 社員詳細画面にリダイレクト

  HR->>App: /employees/:id で基本情報編集
  App->>PG: UPDATE hr.employees
  App-->>HR: 更新完了表示
```

### 2.2 スキル管理

- 社員詳細画面 → スキルタブ → `/employees/:id/skills`
- スキルマスタから選択して紐付け（1〜5段階）
- カテゴリ別にグルーピング表示

### 2.3 1on1メモ管理

- 社員詳細画面 → 1on1タブ → `/employees/:id/notes`
- カテゴリ: performance / career / motivation / concern / other
- プライベートフラグで閲覧制限

## 3. 評価管理フロー

### 3.1 上長（課長）の評価入力 → 人事レビュー → 調整会議

```mermaid
sequenceDiagram
  actor LM as 課長 (LINE_MANAGER)
  actor HR as 人事 (HR_ADMIN / HR_MANAGER)
  participant App as HR Intelligence
  participant AI as Cortex COMPLETE

  LM->>App: /my-team で部下を選び、上長コメントを書く
  LM->>App: 「AIで採点」
  App->>AI: コメントを 5 軸 (1-5) で採点
  AI-->>App: 5 軸スコア + 採点根拠
  App-->>LM: 期待比・推奨グレードを表示
  LM->>App: 実態と違う軸を直す（理由必須）、最終グレードを選ぶ（推奨±1段階）
  LM->>App: 「提出」→ status = submitted
  HR->>App: /evaluations/cross-review で確認（上長修正の内容と理由も見える）
  alt 内容に問題がある
    HR->>App: 「上長に差し戻す」（理由必須）→ status = draft
    App-->>LM: 差し戻し理由を表示、再入力・再提出
  else 人事が軸を直す
    HR->>App: 「5軸スコアを修正（人事）」（理由必須）→ 再計算
  end
  HR->>App: /evaluations/calibration で等級ごとに調整会議
  HR->>App: 目標分布との乖離を見てグレードを調整（理由必須）→「確定」
```

評価のステータス（`hr.evaluations.status`）:

```mermaid
stateDiagram-v2
  [*] --> draft : 上長が下書き保存 / AI採点
  draft --> submitted : 上長が提出
  submitted --> draft : 人事が差し戻し
  submitted --> completed : 評価確定
  completed --> [*]
```

- AI の元の値と修正後の値は `hr.eval_axis_overrides` に軸ごとに残る（誰が・なぜ直したか）
- 推奨グレードは、等級ごとの期待水準（`hr.grade_score_standards`）との差（期待比）で決まる
- 調整会議での変更は `hr.calibration_adjustments` に理由付きで残る

### 3.2 一括評価入力

1. 人事管理者が `/evaluations/batch` を開く
2. 本部・部署・期間を選択
3. 部署内全社員の評価をインライン編集
4. スコア入力 → 自動グレード算出 (4.5+=S, 4.0+=A, ...)
5. 「下書き保存」or「確定保存」

### 3.3 評価データの活用

- ダッシュボードの等級分布・評価分布チャート
- 離職予測MLモデルの特徴量 (`AVG_EVAL_SCORE`)
- 異動マッチスコアの評価スコア成分 (30%ウェイト)

## 4. 離職予測・リスク分析フロー

```mermaid
graph LR
  subgraph ml ["ML Pipeline"]
    xgb["XGBoost離職予測"]
    lgbm["LightGBM関係性分析"]
    shap["SHAP要因分析"]
  end

  subgraph ui ["UI"]
    attrition_list["離職予測一覧"]
    attrition_detail["SHAP詳細"]
    retention["リテンション施策"]
    emp_detail["社員詳細ML cards"]
  end

  xgb -->|"risk_score"| attrition_list
  attrition_list -->|"社員クリック"| attrition_detail
  attrition_detail -->|"AI生成"| retention
  xgb --> emp_detail
  lgbm --> emp_detail
  shap --> emp_detail
```

## 5. 異動管理フロー

異動案は 2 つの画面で作ります。

- **異動シナリオ作成（5.1）:** 定期異動など、複数の昇格・異動・退職をまとめて計画する。起点は自由に選び、空いた席の後任も同じ案の中で決める。
- **玉突き人事（5.2）:** 退職・休職・異動申請で突発的に空いた 1 つのポストを、後任 → その後任…と順に埋める。各ステップで AI の比較コメントが付く。

どちらの案も、同じレビュー（`/review`）と確定（`/snapshots`）の流れに乗ります。

### 5.1 シナリオ作成 → 保存 → 編集 → レビュー依頼

```mermaid
sequenceDiagram
  actor HR as 人事担当者
  actor MGR as 現場マネージャ
  participant Sim as /simulation
  participant Review as /review
  participant Snap as /snapshots

  HR->>Sim: 本部選択 → 部署ツリー表示
  HR->>Sim: 社員クリック → 昇格/異動/退職
  HR->>Sim: AI比較分析・マッチスコア確認
  HR->>Sim: 「確定・保存」クリック
  Sim-->>HR: 保存完了 + レビュー依頼ボタン

  HR->>Sim: 「レビュー依頼」クリック
  Sim-->>MGR: ステータス: pending_review

  MGR->>Review: レビュー一覧で確認
  MGR->>Review: 各アクションを承認 or 差し戻し(コメント必須)

  alt 差し戻しあり
    Review-->>HR: ステータス: revision_requested
    HR->>Sim: 保存済みシナリオをロード(編集)
    HR->>Sim: 差し戻しコメント確認 → 修正
    HR->>Sim: 再保存 → 再レビュー依頼
    HR->>Review: 再レビュー
  end

  MGR->>Review: 全アクション承認 → 最終承認
  Review-->>HR: ステータス: approved

  HR->>Sim: ステータスバーから「確定」
  HR->>Sim: ラベル・発令日を入力
  Sim->>Snap: スナップショット保存

  HR->>Snap: CSV出力 → 勤怠・給与システムへ連携
```

### 5.2 玉突きシミュレーション

```mermaid
sequenceDiagram
  actor HR as 人事担当者
  participant Chain as /chain-simulation

  HR->>Chain: トリガーイベント選択（異動/退職）
  loop 各ステップ
    Chain->>Chain: 空席の候補者一覧表示
    HR->>Chain: 候補者選択 → AI比較分析
    HR->>Chain: 「確定」→ 次ステップ（連鎖空席）
  end
  HR->>Chain: 全ステップ確定 → 保存
  HR->>Chain: レビュー依頼 → /review で承認フロー
```

### 5.3 ステータス遷移

```mermaid
stateDiagram-v2
  [*] --> draft : 保存
  draft --> pending_review : レビュー依頼
  pending_review --> approved : 全承認
  pending_review --> revision_requested : 1件以上差し戻し
  revision_requested --> pending_review : 修正→再提出
  approved --> confirmed : スナップショット確定
  confirmed --> [*]
```

### 5.4 スナップショット確定 → CSV出力

- 承認済みシナリオ/チェーンに「ラベル」と「発令日」を付けて確定
- `scenario_snapshots` テーブルにJSONBで全データ保管
- CSV出力フォーマット:

| カラム | 説明 |
|---|---|
| 発令日 | YYYY-MM-DD |
| 社員番号 | E001 etc. |
| 氏名 | 姓 名 |
| 異動種別 | 異動/昇格/退職 |
| 異動元部署コード | D010 etc. |
| 異動元部署名 | 営業1部 etc. |
| 異動先部署コード | D020 etc. |
| 異動先部署名 | 営業2部 etc. |
| 異動元等級 | M2 etc. |
| 異動先等級 | M2 etc. |
| 備考 | スナップショットラベル |

## 6. AI活用フロー

### 6.1 AIエージェント

- `/agent` で自然言語クエリ → Cortex Agent (claude-haiku-4-5)
- SQL生成 → 結果テーブル表示
- スレッド管理（保存/ロード/削除）

### 6.2 異動マッチスコア

```
matchScore = skillScore × 0.5 + evalScore × 0.3 + tenureScore × 0.2
```

- skillScore: 異動先部署の必須スキルとの一致率
- evalScore: 直近評価平均の正規化 (1-5 → 0-100)
- tenureScore: 在籍年数ベースの適性（3 年以上は `60 + 年数 × 3`（上限 100）、3 年未満は `年数 × 20`（下限 20））
- 計算は `hr-app-v2/src/app/api/simulation/match/route.ts` にある

### 6.3 AI比較分析

- `AI_COMPLETE` (Cortex) で候補者 vs 異動先同僚の比較レポート生成
- markdown形式でダイアログ内表示

## 7. ガバナンス・監査フロー

### 7.1 ロールベースマスキング

Snowflake 側のテーブルに付けたマスキングポリシー（`sql/setup_analytics.sql`）の動き:

| ロール | 給与 | メールアドレス | 評価スコア | 評価コメント |
|---|---|---|---|---|
| HR_ADMIN | 表示 | 表示 | 表示 | 表示 |
| HR_MANAGER | 非表示（NULL） | 部分マスク | 表示 | 表示 |
| HR_VIEWER | 非表示（NULL） | 部分マスク | 非表示（NULL） | `***` |

### 7.2 アクセス履歴

- Snowflake `ACCOUNT_USAGE.ACCESS_HISTORY` を表示
- クエリ実行者・テーブル・時刻

### 7.3 タイムトラベル

- Snowflake Time Travel でデータの過去状態を参照（デモ用）

## 8. データフロー概要

```mermaid
graph LR
  subgraph oltp ["Snowflake Postgres (OLTP)"]
    pg_emp["employees"]
    pg_eval["evaluations"]
    pg_transfer["transfer_requests"]
    pg_whatif["whatif_scenarios"]
    pg_chain["chain_simulations"]
    pg_snap["scenario_snapshots"]
  end

  subgraph analytics ["Snowflake Core (分析/ML)"]
    iceberg["Iceberg Tables (STAGING)"]
    ml["ML Models"]
    cortex["Cortex AI"]
  end

  pg_emp -->|"sync"| iceberg
  pg_eval -->|"sync"| iceberg
  iceberg -->|"特徴量"| ml
  ml -->|"推論結果"| iceberg
  cortex -->|"AI分析"| analytics

  subgraph app ["Next.js App"]
    api_pg["API (pgQuery)"]
    api_sf["API (sfQuery)"]
  end

  api_pg <-->|"CRUD"| oltp
  api_sf <-->|"ML/AI"| analytics
```
