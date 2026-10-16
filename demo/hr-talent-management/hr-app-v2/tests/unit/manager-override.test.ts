import { describe, expect, it } from "vitest";
import { allowedGrades, applyAxisInputs, validateFinalGrade } from "@/lib/manager-override";

const ai = { growth: 3, expertise: 4, leadership: 2, problem_solving: 3, collaboration: 3 };

describe("applyAxisInputs", () => {
  it("accepts the AI as-is without any reason", () => {
    const r = applyAxisInputs(ai, {});
    expect(r.ok && r.changed).toEqual([]);
    expect(r.ok && r.effective).toEqual(ai);
  });
  it("does not ask for a reason when the score equals the AI", () => {
    const r = applyAxisInputs(ai, { leadership: { score: 2 } });
    expect(r.ok && r.changed).toEqual([]);
  });
  it("requires a reason for a changed axis", () => {
    const r = applyAxisInputs(ai, { leadership: { score: 4, reason: "" } });
    expect(r.ok).toBe(false);
    expect(!r.ok && r.error).toContain("リーダーシップ");
  });
  it("applies a changed axis with a reason", () => {
    const r = applyAxisInputs(ai, { leadership: { score: 4, reason: "後輩2名のOJTを担当" } });
    expect(r.ok && r.effective.leadership).toBe(4);
    expect(r.ok && r.changed).toEqual(["leadership"]);
  });
  it("rejects out-of-range and fractional scores", () => {
    expect(applyAxisInputs(ai, { growth: { score: 6, reason: "理由があります" } }).ok).toBe(false);
    expect(applyAxisInputs(ai, { growth: { score: 0, reason: "理由があります" } }).ok).toBe(false);
    expect(applyAxisInputs(ai, { growth: { score: 3.5, reason: "理由があります" } }).ok).toBe(false);
  });
});

describe("validateFinalGrade", () => {
  it("allows the recommendation without a reason", () => {
    expect(validateFinalGrade("B", "B")).toBeNull();
  });
  it("allows one step with a reason", () => {
    expect(validateFinalGrade("A", "B", "期中の大型案件を完遂")).toBeNull();
    expect(validateFinalGrade("A", "B", "")).not.toBeNull();
  });
  it("rejects two steps", () => {
    expect(validateFinalGrade("S", "B", "理由があります")).toContain("1段階まで");
  });
  it("lists the allowed grades around the recommendation", () => {
    expect(allowedGrades("B")).toEqual(["A", "B", "C"]);
    expect(allowedGrades("S")).toEqual(["S", "A"]);
    expect(allowedGrades("D")).toEqual(["C", "D"]);
  });
});
