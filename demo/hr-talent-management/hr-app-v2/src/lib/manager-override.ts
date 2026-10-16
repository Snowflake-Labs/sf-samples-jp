import { AXIS_LABELS, SCORE_AXES, type AxisScores, type ScoreAxis } from "@/lib/scoring";

/**
 * Rules for a line manager correcting the AI's axis scores.
 *
 * The AI score is a starting point, not the answer: the manager knows things
 * the comment does not say. What we insist on is that every departure from
 * the AI is explained, so HR can audit it later.
 */

export const GRADE_STEPS = ["S", "A", "B", "C", "D"] as const;
/** How far a manager may move the final grade away from the recommendation. */
export const MAX_GRADE_STEPS_FROM_RECOMMENDED = 1;
export const MIN_REASON_LENGTH = 5;

export interface AxisInput {
  score: number;
  reason?: string | null;
}

export type AxisInputs = Partial<Record<ScoreAxis, AxisInput>>;

export function gradeDistance(a: string, b: string): number {
  const ia = GRADE_STEPS.indexOf(a as (typeof GRADE_STEPS)[number]);
  const ib = GRADE_STEPS.indexOf(b as (typeof GRADE_STEPS)[number]);
  if (ia < 0 || ib < 0) return Infinity;
  return Math.abs(ia - ib);
}

/** The grades a manager may choose, given the recommendation. */
export function allowedGrades(recommended: string): string[] {
  return GRADE_STEPS.filter((g) => gradeDistance(g, recommended) <= MAX_GRADE_STEPS_FROM_RECOMMENDED);
}

/**
 * Merge the AI scores with the manager's inputs.
 * Returns the effective scores and the list of axes the manager changed,
 * or the first validation error in Japanese (shown to the user as-is).
 */
export function applyAxisInputs(
  ai: AxisScores,
  inputs: AxisInputs
): { ok: true; effective: AxisScores; changed: ScoreAxis[] } | { ok: false; error: string } {
  const effective = { ...ai };
  const changed: ScoreAxis[] = [];
  for (const axis of SCORE_AXES) {
    const input = inputs[axis];
    if (!input) continue;
    const s = Number(input.score);
    if (!Number.isInteger(s) || s < 1 || s > 5) {
      return { ok: false, error: `${axisLabel(axis)}は 1〜5 の整数で入力してください` };
    }
    if (s !== ai[axis]) {
      if (!input.reason || input.reason.trim().length < MIN_REASON_LENGTH) {
        return {
          ok: false,
          error: `${axisLabel(axis)}を AI の ${ai[axis]} から ${s} に変えた理由を${MIN_REASON_LENGTH}文字以上で入力してください`,
        };
      }
      changed.push(axis);
    }
    effective[axis] = s;
  }
  return { ok: true, effective, changed };
}

/** Final grade must stay within one step of the recommendation, and moving it needs a reason. */
export function validateFinalGrade(
  finalGrade: string,
  recommended: string,
  reason?: string | null
): string | null {
  if (!GRADE_STEPS.includes(finalGrade as (typeof GRADE_STEPS)[number])) {
    return "グレードは S/A/B/C/D から選んでください";
  }
  const d = gradeDistance(finalGrade, recommended);
  if (d > MAX_GRADE_STEPS_FROM_RECOMMENDED) {
    return `推奨グレード ${recommended} から変えられるのは${MAX_GRADE_STEPS_FROM_RECOMMENDED}段階までです。それ以上は軸のスコアを見直してください`;
  }
  if (d > 0 && (!reason || reason.trim().length < MIN_REASON_LENGTH)) {
    return `推奨 ${recommended} から ${finalGrade} に変える理由を${MIN_REASON_LENGTH}文字以上で入力してください`;
  }
  return null;
}

function axisLabel(a: ScoreAxis): string {
  return AXIS_LABELS[a];
}
