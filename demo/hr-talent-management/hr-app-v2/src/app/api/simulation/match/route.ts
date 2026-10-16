import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { query } from "@/lib/sf-client";
import { getSession } from "@/lib/session";

interface MatchResult {
  matchScore: number;
  skillScore: number;
  evalScore: number;
  tenureScore: number;
  matchedSkills: string[];
  missingSkills: string[];
  empSkills: { name: string; proficiency: number }[];
  requiredSkills: string[];
  avgEvalScore: number;
  tenureYears: number;
  reason: string;
}

export async function GET(request: Request) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }
  try {
    const { searchParams } = new URL(request.url);
    const employeeId = searchParams.get("employee_id");
    const toDeptId = searchParams.get("to_dept_id");

    if (!employeeId || !toDeptId) {
      return NextResponse.json({ error: "employee_id and to_dept_id are required" }, { status: 400 });
    }

    const empId = Number(employeeId);
    const deptId = Number(toDeptId);
    if (isNaN(empId) || isNaN(deptId)) {
      return NextResponse.json({ error: "Invalid parameters" }, { status: 400 });
    }

    const [empSkills, deptTopSkills, empEval, empTenure, toDeptInfo] = await Promise.all([
      pgQuery<{ SKILL_NAME: string; PROFICIENCY: number; CATEGORY: string }>(`
        SELECT s.skill_name AS "SKILL_NAME", es.proficiency AS "PROFICIENCY", s.category AS "CATEGORY"
        FROM hr.employee_skills es
        JOIN hr.skills s ON es.skill_id = s.skill_id
        WHERE es.employee_id = $1
        ORDER BY es.proficiency DESC
      `, [empId]),

      pgQuery<{ SKILL_NAME: string; AVG_PROF: number }>(`
        SELECT s.skill_name AS "SKILL_NAME", ROUND(AVG(es.proficiency)::numeric, 1)::float AS "AVG_PROF"
        FROM hr.employee_skills es
        JOIN hr.employees e ON es.employee_id = e.employee_id
        JOIN hr.skills s ON es.skill_id = s.skill_id
        WHERE e.dept_id = $1 AND e.status = 'active' AND es.proficiency >= 3
        GROUP BY s.skill_name
        ORDER BY "AVG_PROF" DESC LIMIT 8
      `, [deptId]),

      pgQuery<{ AVG_SCORE: number }>(`
        SELECT ROUND(AVG(score)::numeric, 2)::float AS "AVG_SCORE"
        FROM hr.evaluations WHERE employee_id = $1
      `, [empId]),

      pgQuery<{ TENURE: number; GRADE: string; DEPT_NAME: string; NAME: string }>(`
        SELECT EXTRACT(YEAR FROM AGE(CURRENT_DATE, e.hire_date))::int AS "TENURE",
          p.grade AS "GRADE", d.dept_name AS "DEPT_NAME",
          e.last_name || e.first_name AS "NAME"
        FROM hr.employees e
        JOIN hr.positions p ON e.position_id = p.position_id
        JOIN hr.departments d ON e.dept_id = d.dept_id
        WHERE e.employee_id = $1
      `, [empId]),

      pgQuery<{ DEPT_NAME: string }>(`
        SELECT dept_name AS "DEPT_NAME" FROM hr.departments WHERE dept_id = $1
      `, [deptId]),
    ]);

    const requiredSkills = deptTopSkills.map((s) => s.SKILL_NAME);
    const empSkillNames = new Set(empSkills.map((s) => s.SKILL_NAME));
    const matchedSkills = requiredSkills.filter((s) => empSkillNames.has(s));
    const missingSkills = requiredSkills.filter((s) => !empSkillNames.has(s));

    const skillScore = requiredSkills.length > 0
      ? Math.round((matchedSkills.length / requiredSkills.length) * 100)
      : 50;

    const avgEval = empEval[0]?.AVG_SCORE || 3.0;
    const evalScore = Math.min(100, Math.round((avgEval / 5.0) * 100));

    const tenure = empTenure[0]?.TENURE || 0;
    const tenureScore = tenure >= 3 ? Math.min(100, 60 + tenure * 3) : Math.max(20, tenure * 20);

    const matchScore = Math.round(skillScore * 0.5 + evalScore * 0.3 + tenureScore * 0.2);

    const empName = empTenure[0]?.NAME || "不明";
    const empGrade = empTenure[0]?.GRADE || "不明";
    const fromDept = empTenure[0]?.DEPT_NAME || "不明";
    const toDept = toDeptInfo[0]?.DEPT_NAME || "不明";

    const prompt = `あなたは人事コンサルタントです。以下の異動候補について、配置マッチ度の根拠を日本語で3〜4文で簡潔に述べてください。

社員: ${empName}（${empGrade}）
現在の部署: ${fromDept}
異動先: ${toDept}
保有スキル: ${empSkills.map(s => `${s.SKILL_NAME}(${s.PROFICIENCY})`).join(', ')}
異動先で求められるスキル: ${requiredSkills.join(', ')}
マッチしたスキル: ${matchedSkills.join(', ') || 'なし'}
不足スキル: ${missingSkills.join(', ') || 'なし'}
平均評価スコア: ${Number(avgEval).toFixed(1)}/5.0
勤続年数: ${tenure}年
総合マッチ度: ${matchScore}%

根拠を述べてください:`;

    const aiResult = await query<{ REASON: string }>(`
      SELECT SNOWFLAKE.CORTEX.COMPLETE('claude-haiku-4-5', ?) AS REASON
    `, [prompt]);

    const reason = aiResult[0]?.REASON || "AI分析結果を取得できませんでした。";

    const result: MatchResult = {
      matchScore, skillScore, evalScore, tenureScore,
      matchedSkills, missingSkills,
      empSkills: empSkills.map((s) => ({ name: s.SKILL_NAME, proficiency: s.PROFICIENCY })),
      requiredSkills, avgEvalScore: avgEval, tenureYears: tenure, reason,
    };

    return NextResponse.json(result);
  } catch (error) {
    console.error("Match error:", error);
    return NextResponse.json({ error: "Failed to compute match" }, { status: 500 });
  }
}
