import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { query } from "@/lib/sf-client";
import { getDataPath } from "@/lib/data-path";
import { isEmployeeInScope } from "@/lib/scope";
import { getSession } from "@/lib/session";
import type { Binds } from "snowflake-sdk";

async function viaSf(empId: number) {
  const prediction = await query<{
    RISK_SCORE: number; RISK_LABEL: string; MODEL_VERSION: string; RUN_DATE: string;
  }>(`
    SELECT RISK_SCORE, RISK_LABEL, MODEL_VERSION, RUN_DATE
    FROM HR_ANALYTICS.PUBLIC.PREDICTION_RESULTS WHERE EMPLOYEE_ID = ?
  `, [empId] as Binds);

  const shapValues = await query<{
    FEATURE_NAME: string; SHAP_VALUE: number; FEATURE_VALUE: number;
  }>(`
    SELECT s.FEATURE_NAME, s.SHAP_VALUE, s.FEATURE_VALUE
    FROM HR_ANALYTICS.PUBLIC.SHAP_RESULTS s
    JOIN HR_ANALYTICS.PUBLIC.PREDICTION_RESULTS pr ON s.PREDICTION_ID = pr.ID
    WHERE pr.EMPLOYEE_ID = ? AND s.MODEL_TYPE = 'attrition'
    ORDER BY ABS(s.SHAP_VALUE) DESC LIMIT 10
  `, [empId] as Binds);

  const evidence = await query<{ EVIDENCE_JSON: string }>(`
    SELECT EVIDENCE_JSON::STRING AS EVIDENCE_JSON
    FROM HR_ANALYTICS.PUBLIC.EVIDENCE_STORE
    WHERE EMPLOYEE_ID = ? AND SCORE_TYPE = 'attrition'
    ORDER BY GENERATED_AT DESC LIMIT 1
  `, [empId] as Binds);

  let featureSummary: { FEATURE_NAME: string; FEATURE_VALUE: number }[] = [];
  if (shapValues.length === 0) {
    featureSummary = await query<{ FEATURE_NAME: string; FEATURE_VALUE: number }>(`
      SELECT f.key AS FEATURE_NAME, f.value::FLOAT AS FEATURE_VALUE
      FROM HR_ANALYTICS.PUBLIC.ATTRITION_FEATURES,
        LATERAL FLATTEN(input => OBJECT_CONSTRUCT(
          'TENURE_MONTHS', TENURE_MONTHS, 'AVG_EVAL_SCORE', AVG_EVAL_SCORE,
          'EVAL_TREND', EVAL_TREND, 'SENTIMENT_AVG', SENTIMENT_AVG,
          'SENTIMENT_TREND', SENTIMENT_TREND, 'MONTHS_SINCE_PROMOTION', MONTHS_SINCE_PROMOTION,
          'CAREER_CHANGE_COUNT', CAREER_CHANGE_COUNT, 'RISK_SIGNAL_COUNT', RISK_SIGNAL_COUNT,
          'SELF_EVAL_GAP', SELF_EVAL_GAP, 'PEER_COLLAB_SCORE', PEER_COLLAB_SCORE
        )) f
      WHERE EMPLOYEE_ID = ?
    `, [empId] as Binds);
  }

  return { prediction: prediction[0] || null, shapValues, evidence, featureSummary };
}

async function viaPgLake(empId: number) {
  const prediction = await pgQuery<{
    RISK_SCORE: number; RISK_LABEL: string; MODEL_VERSION: string; RUN_DATE: string;
  }>(`
    SELECT risk_score AS "RISK_SCORE", risk_label AS "RISK_LABEL",
      model_version AS "MODEL_VERSION", run_date AS "RUN_DATE"
    FROM hr_lake.prediction_results WHERE employee_id = $1
  `, [empId]);

  const shapValues = await pgQuery<{
    FEATURE_NAME: string; SHAP_VALUE: number; FEATURE_VALUE: number;
  }>(`
    SELECT s.feature_name AS "FEATURE_NAME", s.shap_value AS "SHAP_VALUE",
      s.feature_value AS "FEATURE_VALUE"
    FROM hr_lake.shap_results s
    JOIN hr_lake.prediction_results pr ON s.prediction_id = pr.id
    WHERE pr.employee_id = $1 AND s.model_type = 'attrition'
    ORDER BY ABS(s.shap_value) DESC LIMIT 10
  `, [empId]);

  const evidence = await pgQuery<{ EVIDENCE_JSON: string }>(`
    SELECT evidence_json AS "EVIDENCE_JSON"
    FROM hr_lake.evidence_store
    WHERE employee_id = $1 AND score_type = 'attrition'
    ORDER BY generated_at DESC LIMIT 1
  `, [empId]);

  return { prediction: prediction[0] || null, shapValues, evidence, featureSummary: [] as { FEATURE_NAME: string; FEATURE_VALUE: number }[] };
}

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }
  try {
    const { id } = await params;
    const empId = Number(id);
    if (!(await isEmployeeInScope(session, empId))) {
      return NextResponse.json({ error: "アクセス権限がありません" }, { status: 403 });
    }
    const dataPath = await getDataPath();
    const t0 = performance.now();

    const { prediction, shapValues, evidence, featureSummary } = dataPath === "pg_lake"
      ? await viaPgLake(empId)
      : await viaSf(empId);

    const ms = Math.round(performance.now() - t0);

    return NextResponse.json({
      prediction,
      shapValues,
      evidence: evidence[0]?.EVIDENCE_JSON ? JSON.parse(evidence[0].EVIDENCE_JSON) : null,
      featureSummary,
      _meta: { dataPath, ms },
    });
  } catch (error) {
    console.error("Attrition detail error:", error);
    return NextResponse.json({ error: "Failed to fetch attrition detail" }, { status: 500 });
  }
}
