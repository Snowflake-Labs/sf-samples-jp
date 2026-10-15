import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { query } from "@/lib/sf-client";
import { getDataPath } from "@/lib/data-path";
import { getSession } from "@/lib/session";
import type { Binds } from "snowflake-sdk";

async function fetchContext(employeeId: number, dataPath: string) {
  if (dataPath === "pg_lake") {
    const [empInfo, shapData, prediction] = await Promise.all([
      pgQuery<{
        NAME: string; DEPT_NAME: string; GRADE: string; TENURE_YEARS: number;
      }>(`
        SELECT e.last_name || e.first_name AS "NAME",
          d.dept_name AS "DEPT_NAME", p.grade AS "GRADE",
          ROUND(EXTRACT(EPOCH FROM AGE(CURRENT_DATE, e.hire_date)) / (365.25 * 86400), 1)::float AS "TENURE_YEARS"
        FROM hr.employees e
        JOIN hr.departments d ON e.dept_id = d.dept_id
        JOIN hr.positions p ON e.position_id = p.position_id
        WHERE e.employee_id = $1
      `, [employeeId]),

      pgQuery<{ FEATURE_NAME: string; SHAP_VALUE: number; FEATURE_VALUE: number }>(`
        SELECT s.feature_name AS "FEATURE_NAME", s.shap_value AS "SHAP_VALUE",
          s.feature_value AS "FEATURE_VALUE"
        FROM hr_lake.shap_results s
        JOIN hr_lake.prediction_results pr ON s.prediction_id = pr.id
        WHERE pr.employee_id = $1 AND s.model_type = 'attrition'
        ORDER BY s.shap_value DESC LIMIT 5
      `, [employeeId]),

      pgQuery<{ RISK_SCORE: number; RISK_LABEL: string }>(`
        SELECT risk_score AS "RISK_SCORE", risk_label AS "RISK_LABEL"
        FROM hr_lake.prediction_results WHERE employee_id = $1
      `, [employeeId]),
    ]);
    return { emp: empInfo[0], shapData, risk: prediction[0] };
  }

  const [empInfo, shapData, prediction] = await Promise.all([
    pgQuery<{
      NAME: string; DEPT_NAME: string; GRADE: string; TENURE_YEARS: number;
    }>(`
      SELECT e.last_name || e.first_name AS "NAME",
        d.dept_name AS "DEPT_NAME", p.grade AS "GRADE",
        ROUND(EXTRACT(EPOCH FROM AGE(CURRENT_DATE, e.hire_date)) / (365.25 * 86400), 1)::float AS "TENURE_YEARS"
      FROM hr.employees e
      JOIN hr.departments d ON e.dept_id = d.dept_id
      JOIN hr.positions p ON e.position_id = p.position_id
      WHERE e.employee_id = $1
    `, [employeeId]),

    query<{ FEATURE_NAME: string; SHAP_VALUE: number; FEATURE_VALUE: number }>(`
      SELECT s.FEATURE_NAME, s.SHAP_VALUE, s.FEATURE_VALUE
      FROM HR_ANALYTICS.PUBLIC.SHAP_RESULTS s
      JOIN HR_ANALYTICS.PUBLIC.PREDICTION_RESULTS pr ON s.PREDICTION_ID = pr.ID
      WHERE pr.EMPLOYEE_ID = ? AND s.MODEL_TYPE = 'attrition'
      ORDER BY s.SHAP_VALUE DESC LIMIT 5
    `, [employeeId] as Binds),

    query<{ RISK_SCORE: number; RISK_LABEL: string }>(`
      SELECT RISK_SCORE, RISK_LABEL FROM HR_ANALYTICS.PUBLIC.PREDICTION_RESULTS WHERE EMPLOYEE_ID = ?
    `, [employeeId] as Binds),
  ]);
  return { emp: empInfo[0], shapData, risk: prediction[0] };
}

export async function POST(request: Request) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }
  try {
    const { employeeId } = await request.json();
    if (!employeeId) {
      return NextResponse.json({ error: "employeeId required" }, { status: 400 });
    }

    const dataPath = await getDataPath();
    const { emp, shapData, risk } = await fetchContext(Number(employeeId), dataPath);

    const shapFactors = shapData.map((s) => `${s.FEATURE_NAME}(SHAP=${Number(s.SHAP_VALUE).toFixed(3)}, 値=${Number(s.FEATURE_VALUE).toFixed(2)})`).join(", ");

    const prompt = `あなたは人事コンサルタントです。以下の社員の離職リスク分析結果に基づき、具体的なリテンション施策を3〜5つ提案してください。

社員情報:
- 氏名: ${emp?.NAME || "不明"}
- 部署: ${emp?.DEPT_NAME || "不明"}
- 等級: ${emp?.GRADE || "不明"}
- 勤続: ${emp?.TENURE_YEARS || "不明"}年
- 離職リスクスコア: ${risk ? (Number(risk.RISK_SCORE) * 100).toFixed(1) + "%" : "不明"}
- リスクレベル: ${risk?.RISK_LABEL || "不明"}

主要リスク要因（SHAP値上位）:
${shapFactors || "データなし"}

各施策について以下の形式で回答してください:
1. **施策名**: 具体的な施策の説明（1〜2文）
   - 期待効果: どのリスク要因に対処するか
   - 実施時期: 即時/1ヶ月以内/3ヶ月以内
   - 担当: 直属上司/人事部/経営層`;

    const aiResult = await query<{ RESPONSE: string }>(`
      SELECT SNOWFLAKE.CORTEX.COMPLETE('claude-haiku-4-5', ?) AS RESPONSE
    `, [prompt]);

    return NextResponse.json({
      suggestion: aiResult[0]?.RESPONSE || "施策を生成できませんでした。",
      employee: emp || null,
      riskScore: risk?.RISK_SCORE || null,
      riskLabel: risk?.RISK_LABEL || null,
      _meta: { dataPath },
    });
  } catch (error) {
    console.error("Retention suggestion error:", error);
    return NextResponse.json({ error: "Failed to generate retention suggestion" }, { status: 500 });
  }
}
