import { pgQuery } from "@/lib/postgres";
import { loadStandards } from "@/lib/recalculate";
import { SCORE_AXES, type AxisScores, type GradeStandard, type ScoreAxis } from "@/lib/scoring";
import type { SessionUser } from "@/lib/types";

/**
 * Data access for the line manager's "マイチーム評価".
 *
 * Scope is the evaluator on the evaluation row, not employees.manager_id:
 * in this data set manager_id points at department heads with 50–150
 * reports, while evaluator_id is the person who actually writes the review.
 */

/** Submission deadline per period (shown on the team list). */
export const EVAL_DEADLINES: Record<string, string> = {
  "2025-H2": "2026-10-02",
};
export const CURRENT_PERIOD = "2025-H2";

import type { Progress } from "@/lib/my-team-ui";
export type { Progress };

export function deriveProgress(r: {
  STATUS: string | null;
  COMMENT: string | null;
  AI_SCORED: boolean;
  RETURN_REASON: string | null;
}): Progress {
  if (r.STATUS === "completed" || r.STATUS === "confirmed") return "completed";
  if (r.STATUS === "submitted") return "submitted";
  if (r.RETURN_REASON) return "returned";
  if (r.AI_SCORED) return "ai_scored";
  if (r.COMMENT && r.COMMENT.trim()) return "draft";
  return "not_started";
}

export function isEditable(p: Progress): boolean {
  return p !== "submitted" && p !== "completed";
}

export interface OwnEvaluation {
  EVALUATION_ID: number;
  EMPLOYEE_ID: number;
  EVALUATOR_ID: number;
  PERIOD: string;
  STATUS: string;
  COMMENT: string | null;
  SELF_COMMENT: string | null;
  SELF_SCORE: string | null;
  GRADE: string | null;
  GRADE_REASON: string | null;
  RETURN_REASON: string | null;
  RETURNED_AT: string | null;
  SUBMITTED_AT: string | null;
  NAME: string;
  EMPLOYEE_CODE: string;
  POSITION_GRADE: string;
  POSITION_TITLE: string;
  DEPT_NAME: string | null;
  AI_SCORED: boolean;
}

/**
 * Load an evaluation the manager is allowed to touch.
 * Returns null both when it does not exist and when it belongs to someone
 * else's team, so the API cannot be used to probe other teams.
 */
export async function loadOwnEvaluation(user: SessionUser, evaluationId: number): Promise<OwnEvaluation | null> {
  const rows = await pgQuery<OwnEvaluation>(
    `SELECT ev.evaluation_id AS "EVALUATION_ID", ev.employee_id AS "EMPLOYEE_ID",
       ev.evaluator_id AS "EVALUATOR_ID", ev.period AS "PERIOD", ev.status AS "STATUS",
       ev.comment AS "COMMENT", ev.self_comment AS "SELF_COMMENT", ev.self_score AS "SELF_SCORE",
       ev.grade AS "GRADE", ev.grade_reason AS "GRADE_REASON",
       ev.return_reason AS "RETURN_REASON", ev.returned_at AS "RETURNED_AT", ev.submitted_at AS "SUBMITTED_AT",
       e.last_name || e.first_name AS "NAME", e.employee_code AS "EMPLOYEE_CODE",
       p.grade AS "POSITION_GRADE", p.title AS "POSITION_TITLE", d.dept_name AS "DEPT_NAME",
       (eqs.evaluation_id IS NOT NULL) AS "AI_SCORED"
     FROM hr.evaluations ev
     JOIN hr.employees e ON ev.employee_id = e.employee_id
     JOIN hr.positions p ON e.position_id = p.position_id
     LEFT JOIN hr.departments d ON e.dept_id = d.dept_id
     LEFT JOIN hr.eval_quantified_scores eqs ON eqs.evaluation_id = ev.evaluation_id
     WHERE ev.evaluation_id = $1 AND ev.evaluator_id = $2`,
    [evaluationId, user.employeeId]
  );
  return rows[0] ?? null;
}

export interface AxisView {
  axis: ScoreAxis;
  ai: number | null;
  effective: number | null;
  reason: string | null;
  aiChanged: boolean;
}

/** The AI's number and the effective number per axis, side by side. */
export async function loadAxes(evaluationId: number): Promise<{
  axes: AxisView[];
  reasoning: string | null;
  aiRecommended: string | null;
  standardGrade: string | null;
  expectationGap: number | null;
  /** The comment the AI actually read. If the manager has since edited it, the scores are stale. */
  aiInputComment: string | null;
}> {
  const [eqs] = await pgQuery<Record<string, string | null>>(
    `SELECT growth_score, expertise_score, leadership_score, problem_solving_score, collaboration_score,
       ai_reasoning, ai_recommended_grade, standard_grade, expectation_gap, ai_input_comment
     FROM hr.eval_quantified_scores WHERE evaluation_id = $1`,
    [evaluationId]
  );
  const overrides = await pgQuery<{ AXIS: ScoreAxis; AI_SCORE: string | null; MANAGER_SCORE: string; REASON: string; AI_CHANGED: boolean }>(
    `SELECT axis AS "AXIS", ai_score AS "AI_SCORE", manager_score AS "MANAGER_SCORE",
       reason AS "REASON", ai_changed AS "AI_CHANGED"
     FROM hr.eval_axis_overrides WHERE evaluation_id = $1`,
    [evaluationId]
  );
  const byAxis = new Map(overrides.map((o) => [o.AXIS, o]));
  const axes = SCORE_AXES.map((axis) => {
    const eff = eqs ? Number(eqs[`${axis}_score`]) : null;
    const o = byAxis.get(axis);
    return {
      axis,
      ai: o ? (o.AI_SCORE === null ? null : Number(o.AI_SCORE)) : eff,
      effective: eff,
      reason: o?.REASON ?? null,
      aiChanged: o?.AI_CHANGED ?? false,
    };
  });
  return {
    axes,
    reasoning: eqs?.ai_reasoning ?? null,
    aiRecommended: eqs?.ai_recommended_grade ?? null,
    standardGrade: eqs?.standard_grade ?? null,
    expectationGap: eqs?.expectation_gap === null || eqs?.expectation_gap === undefined ? null : Number(eqs.expectation_gap),
    aiInputComment: eqs?.ai_input_comment ?? null,
  };
}

export function aiScoresOf(axes: AxisView[]): AxisScores | null {
  if (axes.some((a) => a.ai === null)) return null;
  return Object.fromEntries(axes.map((a) => [a.axis, a.ai as number])) as AxisScores;
}

export async function standardFor(grade: string): Promise<GradeStandard | null> {
  const all = await loadStandards();
  return all.get(grade) ?? null;
}
