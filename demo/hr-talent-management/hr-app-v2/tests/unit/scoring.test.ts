import { describe, it, expect } from "vitest";
import {
  computeExpectationGap,
  gapToGrade,
  getNextGrade,
  assessPromotionReadiness,
  analyzeDistributionGap,
  validateWeights,
  validateTargetDistribution,
  weightSum,
  SCORE_AXES,
  type AxisScores,
  type GradeStandard,
} from "@/lib/scoring";

/** J3 新卒: low bar on leadership, weight tilted to growth/expertise */
const J3: GradeStandard = {
  growth: { expected: 3.0, weight: 0.35 },
  expertise: { expected: 2.0, weight: 0.30 },
  leadership: { expected: 1.5, weight: 0.05 },
  problem_solving: { expected: 2.0, weight: 0.15 },
  collaboration: { expected: 3.0, weight: 0.15 },
};

/** D2 部長: high bar on leadership, weight tilted to leadership/problem solving */
const D2: GradeStandard = {
  growth: { expected: 3.2, weight: 0.10 },
  expertise: { expected: 3.8, weight: 0.20 },
  leadership: { expected: 4.0, weight: 0.35 },
  problem_solving: { expected: 4.0, weight: 0.25 },
  collaboration: { expected: 3.5, weight: 0.10 },
};

/** S1 課長補佐 — used as the "next grade" when assessing an S2 */
const S1: GradeStandard = {
  growth: { expected: 3.5, weight: 0.15 },
  expertise: { expected: 3.3, weight: 0.25 },
  leadership: { expected: 3.0, weight: 0.25 },
  problem_solving: { expected: 3.3, weight: 0.20 },
  collaboration: { expected: 3.3, weight: 0.15 },
};

function scores(g: number, e: number, l: number, p: number, c: number): AxisScores {
  return { growth: g, expertise: e, leadership: l, problem_solving: p, collaboration: c };
}

describe("validateWeights", () => {
  it("accepts weights summing to 1.0", () => {
    expect(validateWeights(J3)).toBe(true);
    expect(validateWeights(D2)).toBe(true);
    expect(validateWeights(S1)).toBe(true);
  });

  it("rejects weights that do not sum to 1.0", () => {
    const bad: GradeStandard = { ...J3, growth: { expected: 3.0, weight: 0.5 } };
    expect(validateWeights(bad)).toBe(false);
  });

  it("reports the actual sum for UI feedback", () => {
    expect(weightSum(J3)).toBeCloseTo(1.0, 5);
  });
});

describe("computeExpectationGap — the same raw score means different things by grade", () => {
  it("treats leadership 2.0 as above expectation for a new graduate", () => {
    const r = computeExpectationGap(scores(3.0, 2.0, 2.0, 2.0, 3.0), J3);
    const leadership = r.perAxis.find((a) => a.axis === "leadership")!;
    expect(leadership.gap).toBeCloseTo(0.5, 5);
    expect(leadership.expected).toBe(1.5);
  });

  it("treats leadership 2.0 as far below expectation for a department head", () => {
    const r = computeExpectationGap(scores(3.2, 3.8, 2.0, 4.0, 3.5), D2);
    const leadership = r.perAxis.find((a) => a.axis === "leadership")!;
    expect(leadership.gap).toBeCloseTo(-2.0, 5);
    expect(leadership.expected).toBe(4.0);
  });

  it("returns a gap of 0 when every axis exactly meets expectation", () => {
    const r = computeExpectationGap(scores(3.0, 2.0, 1.5, 2.0, 3.0), J3);
    expect(r.expectationGap).toBe(0);
  });

  it("returns a gap of 0 for a department head meeting every expectation", () => {
    const r = computeExpectationGap(scores(3.2, 3.8, 4.0, 4.0, 3.5), D2);
    expect(r.expectationGap).toBe(0);
  });

  it("weights the gap, so a miss on a heavy axis hurts more", () => {
    // D2 leadership carries 35%; a -1.0 miss there is worth -0.35
    const heavyMiss = computeExpectationGap(scores(3.2, 3.8, 3.0, 4.0, 3.5), D2);
    // D2 collaboration carries 10%; the same -1.0 miss is worth -0.10
    const lightMiss = computeExpectationGap(scores(3.2, 3.8, 4.0, 4.0, 2.5), D2);
    expect(heavyMiss.expectationGap).toBeCloseTo(-0.35, 5);
    expect(lightMiss.expectationGap).toBeCloseTo(-0.1, 5);
    expect(heavyMiss.expectationGap).toBeLessThan(lightMiss.expectationGap);
  });

  it("makes the gap comparable across grades", () => {
    // A new grad and a dept head who each exceed their own bar by the same
    // weighted amount should land on the same expectation gap.
    const newGrad = computeExpectationGap(scores(4.0, 3.0, 2.5, 3.0, 4.0), J3);
    const deptHead = computeExpectationGap(scores(4.2, 4.8, 5.0, 5.0, 4.5), D2);
    expect(newGrad.expectationGap).toBeGreaterThan(0);
    expect(deptHead.expectationGap).toBeGreaterThan(0);
    // Both are "exceeding", which is the property we rely on for cross-grade ranking
    expect(gapToGrade(newGrad.expectationGap)).not.toBe("D");
    expect(gapToGrade(deptHead.expectationGap)).not.toBe("D");
  });

  it("reports compositeRaw as the plain mean, independent of weights", () => {
    const r = computeExpectationGap(scores(1.0, 2.0, 3.0, 4.0, 5.0), D2);
    expect(r.compositeRaw).toBe(3.0);
  });

  it("reports compositeWeighted as the weighted absolute score", () => {
    const r = computeExpectationGap(scores(4.0, 4.0, 4.0, 4.0, 4.0), D2);
    expect(r.compositeWeighted).toBe(4.0);
  });

  it("returns one entry per axis", () => {
    const r = computeExpectationGap(scores(3, 3, 3, 3, 3), J3);
    expect(r.perAxis).toHaveLength(SCORE_AXES.length);
  });

  it("keeps two decimals on the gap so close scores do not tie in rank", () => {
    // Two people who differ only slightly must not collapse to the same gap.
    const a = computeExpectationGap(scores(3.2, 3.8, 3.0, 4.0, 3.5), D2); // -0.35
    const b = computeExpectationGap(scores(3.2, 3.9, 3.0, 4.0, 3.5), D2); // -0.33
    expect(a.expectationGap).toBeCloseTo(-0.35, 5);
    expect(b.expectationGap).toBeCloseTo(-0.33, 5);
    expect(a.expectationGap).not.toBe(b.expectationGap);
  });

  it("handles the floor and ceiling of the raw scale", () => {
    const floor = computeExpectationGap(scores(1, 1, 1, 1, 1), D2);
    const ceiling = computeExpectationGap(scores(5, 5, 5, 5, 5), D2);
    expect(floor.expectationGap).toBeLessThan(0);
    expect(ceiling.expectationGap).toBeGreaterThan(0);
    expect(floor.compositeWeighted).toBe(1.0);
    expect(ceiling.compositeWeighted).toBe(5.0);
  });
});

describe("gapToGrade — boundaries", () => {
  it("maps the documented bands", () => {
    expect(gapToGrade(2.0)).toBe("S");
    expect(gapToGrade(0.7)).toBe("A");
    expect(gapToGrade(0.0)).toBe("B");
    expect(gapToGrade(-0.7)).toBe("C");
    expect(gapToGrade(-2.0)).toBe("D");
  });

  it("is inclusive at each lower bound", () => {
    expect(gapToGrade(1.0)).toBe("S");
    expect(gapToGrade(0.4)).toBe("A");
    expect(gapToGrade(-0.4)).toBe("B");
    expect(gapToGrade(-1.0)).toBe("C");
  });

  it("drops to the next band just below each bound", () => {
    expect(gapToGrade(0.99)).toBe("A");
    expect(gapToGrade(0.39)).toBe("B");
    expect(gapToGrade(-0.41)).toBe("C");
    expect(gapToGrade(-1.01)).toBe("D");
  });

  it("puts a gap of exactly 0 (met every expectation) in B", () => {
    expect(gapToGrade(0)).toBe("B");
  });
});

describe("getNextGrade", () => {
  it("moves one step up the ladder", () => {
    expect(getNextGrade("J3")).toBe("J2");
    expect(getNextGrade("S2")).toBe("S1");
    expect(getNextGrade("D1")).toBe("E1");
  });

  it("returns null at the top of the ladder", () => {
    expect(getNextGrade("E1")).toBeNull();
  });

  it("returns null for an unknown grade", () => {
    expect(getNextGrade("X9")).toBeNull();
    expect(getNextGrade("")).toBeNull();
  });
});

describe("assessPromotionReadiness", () => {
  it("returns ready when all five axes clear the next grade's bar", () => {
    const r = assessPromotionReadiness(scores(3.5, 3.5, 3.2, 3.5, 3.5), "S2", S1);
    expect(r.readiness).toBe("ready");
    expect(r.axesMet).toBe(5);
    expect(r.shortfalls).toHaveLength(0);
    expect(r.nextGrade).toBe("S1");
  });

  it("returns conditional with the shortfall listed when four axes clear", () => {
    // leadership 2.4 vs S1's 3.0
    const r = assessPromotionReadiness(scores(3.5, 3.8, 2.4, 3.4, 3.5), "S2", S1);
    expect(r.readiness).toBe("conditional");
    expect(r.axesMet).toBe(4);
    expect(r.shortfalls).toHaveLength(1);
    expect(r.shortfalls[0].axis).toBe("leadership");
    expect(r.shortfalls[0].required).toBe(3.0);
    expect(r.shortfalls[0].gap).toBeCloseTo(-0.6, 5);
  });

  it("returns not_ready when three or fewer axes clear", () => {
    const r = assessPromotionReadiness(scores(2.0, 2.0, 2.0, 3.5, 3.5), "S2", S1);
    expect(r.readiness).toBe("not_ready");
    expect(r.axesMet).toBe(2);
    expect(r.shortfalls).toHaveLength(3);
  });

  it("counts an exact match as meeting the bar", () => {
    const r = assessPromotionReadiness(scores(3.5, 3.3, 3.0, 3.3, 3.3), "S2", S1);
    expect(r.axesMet).toBe(5);
    expect(r.readiness).toBe("ready");
  });

  it("returns n_a at the top of the ladder", () => {
    const r = assessPromotionReadiness(scores(5, 5, 5, 5, 5), "E1", null);
    expect(r.readiness).toBe("n_a");
    expect(r.nextGrade).toBeNull();
  });

  it("returns n_a rather than not_ready when the next standard is missing", () => {
    const r = assessPromotionReadiness(scores(1, 1, 1, 1, 1), "S2", null);
    expect(r.readiness).toBe("n_a");
    expect(r.shortfalls).toHaveLength(0);
  });
});

describe("analyzeDistributionGap", () => {
  const target = { S: 0.05, A: 0.2, B: 0.5, C: 0.2, D: 0.05 };

  it("reports the per-grade delta against the target headcount", () => {
    const rows = analyzeDistributionGap({ S: 7, A: 20, B: 50, C: 20, D: 3 }, target, 100);
    const s = rows.find((r) => r.grade === "S")!;
    expect(s.targetCount).toBe(5);
    expect(s.actualCount).toBe(7);
    expect(s.delta).toBe(2); // two too many at S
  });

  it("uses a negative delta when a grade is under-filled", () => {
    const rows = analyzeDistributionGap({ S: 1, A: 20, B: 50, C: 20, D: 9 }, target, 100);
    expect(rows.find((r) => r.grade === "S")!.delta).toBe(-4);
  });

  it("keeps target counts summing to the total despite rounding", () => {
    const rows = analyzeDistributionGap({ S: 1, A: 2, B: 3, C: 1, D: 0 }, target, 7);
    const sum = rows.reduce((acc, r) => acc + r.targetCount, 0);
    expect(sum).toBe(7);
  });

  it("makes the deltas sum to zero when actual counts match the total", () => {
    const rows = analyzeDistributionGap({ S: 2, A: 1, B: 3, C: 1, D: 0 }, target, 7);
    const deltaSum = rows.reduce((acc, r) => acc + r.delta, 0);
    expect(deltaSum).toBe(0);
  });

  it("treats a missing grade in the actual counts as zero", () => {
    const rows = analyzeDistributionGap({ B: 100 }, target, 100);
    expect(rows.find((r) => r.grade === "S")!.actualCount).toBe(0);
    expect(rows.find((r) => r.grade === "S")!.delta).toBe(-5);
  });

  it("handles a zero total without dividing by zero", () => {
    const rows = analyzeDistributionGap({}, target, 0);
    expect(rows).toHaveLength(5);
    for (const r of rows) {
      expect(r.targetCount).toBe(0);
      expect(r.actualCount).toBe(0);
    }
  });

  it("returns an empty result for an empty target", () => {
    expect(analyzeDistributionGap({ B: 10 }, {}, 10)).toHaveLength(0);
  });
});

describe("validateTargetDistribution", () => {
  it("accepts ratios summing to 1.0", () => {
    expect(validateTargetDistribution({ S: 0.05, A: 0.2, B: 0.5, C: 0.2, D: 0.05 })).toBe(true);
  });

  it("rejects ratios that do not sum to 1.0", () => {
    expect(validateTargetDistribution({ S: 0.1, A: 0.2, B: 0.5, C: 0.2, D: 0.05 })).toBe(false);
    expect(validateTargetDistribution({})).toBe(false);
  });
});
