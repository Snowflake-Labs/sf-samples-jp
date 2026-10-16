import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { query } from "@/lib/sf-client";
import { getSession } from "@/lib/session";

/**
 * Dual-path consistency check (M5).
 *
 * The app can read ML results either from Postgres (hr_lake.*, synced by
 * sync_ml_to_pg_lake.py) or straight from Snowflake (HR_ANALYTICS.PUBLIC.*).
 * The two can drift when a sync run is skipped or fails, and nothing today
 * surfaces that. This compares row counts and aggregate checksums per table
 * so the drift is visible instead of silently returning stale numbers.
 */

interface TablePair {
  name: string;
  pgSql: string;
  sfSql: string;
}

const PAIRS: TablePair[] = [
  {
    name: "prediction_results",
    pgSql: `SELECT COUNT(*)::int AS cnt, ROUND(COALESCE(SUM(risk_score), 0)::numeric, 4) AS checksum FROM hr_lake.prediction_results`,
    sfSql: `SELECT COUNT(*) AS CNT, ROUND(COALESCE(SUM(RISK_SCORE), 0), 4) AS CHECKSUM FROM HR_ANALYTICS.PUBLIC.PREDICTION_RESULTS`,
  },
  {
    name: "relationship_results",
    pgSql: `SELECT COUNT(*)::int AS cnt, ROUND(COALESCE(SUM(relationship_score), 0)::numeric, 4) AS checksum FROM hr_lake.relationship_results`,
    sfSql: `SELECT COUNT(*) AS CNT, ROUND(COALESCE(SUM(RELATIONSHIP_SCORE), 0), 4) AS CHECKSUM FROM HR_ANALYTICS.PUBLIC.RELATIONSHIP_RESULTS`,
  },
  {
    name: "transfer_fit_results",
    pgSql: `SELECT COUNT(*)::int AS cnt, ROUND(COALESCE(SUM(fit_score), 0)::numeric, 4) AS checksum FROM hr_lake.transfer_fit_results`,
    sfSql: `SELECT COUNT(*) AS CNT, ROUND(COALESCE(SUM(FIT_SCORE), 0), 4) AS CHECKSUM FROM HR_ANALYTICS.PUBLIC.TRANSFER_FIT_RESULTS`,
  },
  {
    name: "shap_results",
    pgSql: `SELECT COUNT(*)::int AS cnt, ROUND(COALESCE(SUM(shap_value), 0)::numeric, 4) AS checksum FROM hr_lake.shap_results`,
    sfSql: `SELECT COUNT(*) AS CNT, ROUND(COALESCE(SUM(SHAP_VALUE), 0), 4) AS CHECKSUM FROM HR_ANALYTICS.PUBLIC.SHAP_RESULTS`,
  },
  {
    name: "similar_cases",
    pgSql: `SELECT COUNT(*)::int AS cnt, ROUND(COALESCE(SUM(similarity_score), 0)::numeric, 4) AS checksum FROM hr_lake.similar_cases`,
    sfSql: `SELECT COUNT(*) AS CNT, ROUND(COALESCE(SUM(SIMILARITY_SCORE), 0), 4) AS CHECKSUM FROM HR_ANALYTICS.PUBLIC.SIMILAR_CASES`,
  },
  {
    name: "evidence_store",
    pgSql: `SELECT COUNT(*)::int AS cnt, '-' AS checksum FROM hr_lake.evidence_store`,
    sfSql: `SELECT COUNT(*) AS CNT, '-' AS CHECKSUM FROM HR_ANALYTICS.PUBLIC.EVIDENCE_STORE`,
  },
];

// Tolerate small float drift from NUMERIC vs FLOAT rounding across engines
const CHECKSUM_EPSILON = 0.01;

export async function GET() {
  const session = await getSession();
  if (!session) return NextResponse.json({ error: "認証が必要です" }, { status: 401 });

  const results: {
    table: string;
    pgCount: number | null;
    sfCount: number | null;
    countDelta: number | null;
    pgChecksum: string | null;
    sfChecksum: string | null;
    checksumMatch: boolean | null;
    status: "ok" | "drift" | "error";
    error?: string;
  }[] = [];

  for (const pair of PAIRS) {
    let pgRow: { cnt: number; checksum: string } | null = null;
    let sfRow: { CNT: number; CHECKSUM: string } | null = null;
    let errMsg: string | undefined;

    try {
      const [r] = await pgQuery<{ cnt: number; checksum: string }>(pair.pgSql);
      pgRow = r ?? null;
    } catch (err) {
      errMsg = `pg: ${(err as Error).message}`;
      console.error(`[data-consistency] ${pair.name} pg query failed:`, (err as Error).message);
    }

    try {
      const [r] = await query<{ CNT: number; CHECKSUM: string }>(pair.sfSql);
      sfRow = r ?? null;
    } catch (err) {
      errMsg = `${errMsg ? errMsg + "; " : ""}sf: ${(err as Error).message}`;
      console.error(`[data-consistency] ${pair.name} sf query failed:`, (err as Error).message);
    }

    if (!pgRow || !sfRow) {
      results.push({
        table: pair.name,
        pgCount: pgRow ? Number(pgRow.cnt) : null,
        sfCount: sfRow ? Number(sfRow.CNT) : null,
        countDelta: null,
        pgChecksum: pgRow ? String(pgRow.checksum) : null,
        sfChecksum: sfRow ? String(sfRow.CHECKSUM) : null,
        checksumMatch: null,
        status: "error",
        error: errMsg,
      });
      continue;
    }

    const pgCount = Number(pgRow.cnt);
    const sfCount = Number(sfRow.CNT);
    const countDelta = sfCount - pgCount;

    const pgCs = String(pgRow.checksum);
    const sfCs = String(sfRow.CHECKSUM);
    let checksumMatch: boolean;
    if (pgCs === "-" || sfCs === "-") {
      checksumMatch = true; // not comparable for this table
    } else {
      checksumMatch = Math.abs(Number(pgCs) - Number(sfCs)) <= CHECKSUM_EPSILON;
    }

    results.push({
      table: pair.name,
      pgCount,
      sfCount,
      countDelta,
      pgChecksum: pgCs,
      sfChecksum: sfCs,
      checksumMatch,
      status: countDelta === 0 && checksumMatch ? "ok" : "drift",
    });
  }

  const drifted = results.filter((r) => r.status === "drift");
  const errored = results.filter((r) => r.status === "error");

  return NextResponse.json({
    checkedAt: new Date().toISOString(),
    healthy: drifted.length === 0 && errored.length === 0,
    summary: {
      total: results.length,
      ok: results.filter((r) => r.status === "ok").length,
      drift: drifted.length,
      error: errored.length,
    },
    message:
      drifted.length === 0 && errored.length === 0
        ? "pg_lake と Snowflake Core は一致しています。"
        : `${drifted.length}テーブルで乖離、${errored.length}テーブルで取得エラー。sync_ml_to_pg_lake.py の再実行を検討してください。`,
    tables: results,
  });
}
