import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { query } from "@/lib/sf-client";
import { getDataPath } from "@/lib/data-path";
import { getSession } from "@/lib/session";
import type { Binds } from "snowflake-sdk";

interface CommentRequest {
  targetEmployeeId: number | null;
  candidateEmployeeId: number;
  vacantDeptId: number;
  vacantGrade: string;
}

export async function POST(request: Request) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }
  try {
    const body: CommentRequest = await request.json();
    const { targetEmployeeId, candidateEmployeeId, vacantDeptId, vacantGrade } = body;

    if (!candidateEmployeeId || !vacantDeptId) {
      return NextResponse.json({ error: "Missing required fields" }, { status: 400 });
    }

    const pgQueries = [
      pgQuery<{ NAME: string; GRADE: string; DEPT_NAME: string; POSITION_TITLE: string; TENURE: number; AVG_EVAL: number }>(`
        SELECT e.last_name || e.first_name AS "NAME", p.grade AS "GRADE", d.dept_name AS "DEPT_NAME",
          p.title AS "POSITION_TITLE",
          EXTRACT(YEAR FROM AGE(CURRENT_DATE, e.hire_date))::int AS "TENURE",
          COALESCE((SELECT ROUND(AVG(ev.score)::numeric,1)::float FROM hr.evaluations ev WHERE ev.employee_id = e.employee_id), 0) AS "AVG_EVAL"
        FROM hr.employees e
        JOIN hr.positions p ON e.position_id = p.position_id
        JOIN hr.departments d ON e.dept_id = d.dept_id
        WHERE e.employee_id = $1
      `, [candidateEmployeeId]),

      pgQuery<{ SKILL_NAME: string; PROFICIENCY: number }>(`
        SELECT s.skill_name AS "SKILL_NAME", es.proficiency AS "PROFICIENCY"
        FROM hr.employee_skills es
        JOIN hr.skills s ON es.skill_id = s.skill_id
        WHERE es.employee_id = $1
        ORDER BY es.proficiency DESC LIMIT 5
      `, [candidateEmployeeId]),

      pgQuery<{ DEPT_NAME: string }>(`
        SELECT dept_name AS "DEPT_NAME" FROM hr.departments WHERE dept_id = $1
      `, [vacantDeptId]),
    ];

    const dataPath = await getDataPath();

    const riskPromise = dataPath === "pg_lake"
      ? pgQuery<{ RISK_LABEL: string; RISK_SCORE: number }>(`
          SELECT risk_label AS "RISK_LABEL", risk_score AS "RISK_SCORE"
          FROM hr_lake.prediction_results
          WHERE employee_id = $1
        `, [candidateEmployeeId])
      : query<{ RISK_LABEL: string; RISK_SCORE: number }>(`
          SELECT pr.RISK_LABEL, pr.RISK_SCORE
          FROM HR_ANALYTICS.PUBLIC.PREDICTION_RESULTS pr
          WHERE pr.EMPLOYEE_ID = ? AND pr.MODEL_VERSION = (
            SELECT MAX(MODEL_VERSION) FROM HR_ANALYTICS.PUBLIC.PREDICTION_RESULTS WHERE EMPLOYEE_ID = ?
          )
        `, [candidateEmployeeId, candidateEmployeeId] as Binds);

    type TargetInfo = { NAME: string; GRADE: string; DEPT_NAME: string; POSITION_TITLE: string; TENURE: number; AVG_EVAL: number };
    type SkillInfo = { SKILL_NAME: string; PROFICIENCY: number };

    let targetInfoPromise: Promise<TargetInfo[]> | null = null;
    let targetSkillsPromise: Promise<SkillInfo[]> | null = null;

    if (targetEmployeeId) {
      targetInfoPromise = pgQuery<TargetInfo>(`
        SELECT e.last_name || e.first_name AS "NAME", p.grade AS "GRADE", d.dept_name AS "DEPT_NAME",
          p.title AS "POSITION_TITLE",
          EXTRACT(YEAR FROM AGE(CURRENT_DATE, e.hire_date))::int AS "TENURE",
          COALESCE((SELECT ROUND(AVG(ev.score)::numeric,1)::float FROM hr.evaluations ev WHERE ev.employee_id = e.employee_id), 0) AS "AVG_EVAL"
        FROM hr.employees e
        JOIN hr.positions p ON e.position_id = p.position_id
        JOIN hr.departments d ON e.dept_id = d.dept_id
        WHERE e.employee_id = $1
      `, [targetEmployeeId]);
      targetSkillsPromise = pgQuery<SkillInfo>(`
        SELECT s.skill_name AS "SKILL_NAME", es.proficiency AS "PROFICIENCY"
        FROM hr.employee_skills es
        JOIN hr.skills s ON es.skill_id = s.skill_id
        WHERE es.employee_id = $1
        ORDER BY es.proficiency DESC LIMIT 5
      `, [targetEmployeeId]);
    }

    const [pgResults, riskInfo, targetInfoRes, targetSkillsRes] = await Promise.all([
      Promise.all(pgQueries),
      riskPromise,
      targetInfoPromise || Promise.resolve(null),
      targetSkillsPromise || Promise.resolve(null),
    ]);

    const candidateInfo = pgResults[0][0] as Record<string, unknown>;
    const candidateSkills = pgResults[1] as SkillInfo[];
    const vacantDeptName = (pgResults[2][0] as Record<string, unknown>)?.DEPT_NAME || "不明";
    const risk = riskInfo[0];

    let targetSection = "";
    if (targetEmployeeId && targetInfoRes && targetSkillsRes) {
      const targetInfo = targetInfoRes[0];
      const targetSkills = targetSkillsRes;
      if (targetInfo) {
        targetSection = `
【前任者情報】
氏名: ${targetInfo.NAME}（${targetInfo.GRADE}）
部署: ${targetInfo.DEPT_NAME} / ${targetInfo.POSITION_TITLE}
勤続: ${targetInfo.TENURE}年
平均評価: ${targetInfo.AVG_EVAL}/5.0
スキル: ${targetSkills.map(s => `${s.SKILL_NAME}(L${s.PROFICIENCY})`).join(', ')}`;
      }
    }

    const prompt = `あなたは大手企業の人事コンサルタントです。以下の玉突き人事シミュレーションにおける候補者の適性を評価してください。

【空席ポジション】
部署: ${vacantDeptName}
等級: ${vacantGrade}
${targetSection}

【候補者情報】
氏名: ${candidateInfo?.NAME}（${candidateInfo?.GRADE}）
部署: ${candidateInfo?.DEPT_NAME} / ${candidateInfo?.POSITION_TITLE}
勤続: ${candidateInfo?.TENURE}年
平均評価: ${candidateInfo?.AVG_EVAL}/5.0
スキル: ${candidateSkills.map(s => `${s.SKILL_NAME}(L${s.PROFICIENCY})`).join(', ')}
離職リスク: ${risk ? `${risk.RISK_LABEL}（${(Number(risk.RISK_SCORE) * 100).toFixed(0)}%）` : '不明'}

以下の観点で日本語で簡潔に評価してください（合計5〜6文）:
1. 候補者の強み（スキル・経験の観点）
2. 前任者との比較（前任者情報がある場合）
3. リスクや懸念点
4. 総合評価（推薦度: ◎/○/△）`;

    const aiResult = await query<{ COMMENT: string }>(`
      SELECT SNOWFLAKE.CORTEX.COMPLETE('claude-haiku-4-5', ?) AS COMMENT
    `, [prompt]);

    const comment = aiResult[0]?.COMMENT || "AI分析結果を取得できませんでした。";
    return NextResponse.json({ comment });
  } catch (error) {
    console.error("AI comment error:", error);
    return NextResponse.json({ error: "Failed to generate AI comment" }, { status: 500 });
  }
}
