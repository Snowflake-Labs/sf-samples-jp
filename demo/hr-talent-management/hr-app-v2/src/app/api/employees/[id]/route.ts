import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { query } from "@/lib/sf-client";
import { getDataPath } from "@/lib/data-path";
import { getSession, requireRole } from "@/lib/session";
import type { Binds } from "snowflake-sdk";

async function mlViaSf(idNum: number) {
  const safe = <T>(p: Promise<T>, fallback: T, label: string): Promise<T> => p.catch((err) => { console.error(`[mlViaSf] ${label} failed:`, (err as Error).message); return fallback; });
  const [attritionPrediction, relationship, transferFit, shapFactors, relationshipShap, attritionEvidence, relationshipEvidence, similarCases] = await Promise.all([
    safe(query(`SELECT RISK_SCORE, RISK_LABEL, MODEL_VERSION FROM HR_ANALYTICS.PUBLIC.PREDICTION_RESULTS WHERE EMPLOYEE_ID = ?`, [idNum] as Binds), [], "attrition"),
    safe(query(`SELECT rr.RELATIONSHIP_SCORE, rr.COMPOSITE_LABEL, m.LAST_NAME || m.FIRST_NAME AS MANAGER_NAME
      FROM HR_ANALYTICS.PUBLIC.RELATIONSHIP_RESULTS rr
      JOIN HR_ANALYTICS.STAGING.EMPLOYEES m ON rr.MANAGER_ID = m.EMPLOYEE_ID
      WHERE rr.EMPLOYEE_ID = ?`, [idNum] as Binds), [], "relationship"),
    safe(query(`SELECT tf.FIT_SCORE, tf.TARGET_POSITION_ID,
      p.TITLE AS TARGET_POSITION_TITLE, d.DEPT_NAME AS TARGET_DEPT_NAME
      FROM HR_ANALYTICS.PUBLIC.TRANSFER_FIT_RESULTS tf
      JOIN HR_ANALYTICS.STAGING.POSITIONS p ON tf.TARGET_POSITION_ID = p.POSITION_ID
      JOIN HR_ANALYTICS.STAGING.DEPARTMENTS d ON p.DEPT_ID = d.DEPT_ID
      WHERE tf.EMPLOYEE_ID = ? ORDER BY tf.FIT_SCORE DESC LIMIT 5`, [idNum] as Binds), [], "transferFit"),
    safe(query(`SELECT s.FEATURE_NAME, s.SHAP_VALUE, s.FEATURE_VALUE
      FROM HR_ANALYTICS.PUBLIC.SHAP_RESULTS s
      JOIN HR_ANALYTICS.PUBLIC.PREDICTION_RESULTS pr ON s.PREDICTION_ID = pr.ID
      WHERE pr.EMPLOYEE_ID = ? AND s.MODEL_TYPE = 'attrition'
      ORDER BY ABS(s.SHAP_VALUE) DESC LIMIT 10`, [idNum] as Binds), [], "shapAttrition"),
    safe(query(`SELECT s.FEATURE_NAME, s.SHAP_VALUE, s.FEATURE_VALUE
      FROM HR_ANALYTICS.PUBLIC.SHAP_RESULTS s
      JOIN HR_ANALYTICS.PUBLIC.RELATIONSHIP_RESULTS rr ON s.PREDICTION_ID = rr.ID
      WHERE rr.EMPLOYEE_ID = ? AND s.MODEL_TYPE = 'relationship'
      ORDER BY ABS(s.SHAP_VALUE) DESC LIMIT 10`, [idNum] as Binds), [], "shapRelationship"),
    safe(query(`SELECT EVIDENCE_JSON::STRING AS EVIDENCE_JSON
      FROM HR_ANALYTICS.PUBLIC.EVIDENCE_STORE
      WHERE EMPLOYEE_ID = ? AND SCORE_TYPE = 'attrition' LIMIT 1`, [idNum] as Binds), [], "evidenceAttrition"),
    safe(query(`SELECT EVIDENCE_JSON::STRING AS EVIDENCE_JSON
      FROM HR_ANALYTICS.PUBLIC.EVIDENCE_STORE
      WHERE EMPLOYEE_ID = ? AND SCORE_TYPE = 'relationship' LIMIT 1`, [idNum] as Binds), [], "evidenceRelationship"),
    safe(query(`SELECT sc.SIMILAR_EMPLOYEE_ID, sc.SIMILARITY_SCORE, sc.OUTCOME, sc.COMMON_FACTORS,
      e.LAST_NAME || e.FIRST_NAME AS SIM_NAME, e.EMPLOYEE_CODE AS SIM_CODE
      FROM HR_ANALYTICS.PUBLIC.SIMILAR_CASES sc
      JOIN HR_ANALYTICS.STAGING.EMPLOYEES e ON sc.SIMILAR_EMPLOYEE_ID = e.EMPLOYEE_ID
      WHERE sc.SOURCE_EMPLOYEE_ID = ? AND sc.SCORE_TYPE = 'attrition'
      ORDER BY sc.SIMILARITY_SCORE DESC LIMIT 5`, [idNum] as Binds), [], "similarCases"),
  ]);
  return { attritionPrediction, relationship, transferFit, shapFactors, relationshipShap, attritionEvidence, relationshipEvidence, similarCases };
}

async function mlViaPgLake(idNum: number) {
  const safe = <T>(p: Promise<T>, fallback: T, label: string): Promise<T> => p.catch((err) => { console.error(`[mlViaPgLake] ${label} failed:`, (err as Error).message); return fallback; });
  const [attritionPrediction, relationship, transferFit, shapFactors, relationshipShap, attritionEvidence, relationshipEvidence, similarCases] = await Promise.all([
    safe(pgQuery(`SELECT risk_score AS "RISK_SCORE", risk_label AS "RISK_LABEL", model_version AS "MODEL_VERSION"
      FROM hr_lake.prediction_results WHERE employee_id = $1`, [idNum]), [], "attrition"),
    safe(pgQuery(`SELECT rr.relationship_score AS "RELATIONSHIP_SCORE", rr.composite_label AS "COMPOSITE_LABEL",
      m.last_name || m.first_name AS "MANAGER_NAME"
      FROM hr_lake.relationship_results rr
      JOIN hr.employees m ON rr.manager_id = m.employee_id
      WHERE rr.employee_id = $1`, [idNum]), [], "relationship"),
    safe(pgQuery(`SELECT tf.fit_score AS "FIT_SCORE", tf.target_position_id AS "TARGET_POSITION_ID",
      p.title AS "TARGET_POSITION_TITLE", d.dept_name AS "TARGET_DEPT_NAME"
      FROM hr_lake.transfer_fit_results tf
      JOIN hr.positions p ON tf.target_position_id = p.position_id
      JOIN hr.departments d ON p.dept_id = d.dept_id
      WHERE tf.employee_id = $1 ORDER BY tf.fit_score DESC LIMIT 5`, [idNum]), [], "transferFit"),
    safe(pgQuery(`SELECT s.feature_name AS "FEATURE_NAME", s.shap_value AS "SHAP_VALUE", s.feature_value AS "FEATURE_VALUE"
      FROM hr_lake.shap_results s
      JOIN hr_lake.prediction_results pr ON s.prediction_id = pr.id
      WHERE pr.employee_id = $1 AND s.model_type = 'attrition'
      ORDER BY ABS(s.shap_value) DESC LIMIT 10`, [idNum]), [], "shapAttrition"),
    safe(pgQuery(`SELECT s.feature_name AS "FEATURE_NAME", s.shap_value AS "SHAP_VALUE", s.feature_value AS "FEATURE_VALUE"
      FROM hr_lake.shap_results s
      JOIN hr_lake.relationship_results rr ON s.prediction_id = rr.id
      WHERE rr.employee_id = $1 AND s.model_type = 'relationship'
      ORDER BY ABS(s.shap_value) DESC LIMIT 10`, [idNum]), [], "shapRelationship"),
    safe(pgQuery(`SELECT evidence_json AS "EVIDENCE_JSON"
      FROM hr_lake.evidence_store
      WHERE employee_id = $1 AND score_type = 'attrition' LIMIT 1`, [idNum]), [], "evidenceAttrition"),
    safe(pgQuery(`SELECT evidence_json AS "EVIDENCE_JSON"
      FROM hr_lake.evidence_store
      WHERE employee_id = $1 AND score_type = 'relationship' LIMIT 1`, [idNum]), [], "evidenceRelationship"),
    safe(pgQuery(`SELECT sc.similar_employee_id AS "SIMILAR_EMPLOYEE_ID", sc.similarity_score AS "SIMILARITY_SCORE",
      sc.outcome AS "OUTCOME", sc.common_factors AS "COMMON_FACTORS",
      e.last_name || e.first_name AS "SIM_NAME", e.employee_code AS "SIM_CODE"
      FROM hr_lake.similar_cases sc
      JOIN hr.employees e ON sc.similar_employee_id = e.employee_id
      WHERE sc.source_employee_id = $1 AND sc.score_type = 'attrition'
      ORDER BY sc.similarity_score DESC LIMIT 5`, [idNum]), [], "similarCases"),
  ]);
  return { attritionPrediction, relationship, transferFit, shapFactors, relationshipShap, attritionEvidence, relationshipEvidence, similarCases };
}

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }
  try {
    const { id } = await params;
    const idNum = Number(id);
    const url = new URL(request.url);
    const section = url.searchParams.get("section");

    const employees = await pgQuery(`
      SELECT e.employee_id AS "EMPLOYEE_ID", e.employee_code AS "EMPLOYEE_CODE",
        e.first_name AS "FIRST_NAME", e.last_name AS "LAST_NAME",
        e.email AS "EMAIL", e.phone AS "PHONE",
        e.hire_date AS "HIRE_DATE", e.birth_date AS "BIRTH_DATE",
        e.gender AS "GENDER", e.dept_id AS "DEPT_ID",
        e.position_id AS "POSITION_ID", e.manager_id AS "MANAGER_ID",
        e.status AS "STATUS", e.salary AS "SALARY",
        e.employment_type AS "EMPLOYMENT_TYPE",
        e.commute_time_minutes AS "COMMUTE_TIME_MINUTES",
        e.last_promotion_date AS "LAST_PROMOTION_DATE",
        e.created_at AS "CREATED_AT", e.updated_at AS "UPDATED_AT",
        d.dept_name AS "DEPT_NAME", d.parent_dept_id AS "PARENT_DEPT_ID",
        p.title AS "POSITION_TITLE", p.grade AS "GRADE",
        m.last_name || m.first_name AS "MANAGER_NAME"
      FROM hr.employees e
      LEFT JOIN hr.departments d ON e.dept_id = d.dept_id
      LEFT JOIN hr.positions p ON e.position_id = p.position_id
      LEFT JOIN hr.employees m ON e.manager_id = m.employee_id
      WHERE e.employee_id = $1
    `, [idNum]);

    if (employees.length === 0) {
      return NextResponse.json({ error: "Employee not found" }, { status: 404 });
    }

    const emp = employees[0] as Record<string, unknown>;
    const deptId = emp.DEPT_ID as number;

    const [skills, evaluations, notes, deptColleagues, subDeptColleagues] = await Promise.all([
      pgQuery(`
        SELECT s.skill_name AS "SKILL_NAME", s.category AS "CATEGORY", es.proficiency AS "PROFICIENCY"
        FROM hr.employee_skills es
        JOIN hr.skills s ON es.skill_id = s.skill_id
        WHERE es.employee_id = $1
        ORDER BY es.proficiency DESC
      `, [idNum]),
      pgQuery(`
        SELECT evaluation_id AS "EVALUATION_ID", employee_id AS "EMPLOYEE_ID",
          evaluator_id AS "EVALUATOR_ID", period AS "PERIOD", score AS "SCORE",
          grade AS "GRADE", comment AS "COMMENT", self_comment AS "SELF_COMMENT",
          self_score AS "SELF_SCORE", status AS "STATUS",
          created_at AS "CREATED_AT", updated_at AS "UPDATED_AT"
        FROM hr.evaluations WHERE employee_id = $1
        ORDER BY period DESC
      `, [idNum]),
      pgQuery(`
        SELECT note_id AS "NOTE_ID", employee_id AS "EMPLOYEE_ID",
          manager_id AS "MANAGER_ID", note_date AS "NOTE_DATE",
          content AS "CONTENT", category AS "CATEGORY", is_private AS "IS_PRIVATE",
          created_at AS "CREATED_AT"
        FROM hr.one_on_one_notes WHERE employee_id = $1
        ORDER BY note_date DESC LIMIT 20
      `, [idNum]),
      pgQuery(`
        SELECT e.employee_id AS "EMPLOYEE_ID", e.last_name || e.first_name AS "NAME",
          e.employee_code AS "EMPLOYEE_CODE", p.grade AS "GRADE", p.title AS "TITLE",
          e.manager_id AS "MANAGER_ID"
        FROM hr.employees e
        LEFT JOIN hr.positions p ON e.position_id = p.position_id
        WHERE e.dept_id = $1 AND e.status = 'active'
        ORDER BY CASE p.grade
          WHEN 'E1' THEN 1 WHEN 'D1' THEN 2 WHEN 'D2' THEN 3
          WHEN 'M1' THEN 4 WHEN 'M2' THEN 5 WHEN 'S1' THEN 6
          WHEN 'S2' THEN 7 WHEN 'J1' THEN 8 WHEN 'J2' THEN 9
          WHEN 'J3' THEN 10 ELSE 99 END, e.last_name
      `, [deptId]),
      pgQuery(`
        SELECT e.employee_id AS "EMPLOYEE_ID", e.last_name || e.first_name AS "NAME",
          e.employee_code AS "EMPLOYEE_CODE", p.grade AS "GRADE", p.title AS "TITLE",
          e.manager_id AS "MANAGER_ID", e.dept_id AS "DEPT_ID", d.dept_name AS "DEPT_NAME"
        FROM hr.employees e
        LEFT JOIN hr.positions p ON e.position_id = p.position_id
        JOIN hr.departments d ON e.dept_id = d.dept_id
        WHERE d.parent_dept_id = $1 AND e.status = 'active'
        ORDER BY d.dept_name, CASE p.grade
          WHEN 'E1' THEN 1 WHEN 'D1' THEN 2 WHEN 'D2' THEN 3
          WHEN 'M1' THEN 4 WHEN 'M2' THEN 5 WHEN 'S1' THEN 6
          WHEN 'S2' THEN 7 WHEN 'J1' THEN 8 WHEN 'J2' THEN 9
          WHEN 'J3' THEN 10 ELSE 99 END, e.last_name
      `, [deptId]),
    ]);

    const careerHistory = await pgQuery(`
      SELECT ch.history_id AS "HISTORY_ID", ch.dept_id AS "DEPT_ID",
        ch.position_id AS "POSITION_ID", ch.manager_id AS "MANAGER_ID",
        ch.start_date AS "START_DATE", ch.end_date AS "END_DATE",
        ch.transfer_type AS "TRANSFER_TYPE", ch.reason AS "REASON",
        ch.performance_after AS "PERFORMANCE_AFTER",
        d.dept_name AS "DEPT_NAME", p.title AS "POSITION_TITLE",
        COALESCE(m.last_name || m.first_name, '') AS "MANAGER_NAME"
      FROM hr.career_history ch
      LEFT JOIN hr.departments d ON ch.dept_id = d.dept_id
      LEFT JOIN hr.positions p ON ch.position_id = p.position_id
      LEFT JOIN hr.employees m ON ch.manager_id = m.employee_id
      WHERE ch.employee_id = $1
      ORDER BY ch.start_date DESC
    `, [idNum]).catch((err) => { console.error("[careerHistory] query failed:", (err as Error).message); return []; });

    if (section === "basic") {
      return NextResponse.json({
        employee: emp,
        skills,
        evaluations,
        notes,
        careerHistory,
        orgChart: { deptColleagues, subDeptColleagues },
      });
    }

    if (section === "ml") {
      const dataPath = await getDataPath();
      const t0 = performance.now();

      const result = dataPath === "pg_lake"
        ? await mlViaPgLake(idNum)
        : await mlViaSf(idNum);

      const ms = Math.round(performance.now() - t0);

      const parseEvidence = (rows: Record<string, unknown>[]) => {
        if (rows.length === 0) return null;
        try { return JSON.parse(rows[0].EVIDENCE_JSON as string); } catch { return null; }
      };

      return NextResponse.json({
        attrition: result.attritionPrediction[0] || null,
        relationship: result.relationship[0] || null,
        transferFit: result.transferFit,
        shapFactors: result.shapFactors,
        relationshipShap: result.relationshipShap,
        attritionEvidence: parseEvidence(result.attritionEvidence as Record<string, unknown>[]),
        relationshipEvidence: parseEvidence(result.relationshipEvidence as Record<string, unknown>[]),
        similarCases: result.similarCases,
        _meta: { dataPath, ms },
      });
    }

    const dataPath = await getDataPath();
    const mlResult = dataPath === "pg_lake"
      ? await mlViaPgLake(idNum)
      : await mlViaSf(idNum);

    return NextResponse.json({
      employee: emp,
      skills,
      evaluations,
      notes,
      careerHistory,
      orgChart: { deptColleagues, subDeptColleagues },
      mlInsights: {
        attrition: mlResult.attritionPrediction[0] || null,
        relationship: mlResult.relationship[0] || null,
      },
    });
  } catch (error) {
    console.error("Employee detail error:", error);
    return NextResponse.json({ error: "Failed to fetch employee" }, { status: 500 });
  }
}

const EDITABLE_FIELDS: Record<string, string> = {
  FIRST_NAME: "first_name",
  LAST_NAME: "last_name",
  EMAIL: "email",
  PHONE: "phone",
  GENDER: "gender",
  BIRTH_DATE: "birth_date",
  HIRE_DATE: "hire_date",
  DEPT_ID: "dept_id",
  POSITION_ID: "position_id",
  MANAGER_ID: "manager_id",
  STATUS: "status",
  SALARY: "salary",
  EMPLOYMENT_TYPE: "employment_type",
  COMMUTE_TIME_MINUTES: "commute_time_minutes",
  LAST_PROMOTION_DATE: "last_promotion_date",
};

export async function PUT(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const session = await getSession();
  const auth = requireRole(session, ["HR_ADMIN", "HR_MANAGER"]);
  if (!auth.ok) return NextResponse.json(auth.body, { status: auth.status });
  try {
    const { id } = await params;
    const idNum = Number(id);
    if (isNaN(idNum)) {
      return NextResponse.json({ error: "Invalid employee id" }, { status: 400 });
    }

    const body = await request.json();
    const { updated_at: clientUpdatedAt, ...fields } = body as Record<string, unknown>;

    // Optimistic lock: verify the row has not changed since the client read it
    const [current] = await pgQuery<{ updated_at: string; dept_id: number; position_id: number }>(
      `SELECT updated_at, dept_id, position_id FROM hr.employees WHERE employee_id = $1`,
      [idNum]
    );
    if (!current) {
      return NextResponse.json({ error: "Employee not found" }, { status: 404 });
    }
    if (clientUpdatedAt && new Date(clientUpdatedAt as string).getTime() !== new Date(current.updated_at).getTime()) {
      return NextResponse.json(
        { error: "他のユーザーが更新済みです。画面を再読み込みしてください。", code: "STALE_WRITE" },
        { status: 409 }
      );
    }

    // Salary is admin-only
    if ("SALARY" in fields && session!.role !== "HR_ADMIN") {
      delete fields.SALARY;
    }

    const setClauses: string[] = [];
    const values: unknown[] = [];
    let idx = 1;
    for (const [key, value] of Object.entries(fields)) {
      const column = EDITABLE_FIELDS[key];
      if (!column) continue;
      setClauses.push(`${column} = $${idx}`);
      values.push(value === "" ? null : value);
      idx++;
    }

    if (setClauses.length === 0) {
      return NextResponse.json({ error: "更新対象のフィールドがありません" }, { status: 400 });
    }

    values.push(idNum);
    const updated = await pgQuery<Record<string, unknown>>(
      `UPDATE hr.employees SET ${setClauses.join(", ")}, updated_at = NOW()
       WHERE employee_id = $${idx}
       RETURNING employee_id AS "EMPLOYEE_ID", dept_id AS "DEPT_ID",
                 position_id AS "POSITION_ID", updated_at AS "UPDATED_AT"`,
      values
    );

    // Record a career_history row when the department or position changed
    const newDeptId = fields.DEPT_ID != null ? Number(fields.DEPT_ID) : current.dept_id;
    const newPositionId = fields.POSITION_ID != null ? Number(fields.POSITION_ID) : current.position_id;
    if (newDeptId !== current.dept_id || newPositionId !== current.position_id) {
      try {
        await pgQuery(
          `UPDATE hr.career_history SET end_date = CURRENT_DATE
           WHERE employee_id = $1 AND end_date IS NULL`,
          [idNum]
        );
        await pgQuery(
          `INSERT INTO hr.career_history (employee_id, dept_id, position_id, manager_id, start_date, transfer_type, reason)
           VALUES ($1, $2, $3, (SELECT manager_id FROM hr.employees WHERE employee_id = $1), CURRENT_DATE, 'transfer', $4)`,
          [idNum, newDeptId, newPositionId, `画面編集による更新 (${session!.displayName})`]
        );
      } catch (err) {
        console.error("[employees PUT] career_history insert failed:", (err as Error).message);
      }
    }

    return NextResponse.json({ success: true, employee: updated[0] });
  } catch (error) {
    console.error("Employee update error:", error);
    return NextResponse.json({ error: "更新に失敗しました" }, { status: 500 });
  }
}
