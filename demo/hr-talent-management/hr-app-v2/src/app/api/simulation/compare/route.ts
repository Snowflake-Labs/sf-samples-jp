import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { query } from "@/lib/sf-client";
import { getSession } from "@/lib/session";

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

    const [empInfo, empSkills] = await Promise.all([
      pgQuery<{ NAME: string; GRADE: string; DEPT_NAME: string; TENURE: number; AVG_EVAL: number }>(`
        SELECT e.last_name || e.first_name AS "NAME",
          p.grade AS "GRADE", d.dept_name AS "DEPT_NAME",
          EXTRACT(YEAR FROM AGE(CURRENT_DATE, e.hire_date))::int AS "TENURE",
          COALESCE(ev.avg_score, 0)::float AS "AVG_EVAL"
        FROM hr.employees e
        JOIN hr.positions p ON e.position_id = p.position_id
        JOIN hr.departments d ON e.dept_id = d.dept_id
        LEFT JOIN (
          SELECT employee_id, ROUND(AVG(score)::numeric, 2)::float AS avg_score
          FROM hr.evaluations GROUP BY employee_id
        ) ev ON ev.employee_id = e.employee_id
        WHERE e.employee_id = $1
      `, [empId]),

      pgQuery<{ SKILL_NAME: string; PROFICIENCY: number }>(`
        SELECT s.skill_name AS "SKILL_NAME", es.proficiency AS "PROFICIENCY"
        FROM hr.employee_skills es
        JOIN hr.skills s ON es.skill_id = s.skill_id
        WHERE es.employee_id = $1
        ORDER BY es.proficiency DESC
      `, [empId]),
    ]);

    if (!empInfo.length) {
      return NextResponse.json({ error: "Employee not found" }, { status: 404 });
    }
    const emp = empInfo[0];

    const peerRows = await pgQuery<{
      EMPLOYEE_ID: number; NAME: string; GRADE: string; POSITION_TITLE: string;
      TENURE: number; AVG_EVAL: number; SKILLS: string;
    }>(`
      SELECT e.employee_id AS "EMPLOYEE_ID",
        e.last_name || e.first_name AS "NAME",
        p.grade AS "GRADE", p.title AS "POSITION_TITLE",
        EXTRACT(YEAR FROM AGE(CURRENT_DATE, e.hire_date))::int AS "TENURE",
        COALESCE(ev.avg_score, 0)::float AS "AVG_EVAL",
        COALESCE(sk.skills, '') AS "SKILLS"
      FROM hr.employees e
      JOIN hr.positions p ON e.position_id = p.position_id
      LEFT JOIN (
        SELECT employee_id, ROUND(AVG(score)::numeric, 2)::float AS avg_score
        FROM hr.evaluations GROUP BY employee_id
      ) ev ON ev.employee_id = e.employee_id
      LEFT JOIN (
        SELECT es2.employee_id,
          STRING_AGG(s2.skill_name || '(' || es2.proficiency || ')', ', ' ORDER BY es2.proficiency DESC) AS skills
        FROM hr.employee_skills es2
        JOIN hr.skills s2 ON es2.skill_id = s2.skill_id
        GROUP BY es2.employee_id
      ) sk ON sk.employee_id = e.employee_id
      WHERE e.dept_id = $1 AND e.status = 'active' AND p.grade = $2
      ORDER BY ev.avg_score DESC NULLS LAST
    `, [deptId, emp.GRADE]);

    const peers = peerRows.map((p) => ({
      employeeId: p.EMPLOYEE_ID, name: p.NAME, grade: p.GRADE,
      positionTitle: p.POSITION_TITLE, tenure: p.TENURE,
      avgEval: p.AVG_EVAL, skills: p.SKILLS,
    }));

    const toDeptInfo = await pgQuery<{ DEPT_NAME: string }>(`
      SELECT dept_name AS "DEPT_NAME" FROM hr.departments WHERE dept_id = $1
    `, [deptId]);
    const toDeptName = toDeptInfo[0]?.DEPT_NAME || "不明";

    let aiComparison = "";
    const empSkillStr = empSkills.map((s) => `${s.SKILL_NAME}(${s.PROFICIENCY})`).join(", ");

    if (peers.length === 0) {
      const prompt = `あなたは人事コンサルタントです。以下の社員の異動先${toDeptName}への配置について、同ランク（${emp.GRADE}）の社員が現在いないことを踏まえ、この社員の適性を日本語200文字以内で分析してください。

社員: ${emp.NAME}（${emp.GRADE}）
現部署: ${emp.DEPT_NAME}
異動先: ${toDeptName}
保有スキル: ${empSkillStr}
平均評価: ${emp.AVG_EVAL}/5.0
勤続: ${emp.TENURE}年

分析:`;
      const aiResult = await query<{ RESULT: string }>(`
        SELECT SNOWFLAKE.CORTEX.COMPLETE('claude-haiku-4-5', ?) AS RESULT
      `, [prompt]);
      aiComparison = aiResult[0]?.RESULT || "";
    } else if (peers.length === 1) {
      const peer = peers[0];
      const prompt = `あなたは人事コンサルタントです。以下の異動候補者と異動先の同ランク社員を比較し、配置の妥当性を日本語300文字以内で分析してください。強み・弱み・補完関係にも言及してください。

【異動候補者】
氏名: ${emp.NAME}（${emp.GRADE}）
現部署: ${emp.DEPT_NAME}
保有スキル: ${empSkillStr}
平均評価: ${emp.AVG_EVAL}/5.0
勤続: ${emp.TENURE}年

【異動先 ${toDeptName} の同ランク社員】
氏名: ${peer.name}（${peer.grade}）
役職: ${peer.positionTitle}
保有スキル: ${peer.skills}
平均評価: ${peer.avgEval}/5.0
勤続: ${peer.tenure}年

比較分析:`;
      const aiResult = await query<{ RESULT: string }>(`
        SELECT SNOWFLAKE.CORTEX.COMPLETE('claude-haiku-4-5', ?) AS RESULT
      `, [prompt]);
      aiComparison = aiResult[0]?.RESULT || "";
    } else {
      const peerProfiles = peers.map((p) =>
        `${p.name}(${p.grade}) 役職:${p.positionTitle} 評価:${p.avgEval}/5.0 勤続:${p.tenure}年 スキル:${p.skills || "なし"}`
      ).join("\n");
      const prompt = `あなたは人事コンサルタントです。以下は${toDeptName}の${emp.GRADE}ランク社員のプロフィールです。
異動候補者「${emp.NAME}（${emp.GRADE}）保有スキル:${empSkillStr} 評価:${emp.AVG_EVAL}/5.0 勤続:${emp.TENURE}年」と比較し、
(1)既存メンバーの特徴の要約 (2)候補者の強み・弱み (3)チームへの補完効果 (4)配置の総合評価 を日本語400文字以内でまとめてください。

【異動先メンバー】
${peerProfiles}

分析:`;
      const aiResult = await query<{ RESULT: string }>(`
        SELECT SNOWFLAKE.CORTEX.COMPLETE('claude-haiku-4-5', ?) AS RESULT
      `, [prompt]);
      aiComparison = aiResult[0]?.RESULT || "";
    }

    return NextResponse.json({
      employee: {
        name: emp.NAME, grade: emp.GRADE, deptName: emp.DEPT_NAME,
        tenure: emp.TENURE, avgEval: emp.AVG_EVAL,
        skills: empSkills.map((s) => ({ name: s.SKILL_NAME, proficiency: s.PROFICIENCY })),
      },
      toDeptName, peers, peerCount: peers.length, aiComparison,
    });
  } catch (error) {
    console.error("Compare error:", error);
    return NextResponse.json({ error: "Failed to compare" }, { status: 500 });
  }
}
