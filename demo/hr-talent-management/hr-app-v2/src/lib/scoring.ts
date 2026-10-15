import { GRADE_ORDER } from "@/lib/types";

/**
 * Expectation-based scoring.
 *
 * The LLM scores each axis 1-5 on a single company-wide absolute scale.
 * What "good" means then depends on the employee's grade: a 2.0 on
 * leadership is above expectation for a new graduate and far below it
 * for a department head. So the ranking metric is not the raw score but
 * the weighted gap between the raw score and the level expected at that
 * grade.
 *
 *   gap_i  = actual_i - expected_i        (per axis, -4 .. +4)
 *   overall = Σ (weight_i × gap_i)        (0 means "met every expectation")
 *
 * Because the gap is relative to each grade's own bar, it is comparable
 * across grades: a new graduate at +1.0 and a department head at +1.0
 * both exceeded their level's expectation by the same amount.
 */

export const SCORE_AXES = [
  "growth",
  "expertise",
  "leadership",
  "problem_solving",
  "collaboration",
] as const;

export type ScoreAxis = (typeof SCORE_AXES)[number];

export const AXIS_LABELS: Record<ScoreAxis, string> = {
  growth: "成長性",
  expertise: "専門性",
  leadership: "リーダーシップ",
  problem_solving: "課題解決力",
  collaboration: "協調性",
};

/** Raw 1-5 scores produced by the LLM, on the absolute company-wide scale. */
export type AxisScores = Record<ScoreAxis, number>;

/** Expected level and weight for one axis at one grade. */
export interface AxisStandard {
  expected: number;
  weight: number;
}

/** The full standard for one grade: expected level + weight per axis. */
export type GradeStandard = Record<ScoreAxis, AxisStandard>;

export const WEIGHT_SUM_EPSILON = 0.001;

/** Grade boundaries on the weighted expectation gap. */
export const GAP_GRADE_THRESHOLDS: { min: number; grade: string; label: string }[] = [
  { min: 1.0, grade: "S", label: "期待を大きく超える" },
  { min: 0.4, grade: "A", label: "期待を超える" },
  { min: -0.4, grade: "B", label: "期待通り" },
  { min: -1.0, grade: "C", label: "期待をやや下回る" },
  { min: -Infinity, grade: "D", label: "期待を大きく下回る" },
];

function round1(n: number): number {
  return Math.round(n * 10) / 10;
}

/**
 * The expectation gap is the ranking metric, so it keeps two decimals.
 * Rounding it to one decimal would collapse genuinely different people
 * into the same rank (e.g. -0.34 and -0.35 both becoming -0.3).
 */
function round2(n: number): number {
  return Math.round(n * 100) / 100;
}

/**
 * True when the five weights sum to 1.0 (within epsilon).
 * Mirrors the DB CHECK constraint so the UI can validate before saving.
 */
export function validateWeights(standard: GradeStandard): boolean {
  const sum = SCORE_AXES.reduce((acc, axis) => acc + standard[axis].weight, 0);
  return Math.abs(sum - 1.0) < WEIGHT_SUM_EPSILON;
}

export function weightSum(standard: GradeStandard): number {
  return SCORE_AXES.reduce((acc, axis) => acc + standard[axis].weight, 0);
}

export interface AxisGap {
  axis: ScoreAxis;
  actual: number;
  expected: number;
  gap: number;
  weight: number;
  weightedGap: number;
}

export interface ExpectationResult {
  /** Σ(weight × (actual - expected)). 0 means every expectation was met. Two decimals: this drives ranking. */
  expectationGap: number;
  /** Σ(weight × actual). Weighted absolute score, still on a 1-5 scale. */
  compositeWeighted: number;
  /** Plain mean of the five raw scores. Kept for reference/audit. */
  compositeRaw: number;
  perAxis: AxisGap[];
}

/**
 * Compute the weighted expectation gap plus the supporting per-axis detail.
 */
export function computeExpectationGap(
  actual: AxisScores,
  standard: GradeStandard
): ExpectationResult {
  const perAxis: AxisGap[] = SCORE_AXES.map((axis) => {
    const a = actual[axis];
    const { expected, weight } = standard[axis];
    const gap = a - expected;
    return { axis, actual: a, expected, gap, weight, weightedGap: gap * weight };
  });

  const expectationGap = perAxis.reduce((acc, x) => acc + x.weightedGap, 0);
  const compositeWeighted = perAxis.reduce((acc, x) => acc + x.actual * x.weight, 0);
  const compositeRaw = SCORE_AXES.reduce((acc, axis) => acc + actual[axis], 0) / SCORE_AXES.length;

  return {
    expectationGap: round2(expectationGap),
    compositeWeighted: round1(compositeWeighted),
    compositeRaw: round1(compositeRaw),
    perAxis,
  };
}

/**
 * Map a weighted expectation gap onto S/A/B/C/D.
 * Grades describe performance against the grade's own bar, not raw ability.
 */
export function gapToGrade(gap: number): string {
  for (const t of GAP_GRADE_THRESHOLDS) {
    if (gap >= t.min) return t.grade;
  }
  return "D";
}

export function gapToLabel(gap: number): string {
  for (const t of GAP_GRADE_THRESHOLDS) {
    if (gap >= t.min) return t.label;
  }
  return GAP_GRADE_THRESHOLDS[GAP_GRADE_THRESHOLDS.length - 1].label;
}

/**
 * The grade one step up. GRADE_ORDER runs senior-to-junior
 * (E1 .. J3), so promotion moves toward index 0.
 * Returns null at the top of the ladder or for an unknown grade.
 */
export function getNextGrade(grade: string): string | null {
  const idx = GRADE_ORDER.indexOf(grade);
  if (idx <= 0) return null; // unknown (-1) or already top (0)
  return GRADE_ORDER[idx - 1];
}

export type PromotionReadiness = "ready" | "conditional" | "not_ready" | "n_a";

export interface PromotionShortfall {
  axis: ScoreAxis;
  actual: number;
  required: number;
  gap: number;
}

export interface PromotionAssessment {
  nextGrade: string | null;
  readiness: PromotionReadiness;
  axesMet: number;
  axesTotal: number;
  shortfalls: PromotionShortfall[];
}

/**
 * Judge readiness for the next grade by testing the raw scores against
 * the *next* grade's expected levels.
 *
 *   5/5 axes met -> ready
 *   4/5 axes met -> conditional (shortfall is listed)
 *   <=3/5        -> not_ready
 *
 * Returns n_a at the top of the ladder, or when the next grade has no
 * standard configured (so a missing row never reads as "not ready").
 */
export function assessPromotionReadiness(
  actual: AxisScores,
  currentGrade: string,
  nextStandard: GradeStandard | null
): PromotionAssessment {
  const nextGrade = getNextGrade(currentGrade);

  if (!nextGrade || !nextStandard) {
    return {
      nextGrade,
      readiness: "n_a",
      axesMet: 0,
      axesTotal: SCORE_AXES.length,
      shortfalls: [],
    };
  }

  const shortfalls: PromotionShortfall[] = [];
  let axesMet = 0;

  for (const axis of SCORE_AXES) {
    const a = actual[axis];
    const required = nextStandard[axis].expected;
    if (a >= required) {
      axesMet++;
    } else {
      shortfalls.push({ axis, actual: a, required, gap: round2(a - required) });
    }
  }

  let readiness: PromotionReadiness;
  if (axesMet === SCORE_AXES.length) readiness = "ready";
  else if (axesMet === SCORE_AXES.length - 1) readiness = "conditional";
  else readiness = "not_ready";

  return { nextGrade, readiness, axesMet, axesTotal: SCORE_AXES.length, shortfalls };
}

export const READINESS_LABELS: Record<PromotionReadiness, string> = {
  ready: "昇格可",
  conditional: "条件付き",
  not_ready: "時期尚早",
  n_a: "対象外",
};

export interface DistributionGapRow {
  grade: string;
  targetRatio: number;
  targetCount: number;
  actualCount: number;
  /** actualCount - targetCount. Positive means too many at this grade. */
  delta: number;
}

/**
 * Compare an actual grade distribution against the calibration target.
 *
 * Target counts are rounded to whole people and then the largest bucket
 * absorbs any rounding drift, so the target counts always sum to `total`
 * and the deltas sum to zero.
 */
export function analyzeDistributionGap(
  actual: Record<string, number>,
  target: Record<string, number>,
  total: number
): DistributionGapRow[] {
  const grades = Object.keys(target);
  if (grades.length === 0 || total <= 0) {
    return grades.map((grade) => ({
      grade,
      targetRatio: target[grade] ?? 0,
      targetCount: 0,
      actualCount: actual[grade] ?? 0,
      delta: actual[grade] ?? 0,
    }));
  }

  const rows: DistributionGapRow[] = grades.map((grade) => {
    const targetRatio = target[grade] ?? 0;
    return {
      grade,
      targetRatio,
      targetCount: Math.round(targetRatio * total),
      actualCount: actual[grade] ?? 0,
      delta: 0,
    };
  });

  // Push rounding error into the biggest bucket so targets sum to `total`
  const sum = rows.reduce((acc, r) => acc + r.targetCount, 0);
  const drift = total - sum;
  if (drift !== 0) {
    const biggest = rows.reduce((a, b) => (b.targetCount > a.targetCount ? b : a), rows[0]);
    biggest.targetCount += drift;
  }

  for (const r of rows) {
    r.delta = r.actualCount - r.targetCount;
  }

  return rows;
}

/** True when the target ratios sum to 1.0 (within epsilon). */
export function validateTargetDistribution(target: Record<string, number>): boolean {
  const sum = Object.values(target).reduce((a, b) => a + b, 0);
  return Math.abs(sum - 1.0) < WEIGHT_SUM_EPSILON;
}
