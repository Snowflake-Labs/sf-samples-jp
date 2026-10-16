import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession, requireRole } from "@/lib/session";
import { loadStandards } from "@/lib/recalculate";
import {
  computeExpectationGap,
  gapToGrade,
  SCORE_AXES,
  WEIGHT_SUM_EPSILON,
  type AxisScores,
  type GradeStandard,
  type ScoreAxis,
} from "@/lib/scoring";

/**
 * Dry-run a standards change.
 *
 * Changing a grade's expected levels or weights silently re-ranks people,
 * so the admin screen shows who moves before the change is committed.
 * Nothing is written here.
 */

interface ScoreRow {
  EMPLOYEE_ID: number;
  NAME: string;
  DEPT_NAME: string;
  GROWTH_SCORE: number;
  EXPERTISE_SCORE: number;
  LEADERSHIP_SCORE: number;
  PROBLEM_SOLVING_SCORE: number;
  COLLABORATION_SCORE: number;
  EXPECTATION_GAP: string | null;
  STANDARD_GRADE: string | null;
}

export async function POST(request: Request) {
  const session = await getSession();
  const auth = requireRole(session, ["HR_ADMIN"]);
  if (!auth.ok) return NextResponse.json(auth.body, { status: auth.status });
  try {
    const body = (await request.json()) as {
      grade: string;
      axes: Record<ScoreAxis, { expected: number; weight: number }>;
      period?: string;
    };
    const { grade, axes, period } = body;

    if (!grade || !axes) {
      return NextResponse.json({ error: "grade と axes が必要です" }, { status: 400 });
    }

    const weightSum = SCORE_AXES.reduce((a, k) => a + (axes[k]?.weight ?? 0), 0);
    if (Math.abs(weightSum - 1.0) >= WEIGHT_SUM_EPSILON) {
      return NextResponse.json(
        { error: `重みの合計が ${weightSum.toFixed(3)} です。1.000 にしてください` },
        { status: 400 }
      );
    }

    const proposed: GradeStandard = {
      growth: axes.growth,
      expertise: axes.expertise,
      leadership: axes.leadership,
      problem_solving: axes.problem_solving,
      collaboration: axes.collaboration,
    };

    const currentStandards = await loadStandards();
    const current = currentStandards.get(grade) ?? null;

    // Only people at this grade are affected.
    const rows = await pgQuery<ScoreRow>(
      `SELECT eqs.employee_id AS "EMPLOYEE_ID",
         e.last_name || e.first_name AS "NAME", d.dept_name AS "DEPT_NAME",
         eqs.growth_score AS "GROWTH_SCORE", eqs.expertise_score AS "EXPERTISE_SCORE",
         eqs.leadership_score AS "LEADERSHIP_SCORE", eqs.problem_solving_score AS "PROBLEM_SOLVING_SCORE",
         eqs.collaboration_score AS "COLLABORATION_SCORE",
         eqs.expectation_gap AS "EXPECTATION_GAP", eqs.standard_grade AS "STANDARD_GRADE"
       FROM hr.eval_quantified_scores eqs
       JOIN hr.employees e ON eqs.employee_id = e.employee_id
       JOIN hr.positions pos ON e.position_id = pos.position_id
       LEFT JOIN hr.departments d ON e.dept_id = d.dept_id
       WHERE pos.grade = $1
         AND eqs.growth_score IS NOT NULL
         AND ($2::text IS NULL OR eqs.period = $2)`,
      [grade, period ?? null]
    );

    const changes = rows.map((r) => {
      const actual: AxisScores = {
        growth: Number(r.GROWTH_SCORE),
        expertise: Number(r.EXPERTISE_SCORE),
        leadership: Number(r.LEADERSHIP_SCORE),
        problem_solving: Number(r.PROBLEM_SOLVING_SCORE),
        collaboration: Number(r.COLLABORATION_SCORE),
      };
      const after = computeExpectationGap(actual, proposed);
      const afterGrade = gapToGrade(after.expectationGap);

      // Prefer the stored values so the diff reflects what people actually see;
      // fall back to recomputing when the row predates the gap columns.
      const beforeGap =
        r.EXPECTATION_GAP !== null
          ? Number(r.EXPECTATION_GAP)
          : current
            ? computeExpectationGap(actual, current).expectationGap
            : null;
      const beforeGrade =
        r.STANDARD_GRADE ?? (beforeGap !== null ? gapToGrade(beforeGap) : null);

      return {
        employee_id: r.EMPLOYEE_ID,
        name: r.NAME,
        dept_name: r.DEPT_NAME,
        before_gap: beforeGap,
        after_gap: after.expectationGap,
        gap_delta: beforeGap === null ? null : Math.round((after.expectationGap - beforeGap) * 100) / 100,
        before_grade: beforeGrade,
        after_grade: afterGrade,
        grade_changed: beforeGrade !== null && beforeGrade !== afterGrade,
      };
    });

    const gradeChanges = changes.filter((c) => c.grade_changed);
    const distributionBefore: Record<string, number> = {};
    const distributionAfter: Record<string, number> = {};
    for (const c of changes) {
      if (c.before_grade) distributionBefore[c.before_grade] = (distributionBefore[c.before_grade] ?? 0) + 1;
      distributionAfter[c.after_grade] = (distributionAfter[c.after_grade] ?? 0) + 1;
    }

    return NextResponse.json({
      grade,
      affected_count: changes.length,
      grade_change_count: gradeChanges.length,
      distribution_before: distributionBefore,
      distribution_after: distributionAfter,
      // Biggest movers first — that is what a reviewer wants to eyeball
      changes: changes
        .sort((a, b) => Math.abs(b.gap_delta ?? 0) - Math.abs(a.gap_delta ?? 0))
        .slice(0, 100),
    });
  } catch (error) {
    console.error("Standards preview error:", error);
    return NextResponse.json({ error: "影響プレビューの計算に失敗しました" }, { status: 500 });
  }
}
