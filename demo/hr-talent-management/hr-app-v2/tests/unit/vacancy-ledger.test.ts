import { describe, it, expect } from "vitest";
import { buildVacancyLedger, buildChains, type LedgerAction } from "@/lib/vacancy-ledger";

let n = 0;
function act(p: Partial<LedgerAction> & Pick<LedgerAction, "type" | "employeeName" | "fromDeptId" | "fromGrade">): LedgerAction {
  n++;
  return {
    id: `a${n}`,
    employeeId: n,
    fromDeptName: `部${p.fromDeptId}`,
    ...p,
  } as LedgerAction;
}

describe("buildVacancyLedger", () => {
  it("opens a slot when someone retires", () => {
    const r = buildVacancyLedger([act({ type: "retire", employeeName: "田中", fromDeptId: 10, fromGrade: "M1" })], []);
    expect(r.open).toHaveLength(1);
    expect(r.open[0]).toMatchObject({ deptId: 10, grade: "M1", source: "generated" });
  });

  it("closes the slot once someone moves into it", () => {
    const r = buildVacancyLedger([
      act({ type: "retire", employeeName: "田中", fromDeptId: 10, fromGrade: "M1" }),
      act({ type: "transfer", employeeName: "佐藤", fromDeptId: 20, fromGrade: "M1", toDeptId: 10, toGrade: "M1" }),
    ], []);
    // 田中's seat is filled; 佐藤's old seat in dept 20 is now the only open one
    expect(r.open).toHaveLength(1);
    expect(r.open[0]).toMatchObject({ deptId: 20, grade: "M1" });
    expect(r.filled[0].filledByName).toBe("佐藤");
  });

  it("reports a second fill of the same slot as over plan instead of reusing it (the reported bug)", () => {
    const r = buildVacancyLedger([
      act({ type: "retire", employeeName: "田中", fromDeptId: 10, fromGrade: "M1" }),
      act({ type: "transfer", employeeName: "佐藤", fromDeptId: 20, fromGrade: "M1", toDeptId: 10, toGrade: "M1" }),
      act({ type: "transfer", employeeName: "鈴木", fromDeptId: 30, fromGrade: "M1", toDeptId: 10, toGrade: "M1" }),
    ], []);
    expect(r.overfills).toHaveLength(1);
    expect(r.overfills[0].employeeName).toBe("鈴木");
    expect(r.open.some((s) => s.deptId === 10)).toBe(false);
  });

  it("consumes a pre-existing DB vacancy exactly once", () => {
    const existing = [{ positionId: 99, title: "営業課長", deptId: 10, deptName: "営業部", grade: "M1" }];
    const r = buildVacancyLedger([
      act({ type: "transfer", employeeName: "佐藤", fromDeptId: 20, fromGrade: "M1", toDeptId: 10, toGrade: "M1" }),
    ], existing);
    expect(r.open.find((s) => s.id === "pos:99")).toBeUndefined();
    expect(r.filled.find((s) => s.id === "pos:99")?.filledByName).toBe("佐藤");
  });

  it("promotion fills a slot at the new grade and opens one at the old grade", () => {
    const r = buildVacancyLedger([
      act({ type: "retire", employeeName: "課長", fromDeptId: 10, fromGrade: "M1" }),
      act({ type: "promote", employeeName: "主任", fromDeptId: 10, fromGrade: "S1", toGrade: "M1" }),
    ], []);
    expect(r.open).toHaveLength(1);
    expect(r.open[0]).toMatchObject({ deptId: 10, grade: "S1" });
  });

  it("does not let a person fill the seat they just vacated", () => {
    const r = buildVacancyLedger([
      act({ type: "transfer", employeeName: "佐藤", fromDeptId: 10, fromGrade: "M1", toDeptId: 10, toGrade: "M1" }),
    ], []);
    expect(r.overfills).toHaveLength(1);
    expect(r.open).toHaveLength(1);
  });

  it("prefers the chain's own vacancy over an unrelated existing one", () => {
    const existing = [{ positionId: 1, title: "既存", deptId: 10, deptName: "営業部", grade: "M1" }];
    const retire = act({ type: "retire", employeeName: "田中", fromDeptId: 10, fromGrade: "M1" });
    const fill = act({ type: "transfer", employeeName: "佐藤", fromDeptId: 20, fromGrade: "M1", toDeptId: 10, toGrade: "M1" });
    const r = buildVacancyLedger([retire, fill], existing);
    expect(r.fillByAction.get(fill.id)?.openedBy).toBe(retire.id);
    expect(r.open.some((s) => s.id === "pos:1")).toBe(true);
  });
});

describe("buildChains", () => {
  it("links retire -> fill -> backfill into one chain", () => {
    const actions = [
      act({ type: "retire", employeeName: "A", fromDeptId: 10, fromGrade: "M1" }),
      act({ type: "transfer", employeeName: "B", fromDeptId: 20, fromGrade: "M1", toDeptId: 10, toGrade: "M1" }),
      act({ type: "promote", employeeName: "C", fromDeptId: 20, fromGrade: "S1", toGrade: "M1" }),
      act({ type: "retire", employeeName: "X", fromDeptId: 50, fromGrade: "J1" }),
    ];
    const chains = buildChains(actions, buildVacancyLedger(actions, []));
    expect(chains).toHaveLength(2);
    expect(chains[0].map((s) => s.actionId)).toEqual([actions[0].id, actions[1].id, actions[2].id]);
  });
});
