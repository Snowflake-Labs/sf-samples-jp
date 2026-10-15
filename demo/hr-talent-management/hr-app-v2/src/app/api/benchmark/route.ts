import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { query } from "@/lib/sf-client";
import { getSession } from "@/lib/session";

interface BenchResult {
  path: string;
  ms: number;
  rows: number;
  error?: string;
}

const QUERIES: Record<string, { sf: string; pg: string; label: string }> = {
  prediction_risk: {
    label: "離職予測リスク分布",
    sf: `SELECT RISK_LABEL, COUNT(*) AS CNT FROM HR_ANALYTICS.PUBLIC.PREDICTION_RESULTS GROUP BY RISK_LABEL`,
    pg: `SELECT risk_label, COUNT(*) AS cnt FROM hr_lake.prediction_results GROUP BY risk_label`,
  },
  prediction_top: {
    label: "離職リスクTOP 50",
    sf: `SELECT EMPLOYEE_ID, RISK_SCORE, RISK_LABEL FROM HR_ANALYTICS.PUBLIC.PREDICTION_RESULTS ORDER BY RISK_SCORE DESC LIMIT 50`,
    pg: `SELECT employee_id, risk_score, risk_label FROM hr_lake.prediction_results ORDER BY risk_score DESC LIMIT 50`,
  },
  relationship_all: {
    label: "関係性スコア全件",
    sf: `SELECT COUNT(*) AS CNT, AVG(RELATIONSHIP_SCORE) AS AVG_SCORE FROM HR_ANALYTICS.PUBLIC.RELATIONSHIP_RESULTS`,
    pg: `SELECT COUNT(*) AS cnt, AVG(relationship_score) AS avg_score FROM hr_lake.relationship_results`,
  },
  shap_agg: {
    label: "SHAP集計(特徴量平均)",
    sf: `SELECT FEATURE_NAME, AVG(ABS(SHAP_VALUE)) AS AVG_ABS_SHAP FROM HR_ANALYTICS.PUBLIC.SHAP_RESULTS WHERE MODEL_TYPE='attrition' GROUP BY FEATURE_NAME ORDER BY AVG_ABS_SHAP DESC LIMIT 15`,
    pg: `SELECT feature_name, AVG(ABS(shap_value)) AS avg_abs_shap FROM hr_lake.shap_results WHERE model_type='attrition' GROUP BY feature_name ORDER BY avg_abs_shap DESC LIMIT 15`,
  },
  evidence_count: {
    label: "エビデンス件数(タイプ別)",
    sf: `SELECT SCORE_TYPE, COUNT(*) AS CNT FROM HR_ANALYTICS.PUBLIC.EVIDENCE_STORE GROUP BY SCORE_TYPE`,
    pg: `SELECT score_type, COUNT(*) AS cnt FROM hr_lake.evidence_store GROUP BY score_type`,
  },
  evidence_single: {
    label: "エビデンス単一取得(employee_id=1)",
    sf: `SELECT * FROM HR_ANALYTICS.PUBLIC.EVIDENCE_STORE WHERE EMPLOYEE_ID = 1`,
    pg: `SELECT * FROM hr_lake.evidence_store WHERE employee_id = 1`,
  },
};

async function runSf(sql: string): Promise<BenchResult> {
  const t0 = performance.now();
  try {
    const rows = await query(sql);
    return { path: "snowflake-sdk", ms: Math.round(performance.now() - t0), rows: rows.length };
  } catch (e) {
    return { path: "snowflake-sdk", ms: Math.round(performance.now() - t0), rows: 0, error: (e as Error).message };
  }
}

async function runPg(sql: string): Promise<BenchResult> {
  const t0 = performance.now();
  try {
    const rows = await pgQuery(sql);
    return { path: "pg_lake", ms: Math.round(performance.now() - t0), rows: rows.length };
  } catch (e) {
    return { path: "pg_lake", ms: Math.round(performance.now() - t0), rows: 0, error: (e as Error).message };
  }
}

export async function GET(request: Request) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }
  try {
    const { searchParams } = new URL(request.url);
    const queryKey = searchParams.get("query");
    const iterations = Math.min(Number(searchParams.get("iterations") || "3"), 10);

    if (queryKey && !QUERIES[queryKey]) {
      return NextResponse.json({ error: `Unknown query: ${queryKey}. Available: ${Object.keys(QUERIES).join(", ")}` }, { status: 400 });
    }

    const targets = queryKey ? { [queryKey]: QUERIES[queryKey] } : QUERIES;

    const results: Record<string, { label: string; iterations: { sf: BenchResult; pg: BenchResult }[]; avg_sf_ms: number; avg_pg_ms: number; speedup: string }> = {};

    for (const [key, q] of Object.entries(targets)) {
      const iters: { sf: BenchResult; pg: BenchResult }[] = [];

      for (let i = 0; i < iterations; i++) {
        const [sf, pg] = await Promise.all([runSf(q.sf), runPg(q.pg)]);
        iters.push({ sf, pg });
      }

      const avgSf = Math.round(iters.reduce((s, r) => s + r.sf.ms, 0) / iterations);
      const avgPg = Math.round(iters.reduce((s, r) => s + r.pg.ms, 0) / iterations);
      const ratio = avgSf > 0 ? (avgPg / avgSf).toFixed(2) : "N/A";

      results[key] = {
        label: q.label,
        iterations: iters,
        avg_sf_ms: avgSf,
        avg_pg_ms: avgPg,
        speedup: avgPg < avgSf ? `pg_lake ${(avgSf / avgPg).toFixed(1)}x faster` : `snowflake-sdk ${(avgPg / avgSf).toFixed(1)}x faster`,
      };
    }

    return NextResponse.json({
      benchmark: results,
      config: { iterations, queries: Object.keys(targets) },
    });
  } catch (error) {
    console.error("Benchmark error:", error);
    return NextResponse.json({ error: "Benchmark failed" }, { status: 500 });
  }
}
