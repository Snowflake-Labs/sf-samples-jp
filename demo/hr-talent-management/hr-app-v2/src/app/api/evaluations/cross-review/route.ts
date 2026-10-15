import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession, getAllowedDeptIds } from "@/lib/session";

export async function GET(request: Request) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  try {
    const { searchParams } = new URL(request.url);
    const honbu = searchParams.get("honbu");
    const deptId = searchParams.get("dept_id");
    const period = searchParams.get("period");
    const gradeFilter = searchParams.get("grade");
    const sortBy = searchParams.get("sort_by") || "composite";
    const order = searchParams.get("order") === "asc" ? "ASC" : "DESC";

    if (!period) {
      return NextResponse.json({ error: "period は必須です" }, { status: 400 });
    }

    const params: unknown[] = [period];
    let idx = 2;

    let deptFilter = "";
    if (deptId) {
      const dId = Number(deptId);
      if (isNaN(dId)) return NextResponse.json({ error: "Invalid dept_id" }, { status: 400 });
      deptFilter = `AND e.dept_id IN (SELECT dept_id FROM hr.departments WHERE dept_id = $${idx} OR parent_dept_id = $${idx + 1})`;
      params.push(dId, dId);
      idx += 2;
    } else if (honbu) {
      const hId = Number(honbu);
      if (isNaN(hId)) return NextResponse.json({ error: "Invalid honbu" }, { status: 400 });
      deptFilter = `AND e.dept_id IN (SELECT dept_id FROM hr.departments WHERE dept_id = $${idx} OR parent_dept_id = $${idx + 1})`;
      params.push(hId, hId);
      idx += 2;
    }

    // dept scope check
    const allowed = getAllowedDeptIds(session);
    if (allowed) {
      const scopePlaceholders = allowed.map((d) => { params.push(d); return `$${idx++}`; }).join(",");
      deptFilter += ` AND e.dept_id IN (${scopePlaceholders})`;
    }

    let gradeClause = "";
    if (gradeFilter) {
      gradeClause = `AND pos.grade = $${idx}`;
      params.push(gradeFilter);
      idx++;
    }

    const sortColumn: Record<string, string> = {
      // The expectation gap is the ranking metric, so it is the default sort.
      gap: 'eqs.expectation_gap',
      composite: 'COALESCE(eqs.manual_composite, eqs.composite_score)',
      growth: 'eqs.growth_score',
      expertise: 'eqs.expertise_score',
      leadership: 'eqs.leadership_score',
      problem_solving: 'eqs.problem_solving_score',
      collaboration: 'eqs.collaboration_score',
      eval_score: 'ev.score',
      dept_rank: 'eqs.dept_rank',
      grade_rank: 'eqs.grade_rank',
    };
    const orderExpr = sortColumn[sortBy] || sortColumn.gap;

    const rows = await pgQuery(`
      SELECT
        e.employee_id AS "EMPLOYEE_ID",
        e.last_name || e.first_name AS "NAME",
        e.employee_code AS "EMPLOYEE_CODE",
        d.dept_name AS "DEPT_NAME",
        pos.grade AS "GRADE",
        pos.title AS "POSITION_TITLE",
        ev.evaluation_id AS "EVALUATION_ID",
        ev.score AS "EVAL_SCORE",
        ev.grade AS "EVAL_GRADE",
        ev.comment AS "COMMENT",
        ev.self_comment AS "SELF_COMMENT",
        ev.status AS "EVAL_STATUS",
        eqs.growth_score AS "GROWTH",
        eqs.expertise_score AS "EXPERTISE",
        eqs.leadership_score AS "LEADERSHIP",
        eqs.problem_solving_score AS "PROBLEM_SOLVING",
        eqs.collaboration_score AS "COLLABORATION",
        eqs.composite_score AS "AI_COMPOSITE",
        eqs.ai_recommended_grade AS "AI_GRADE",
        eqs.ai_reasoning AS "AI_REASONING",
        eqs.manual_composite AS "MANUAL_COMPOSITE",
        eqs.manual_grade AS "MANUAL_GRADE",
        eqs.manual_note AS "MANUAL_NOTE",
        eqs.dept_rank AS "DEPT_RANK",
        eqs.grade_rank AS "GRADE_RANK",
        eqs.composite_raw AS "COMPOSITE_RAW",
        eqs.expectation_gap AS "EXPECTATION_GAP",
        eqs.standard_grade AS "STANDARD_GRADE",
        eqs.next_grade AS "NEXT_GRADE",
        eqs.next_grade_axes_met AS "NEXT_GRADE_AXES_MET",
        eqs.promotion_readiness AS "PROMOTION_READINESS",
        eqs.promotion_shortfalls AS "PROMOTION_SHORTFALLS",
        gss.growth_expected AS "EXP_GROWTH",
        gss.expertise_expected AS "EXP_EXPERTISE",
        gss.leadership_expected AS "EXP_LEADERSHIP",
        gss.problem_solving_expected AS "EXP_PROBLEM_SOLVING",
        gss.collaboration_expected AS "EXP_COLLABORATION",
        ea.extracted_strengths AS "STRENGTHS",
        ea.extracted_improvements AS "IMPROVEMENTS",
        ea.sentiment_score AS "SENTIMENT",
        ea.category AS "CATEGORY",
        ev.grade_reason AS "MANAGER_GRADE_REASON",
        ev.return_reason AS "RETURN_REASON",
        (SELECT json_agg(json_build_object('axis', o.axis, 'ai', o.ai_score, 'manager', o.manager_score,
                                           'reason', o.reason, 'by', o.updated_by) ORDER BY o.axis)
         FROM hr.eval_axis_overrides o WHERE o.evaluation_id = ev.evaluation_id) AS "MANAGER_OVERRIDES"
      FROM hr.evaluations ev
      JOIN hr.employees e ON ev.employee_id = e.employee_id
      JOIN hr.departments d ON e.dept_id = d.dept_id
      JOIN hr.positions pos ON e.position_id = pos.position_id
      LEFT JOIN hr.eval_quantified_scores eqs ON ev.evaluation_id = eqs.evaluation_id
      LEFT JOIN hr.grade_score_standards gss ON pos.grade = gss.grade
      LEFT JOIN hr.evaluation_analysis ea ON ev.evaluation_id = ea.evaluation_id
      WHERE ev.period = $1 AND e.status = 'active'
        ${deptFilter}
        ${gradeClause}
      ORDER BY ${orderExpr} ${order} NULLS LAST, e.last_name
    `, params);

    // Summary
    const gradeDistribution: Record<string, number> = {};
    const readinessDistribution: Record<string, number> = {};
    let totalComposite = 0;
    let compositeCount = 0;
    let totalGap = 0;
    let gapCount = 0;
    for (const r of rows as Record<string, unknown>[]) {
      const g = (r.STANDARD_GRADE as string) || (r.MANUAL_GRADE as string) || (r.EVAL_GRADE as string) || "?";
      gradeDistribution[g] = (gradeDistribution[g] || 0) + 1;
      const c = (r.MANUAL_COMPOSITE ?? r.AI_COMPOSITE) as number | null;
      if (c != null) { totalComposite += Number(c); compositeCount++; }
      const gap = r.EXPECTATION_GAP as number | null;
      if (gap != null) { totalGap += Number(gap); gapCount++; }
      const pr = r.PROMOTION_READINESS as string | null;
      if (pr) readinessDistribution[pr] = (readinessDistribution[pr] || 0) + 1;
    }

    // 画面の初期期間を「今日の日付」ではなくデータのある期間から選べるように返す。
    // この画面の主役は期待比なので、初期表示は「定量化済みの評価がある最新期間」にする。
    // 評価はあっても未定量化の期間を選ぶと、期待比が全行「—」になり順位が意味をなさない。
    const periodRows = await pgQuery<{ period: string }>(
      `SELECT DISTINCT period FROM hr.evaluations WHERE period IS NOT NULL ORDER BY period DESC LIMIT 12`
    );
    const quantifiedRows = await pgQuery<{ period: string }>(
      `SELECT DISTINCT period FROM hr.eval_quantified_scores ORDER BY period DESC`
    );

    return NextResponse.json({
      availablePeriods: periodRows.map((r) => r.period),
      quantifiedPeriods: quantifiedRows.map((r) => r.period),
      employees: rows,
      summary: {
        total: rows.length,
        gradeDistribution,
        readinessDistribution,
        avgComposite: compositeCount > 0 ? Math.round((totalComposite / compositeCount) * 10) / 10 : null,
        avgExpectationGap: gapCount > 0 ? Math.round((totalGap / gapCount) * 100) / 100 : null,
        quantified: compositeCount,
        unquantified: rows.length - compositeCount,
      },
    });
  } catch (error) {
    console.error("Cross-review error:", error);
    return NextResponse.json({ error: "横断レビューデータの取得に失敗しました" }, { status: 500 });
  }
}

export async function PUT(request: Request) {
  const session = await getSession();
  if (!session || (session.role !== "HR_ADMIN" && session.role !== "HR_MANAGER")) {
    return NextResponse.json({ error: "権限がありません" }, { status: 403 });
  }

  try {
    const body = await request.json();
    const { updates } = body as {
      updates: { evaluation_id: number; manual_composite?: number; manual_grade?: string; manual_note?: string }[];
    };

    if (!updates || !Array.isArray(updates)) {
      return NextResponse.json({ error: "updates 配列が必要です" }, { status: 400 });
    }

    let updated = 0;
    for (const u of updates) {
      await pgQuery(`
        UPDATE hr.eval_quantified_scores
        SET manual_composite = $1, manual_grade = $2, manual_note = $3, updated_at = NOW()
        WHERE evaluation_id = $4
      `, [u.manual_composite ?? null, u.manual_grade ?? null, u.manual_note ?? null, u.evaluation_id]);
      updated++;
    }

    // Recalculate ranks
    if (updated > 0) {
      const periods = await pgQuery<{ period: string }>(`
        SELECT DISTINCT period FROM hr.eval_quantified_scores
        WHERE evaluation_id = ANY($1)
      `, [updates.map((u) => u.evaluation_id)]);

      for (const { period } of periods) {
        await pgQuery(`
          WITH ranked AS (
            SELECT eqs.id,
              RANK() OVER (PARTITION BY e.dept_id
                           ORDER BY COALESCE(eqs.manual_composite, eqs.expectation_gap) DESC NULLS LAST) AS d_rank,
              RANK() OVER (PARTITION BY pos.grade
                           ORDER BY COALESCE(eqs.manual_composite, eqs.expectation_gap) DESC NULLS LAST) AS g_rank
            FROM hr.eval_quantified_scores eqs
            JOIN hr.employees e ON eqs.employee_id = e.employee_id
            JOIN hr.positions pos ON e.position_id = pos.position_id
            WHERE eqs.period = $1
          )
          UPDATE hr.eval_quantified_scores SET dept_rank = ranked.d_rank, grade_rank = ranked.g_rank
          FROM ranked WHERE eval_quantified_scores.id = ranked.id
        `, [period]);
      }
    }

    return NextResponse.json({ updated });
  } catch (error) {
    console.error("Cross-review update error:", error);
    return NextResponse.json({ error: "更新に失敗しました" }, { status: 500 });
  }
}
