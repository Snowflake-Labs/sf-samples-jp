#!/usr/bin/env bash
# 準備：道具と接続の確認 → データの取得と照合 → ローカル検査 → Snowflake の専用オブジェクト → ロール分離の検証
#       → モデルの確認 → イメージの build と push → 手本の作成。再実行しても既存のデータやほかのオブジェクトは消さない。
#
#   scripts/setup.sh [--corpus yakkan|contract|all] [--skip-build] [--skip-fetch] [--yes]
#
# --yes が無ければ、検査まで行い、Snowflake のオブジェクトを作る前に止まる（作る文の一覧を表示する）。
set -euo pipefail
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh"

CORPUS=all; SKIP_BUILD=0; SKIP_FETCH=0; YES=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --corpus) CORPUS="${2:?--corpus の値}"; shift 2 ;;
    --skip-build) SKIP_BUILD=1; shift ;;
    --skip-fetch) SKIP_FETCH=1; shift ;;
    --yes) YES=1; shift ;;
    --help|-h) sed -n 2,7p "$0"; exit 0 ;;
    *) die "未知の引数: $1（--help を見る）" ;;
  esac
done
case "$CORPUS" in yakkan|contract) CORPORA=("$CORPUS") ;; all) CORPORA=(yakkan contract) ;;
  *) die "--corpus は yakkan・contract・all のどれか: $CORPUS" ;; esac

# 1. 道具と接続
require_cmd uv "https://docs.astral.sh/uv/ の手順で uv を入れる"
[[ "$SKIP_BUILD" == 1 ]] || require_cmd docker "Docker と buildx を入れる（またはイメージを作らないなら --skip-build）"
[[ "$SKIP_BUILD" == 1 ]] || require_cmd snow "Snowflake CLI を入れる（イメージリポジトリへのログインに使う）"
cd "$HOME_DIR"
uv sync --quiet || die "uv sync に失敗した"
jp() { uv run --quiet python -m jpcalc "$@"; }
uv run --quiet python -c 'from jpcalc.common.local_settings import resolve_connection_name as r; r()' \
  || die "接続名が無い。SNOWFLAKE_CONNECTION_NAME を設定するか、configs/deploy.env.example を configs/deploy.local.env にコピーして CONNECTION_NAME を指定する"
log "接続名を解決した（値は表示しない）"

# 2〜3. データの索引・分割・予測用の PDF（pilot と手本）の取得と照合
for c in "${CORPORA[@]}"; do
  if [[ "$SKIP_FETCH" == 0 ]]; then
    log "[$c] 公開索引を作る"; jp index --corpus "$c" || die "[$c] 索引の取得に失敗した（ネットワークと固定 revision を確かめる）"
  fi
  jp split --corpus "$c" --check-only || die "[$c] 分割が記録と一致しない（configs/split.yaml を確かめる）"
  if [[ "$SKIP_FETCH" == 0 ]]; then
    for sl in pilot shots; do jp fetch --corpus "$c" --slice "$sl" || die "[$c] $sl の取得・照合に失敗した"; done
  fi
done

# 4. ローカル検査（設定・命名・秘密情報・正解漏れガード・単体テスト）。通るまで DDL・PUT・AI を行わない
"$HOME_DIR/scripts/start.sh" --test || die "ローカル検査が通らない（上の出力を見て直す）"

# 5〜7. Snowflake の専用オブジェクトとロール分離の検証
if [[ "$YES" == 0 ]]; then
  jp setup | tail -n 5 || true
  log "Snowflake のオブジェクトはまだ作っていない。作成するには --yes を付けて再実行する。実行予定の SQL は jpcalc setup で確認できる"
  exit 2
fi
jp setup --apply || die "setup に失敗した。ACCOUNTADMIN を使用できるユーザーで接続しているか確認し、再実行する"
jp verify-roles || die "ロール分離の検証に失敗した（予測ロールが評価側に触れられる）。評価データを置かない"
# 既定のモデルはクロスリージョン推論を要る。使えなければ、数分かかるイメージのビルドの前に止める
jp check-model || die "設定のモデルを使えない（README の 3.1 と 15 を見る。アカウントの設定はこのスクリプトでは変えない）"

# 8. イメージ
if [[ "$SKIP_BUILD" == 0 ]]; then
  "$HOME_DIR/scripts/build_push.sh" || die "イメージの build・push に失敗した（Docker の起動と snow のログインを確かめる）"
fi

# 9. few-shot の手本（DEV の手本用 PDF の正解から機械的に作る。評価対象の PDF と元文書を共有しない）
for c in "${CORPORA[@]}"; do
  # 手本用 PDF の正解に加え、pilot の正解の関数名（手本の関数名が重ならないように置き換えるため）を評価側の置き場所に取得する
  docs="$( { jp targets --corpus "$c" --slice shots && echo && jp targets --corpus "$c" --slice pilot; } 2>/dev/null \
    | tr ',' '\n' | sed 's/--.*//' | grep -v '^$' | sort -u | paste -sd, -)" \
    || die "[$c] 手本の対象を決められない（configs/pipeline.yaml の slices を確かめる）"
  jp fetch-gold --corpus "$c" --docs "$docs" || die "[$c] 手本・pilot の正解の取得に失敗した"
  # 手本は手本用 PDF の pdoc（読み取りの結果。AI を使わない）から作る。クリーンな状態では pdoc が無いので先に作る
  jp pdoc --corpus "$c" --slice shots >/dev/null || die "[$c] 手本用 PDF の pdoc を作れない"
  jp make-shots --corpus "$c" || die "[$c] 手本を作れない"
done

# 10. 要約
for c in "${CORPORA[@]}"; do
  n="$(jp targets --corpus "$c" --slice pilot 2>&1 >/dev/null)" || die "[$c] pilot の対象を決められない"
  log "[$c] pilot: ${n#targets: }・見込み 1 PDF あたり AI 約 10 要求（キャッシュに当たれば 0）"
done
log "setup が完了した。次は README §5 の手順に従い、保険約款 1 PDF から始める（scripts/start.sh --corpus yakkan --docs group-0006-c2--grp-a4-1col-mincho --input pdf --cards auto）"
