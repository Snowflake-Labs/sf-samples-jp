# 日本語の構造化文書を Snowflake で読み取るハンズオン

日本語の PDF（保険約款・ビジネス契約書）を Snowflake に取り込み、Cortex AI 関数と規則を組み合わせて構造化します。
処理後は、「第３条第４項第１号には何が書いてあるか」「甲は誰か」といった情報を SQL で取得できます。
データセットに付属する正解データを使い、読み取り精度も評価します。

- 作成者：[sfc-gh-yshibui](https://github.com/sfc-gh-yshibui)
- 対象者：Snowflake で日本語の非構造化文書（約款・契約書・規程など）を扱う開発者・データエンジニア
- 所要時間：約 30〜40 分（待ち時間を含む。内訳は「[所要時間と費用の目安](#所要時間と費用の目安)」）
- 費用の目安：AI 関数で約 0.8 クレジット（2 文書。実行時に見込みを表示します）＋ウェアハウスとコンピュートプールの稼働分

## 目次

1. [このハンズオンで学ぶこと](#1-このハンズオンで学ぶこと)
2. [全体像](#2-全体像)
3. [準備](#3-準備)
4. [ステップ 1：環境を作る（setup）](#4-ステップ-1環境を作るsetup)
5. [ステップ 2：契約書を読み取る（start）](#5-ステップ-2契約書を読み取るstart)
6. [ステップ 3：結果を SQL で引く](#6-ステップ-3結果を-sql-で引く)
7. [ステップ 4：精度を確かめる](#7-ステップ-4精度を確かめる)
8. [ステップ 5：保険約款を読み取る](#8-ステップ-5保険約款を読み取る)
9. [ステップ 6：失敗と再開を体験する](#9-ステップ-6失敗と再開を体験する)
10. [ステップ 7：後片付け（teardown）](#10-ステップ-7後片付けteardown)
11. [技術の解説](#11-技術の解説)
12. [エッジケースの対応](#12-エッジケースの対応)
13. [発展：文書を増やす・設定を変える](#13-発展文書を増やす設定を変える)
14. [困ったとき](#14-困ったとき)
15. [既知の限界と注意事項](#15-既知の限界と注意事項)
16. [出典とライセンス](#16-出典とライセンス)

---

## 1. このハンズオンで学ぶこと

### 課題：日本語の約款・契約書は「文字を読めるだけ」では使えない

約款や契約書の内容を正しく調べるには、文字列だけでなく**文書の構造**も必要です。

- **記載箇所：** 「第３条第４項第１号」のような引用パスで条項を特定する必要があります。一方、番号の表記は `第一条`・`第１条`・`１`・`（１）`・`①`・`ア` などさまざまで、付け方も文書ごとに異なります。
- **参照先：** 本文中の「前条」「第５条第２項に定める」「別表１」が、実際にどの条項を指すのかをたどる必要があります。
- **当事者と定義語：** 契約書の「甲」「乙」が誰を指し、「本件業務」がどこで定義されているかを把握する必要があります。
- **レイアウト：** 2 段組、柱やヘッダ、ページをまたぐ表、フローチャートを本文と区別して扱う必要があります。

PDF を単純にテキストへ変換するだけでは、こうした構造は失われます。一方、すべてを生成 AI に任せると、番号の取り違えや参照先の誤りを検出しにくくなります。

### このハンズオンのやり方

そこで、AI に任せる処理と、規則で決定する処理を分けます。

| 読み取るもの | 方法 |
|---|---|
| 本文と表 | `AI_PARSE_DOCUMENT`（LAYOUT モード） |
| 図（フローチャート） | 切り出した画像を `AI_COMPLETE` に渡し、ノードと矢印を JSON で返させる |
| 条項木・引用パス・参照・当事者・定義語 | PDF のテキスト層（文字と座標）から規則で組み立てる。同じ PDF からは毎回同じ結果になる |

結果は文書ごとに 1 つの JSON にまとめてステージへ保存し、登録表に展開します。これにより、必要な情報を SQL で取得できます。

### 具体例：PDF から構造化 JSON へ

データセットの秘密保持契約書（`nda-0003--ct-a4-1col-form`、3 ページ）の 1 ページ目には、次のように印刷されています（抜粋。会社名はデータセットの架空のものです）。

```text
秘密保持契約書

   甲   株式会社霜月食品工業
   乙   コトナミ冷熱技研株式会社

株式会社霜月食品工業（以下「甲」という。）とコトナミ冷熱技研株式会社（以下「乙」という。）とは、…次のとおり契約（以下「本契約」という。）を締結する。

第１条（目的および検討の期間）
甲および乙は、本件共同検討のために必要な範囲に限り、開示情報を相互に開示する。
２ 本件共同検討は、本契約を締結した日から７か月の間に行う。…
    ⋮
第３条（開示情報の特定および除外）
    ⋮
３ 配合条件および試作品は、第１項の表示の有無を問わず開示情報として扱う。
４ 次に掲げる情報は、開示情報に含まれない。…
（１）開示を受けた時に、受領した当事者が正当に保有していた情報
（２）開示を受けた後に、受領した当事者の責めによらずに公知となった情報
```

この PDF だけを入力として、パイプラインは次の構造を取り出します。

```mermaid
flowchart TB
    pdf["doc.pdf<br/>（文字と座標・画像）"]
    pdf --> o["outline<br/>条項木"]
    pdf --> e["elements<br/>本文要素と引用パス"]
    pdf --> r["refs<br/>参照"]
    pdf --> p["parties<br/>当事者"]
    pdf --> t["tables<br/>表"]
    pdf --> f["figures<br/>図"]
    o & e & r & p & t & f --> json["1 文書 1 つの JSON<br/>→ 登録表"]
```

出力 JSON の該当部分は次のとおりです（run `h10-readme-contract` の出力から抜粋）。

```json
{
  "outline": [
    {"id": "c3",  "depth": 0, "node_kind": "article",   "label": "第１条", "title": "目的および検討の期間", "citation": "第１条"},
    {"id": "c12", "depth": 0, "node_kind": "article",   "label": "第３条", "title": "開示情報の特定および除外", "citation": "第３条"}
  ],
  "elements": [
    {"element_id": "c5",  "node_kind": "paragraph", "label": "２",     "citation": "第１条 ２",
     "parent_id": "c3",  "text": "本件共同検討は、本契約を締結した日から７か月の間に行う。…"},
    {"element_id": "c15", "node_kind": "paragraph", "label": "３",     "citation": "第３条 ３",
     "parent_id": "c12", "text": "配合条件および試作品は、第１項の表示の有無を問わず開示情報として扱う。",
     "refs_to": ["第3条"]},
    {"element_id": "c17", "node_kind": "item",      "label": "（１）", "citation": "第３条 ４ （１）",
     "parent_id": "c16", "text": "開示を受けた時に、受領した当事者が正当に保有していた情報"}
  ],
  "refs": [
    {"from_citation": "第3条 3", "to_citation": "第3条"},
    {"from_citation": "第6条",   "to_citation": "第1条 2"}
  ],
  "parties": [
    {"alias": "甲", "name": "株式会社霜月食品工業",     "role": "甲", "page": 1},
    {"alias": "乙", "name": "コトナミ冷熱技研株式会社", "role": "乙", "page": 1}
  ],
  "tables": [
    {"id": "r2t_p001_0", "pages": [1], "n_rows": 2, "n_cols": 2,
     "grid": [{"row": 0, "col": 0, "text": "甲", "is_header": true},
              {"row": 0, "col": 1, "text": "株式会社霜月食品工業", "is_header": true}, …]}
  ]
}
```

この例では、次の 4 点を確認できます。

- 「２」「（１）」には、親の条項をたどった引用パス（`第１条 ２`・`第３条 ４ （１）`）が付きます。
- 本文の「第１項」は、同じ条の第 1 項として `第3条` に解決されます（`refs_to`）。
- 前文の「以下『甲』という」から、甲・乙が誰かが取り出されます。
- 番号の字形（全角の `１`、括弧の `（１）`）は、印刷されたとおりに残ります。

図は画像として切り出し、`AI_COMPLETE` でノードと矢印のデータに変換します。
保険約款（`auto-0001--nl-a4-2col-mincho`）の 13 ページ目にある「保険金のお支払いの流れ」の図は、次の JSON になりました（run `h10-readme-yakkan`）。
下の Mermaid は、その JSON から描き直したものです。

```mermaid
flowchart LR
    n1(["請求書類のご提出"]) --> n2["内容の確認"] --> n3["損害の調査"] --> n4{"お支払いの可否"}
    n4 -->|支払う| n5(["保険金のお支払い"])
    n4 -->|支払わない| n6(["理由のご説明"])
```

```json
{
  "id": "r4f_p013_0", "pages": [13],
  "nodes": [{"id": "n1", "label": "請求書類のご提出", "shape": "rounded"}, {"id": "n4", "label": "お支払いの可否", "shape": "diamond"}, …],
  "edges": [{"from": "n1", "to": "n2", "relation": "flow"}, …, {"from": "n4", "to": "n5", "relation": "flow", "label": "支払う"},
            {"from": "n4", "to": "n6", "relation": "flow", "label": "支払わない"}],
  "paths": [["請求書類のご提出", "内容の確認", "損害の調査", "お支払いの可否", "保険金のお支払い"],
            ["請求書類のご提出", "内容の確認", "損害の調査", "お支払いの可否", "理由のご説明"]]
}
```

### 学べること

- PDF の取得、読み取り、登録、評価を Snowflake の Task グラフでつなぐ方法（SQL のステップと SPCS のジョブを組み合わせます）
- `AI_PARSE_DOCUMENT` と `AI_COMPLETE`（画像入力・few-shot）の実践的な使い方と、課金を抑えるキャッシュ
- 失敗したステップだけをやり直す再開の仕組み
- 予測と正解データを別のロール・DB に分離して評価する仕組み（読み取り側から正解データを参照できない構成）
- 引用誤り率と網羅率による、構造の読み取り精度の測り方

---

## 2. 全体像

```mermaid
flowchart LR
    subgraph local["手元の PC"]
        hf[("Hugging Face<br/>データセット")] -->|"取得・SHA-256 で照合"| data["data/<br/>doc.pdf（--eval なら正解も）"]
    end
    data -->|PUT| docs[("@RAW.DOCS<br/>doc.pdf")]
    data -.->|"--eval のときだけ"| gold[("評価 DB の<br/>正解ステージ")]
    subgraph sf["Snowflake（Task グラフ。start.sh が起動）"]
        direction LR
        s00["S00 準備・台帳への登録"] --> s10["S10 入力の確認"]
        s10 --> s20["S20 本文・表<br/>AI_PARSE_DOCUMENT（LAYOUT）<br/>[SQL]"]
        s10 --> s30["S30 幾何<br/>座標・段組・表と図の領域・図の切り出し<br/>[SPCS ジョブ]"]
        s30 --> s40["S40 図<br/>AI_COMPLETE（few-shot 2 例）<br/>[SQL]"]
        s20 --> s50["S50 統合<br/>条項木・引用パス・参照・当事者・定義語<br/>→ 出力 JSON [SPCS ジョブ]"]
        s40 --> s50
        s50 --> s55["S55 登録<br/>DOCUMENTS・OUTLINE・ELEMENTS・REFS ほか<br/>[SQL]"]
        s55 --> s60["S60 評価（--eval のときだけ）<br/>評価ロールで実行 [SPCS ジョブ]"]
        s60 --> s70["S70 完了の記録"]
    end
    docs --> s00
    gold --> s60
    s55 --> tables[("登録表・ビュー<br/>SQL で引く")]
    s60 --> evaldb[("評価 DB<br/>V_RUN_SUMMARY ほか")]
```

このハンズオンで作成する Snowflake オブジェクトには、すべて `JA_DOC_STRUCTURED_` という接頭辞が付きます。

| 種類 | 名前 | 役割 |
|---|---|---|
| データベース | `JA_DOC_STRUCTURED_DB` | 読み取り側。PDF・中間成果物・出力 JSON・登録表・台帳・プロシージャ・Task |
| データベース | `JA_DOC_STRUCTURED_EVAL_DB` | 評価側。正解と評価結果。**読み取りのロールからは見えない** |
| ロール | `JA_DOC_STRUCTURED_ADMIN`・`_PREDICT`・`_EVAL_ROLE` | 管理・読み取り・評価 |
| ウェアハウス | `JA_DOC_STRUCTURED_WH`（XSMALL） | SQL と AI 関数 |
| コンピュートプール | `JA_DOC_STRUCTURED_POOL`（CPU_X64_S） | SPCS ジョブ |

アカウント設定は変更しません。後片付けでは、この接頭辞を持つオブジェクトだけを名前で指定して削除します。

---

## 3. 準備

### 3.1 必要なもの

| もの | 確認のしかた | 補足 |
|---|---|---|
| Snowflake アカウントと、ACCOUNTADMIN を使える接続 | `snow connection list` | ロール・データベース・ウェアハウス・コンピュートプールを作るために使います |
| Cortex AI 関数と SPCS が使えるリージョン | — | 図には `claude-opus-5` を使います。使えないときは「[15. 既知の限界と注意事項](#15-既知の限界と注意事項)」を参照 |
| [Snowflake CLI](https://docs.snowflake.com/en/developer-guide/snowflake-cli/index)（`snow`） | `snow --version` | 接続の設定は CLI のドキュメントを参照 |
| [uv](https://docs.astral.sh/uv/) | `uv --version` | Python 3.11 と依存を自動で用意します |
| Docker（buildx） | `docker info` | ジョブのイメージ（linux/amd64）を作ります。**ハンズオンの前に Docker を起動しておいてください** |
| git | `git --version` | |
| huggingface.co への HTTPS 接続 | `curl -sI https://huggingface.co` | データセットを取得します。アカウントとトークンは不要です |

### 3.2 リポジトリを取得して、接続名を設定する

```bash
git clone <このリポジトリの URL>
cd read-japanese-structured-document

# ローカル設定を作る（git 管理外）
cp configs/deploy.env.example configs/deploy.local.env
```

`configs/deploy.local.env` の `CONNECTION_NAME=<your_connection>` を、`snow connection list` に表示される接続名へ書き換えます。
変更するのはこの 1 行だけです。接続名は、リポジトリ内のほかのファイルには記載しないでください。

### 3.3 依存を入れて、テストを流す（Snowflake には接続しない）

```bash
uv sync
scripts/start.sh --test        # lint・正解漏れのガード・単体テスト
```

最後に `[test] すべて通過` と表示されれば、準備は完了です。
この時点ではデータを取得していないため、実文書を使うテストは理由を表示してスキップされます。

---

## 4. ステップ 1：環境を作る（setup）

```bash
scripts/setup.sh
```

```mermaid
flowchart LR
    a["前提の確認<br/>uv・snow・Docker・接続"] --> b["Hugging Face から pilot を取得<br/>SHA-256 で照合"]
    b -->|"不一致"| stop(["何も作らずに停止"])
    b -->|"一致"| c["DDL<br/>ロール・DB・WH・プール<br/>ステージ・表"]
    c --> d["ロール分離の検証<br/>27 件"]
    d --> e["イメージのビルドと push"]
    e --> f["図の few-shot・プロシージャ<br/>Task グラフ・ビュー"]
    f --> g(["作成物の一覧<br/>setup 完了"])
```

処理には約 4 分かかります。次の順に実行し、問題が起きた場合はその時点で停止します。

1. 前提の確認（uv・snow・Docker・接続）
2. Hugging Face から、両コーパスの pilot（各 10 文書）の `doc.pdf` を取得し、manifest の SHA-256 で照合する。**1 件でも合わなければ、Snowflake には何も作らずに止まります**
3. ロール・データベース・ウェアハウス・コンピュートプール・ステージ・表を作る
4. ロール分離の検証（読み取りのロールが評価 DB を読めないことなど、27 件）
5. ジョブのイメージをビルドしてイメージリポジトリに push する
6. 図の few-shot（お手本 2 例）・プロシージャ・Task グラフ・ビューを登録する

最後に、作成したオブジェクトの件数（データベース 2、ロール 3、ウェアハウス 1、コンピュートプール 1）と `setup 完了` が表示されます。
setup は繰り返し実行しても同じ状態になります。2 回目以降は `scripts/setup.sh --skip-build` を使うと、イメージのビルドを省略できます。

> 取得時に Hugging Face から「unauthenticated requests」という警告が表示されることがあります。このハンズオンでは公開データセットを匿名で取得するため、問題ありません。

---

## 5. ステップ 2：契約書を読み取る（start）

秘密保持契約書（NDA）を 1 文書読み取り、正解データを使った評価（`--eval`）まで実行します。

```bash
scripts/start.sh --corpus contract --docs nda-0003--ct-a4-1col-form --eval
```

```mermaid
flowchart LR
    a["対象の決定<br/>ページ数・見込みクレジットの表示"] --> b["取得と照合"]
    b --> c["doc.pdf を PUT<br/>（同じ md5 は飛ばす）"]
    c --> d["正解を評価ステージへ<br/>（--eval のときだけ・評価ロール）"]
    d --> e["run を台帳 RUNS に登録"]
    e --> f["EXECUTE TASK で<br/>Task グラフを起動"]
    f --> g["S00〜S70 の<br/>進み具合を表示"]
    g --> h(["完了の要約<br/>出力 JSON・登録表・評価"])
```

最初に対象と見込みクレジットが表示されます。

```
[run] 対象：contract 1 文書・3 ページ・見込み約 0.2 クレジット（docs。目安で請求額ではない）
```

続いて PDF と正解データを Snowflake に置き、Task グラフを起動します。実行中は、ステップごとの進捗が表示されます。

```
[run] S00 1✓  S10 3✓  S20 1✓  S30 3✓  S40 1✓  S50 1✓  S55 1✓  S60 1✓  S70 1✓
```

数字は処理した文書数です。`✓` は成功、`…` は実行中、`✗` は失敗を示します。
S10・S30 が 3 件なのは、図の few-shot に使う「お手本」の文書 2 件も一緒に処理するためです。お手本の文書は評価から除きます。

5 分ほどで完了し、次のような要約が出ます（run `h10-readme-contract` の実行例）。

```
[run] 完了：run_id=20261013T000617Z_contract_custom  出力 JSON 1 件  @JA_DOC_STRUCTURED_DB.JA_DOC_STRUCTURED_OUTPUT.RESULTS/<run_id>/
[run] 登録表：DOCUMENTS 1・ELEMENTS 48・TABLES 4・FIGURES 4・REFS 14・PARTIES 2・DEFINED_TERMS 0
[run] 評価：n_docs=1  …  citation_error_rate=0.0  citation_coverage=1.0  text_cer=0.0609  article_recall=1.0  …
```

**表示された `run_id` を控えてください。** 次のステップで SQL を実行するときに使います。既定の run_id は「UTC の日時_コーパス_指定の種類」です。`--run-id <名前>` を指定して任意の名前を付けることもできます。

対象文書は、`--docs id1,id2`（カンマ区切り）、`--docs-file <ファイル>`（1 行 1 文書）、`--slice pilot` のいずれか 1 つで指定します。
`--eval` を付けない場合は正解データを Snowflake に置かず、読み取りと登録だけを実行します。

### 5.1 1 文書の読み取りの流れ

Task グラフの中で、1 つの `doc.pdf` は次のように読み取られます。
AI 関数を呼ぶのは S20 と S40 だけで、どちらも結果をキャッシュ表に保存します。
条項木・引用パス・参照・当事者・定義語は、S50 が PDF のテキスト層から規則で組み立てます。

```mermaid
flowchart LR
    pdf[("@RAW.DOCS<br/>&lt;corpus&gt;/&lt;doc_id&gt;/doc.pdf")]
    pdf --> s10["S10 入力の確認<br/>台帳 RAW.FILES と同じ md5 で<br/>ステージにあるか"]
    s10 --> s20["S20 本文・表（SQL）<br/>AI_PARSE_DOCUMENT<br/>LAYOUT・page_split"]
    s10 --> s30["S30 幾何（SPCS ジョブ）<br/>pdfplumber：文字と座標・行・段組・柱・罫線<br/>表と図の領域、図の切り出し（150dpi）"]
    s20 --> c1[("PARSED.PARSE_RAW<br/>PARSE_PAGES<br/>ページごとの Markdown")]
    s30 --> w[("@RAW.WORK・OPS.REGIONS<br/>行・領域・図の画像")]
    w --> s40["S40 図（SQL）<br/>AI_COMPLETE：図の画像＋お手本 2 例<br/>→ ノードと矢印の JSON"]
    s40 --> c2[("PARSED.FIGURE_RAW")]
    c1 --> s50
    w --> s50
    c2 --> s50
    s50["S50 統合（SPCS ジョブ）<br/>・本文：柱・ページ番号を除いた text と除く前の text_with_furniture<br/>・表：Markdown の表と罫線なしの列挙を格子に、ページ・段をまたぐ表を 1 つにつなぐ<br/>・図：ノードと辺から根→葉の経路を計算<br/>・条項木：テキスト層の行から章・条・項・号を組み立て、引用パスを付ける<br/>・参照・当事者・定義語を規則で抽出<br/>・番号の飛び・重複・未解決の参照 → repair_queue、出力の検査"]
    s50 --> out[("@OUTPUT.RESULTS<br/>&lt;run_id&gt;/&lt;corpus&gt;/&lt;doc_id&gt;.json")]
    out --> s55["S55 登録（SQL）<br/>JSON を 11 の登録表へ展開"]
    out --> s60["S60 評価（--eval のときだけ）"]
```

| ステップ | 何をするか | 書き出す先 | AI |
|---|---|---|---|
| S10 入力の確認 | PUT 済みの `doc.pdf` が、台帳と同じ md5 でステージにあるかを確かめる | `OPS.STEP_RUNS` | — |
| S20 本文・表 | `AI_PARSE_DOCUMENT`（LAYOUT）で、ページごとの Markdown（見出し・段落・表）を得る。NULL やページ数の不一致はエラー行として残す | `PARSED.PARSE_RAW`・`PARSE_PAGES` | ✔ |
| S30 幾何 | `pdfplumber` で文字の座標から行・段組・柱・罫線を取り、表と図の領域を見つけて、図だけを画像に切り出す | `@RAW.WORK`・`OPS.REGIONS` | — |
| S40 図 | 切り出した図の画像を、お手本 2 例（画像と期待 JSON）と一緒に `AI_COMPLETE` に渡し、ノードと矢印を JSON で受け取る | `PARSED.FIGURE_RAW` | ✔ |
| S50 統合 | 上の 3 つを合わせて 1 文書 1 つの JSON を作る。条項木と引用パスはテキスト層の行から規則で組み立てる。出力を検査し、違反があれば書かずに失敗する | `@OUTPUT.RESULTS` | — |
| S55 登録 | JSON を `DOCUMENTS`・`OUTLINE`・`ELEMENTS` などの表に展開する（§6.2） | `OUTPUT` スキーマの表 | — |

- **キャッシュ：** S20・S40 の結果は、入力のハッシュ・関数・モデル・オプションをキーに保存します。同じ PDF を別の run で読み直しても AI 関数は呼ばれません。
- **中間成果物の受け渡し：** ステップの間はステージとキャッシュ表だけで受け渡します。途中で失敗しても、成功したステップの結果を使って再開できます（§9）。
- **正解は使わない：** 読み取り（S10〜S55）は `doc.pdf` と自分の run の中間成果物だけを読みます。正解は評価（S60）のときに、評価ロールだけが読みます。

---

## 6. ステップ 3：結果を SQL で引く

### 6.1 出力 JSON の形

1 文書の読み取り結果は、1 つの JSON にまとめられます。
主なキーは `outline`（条項木）・`elements`（本文要素）・`tables`・`figures`・`refs`（参照）・`parties`（当事者）・`defined_terms`（定義語）です。
上の契約書では、次のような値が入ります。会社名はデータセットの架空のものです。

```json
"outline": [
  {"id": "c3", "depth": 0, "node_kind": "article", "label": "第１条", "title": "目的および検討の期間", "citation": "第１条", "page": 1}
],
"parties": [
  {"alias": "甲", "name": "株式会社霜月食品工業", "role": "甲", "page": 1},
  {"alias": "乙", "name": "コトナミ冷熱技研株式会社", "role": "乙", "page": 1}
],
"refs": [{"from_citation": "第4条 6", "to_citation": "第4条"}]
```

番号の字形（`第１条` の全角数字など）は、PDF に印刷された表記のまま保存します。
ほかに `pages`（ページごとの本文）・`repair_queue`（番号の飛び・重複など）・`provenance`（使った関数・モデル・イメージのタグ・エラー数）があります。

### 6.2 登録表とビュー

S55 が JSON を `JA_DOC_STRUCTURED_DB.JA_DOC_STRUCTURED_OUTPUT` の表に展開します。どの表も先頭の列は `run_id, corpus, doc_id` です。

```mermaid
flowchart LR
    json[("@OUTPUT.RESULTS<br/>出力 JSON")] -->|"S55"| tbl["DOCUMENTS・PAGES・OUTLINE・ELEMENTS<br/>TABLES・FIGURES・REFS<br/>PARTIES・DEFINED_TERMS・TERM_USES"]
    tbl --> vp["V_PROVISIONS<br/>OUTLINE の見出し＋ELEMENTS の本文"]
    tbl --> vr["V_REFS_RESOLVED<br/>REFS を参照先の条項に結ぶ"]
    vp --> vr
    key["CITATION_KEY()<br/>全角・半角・空白を吸収"] -.-> vp
    key -.-> vr
    vp --> q["照会例<br/>sql/examples/queries.sql"]
    vr --> q
    tbl --> q
```

| 表・ビュー | 1 行の単位 |
|---|---|
| `DOCUMENTS` | 1 文書（題名・ページ数・エラー数・出力 JSON の場所） |
| `OUTLINE` | 条項木の 1 節点（章・条・項・号。見出しと引用パス） |
| `ELEMENTS` | 1 本文要素（項・号の本文と引用パス） |
| `TABLES`・`FIGURES` | 1 表・1 図（格子・ノードと辺）。ページ・段をまたいでつないだ表は `fragments`（元の断片）と `stitch`（つないだ理由）を持つ |
| `REFS` | 1 参照（参照元と参照先の引用パス） |
| `PARTIES`・`DEFINED_TERMS`・`TERM_USES` | 当事者・定義語・定義語の使用箇所（契約書だけ） |
| `V_PROVISIONS` | 条項の見出しと本文をまとめたビュー |
| `V_REFS_RESOLVED` | 参照を、文書内の参照先の条項に結び付けたビュー |
| `CITATION_KEY(c)` | 引用パスの照合キー（全角と半角、空白の違いを吸収する関数） |

### 6.3 照会例を流す

`sql/examples/queries.sql` には 5 つの照会例があります。ファイル先頭の `SET run_id = '…'` を、ステップ 2 で控えた run_id に書き換えてから実行します。

```bash
snow sql -c <接続名> -f sql/examples/queries.sql \
  -D db=JA_DOC_STRUCTURED_DB -D schema_output=JA_DOC_STRUCTURED_OUTPUT \
  -D role_predict=JA_DOC_STRUCTURED_PREDICT -D warehouse=JA_DOC_STRUCTURED_WH
```

Snowsight のワークシートで流すときは、`<% db %>` などのテンプレート変数を上の名前に置き換えてください。下の抜粋を単独で流すときは、先に `USE ROLE JA_DOC_STRUCTURED_PREDICT; USE WAREHOUSE JA_DOC_STRUCTURED_WH; SET run_id = '<run_id>'; SET doc_id = 'nda-0003--ct-a4-1col-form';` を実行します。主な照会は次のとおりです。

```sql
-- 条項を引用パスで引く。半角で書いても、全角で保存された「第３条 ４ （１）」が引ける
SELECT citation, title, text
FROM JA_DOC_STRUCTURED_DB.JA_DOC_STRUCTURED_OUTPUT.V_PROVISIONS
WHERE run_id = $run_id AND doc_id = $doc_id
  AND citation_key = JA_DOC_STRUCTURED_DB.JA_DOC_STRUCTURED_OUTPUT.CITATION_KEY('第3条 4 (1)');
```

```
| CITATION         | TITLE | TEXT                                                     |
| 第３条 ４ （１） |       | 開示を受けた時に、受領した当事者が正当に保有していた情報 |
```

```sql
-- 第４条を参照している条項
SELECT from_citation, to_citation, to_title
FROM JA_DOC_STRUCTURED_DB.JA_DOC_STRUCTURED_OUTPUT.V_REFS_RESOLVED
WHERE run_id = $run_id AND doc_id = $doc_id
  AND JA_DOC_STRUCTURED_DB.JA_DOC_STRUCTURED_OUTPUT.CITATION_KEY(to_citation)
      LIKE JA_DOC_STRUCTURED_DB.JA_DOC_STRUCTURED_OUTPUT.CITATION_KEY('第4条') || '%'
ORDER BY from_citation;

-- 甲は誰か
SELECT doc_id, alias, name, role
FROM JA_DOC_STRUCTURED_DB.JA_DOC_STRUCTURED_OUTPUT.PARTIES
WHERE run_id = $run_id;
```

ほかに「定義語の定義箇所と使用数」「参照の解決率」があります。

**確認してみましょう：** 引用パスを `'第6条 2'` などに変更し、該当する条項の本文を取得できることを確認してください。

---

## 7. ステップ 4：精度を確かめる

`--eval` を付けた run は、正解と照合した結果が評価 DB に記録されます。評価 DB は評価ロールでしか読めません。
ステップ 2 では、次のように `--eval` を付けて流しました。

```bash
# 読み取り・登録に続けて、正解での採点（S60）まで流す
scripts/start.sh --corpus contract --docs nda-0003--ct-a4-1col-form --eval
```

`--eval` を付けずに実行した run は、あとから評価できます。対象文書の正解データを取得して評価ステージに置き、S60 を実行します。

```bash
scripts/start.sh --resume <run_id> --eval
```

```mermaid
flowchart LR
    out[("出力 JSON<br/>@OUTPUT.RESULTS")] --> s60["S60 採点ジョブ<br/>（評価ロール）"]
    gold[("正解<br/>評価 DB の GOLD.FILES")] --> s60
    s60 --> rec["EVAL_RUNS・DOC_METRICS<br/>PAGE_METRICS・ELEMENT_ERRORS"]
    rec --> v["V_RUN_SUMMARY・V_DOC・V_PAGE ほか"]
    er(["JA_DOC_STRUCTURED_EVAL_ROLE"]) -->|"読める"| v
    pr(["JA_DOC_STRUCTURED_PREDICT"]) -.->|"読めない"| gold
```

```sql
USE ROLE JA_DOC_STRUCTURED_EVAL_ROLE;
USE WAREHOUSE JA_DOC_STRUCTURED_WH;
SELECT pred_run_id, n_docs, citation_error_rate, citation_coverage, article_recall,
       text_cer, table_cell_f1, figure_edge_f1, refs_recall_reachable, parties_f1
FROM JA_DOC_STRUCTURED_EVAL_DB.JA_DOC_STRUCTURED_RESULTS.V_RUN_SUMMARY;
```

主な指標の意味は次のとおりです。

| 指標 | 意味 | 見方 |
|---|---|---|
| `citation_error_rate`（引用誤り率） | 正解と対応づいた本文要素のうち、引用パスが違うものの割合 | 主指標。小さいほどよい。**必ず網羅率と一緒に見る**（要素を出さなければ誤り率は下がるため） |
| `citation_coverage`（網羅率） | 正解の本文要素のうち、予測と対応づいたものの割合 | 大きいほどよい |
| `article_recall` | 条の再現率 | |
| `text_cer` | 本文の文字誤り率（編集距離 ÷ 正解の長さ） | AI（LAYOUT）の出力の質 |
| `table_cell_f1`・`figure_edge_f1` | 表のセルの一致、図の矢印（始点・終点・ラベル）の一致 | AI の出力に依存し、実行ごとに少し揺れる |
| `refs_recall_reachable` | 文書内にたどれる参照のうち、正しく取れた割合 | |
| `parties_f1` | 当事者（呼称と名称の対）の一致 | 契約書だけ |

文書ごとの値は `V_DOC`、ページごとの値は `V_PAGE` で確認できます。

---

## 8. ステップ 5：保険約款を読み取る

コーパスの設定を切り替え、同じパイプラインで保険約款を読み取ります。約款には 2 段組のページがあり、表や図も多く含まれます。

```bash
scripts/start.sh --corpus yakkan --docs auto-0001--nl-a4-2col-mincho --eval
```

```mermaid
flowchart LR
    opt["--corpus yakkan"] --> cfg["configs/corpora/yakkan.yaml"]
    cfg --> k1["structure_builder: yakkan<br/>（約款用の条項木の組み立て器）"]
    cfg --> k2["features: parties・defined_terms<br/>を false（抽出しない）"]
    cfg --> k3["figure_shots<br/>約款の図のお手本 2 文書"]
    cfg --> k4["source.huggingface<br/>約款のデータセットとコミット"]
    k1 & k2 & k3 & k4 --> pipe(["同じパイプライン<br/>S00〜S70"])
```

16 ページ・図 8 つの文書で、約 9 分かかります（見込み約 0.6 クレジット）。
完了後、ステップ 3 と 4 の SQL を、この run の run_id と `doc_id = 'auto-0001--nl-a4-2col-mincho'` を指定して実行してください。

- 約款では当事者・定義語の抽出を無効にしているので、`PARTIES`・`DEFINED_TERMS` は 0 行です。
- 約款の評価に出る定義語の指標は、正解側の定義語と本文の対応を採点したものです。
- コーパスの違い（条項木の組み立て器・当事者抽出の有無・お手本の文書など）は、コードではなく `configs/corpora/<name>.yaml` で切り替えています。

参考までに、作成者の実行（run `h10-readme-yakkan`）では引用誤り率 0.022・網羅率 0.978・表セル F1 0.77 でした。
この run は、ページ・段をまたぐ表をつなぐ処理（§12.1）を入れる前のものです。同じ LAYOUT の出力に連結を通すと、この文書の表セル F1 は 0.88 になります（ローカルでの再生。run `h12-dev5-on-yakkan`）。

---

## 9. ステップ 6：失敗と再開を体験する

処理の途中で失敗した場合に備え、故障注入オプションを使って再開の手順を確認します。

```bash
# S50（統合）で、指定した文書だけ失敗させる
scripts/start.sh --corpus contract --docs nda-0003--ct-a4-1col-form --fail S50:nda-0003--ct-a4-1col-form --run-id try-fail
```

```mermaid
flowchart LR
    subgraph first["1 回目（--fail S50:…）"]
        a1["S00〜S40 ✓"] --> a2["S50 ✗"] --> a3(["FAILED・終了コード 1<br/>再開のコマンドを表示"])
    end
    subgraph second["2 回目（--resume try-fail --eval）"]
        b0["正解を評価ステージへ"] --> b1["S10 の入力の確認はやり直す<br/>S20〜S40 は成功済みで飛ばす"]
        b1 --> b2["S50 をやり直す<br/>（attempt 2）"] --> b3["S55・S60・S70"] --> b4(["完了"])
        cache[("AI のキャッシュ<br/>PARSE_RAW・FIGURE_RAW")] -.->|"呼び直さない"| b1
    end
    a3 --> b0
```

S50 が `✗` になり、失敗の理由、ジョブログの末尾、再開用のコマンドが表示されます。コマンドは終了コード 1 で終了します。

```
[run] run try-fail は FAILED で終わった。原因を直してから：scripts/start.sh --resume try-fail
```

再開します。`--eval` を付けると、評価も足せます。

```bash
scripts/start.sh --resume try-fail --eval
```

再開時は、成功済みのステップを飛ばし、失敗した S50 と未実行の S55 以降だけを実行します。S10 の入力確認だけは、再開のたびに行います。
AI 関数の結果はキャッシュ（入力のハッシュ・モデル・オプションをキーにした表）から引くので、
同じ PDF を読み直しても `AI_PARSE_DOCUMENT`・`AI_COMPLETE` は呼ばれず、課金されません。

**確かめてみよう：** 台帳を見ると、S50 だけ `attempt` が 2 になっています。

```sql
USE ROLE JA_DOC_STRUCTURED_ADMIN;
USE WAREHOUSE JA_DOC_STRUCTURED_WH;
SELECT step, doc_id, status, attempt
FROM JA_DOC_STRUCTURED_DB.JA_DOC_STRUCTURED_OPS.STEP_RUNS
WHERE run_id = 'try-fail' ORDER BY step;
```

---

## 10. ステップ 7：後片付け（teardown）

```bash
scripts/teardown.sh
```

```mermaid
flowchart LR
    a["削除対象の一覧<br/>（接頭辞の名前だけ）"] --> b{"確認<br/>（--yes で省略）"}
    b -->|"はい"| c["評価記録と出力 JSON を<br/>results/&lt;run_id&gt;/ に書き出す"]
    c --> d{"件数の照合"}
    d -->|"不一致"| stop(["何も消さずに停止"])
    d -->|"一致"| e["Task を止める<br/>プールのジョブを止める"]
    e --> f["DROP：プール → DB 2 つ<br/>→ ウェアハウス → ロール"]
    f --> g(["残存 0 件を確認<br/>teardown 完了"])
```

削除対象を一覧表示し、確認後に次の処理を行います。`--yes` を付けると確認を省略できます。

1. 評価記録と出力 JSON を `results/<run_id>/` に書き出し、件数を照合する。合わなければ何も削除せずに止まります
2. Task・ジョブを止め、コンピュートプール・データベース 2 つ・ウェアハウス・ロールを、名前を指定して削除する
3. 接頭辞 `JA_DOC_STRUCTURED_` のオブジェクトが 0 件であることを確かめる

最後に `teardown 完了` と表示されれば、Snowflake 側の後片付けは完了です。
`results/<run_id>/out/` には出力 JSON が残るので、Snowflake を消したあとも結果を見返せます。

手元のファイルは teardown では消えません。不要になったら、次のように削除します。

```bash
rm -rf data/ out/ work/ results/ logs/              # 取得したデータ・出力・評価記録・ログ（すべて git 管理外）
docker rmi $(docker images -q jpdocread | sort -u)  # ビルドしたイメージ（push 用の別名は docker images で確かめて消す）
```

---

## 11. 技術の解説

### 11.1 本文と表：`AI_PARSE_DOCUMENT`（S20）

- `LAYOUT` モード・`page_split => TRUE` で、ページごとの Markdown（見出し・段落・表）を得ます。
  OCR モードは 2 段組の読み順を崩すので使いません。
- 結果は、入力のハッシュ・関数・オプションをキーにして `PARSED.PARSE_RAW` に保存し、同じキーなら呼び直しません。
- NULL・エラー・ページ数の不一致は、空文字で埋めずにエラー行として残します（`sql/procedures/s20_parse_text.sql`）。
- 表は、LAYOUT の Markdown の表と、罫線の無い列挙を格子に組み直します。見出しの行・列（`header_path`）は規則で決めます。
- **ページ・段をまたぐ表は、S50 で 1 つにつなぎます。** 条件と工夫は「[12.1 ページ・段をまたぐ表](#121-ページ段をまたぐ表)」を参照してください。つないだ表は、次のように引けます。

  ```sql
  SELECT doc_id, item_id, pages, ARRAY_SIZE(fragments) AS n_fragments, stitch:reasons AS reasons
  FROM JA_DOC_STRUCTURED_DB.JA_DOC_STRUCTURED_OUTPUT.TABLES
  WHERE run_id = $run_id AND fragments IS NOT NULL;
  ```

### 11.2 幾何と図：pdfplumber と `AI_COMPLETE`（S30・S40）

- S30 は SPCS のジョブで動きます。`pdfplumber` で行の座標・段組・柱・罫線を取り、表と図の領域を見つけて、図の部分だけを画像に切り出します（`pypdfium2`、150dpi）。
- S40 は、切り出した画像を `AI_COMPLETE`（既定 `claude-opus-5`）に渡し、ノードと矢印を JSON で返させます。
  `PROMPT()` で、お手本 2 例（few-shot）の画像と期待 JSON を一緒に渡します。根から葉への経路（`paths`）は、返った辺から機械的に計算します。
- 実装で踏んだ注意点：
  - プロンプト本文に素の `{` があると、全行が黙って NULL になります。お手本の JSON は引数で渡します。
  - `response_format` は使わず、`TRY_PARSE_JSON` とコードフェンスの除去で解析します。解析に失敗したら 1 回だけ再試行します。
  - `max_tokens` は、予測したノード候補の数から決めます。正解の要素数は使いません。
- 図はページごとの領域を切り出して読みます。ページや段をまたぐ図の扱いは §12.1 を参照してください。

### 11.3 条項木・参照・当事者：テキスト層と規則（S50）

- PDF のテキスト層（文字と座標）から、条・項・号の見出しの候補を規則で拾い、得点を付けて、条項木を組み立てます。
  約款と契約書では番号の付け方が違うので、文書の体裁を判定して、組み立て器を切り替えます。
- 引用パス（`第３条 ４ （１）`）は条項木から機械的に作ります。番号の字形は印刷されたとおりに残し、照会のときだけ `CITATION_KEY` で正規化して照合します。
- 「前条」「第５条第２項」「別表１」などの参照は、規則で引用パスに解決します。
- 契約書では、前文の「以下『甲』という」や当事者欄から当事者を、定義条から定義語を抽出します。
- AI を使わないので、同じ PDF からは毎回同じ結果になり、移植元の実装の出力とも 1 文字単位で比べられます。
- 番号の飛び・重複・解決できない参照は `REPAIR_QUEUE` に記録します。

### 11.4 パイプラインの仕組み

- **Task グラフ：** `start.sh` が run を台帳（`OPS.RUNS`）に登録し、`EXECUTE TASK … USING CONFIG` でルートの Task を起動します。
  各 Task の本体は、プロシージャを呼ぶ 1 文の `CALL` です。
- **SPCS ジョブ：** S30・S50・S60 は、ローカルでビルドしたイメージを `EXECUTE JOB SERVICE` で動かします。
  ジョブ内の接続は SPCS が渡すトークンを使い、資格情報はイメージに入れません。
- **再開：** `OPS.STEP_RUNS` に `(run_id, step, doc_id)` ごとの状態を記録します。成功済みのステップは再実行せず、AI 関数の結果はキャッシュでも保護します。
- **登録の冪等性：** S55 は `(run_id, doc_id)` ごとに削除してから挿入するので、何度流しても行は増えません。
- **評価の分離：** 正解データは評価 DB のステージにだけ置きます。読み取り用のロールには評価 DB の権限がないため、正解データを参照できません。
  評価（S60）は、評価ロールが持つプロシージャから起動します。setup の検証では `USE SECONDARY ROLES NONE` を付けて、この分離を確かめます。

### 11.5 実装の場所

| ステップ | 実装 |
|---|---|
| 取得と照合・PUT・run の制御 | `src/jpdocread/fetch/`・`deploy.py`・`run.py` |
| S00・S10・S70・ジョブの起動 | `sql/procedures/steps.sql` |
| S20 本文・表 | `sql/procedures/s20_parse_text.sql` |
| S30・S50・S60 のジョブ本体 | `src/jpdocread/jobs.py`（読み取りは `src/jpdocread/read/`、採点は `src/jpdocread/eval/`） |
| S40 図 | `sql/procedures/s40_figures.sql` |
| S55 登録 | `sql/procedures/s55_register.sql`（列の定義は `src/jpdocread/load/rows.py`） |
| S60 評価の起動 | `sql/procedures/s60_evaluate.sql` |
| Task グラフ | `sql/tasks/dag.sql` |
| 登録表のビュー・評価ビュー | `sql/views/output_views.sql`・`eval_views.sql` |

各スクリプトは `--help`、`jpdocread` は `uv run jpdocread <サブコマンド> --help` で、すべてのオプションを確かめられます。

---

## 12. エッジケースの対応

約款や契約書で読み取りが崩れやすい箇所と、その対処をまとめます。判断に十分な根拠がない場合は無理に出力せず、処理できなかった内容を記録に残す方針です。

### 12.1 ページ・段をまたぐ表

- **課題：** `AI_PARSE_DOCUMENT` はページごとに結果を返すため、ページや 2 段組の段をまたぐ表が分割されます。約款では表の約 3 割がこのケースに該当し、分割したままではセル F1 が約 0.6 まで低下します。
- **対処：** S50 で、隣り合う表が「間に本文がない」「列数が同じ」「見出しの再掲または行番号の続き（⑤ → ⑥）がある」という条件をすべて満たす場合に限り、1 つの表として結合します（`src/jpdocread/read/stitch.py`）。ページ番号、柱、繰り返される章名は本文として扱いません。再掲された見出しは結合時に削除します。元の断片は `fragments`、結合理由は `stitch` に残り、`tables.stitch: false` を指定すれば結合前の出力に戻せます。
- **結果：** 規則の調整に使っていない文書では、ページをまたぐ表のセル F1 が約款で 0.585 から 0.891、契約書で 0.558 から 0.908 に向上しました。別々の表を誤って結合した例はありません（run `h12-ho-yakkan`・`h12-ho-contract`）。ページを分割しない LAYOUT（0.797）や、画像を縦に並べて `AI_COMPLETE` に渡す方式（0.783）より精度が高く、追加の AI 呼び出しもありません。
- **残る課題：** 見出しを読み誤った場合や、見出しの再掲と番号の続きがどちらもない場合は結合できません。ページをまたぐ図はデータセットに例がないため、結合の対象外です。

### 12.2 その他

| 課題 | 解決・回避した工夫 |
|---|---|
| 2 段組で文が混ざる | OCR モードを使わず LAYOUT で読む。テキスト層の段の境目は、ページごとでなく文書全体で 1 つに決める（図だけのページや表の空白で誤らない） |
| 柱・ページ番号・目次が条の見出しに紛れる | 繰り返し出る行を柱として外し、印刷された目次は見出しの照合に使う |
| 番号の字形がばらばら（`第一条`・`第１条`・`（１）`） | 印刷どおりに残し、照会のときだけ `CITATION_KEY()` でそろえる |
| 章ごとに条番号が 1 に戻る／戻らない | 章の境目の条番号を多数決で見て体裁を決め、条の取りこぼしを防ぐ |
| 番号の飛び・解決できない参照 | 推測で埋めず `repair_queue` に記録する |
| AI 関数の NULL・解析できない JSON | 空文字で埋めずエラー行として残す。図の JSON はフェンスを外して読み、失敗は 1 回だけ再試行する |
| プロンプトに `{` があると全行が黙って NULL | お手本の JSON は引数で渡し、テストで `{` が無いことを確かめる |
| 大きな図で応答が切れる・矢印が循環する | `max_tokens` を予測したノード数から決める。経路は AI に任せず辺から計算する |
| 途中の失敗で AI を再課金する | 失敗したステップだけを再開し、AI の結果はキャッシュから引く |
| 壊れた・準備中のデータを読む | SHA-256 と `status` を照合し、合わなければ何も作らずに止まる |
| 評価が甘くなる | お手本の文書・同じ文面の別レイアウトを評価から除き、正解は読み取り側のロールから見えない評価 DB に置く |

---

## 13. 発展：文書を増やす・設定を変える

### 13.1 対象の文書を増やす

`--slice pilot` で各コーパスの pilot 10 文書を流せます。`--slice all` は全文書です。
全文書を指定すると、課金対象のページ数と見込みクレジットを表示し、実行前に確認を求めます。参考値として、移植元の実測では約款に約 40、契約書に約 13〜15 クレジットかかりました。
文書の一覧は、`uv run jpdocread fetch --corpus <c> --slice all --dry-run` でデータを取得せずに確認できます。

### 13.2 設定を変える

| 変えたいもの | 場所 |
|---|---|
| 図のモデル・`max_tokens` の係数 | `configs/pipeline.yaml` の `figure` |
| コーパスごとの組み立て器・抽出の有無・お手本の文書・pilot | `configs/corpora/<name>.yaml` |
| ページ・段をまたぐ表をつなぐか | `configs/corpora/<name>.yaml` の `tables.stitch`（同梱の設定は両コーパスとも `true`。`false` にするか、キーを書かなければページごとの表を出す） |
| データセットの版（Hugging Face のコミット） | `configs/corpora/<name>.yaml` の `source.huggingface.revision`（40 桁のコミット SHA。`main`・タグ・短縮した SHA はエラーになります） |
| 手元のデータセットから読む（ネットワークに出られない環境） | `configs/corpora/<name>.yaml` の `source.kind` を `local` にし、`configs/deploy.local.env` に `DATA_ROOT_YAKKAN`・`DATA_ROOT_CONTRACT`（`manifest.json` がある階層）を書く |

データセットの版を上げる場合は、`revision` を新しいコミット SHA に変更し、`uv run jpdocread fetch --corpus <name> --dry-run` で対象を確認してから実行してください。
取得元や版が異なるデータは、`data/` 内の別の場所に保存されます。同じ場所に内容の異なる manifest が置かれた場合、取得処理は停止します。

### 13.3 開発者向け

```bash
uv run ruff check . && uv run ruff format --check .   # lint と format
uv run pytest                                          # 単体テスト（Snowflake・Hugging Face への接続は既定で除外）
uv run pytest -m network                               # Hugging Face から実際に取得する試験
uv run jpdocread guard                                 # 正解漏れのガード（読み取り側が正解を参照していないか）
uv run jpdocread fetch --corpus contract --docs-file tests/fixtures/real_docs_contract.txt --eval  # 実文書のテスト用データ
```

```
configs/    設定（パイプライン・コーパス・オブジェクト名・ローカル設定のひな型）
scripts/    setup.sh・start.sh・teardown.sh と共通処理
sql/        setup（DDL）・procedures（各ステップ）・tasks（Task グラフ）・views・verify（ロール分離）・examples（照会例）
container/  ジョブのイメージと SPCS のジョブ仕様
src/jpdocread/  fetch（取得と照合）・read（読み取り）・load（登録表の行）・eval（採点）・run・deploy・jobs（Snowflake での実行）
tests/      unit・guard・ported（移植元のテスト）・integration・fixtures（合成データ）
```

---

## 14. 困ったとき

| 症状 | 対処 |
|---|---|
| `Docker デーモンが動いていない` | Docker Desktop を起動してから setup をやり直す（何も作られていません） |
| `接続名が無い` | `configs/deploy.local.env` の `CONNECTION_NAME` を、`snow connection list` の名前にする |
| snow が設定した接続を使わず認証に失敗する | 期限切れのトークンが環境変数に残っている。スクリプトは自動で外して実行する。手で snow を使うときは `env -u SNOWFLAKE_TOKEN snow …` |
| setup が DDL の前に止まる | 取得したデータが manifest と一致しない。表示されたファイルを確かめ、データを取り直す |
| huggingface.co に接続できない・429 が出る | ネットワークを確かめる。429 なら時間をおいて再実行する |
| `run_id が既にある` | 別の `--run-id` にするか、`--resume <run_id>` |
| start が途中で失敗した | 表示された理由とログを見て、`scripts/start.sh --resume <run_id>`。一時的な AI 関数のエラーは再開で通ることがあります |
| `--skip-build` で `イメージがリポジトリに無い` | teardown でイメージも消えている。`--skip-build` を外して setup |

ログは `logs/` に保存されます（`setup-<日時>.log` など）。失敗したステップの理由は `JA_DOC_STRUCTURED_DB.JA_DOC_STRUCTURED_OPS.STEP_RUNS` の `error_text` で確認できます。ジョブログの末尾は、start.sh が失敗したときにも表示されます。

### 所要時間と費用の目安

作成者の環境（AWS 東京リージョン）で、2026-10-13 に計測した値です。

| 手順 | 時間 | AI 関数の見込み |
|---|---|---|
| `setup.sh`（クリーンから、ビルド込み） | 約 3.6 分 | なし |
| ステップ 2：契約書 1 文書（3 ページ） | 約 5.5 分（run `h10-readme-contract`） | 約 0.2 クレジット |
| ステップ 5：約款 1 文書（16 ページ・図 8） | 約 8.5 分（run `h10-readme-yakkan`） | 約 0.6 クレジット |
| ステップ 6：故障注入と再開 | 約 7.5 分（2 回分。run `h10-fail-contract`） | 0（キャッシュから引く） |
| `teardown.sh` | 約 1 分 | なし |

- 見込みクレジットは、ページ数と図の数に単価を掛けた目安で、請求額ではありません。単価は LAYOUT 約 0.0037 クレジット/ページ、図 約 0.042 クレジット/図（移植元の実測）。
- 実際の消費は、ウェアハウスとコンピュートプールの稼働分が加わります。どちらも短い時間で自動停止します。
- 実際の消費量は、アカウントの使用量画面で確認してください。

---

## 15. 既知の限界と注意事項

- **データは合成です。** 架空の会社・商品・人物からなる合成データセットで、実在の約款・契約書とは関係ありません。法的な参照には使えません。
- **電子生成の PDF が前提です。** テキスト層のある PDF だけを対象にしています。スキャンした PDF には使えません。
- **日本語は `AI_PARSE_DOCUMENT` の公式対応言語に含まれません。** 動作は確認していますが、予告なく結果が変わる可能性があります。
- **AI の出力は揺れます。** 図の `AI_COMPLETE` は temperature 0 でも実行ごとに結果が少し変わり、本文と表も呼び直すと変わることがあります。1 回の実行の値の差で優劣を判断しないでください。
- **モデルとリージョン：** 図のモデル（既定 `claude-opus-5`）が自分のリージョンで使えないときは、`configs/pipeline.yaml` の `figure.model` を変えてください。
  クロスリージョン推論を有効にするかは、アカウント管理者が判断してください。本ハンズオンのスクリプトはアカウントの設定を変更しません。
- **規則は改善していません。** 社内で検証した構成をそのまま移しています。約款の重要事項説明書の扱いと号の再現率、図の領域の誤検出（余分な `AI_COMPLETE` の課金）に課題が残ります。
- **ページをまたぐ表の残りの失敗：** LAYOUT が続きのページの見出しを読み誤ると（例「貸主」→「貨主」）、再掲と判定できずに表が分かれたまま残ります。片方のページが表として返らないときもつなげません。図はページ・段をまたぐ例がデータに無いため、つなぐ処理はありません。
- **範囲外：** データセットに含まれる質問応答（`qa.json`）を使った検索・QA の評価は扱いません。
- **権限：** setup は ACCOUNTADMIN でロールとアカウント権限を作ります。共有のアカウントで流すときは、管理者に確認してください。
- **データの扱い：** 取得したデータ・出力・ログは `data/`・`out/`・`results/`・`logs/` に置き、`.gitignore` でコミットの対象から外しています。リポジトリにはデータを含めません。

---

## 16. 出典とライセンス

### データセット

次の 2 つのデータセットを、[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) のもとで利用しています。
取得したファイルは改変せずにそのまま読みます。リポジトリにはデータを含めず、実行時に Hugging Face から取得します。
正式な引用方法は、各データカードの Citation を参照してください。

| コーパス | データセット | 作成者 | 規模 | URL |
|---|---|---|---|---|
| `yakkan` | Japanese Insurance Policy Document Understanding（日本語保険約款の合成データセット） | cvusk | 113 文書・1,437 ページ | <https://huggingface.co/datasets/cvusk/japanese-insurance-document-understanding> |
| `contract` | Japanese Contract Document Understanding（日本語ビジネス契約書の合成データセット） | cvusk | 100 文書・656 ページ | <https://huggingface.co/datasets/cvusk/japanese-contract-document-understanding> |

取得するコミットは、`configs/corpora/<name>.yaml` の `source.huggingface.revision` で固定しています。データセットが更新されても、入力は変わりません。

### フォント

データセットの PDF には、次のフォントが埋め込まれています。

- Noto フォント：SIL Open Font License 1.1
- IPAex フォント：IPA フォントライセンス v1.0

### 手法

社内で検証した 2 つのパイプライン（保険約款・契約書）の採用構成を、1 つの設定駆動のパイプラインとして整理し、移植したものです。
コードと設定のコメントに出てくる「移植元」は、この社内のパイプラインを指します。社内のパイプラインと資料は、このリポジトリには含まれません。
