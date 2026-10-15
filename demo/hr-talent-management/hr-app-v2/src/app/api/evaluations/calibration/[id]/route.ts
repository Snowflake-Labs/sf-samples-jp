import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession, requireRole } from "@/lib/session";
import { analyzeDistributionGap, READINESS_LABELS } from "@/lib/scoring";

/**
 * One calibration session: the target distribution, how the actual
 * distribution compares, and the roster the meeting works through.
 */

interface SessionRow {
  SESSION_ID: number;
  SESSION_NAME: string;
  PERIOD: string;
  SCOPE_DEPT_ID: number | null;
  SCOPE_GRADE: string | null;
  DEPT_NAME: string | null;
  TARGET_DISTRIBUTION: Record<string, number>;
  STATUS: string;
  FACILITATOR: string | null;
  NOTES: string | null;
  FINALIZED_AT: string | null;
}

interface MemberRow {
  EVALUATION_ID: number;
  EMPLOYEE_ID: number;
  NAME: string;
  EMPLOYEE_CODE: string;
  DEPT_NAME: string;
  POSITION_GRADE: string;
  POSITION_TITLE: string;
  GROWTH_SCORE: number | null;
  EXPERTISE_SCORE: number | null;
  LEADERSHIP_SCORE: number | null;
  PROBLEM_SOLVING_SCORE: number | null;
  COLLABORATION_SCORE: number | null;
  COMPOSITE_SCORE: string | null;
  COMPOSITE_RAW: string | null;
  EXPECTATION_GAP: string | null;
  STANDARD_GRADE: string | null;
  MANUAL_GRADE: string | null;
  MANUAL_COMPOSITE: string | null;
  DEPT_RANK: number | null;
  GRADE_RANK: number | null;
  NEXT_GRADE: string | null;
  NEXT_GRADE_AXES_MET: number | null;
  PROMOTION_READINESS: string | null;
  PROMOTION_SHORTFALLS: unknown;
  AI_REASONING: string | null;
  COMMENT: string | null;
  ADJUSTED_GRADE: string | null;
  ADJUSTMENT_REASON: string | null;
}

export async function GET(request: Request, ctx: { params: Promise<{ id: string }> }) {
  const session = await getSession();
  const auth = requireRole(session, ["HR_ADMIN", "HR_MANAGER"]);
  if (!auth.ok) return NextResponse.json(auth.body, { status: auth.status });
  try {
    const { id } = await ctx.params;
    const sessionId = Number(id);
    if (!Number.isInteger(sessionId)) {
      return NextResponse.json({ error: "session_id が不正です" }, { status: 400 });
    }

    const sessions = await pgQuery<SessionRow>(
      `SELECT cs.session_id AS "SESSION_ID", cs.session_name AS "SESSION_NAME",
         cs.period AS "PERIOD", cs.scope_dept_id AS "SCOPE_DEPT_ID", d.dept_name AS "DEPT_NAME",
         cs.scope_grade AS "SCOPE_GRADE",
         cs.target_distribution AS "TARGET_DISTRIBUTION", cs.status AS "STATUS",
         cs.facilitator AS "FACILITATOR", cs.notes AS "NOTES", cs.finalized_at AS "FINALIZED_AT"
       FROM hr.calibration_sessions cs
       LEFT JOIN hr.departments d ON cs.scope_dept_id = d.dept_id
       WHERE cs.session_id = $1`,
      [sessionId]
    );
    if (sessions.length === 0) {
      return NextResponse.json({ error: "調整会議が見つかりません" }, { status: 404 });
    }
    const cs = sessions[0];

    // Roster: everyone in scope with a quantified score, plus any adjustment
    // already made in this session.
    const members = await pgQuery<MemberRow>(
      `SELECT ev.evaluation_id AS "EVALUATION_ID", e.employee_id AS "EMPLOYEE_ID",
         e.last_name || e.first_name AS "NAME", e.employee_code AS "EMPLOYEE_CODE",
         d.dept_name AS "DEPT_NAME", pos.grade AS "POSITION_GRADE", pos.title AS "POSITION_TITLE",
         eqs.growth_score AS "GROWTH_SCORE", eqs.expertise_score AS "EXPERTISE_SCORE",
         eqs.leadership_score AS "LEADERSHIP_SCORE", eqs.problem_solving_score AS "PROBLEM_SOLVING_SCORE",
         eqs.collaboration_score AS "COLLABORATION_SCORE",
         eqs.composite_score AS "COMPOSITE_SCORE", eqs.composite_raw AS "COMPOSITE_RAW",
         eqs.expectation_gap AS "EXPECTATION_GAP", eqs.standard_grade AS "STANDARD_GRADE",
         eqs.manual_grade AS "MANUAL_GRADE", eqs.manual_composite AS "MANUAL_COMPOSITE",
         eqs.dept_rank AS "DEPT_RANK", eqs.grade_rank AS "GRADE_RANK",
         eqs.next_grade AS "NEXT_GRADE", eqs.next_grade_axes_met AS "NEXT_GRADE_AXES_MET",
         eqs.promotion_readiness AS "PROMOTION_READINESS", eqs.promotion_shortfalls AS "PROMOTION_SHORTFALLS",
         eqs.ai_reasoning AS "AI_REASONING", ev.comment AS "COMMENT",
         ca.after_grade AS "ADJUSTED_GRADE", ca.reason AS "ADJUSTMENT_REASON",
         ev.grade_reason AS "MANAGER_GRADE_REASON",
         (SELECT json_agg(json_build_object('axis', o.axis, 'ai', o.ai_score, 'manager', o.manager_score,
                                            'reason', o.reason, 'by', o.updated_by) ORDER BY o.axis)
          FROM hr.eval_axis_overrides o WHERE o.evaluation_id = ev.evaluation_id) AS "MANAGER_OVERRIDES"
       FROM hr.evaluations ev
       JOIN hr.employees e ON ev.employee_id = e.employee_id
       JOIN hr.positions pos ON e.position_id = pos.position_id
       LEFT JOIN hr.departments d ON e.dept_id = d.dept_id
       LEFT JOIN hr.eval_quantified_scores eqs ON eqs.evaluation_id = ev.evaluation_id
       LEFT JOIN LATERAL (
         SELECT after_grade, reason FROM hr.calibration_adjustments
         WHERE session_id = $1 AND evaluation_id = ev.evaluation_id
         ORDER BY created_at DESC LIMIT 1
       ) ca ON TRUE
       WHERE ev.period = $2
         AND ($3::int IS NULL OR e.dept_id IN (
               SELECT dept_id FROM hr.departments WHERE dept_id = $3 OR parent_dept_id = $3))
         AND ($4::text IS NULL OR pos.grade = $4)
         -- 調整できるのは定量化済みの人だけ。未定量化を含めると全社で1万件超・数MBになる
         AND eqs.evaluation_id IS NOT NULL
       ORDER BY eqs.expectation_gap DESC NULLS LAST`,
      [sessionId, cs.PERIOD, cs.SCOPE_DEPT_ID, cs.SCOPE_GRADE]
    );

    // 未定量化の人数は件数だけ返す（画面の「未定量化 N名」表示用）
    const [{ total }] = await pgQuery<{ total: number }>(
      `SELECT COUNT(*)::int AS total
       FROM hr.evaluations ev
       JOIN hr.employees e ON ev.employee_id = e.employee_id
       JOIN hr.positions pos ON e.position_id = pos.position_id
       WHERE ev.period = $1
         AND ($2::int IS NULL OR e.dept_id IN (
               SELECT dept_id FROM hr.departments WHERE dept_id = $2 OR parent_dept_id = $2))
         AND ($3::text IS NULL OR pos.grade = $3)`,
      [cs.PERIOD, cs.SCOPE_DEPT_ID, cs.SCOPE_GRADE]
    );

    // The effective grade is the adjusted one when the meeting changed it,
    // then any earlier manual override, then the AI's standard grade.
    const actual: Record<string, number> = {};
    for (const m of members) {
      const g = m.ADJUSTED_GRADE ?? m.MANUAL_GRADE ?? m.STANDARD_GRADE;
      if (g) actual[g] = (actual[g] ?? 0) + 1;
    }
    const graded = Object.values(actual).reduce((a, b) => a + b, 0);

    const distribution = analyzeDistributionGap(actual, cs.TARGET_DISTRIBUTION, graded);

    return NextResponse.json({
      session: cs,
      members,
      distribution,
      summary: {
        total,
        graded,
        ungraded: total - graded,
        adjusted: members.filter((m) => m.ADJUSTED_GRADE).length,
        aligned: distribution.every((d) => d.delta === 0),
      },
      readiness_labels: READINESS_LABELS,
    });
  } catch (error) {
    console.error("Calibration detail error:", error);
    return NextResponse.json({ error: "調整会議の詳細取得に失敗しました" }, { status: 500 });
  }
}

export async function PATCH(request: Request, ctx: { params: Promise<{ id: string }> }) {
  const session = await getSession();
  const auth = requireRole(session, ["HR_ADMIN"]);
  if (!auth.ok) return NextResponse.json(auth.body, { status: auth.status });
  const user = auth.user;
  try {
    const { id } = await ctx.params;
    const sessionId = Number(id);
    const body = await request.json();
    const { status, notes, target_distribution } = body as {
      status?: string;
      notes?: string;
      target_distribution?: Record<string, number>;
    };

    const existing = await pgQuery<{ STATUS: string }>(
      `SELECT status AS "STATUS" FROM hr.calibration_sessions WHERE session_id = $1`,
      [sessionId]
    );
    if (existing.length === 0) {
      return NextResponse.json({ error: "調整会議が見つかりません" }, { status: 404 });
    }
    if (existing[0].STATUS === "finalized") {
      return NextResponse.json(
        { error: "確定済みの調整会議は変更できません" },
        { status: 409 }
      );
    }

    if (status && !["draft", "in_review", "finalized"].includes(status)) {
      return NextResponse.json({ error: "status が不正です" }, { status: 400 });
    }

    await pgQuery(
      `UPDATE hr.calibration_sessions SET
         status = COALESCE($2, status),
         notes = COALESCE($3, notes),
         target_distribution = COALESCE($4::jsonb, target_distribution),
         finalized_at = CASE WHEN $2 = 'finalized' THEN NOW() ELSE finalized_at END
       WHERE session_id = $1`,
      [sessionId, status ?? null, notes ?? null, target_distribution ? JSON.stringify(target_distribution) : null]
    );

    console.log(`[calibration] ${user.username} updated session ${sessionId}` + (status ? ` -> ${status}` : ""));
    return NextResponse.json({ ok: true });
  } catch (error) {
    console.error("Calibration PATCH error:", error);
    return NextResponse.json({ error: "調整会議の更新に失敗しました" }, { status: 500 });
  }
}
