import { pgQuery } from "@/lib/postgres";
import {
  computeExpectationGap,
  gapToGrade,
  getNextGrade,
  assessPromotionReadiness,
  type AxisScores,
  type GradeStandard,
} from "@/lib/scoring";

/**
 * Recompute expectation gaps from the raw scores already in the table.
 *
 * The LLM scores on an absolute scale, so they do not depend on the
 * standard. Changing a grade standard therefore only changes the
 * comparison, not the scoring — this endpoint replays the comparison
 * without spending a single Cortex call.
 */

interface ScoreRow {
  ID: number;
  EVALUATION_ID: number;
  PERIOD: string;
  GROWTH_SCORE: number;
  EXPERTISE_SCORE: number;
  LEADERSHIP_SCORE: number;
  PROBLEM_SOLVING_SCORE: number;
  COLLABORATION_SCORE: number;
  POSITION_GRADE: string;
}

interface StandardRow {
  GRADE: string;
  GROWTH_EXPECTED: string;
  GROWTH_WEIGHT: string;
  EXPERTISE_EXPECTED: string;
  EXPERTISE_WEIGHT: string;
  LEADERSHIP_EXPECTED: string;
  LEADERSHIP_WEIGHT: string;
  PROBLEM_SOLVING_EXPECTED: string;
  PROBLEM_SOLVING_WEIGHT: string;
  COLLABORATION_EXPECTED: string;
  COLLABORATION_WEIGHT: string;
}

function rowToStandard(r: StandardRow): GradeStandard {
  return {
    growth: { expected: Number(r.GROWTH_EXPECTED), weight: Number(r.GROWTH_WEIGHT) },
    expertise: { expected: Number(r.EXPERTISE_EXPECTED), weight: Number(r.EXPERTISE_WEIGHT) },
    leadership: { expected: Number(r.LEADERSHIP_EXPECTED), weight: Number(r.LEADERSHIP_WEIGHT) },
    problem_solving: {
      expected: Number(r.PROBLEM_SOLVING_EXPECTED),
      weight: Number(r.PROBLEM_SOLVING_WEIGHT),
    },
    collaboration: {
      expected: Number(r.COLLABORATION_EXPECTED),
      weight: Number(r.COLLABORATION_WEIGHT),
    },
  };
}

export async function loadStandards(): Promise<Map<string, GradeStandard>> {
  const rows = await pgQuery<StandardRow>(
    `SELECT grade AS "GRADE",
      growth_expected AS "GROWTH_EXPECTED", growth_weight AS "GROWTH_WEIGHT",
      expertise_expected AS "EXPERTISE_EXPECTED", expertise_weight AS "EXPERTISE_WEIGHT",
      leadership_expected AS "LEADERSHIP_EXPECTED", leadership_weight AS "LEADERSHIP_WEIGHT",
      problem_solving_expected AS "PROBLEM_SOLVING_EXPECTED", problem_solving_weight AS "PROBLEM_SOLVING_WEIGHT",
      collaboration_expected AS "COLLABORATION_EXPECTED", collaboration_weight AS "COLLABORATION_WEIGHT"
     FROM hr.grade_score_standards`
  );
  return new Map(rows.map((r) => [r.GRADE, rowToStandard(r)]));
}

/**
 * Recompute gaps for one period (or every period when `period` is null).
 * Exported so the standards-master API can call it after a change.
 */
export async function recalculatePeriod(period: string | null): Promise<{
  updated: number;
  skipped: number;
  periods: string[];
}> {
  const standards = await loadStandards();

  const rows = await pgQuery<ScoreRow>(
    `SELECT eqs.id AS "ID", eqs.evaluation_id AS "EVALUATION_ID", eqs.period AS "PERIOD",
       eqs.growth_score AS "GROWTH_SCORE", eqs.expertise_score AS "EXPERTISE_SCORE",
       eqs.leadership_score AS "LEADERSHIP_SCORE", eqs.problem_solving_score AS "PROBLEM_SOLVING_SCORE",
       eqs.collaboration_score AS "COLLABORATION_SCORE", pos.grade AS "POSITION_GRADE"
     FROM hr.eval_quantified_scores eqs
     JOIN hr.employees e ON eqs.employee_id = e.employee_id
     JOIN hr.positions pos ON e.position_id = pos.position_id
     WHERE ($1::text IS NULL OR eqs.period = $1)
       AND eqs.growth_score IS NOT NULL`,
    [period]
  );

  let updated = 0;
  let skipped = 0;

  for (const r of rows) {
    const standard = standards.get(r.POSITION_GRADE);
    if (!standard) {
      skipped++;
      continue;
    }

    const actual: AxisScores = {
      growth: Number(r.GROWTH_SCORE),
      expertise: Number(r.EXPERTISE_SCORE),
      leadership: Number(r.LEADERSHIP_SCORE),
      problem_solving: Number(r.PROBLEM_SOLVING_SCORE),
      collaboration: Number(r.COLLABORATION_SCORE),
    };

    const expectation = computeExpectationGap(actual, standard);
    const stdGrade = gapToGrade(expectation.expectationGap);
    const nextGrade = getNextGrade(r.POSITION_GRADE);
    const nextStandard = nextGrade ? standards.get(nextGrade) ?? null : null;
    const promotion = assessPromotionReadiness(actual, r.POSITION_GRADE, nextStandard);

    await pgQuery(
      `UPDATE hr.eval_quantified_scores SET
         composite_score = $2, composite_raw = $3, expectation_gap = $4, standard_grade = $5,
         next_grade = $6, next_grade_axes_met = $7, promotion_readiness = $8,
         promotion_shortfalls = $9, ai_recommended_grade = $5, updated_at = NOW()
       WHERE id = $1`,
      [
        r.ID,
        expectation.compositeWeighted,
        expectation.compositeRaw,
        expectation.expectationGap,
        stdGrade,
        promotion.nextGrade,
        promotion.axesMet,
        promotion.readiness,
        JSON.stringify(promotion.shortfalls),
      ]
    );
    updated++;
  }

  // Re-rank every period we touched
  const periods = [...new Set(rows.map((r) => r.PERIOD))];
  for (const p of periods) {
    await pgQuery(
      `WITH ranked AS (
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
       FROM ranked WHERE eval_quantified_scores.id = ranked.id`,
      [p]
    );
  }

  return { updated, skipped, periods };
}

/** Re-rank one period: department rank and grade rank on the (manual or) expectation gap. */
export async function rerankPeriod(period: string): Promise<void> {
  await pgQuery(
    `WITH ranked AS (
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
     FROM ranked WHERE eval_quantified_scores.id = ranked.id`,
    [period]
  );
}

export interface SaveScoresInput {
  evaluationId: number;
  employeeId: number;
  period: string;
  positionGrade: string;
  /** What the AI said. Stored on override rows so the audit trail keeps it. */
  ai: AxisScores | null;
  /** The scores that count (AI unless a manager corrected an axis). */
  effective: AxisScores;
  reasoning?: string | null;
  modelVersion?: string | null;
}

/**
 * Write the effective axis scores and everything derived from them.
 *
 * The five *_score columns always hold the effective value, so every
 * downstream screen (cross review, calibration, promotion, re-ranking,
 * standards recalculation) sees the manager's correction without changing.
 * The AI's own number lives on hr.eval_axis_overrides.ai_score.
 */
export async function saveScores(
  input: SaveScoresInput,
  standards?: Map<string, GradeStandard>
): Promise<{ expectationGap: number | null; standardGrade: string | null }> {
  const std = standards ?? (await loadStandards());
  const standard = std.get(input.positionGrade) ?? null;
  const actual = input.effective;
  const expectation = standard ? computeExpectationGap(actual, standard) : null;
  const nextGrade = getNextGrade(input.positionGrade);
  const nextStandard = nextGrade ? std.get(nextGrade) ?? null : null;
  const promotion = assessPromotionReadiness(actual, input.positionGrade, nextStandard);
  const raw = Math.round((Object.values(actual).reduce((a, b) => a + b, 0) / 5) * 10) / 10;
  const gap = expectation ? expectation.expectationGap : null;
  const stdGrade = gap === null ? null : gapToGrade(gap);

  // ai_recommended_grade is what the AI's own scores imply, kept apart from
  // standard_grade (which follows the effective scores).
  let aiGrade: string | null = stdGrade;
  if (input.ai && standard) aiGrade = gapToGrade(computeExpectationGap(input.ai, standard).expectationGap);

  await pgQuery(
    `INSERT INTO hr.eval_quantified_scores
       (evaluation_id, employee_id, period,
        growth_score, expertise_score, leadership_score, problem_solving_score, collaboration_score,
        composite_score, composite_raw, expectation_gap, standard_grade,
        next_grade, next_grade_axes_met, promotion_readiness, promotion_shortfalls,
        ai_recommended_grade, ai_reasoning, model_version)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19)
     ON CONFLICT (evaluation_id) DO UPDATE SET
       growth_score = EXCLUDED.growth_score, expertise_score = EXCLUDED.expertise_score,
       leadership_score = EXCLUDED.leadership_score, problem_solving_score = EXCLUDED.problem_solving_score,
       collaboration_score = EXCLUDED.collaboration_score, composite_score = EXCLUDED.composite_score,
       composite_raw = EXCLUDED.composite_raw, expectation_gap = EXCLUDED.expectation_gap,
       standard_grade = EXCLUDED.standard_grade, next_grade = EXCLUDED.next_grade,
       next_grade_axes_met = EXCLUDED.next_grade_axes_met,
       promotion_readiness = EXCLUDED.promotion_readiness,
       promotion_shortfalls = EXCLUDED.promotion_shortfalls,
       ai_recommended_grade = EXCLUDED.ai_recommended_grade,
       ai_reasoning = COALESCE(EXCLUDED.ai_reasoning, hr.eval_quantified_scores.ai_reasoning),
       model_version = COALESCE(EXCLUDED.model_version, hr.eval_quantified_scores.model_version),
       updated_at = NOW()`,
    [
      input.evaluationId, input.employeeId, input.period,
      actual.growth, actual.expertise, actual.leadership, actual.problem_solving, actual.collaboration,
      expectation ? expectation.compositeWeighted : raw, raw, gap, stdGrade,
      promotion.nextGrade, promotion.axesMet, promotion.readiness, JSON.stringify(promotion.shortfalls),
      aiGrade, input.reasoning ?? null, input.modelVersion ?? null,
    ]
  );
  return { expectationGap: gap, standardGrade: stdGrade };
}

/**
 * Merge a fresh AI result with any manager overrides already on file.
 * Overridden axes keep the manager's score; if the AI's number moved,
 * the override is flagged so the manager can take another look.
 */
export async function mergeWithOverrides(
  evaluationId: number,
  ai: AxisScores
): Promise<AxisScores> {
  const rows = await pgQuery<{ AXIS: string; MANAGER_SCORE: string; AI_SCORE: string | null }>(
    `SELECT axis AS "AXIS", manager_score AS "MANAGER_SCORE", ai_score AS "AI_SCORE"
     FROM hr.eval_axis_overrides WHERE evaluation_id = $1`,
    [evaluationId]
  );
  const effective = { ...ai };
  for (const r of rows) {
    const axis = r.AXIS as keyof AxisScores;
    const newAi = ai[axis];
    // The AI now agrees with the manager: nothing left to explain, so drop the override.
    if (Number(r.MANAGER_SCORE) === newAi) {
      await pgQuery(`DELETE FROM hr.eval_axis_overrides WHERE evaluation_id = $1 AND axis = $2`, [evaluationId, axis]);
      continue;
    }
    effective[axis] = Number(r.MANAGER_SCORE);
    if (r.AI_SCORE === null || Number(r.AI_SCORE) !== newAi) {
      await pgQuery(
        `UPDATE hr.eval_axis_overrides SET ai_score = $3, ai_changed = true
         WHERE evaluation_id = $1 AND axis = $2`,
        [evaluationId, axis, newAi]
      );
    }
  }
  return effective;
}
