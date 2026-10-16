import { NextResponse } from "next/server";
import { query } from "@/lib/sf-client";
import { getSession, requireRole } from "@/lib/session";

/**
 * ML re-inference trigger (B4).
 *
 * GET  -> report staleness: when features were last refreshed vs. when
 *         evaluations were last updated, so the UI can warn that risk
 *         scores are behind the latest evaluation round.
 * POST -> refresh the Feature Store dynamic tables and re-run SQL
 *         inference so PREDICTION_RESULTS reflects the new evaluations.
 *
 * Training is intentionally NOT re-run here — that stays a deliberate
 * offline step (scripts/ml_pipeline_v3.py). This only
 * refreshes features and re-scores with the currently registered model.
 *
 * The object names and the PREDICT signature below were verified against
 * the account (SHOW DYNAMIC TABLES / SHOW FUNCTIONS IN MODEL). Note that
 * the model lives in the ML schema and takes 14 features, and that the
 * risk score is output_feature_1 (probability of attrition) — not
 * output_feature_0, which is the complement.
 */

const ATTRITION_FV = 'HR_ANALYTICS.FEATURE_STORE."ATTRITION_FEATURES_FV$V20260315"';
const RELATIONSHIP_FV = 'HR_ANALYTICS.FEATURE_STORE."RELATIONSHIP_FEATURES_FV$V20260315"';
const FEATURE_VIEWS = [ATTRITION_FV, RELATIONSHIP_FV];

/** The 14 features ATTRITION_MODEL!PREDICT_PROBA expects, in order. */
const ATTRITION_FEATURES = [
  "TENURE_MONTHS", "AVG_EVAL_SCORE", "EVAL_TREND", "RISK_SIGNAL_COUNT",
  "CAREER_CHANGE_COUNT", "SENTIMENT_AVG", "SENTIMENT_TREND", "MONTHS_SINCE_PROMOTION",
  "TEAM_SIZE", "PREVIOUS_COMPANY_COUNT", "COMMUTE_TIME_MINUTES", "SELF_EVAL_GAP",
  "PEER_COLLAB_SCORE", "EVAL_CATEGORY_LATEST",
] as const;

export async function GET() {
  const session = await getSession();
  if (!session) return NextResponse.json({ error: "認証が必要です" }, { status: 401 });

  try {
    const [featureAge, evalAge, predAge] = await Promise.all([
      // Dynamic tables carry no COMPUTED_AT, so read the refresh history.
      query<{ LAST_REFRESH: string | null }>(`
        SELECT MAX(REFRESH_END_TIME) AS LAST_REFRESH
        FROM TABLE(HR_ANALYTICS.INFORMATION_SCHEMA.DYNAMIC_TABLE_REFRESH_HISTORY(
          NAME => '${ATTRITION_FV}'))
        WHERE STATE = 'SUCCEEDED'
      `).catch((err) => { console.error("[ml/refresh] feature age failed:", err.message); return []; }),
      query<{ LAST_UPDATED: string | null }>(`
        SELECT MAX(UPDATED_AT) AS LAST_UPDATED FROM HR_ANALYTICS.STAGING.EVALUATIONS
      `).catch((err) => { console.error("[ml/refresh] eval age failed:", err.message); return []; }),
      query<{ LAST_RUN: string | null }>(`
        SELECT MAX(RUN_DATE) AS LAST_RUN FROM HR_ANALYTICS.PUBLIC.PREDICTION_RESULTS
      `).catch((err) => { console.error("[ml/refresh] pred age failed:", err.message); return []; }),
    ]);

    const featuresComputedAt = featureAge[0]?.LAST_REFRESH ?? null;
    const evaluationsUpdatedAt = evalAge[0]?.LAST_UPDATED ?? null;
    const predictionsRunAt = predAge[0]?.LAST_RUN ?? null;

    const stale =
      !!evaluationsUpdatedAt &&
      !!featuresComputedAt &&
      new Date(evaluationsUpdatedAt).getTime() > new Date(featuresComputedAt).getTime();

    return NextResponse.json({
      stale,
      featuresComputedAt,
      evaluationsUpdatedAt,
      predictionsRunAt,
      message: stale
        ? "評価が更新されています。離職リスクスコアは最新の評価を反映していません。"
        : "リスクスコアは最新の評価を反映しています。",
    });
  } catch (error) {
    console.error("ML staleness check error:", error);
    return NextResponse.json({ error: "鮮度チェックに失敗しました" }, { status: 500 });
  }
}

export async function POST() {
  const session = await getSession();
  const auth = requireRole(session, ["HR_ADMIN"]);
  if (!auth.ok) return NextResponse.json(auth.body, { status: auth.status });
  const steps: { step: string; ok: boolean; detail?: string }[] = [];

  try {
    // 1. Refresh the Feature Store dynamic tables so features pick up new evaluations
    for (const fv of FEATURE_VIEWS) {
      try {
        await query(`ALTER DYNAMIC TABLE ${fv} REFRESH`);
        steps.push({ step: `refresh ${fv}`, ok: true });
      } catch (err) {
        const detail = (err as Error).message;
        console.error(`[ml/refresh] ${fv} refresh failed:`, detail);
        steps.push({ step: `refresh ${fv}`, ok: false, detail });
      }
    }

    // 2. Re-run SQL inference against the registered model.
    //    Reads the dynamic table we just refreshed, so the scores reflect
    //    the refresh rather than a stale copy of the features.
    const featureArgs = ATTRITION_FEATURES.map((c) => `f.${c}`).join(", ");
    try {
      await query(`
        INSERT INTO HR_ANALYTICS.PUBLIC.PREDICTION_RESULTS
          (EMPLOYEE_ID, RUN_DATE, RISK_SCORE, RISK_LABEL, MODEL_VERSION, DEPT_ID)
        WITH scored AS (
          SELECT f.EMPLOYEE_ID, f.DEPT_ID,
                 HR_ANALYTICS.ML.ATTRITION_MODEL!PREDICT_PROBA(${featureArgs}
                 ):output_feature_1::FLOAT AS RISK_SCORE
          FROM ${ATTRITION_FV} f
        )
        SELECT EMPLOYEE_ID, CURRENT_DATE(), RISK_SCORE,
               CASE WHEN RISK_SCORE >= 0.7 THEN 'high'
                    WHEN RISK_SCORE >= 0.4 THEN 'medium'
                    ELSE 'low' END,
               'sql-inference-refresh', DEPT_ID
        FROM scored
      `);
      steps.push({ step: "sql inference", ok: true });
    } catch (err) {
      const detail = (err as Error).message;
      console.error("[ml/refresh] sql inference failed:", detail);
      steps.push({ step: "sql inference", ok: false, detail });
    }

    const failed = steps.filter((s) => !s.ok);
    return NextResponse.json({
      success: failed.length === 0,
      steps,
      message:
        failed.length === 0
          ? "特徴量を更新し、リスクスコアを再計算しました。"
          : `${failed.length}件のステップが失敗しました。詳細はstepsを確認してください。`,
    }, { status: failed.length === 0 ? 200 : 207 });
  } catch (error) {
    console.error("ML refresh error:", error);
    return NextResponse.json({ error: "再推論に失敗しました", steps }, { status: 500 });
  }
}
