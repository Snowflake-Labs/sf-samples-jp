import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession } from "@/lib/session";

const GRADE_LABELS: Record<string, string> = {
  E1: "役員", D1: "本部長", D2: "部長", M1: "次長", M2: "課長",
  S1: "課長補佐", S2: "主査", J1: "主任", J2: "主事", J3: "新卒",
};

function buildReason(row: Record<string, unknown>): string {
  const parts: string[] = [];
  const sm = Number(row.SKILL_MATCH) || 0;
  const eval_ = Number(row.AVG_EVAL) || 0;
  const tenure = Number(row.TENURE) || 0;
  const smPct = Math.round((Math.min(sm, 5) / 5) * 100);

  if (smPct >= 80) parts.push(`対象部署で求められるスキル${sm}/5件を保有（適合率${smPct}%）`);
  else if (smPct >= 40) parts.push(`スキル適合${sm}/5件（${smPct}%）`);

  if (eval_ >= 4.0) parts.push(`高評価（平均${eval_.toFixed(1)}）`);
  else if (eval_ >= 3.5) parts.push(`評価${eval_.toFixed(1)}`);

  if (tenure >= 10) parts.push(`勤続${tenure}年のベテラン`);
  else if (tenure >= 5) parts.push(`勤続${tenure}年`);

  if (parts.length === 0) parts.push(`総合スコアに基づく推薦`);
  return parts.join("。");
}

export async function GET(request: Request) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }
  try {
    const { searchParams } = new URL(request.url);
    const deptId = searchParams.get("dept_id");
    const grade = searchParams.get("grade");
    const honbu = searchParams.get("honbu") || "";
    const limit = Math.min(Number(searchParams.get("limit") || "20"), 30);
    const minScore = Number(searchParams.get("min_score") || "0");
    const minTenure = Number(searchParams.get("min_tenure") || "0");
    const minEval = Number(searchParams.get("min_eval") || "0");
    const gradeFilter = searchParams.get("grade_filter") || "";
    const entryType = searchParams.get("entry_type") || "";
    const deptFilter = searchParams.get("dept_filter") || "";
    const managerId = searchParams.get("manager_id") || "";

    if (!deptId || !grade) {
      return NextResponse.json({ error: "dept_id and grade are required" }, { status: 400 });
    }
    const dId = Number(deptId);
    if (isNaN(dId)) {
      return NextResponse.json({ error: "Invalid dept_id" }, { status: 400 });
    }

    const oneBelow = (() => {
      const grades = ["E1", "D1", "D2", "M1", "M2", "S1", "S2", "J1", "J2", "J3"];
      const idx = grades.indexOf(grade);
      if (idx < 0 || idx >= grades.length - 1) return grade;
      return grades[idx + 1];
    })();

    const params: unknown[] = [dId, grade, oneBelow];
    let idx = 4;

    let honbuFilter = "";
    if (honbu) {
      const hId = Number(honbu);
      if (isNaN(hId)) {
        return NextResponse.json({ error: "Invalid honbu" }, { status: 400 });
      }
      honbuFilter = `AND e.dept_id IN (SELECT dept_id FROM hr.departments WHERE dept_id = $${idx} OR parent_dept_id = $${idx + 1})`;
      params.push(hId, hId);
      idx += 2;
    }

    // Grade filter overrides default grade matching
    let gradeClause = `AND p.grade IN ($2, $3)`;
    if (gradeFilter) {
      const validGrades = gradeFilter.split(",").filter((g) => GRADE_LABELS[g]);
      if (validGrades.length > 0) {
        const placeholders = validGrades.map((g) => { params.push(g); return `$${idx++}`; }).join(",");
        gradeClause = `AND p.grade IN (${placeholders})`;
      }
    }

    let entryTypeFilter = "";
    if (entryType === "new_grad" || entryType === "mid_career") {
      entryTypeFilter = `AND e.entry_type = $${idx}`;
      params.push(entryType);
      idx++;
    }

    let deptFilterClause = "";
    if (deptFilter) {
      const dfId = Number(deptFilter);
      if (!isNaN(dfId)) {
        deptFilterClause = `AND e.dept_id IN (SELECT dept_id FROM hr.departments WHERE dept_id = $${idx} OR parent_dept_id = $${idx + 1})`;
        params.push(dfId, dfId);
        idx += 2;
      }
    }

    let managerFilterClause = "";
    if (managerId) {
      const mId = Number(managerId);
      if (!isNaN(mId)) {
        managerFilterClause = `AND e.manager_id = $${idx}`;
        params.push(mId);
        idx++;
      }
    }

    params.push(dId);
    const excludeIdx = idx++;
    params.push(minScore);
    const minScoreIdx = idx++;
    params.push(minTenure);
    const minTenureIdx = idx++;
    params.push(minEval);
    const minEvalIdx = idx++;
    params.push(limit);
    const limitIdx = idx++;

    const results = await pgQuery(`
      WITH dept_top_skills AS (
        SELECT s.skill_name
        FROM hr.employee_skills es
        JOIN hr.employees e ON es.employee_id = e.employee_id
        JOIN hr.skills s ON es.skill_id = s.skill_id
        WHERE e.dept_id = $1 AND e.status = 'active' AND es.proficiency >= 3
        GROUP BY s.skill_name
        ORDER BY AVG(es.proficiency) DESC
        LIMIT 5
      ),
      candidates AS (
        SELECT e.employee_id AS "EMPLOYEE_ID",
          e.last_name || e.first_name AS "NAME",
          e.dept_id AS "DEPT_ID", d.dept_name AS "DEPT_NAME",
          p.grade AS "GRADE", p.title AS "POSITION_TITLE",
          COALESCE(ev.avg_score, 3.0) AS "AVG_EVAL",
          EXTRACT(YEAR FROM AGE(CURRENT_DATE, e.hire_date))::int AS "TENURE",
          COALESCE(sm.skill_match, 0) AS "SKILL_MATCH",
          e.entry_type AS "ENTRY_TYPE",
          e.salary AS "SALARY",
          e.position_id AS "POSITION_ID",
          e.manager_id AS "MANAGER_ID",
          mgr.last_name || mgr.first_name AS "MANAGER_NAME"
        FROM hr.employees e
        JOIN hr.departments d ON e.dept_id = d.dept_id
        JOIN hr.positions p ON e.position_id = p.position_id
        LEFT JOIN hr.employees mgr ON e.manager_id = mgr.employee_id
        LEFT JOIN (
          SELECT employee_id, ROUND(AVG(score)::numeric, 2)::float AS avg_score
          FROM hr.evaluations GROUP BY employee_id
        ) ev ON ev.employee_id = e.employee_id
        LEFT JOIN (
          SELECT es2.employee_id, COUNT(DISTINCT dts.skill_name)::int AS skill_match
          FROM hr.employee_skills es2
          JOIN hr.skills s2 ON es2.skill_id = s2.skill_id
          JOIN dept_top_skills dts ON dts.skill_name = s2.skill_name
          WHERE es2.proficiency >= 2
          GROUP BY es2.employee_id
        ) sm ON sm.employee_id = e.employee_id
        WHERE e.status = 'active'
          ${gradeClause}
          ${honbuFilter}
          ${entryTypeFilter}
          ${deptFilterClause}
          ${managerFilterClause}
          AND e.dept_id != $${excludeIdx}
      ),
      scored AS (
        SELECT *,
          ROUND(
            (LEAST("SKILL_MATCH", 5)::float / 5.0) * 50 +
            (LEAST("AVG_EVAL", 5)::float / 5.0) * 30 +
            LEAST("TENURE"::float / 10.0, 1) * 20
          )::int AS "COMPOSITE_SCORE",
          ROUND((LEAST("SKILL_MATCH", 5)::float / 5.0) * 100)::int AS "SKILL_PCT",
          ROUND((LEAST("AVG_EVAL", 5)::float / 5.0) * 100)::int AS "EVAL_PCT",
          ROUND(LEAST("TENURE"::float / 10.0, 1) * 100)::int AS "TENURE_PCT"
        FROM candidates
      )
      SELECT * FROM scored
      WHERE "COMPOSITE_SCORE" >= $${minScoreIdx}
        AND "TENURE" >= $${minTenureIdx}
        AND "AVG_EVAL" >= $${minEvalIdx}
      ORDER BY "COMPOSITE_SCORE" DESC
      LIMIT $${limitIdx}
    `, params);

    const enriched = results.map((r) => ({
      ...r,
      REASON: buildReason(r),
    }));

    return NextResponse.json(enriched);
  } catch (error) {
    console.error("Candidates error:", error);
    return NextResponse.json({ error: "Failed to fetch candidates" }, { status: 500 });
  }
}
