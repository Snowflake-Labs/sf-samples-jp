/**
 * Vacancy ledger for transfer scenarios.
 *
 * A scenario is an ordered list of moves. Each move can open a slot
 * (the person leaves a dept/grade) and can fill a slot (the person
 * arrives in a dept/grade). The ledger replays the moves in order so
 * that a slot, once filled, is no longer offered — which is what keeps
 * a chain from filling the same vacancy twice.
 *
 * It is derived from the action list rather than stored, so a scenario
 * reloaded from the DB reconciles the same way it did when it was built.
 */

export type LedgerActionType = "promote" | "transfer" | "retire";

export interface LedgerAction {
  id: string;
  type: LedgerActionType;
  employeeId: number;
  employeeName: string;
  fromDeptId: number;
  fromDeptName: string;
  fromGrade: string;
  toDeptId?: number;
  toDeptName?: string;
  toGrade?: string;
}

export interface ExistingVacancy {
  positionId: number;
  title: string;
  deptId: number;
  deptName: string;
  grade: string;
}

export interface Slot {
  /** Stable id: "gen:<actionId>" or "pos:<positionId>" */
  id: string;
  deptId: number;
  deptName: string;
  grade: string;
  source: "generated" | "existing";
  /** Human label for where the slot came from */
  origin: string;
  /** Action that opened the slot (generated slots only) */
  openedBy?: string;
  /** Action that filled the slot, if any */
  filledBy?: string;
  filledByName?: string;
}

export interface LedgerResult {
  open: Slot[];
  filled: Slot[];
  /** Arrivals that found no open slot: headcount goes over plan */
  overfills: { actionId: string; employeeName: string; deptName: string; grade: string }[];
  /** actionId -> slot it filled, for drawing chains */
  fillByAction: Map<string, Slot>;
}

const ACTION_VERB: Record<LedgerActionType, string> = {
  promote: "昇格",
  transfer: "異動",
  retire: "退職",
};

function arrival(a: LedgerAction): { deptId: number; deptName: string; grade: string } | null {
  if (a.type === "retire") return null;
  if (a.type === "promote") {
    if (!a.toGrade) return null;
    return { deptId: a.fromDeptId, deptName: a.fromDeptName, grade: a.toGrade };
  }
  if (a.toDeptId == null) return null;
  return {
    deptId: a.toDeptId,
    deptName: a.toDeptName ?? a.fromDeptName,
    grade: a.toGrade ?? a.fromGrade,
  };
}

export function buildVacancyLedger(
  actions: LedgerAction[],
  existing: ExistingVacancy[]
): LedgerResult {
  const slots: Slot[] = existing.map((v) => ({
    id: `pos:${v.positionId}`,
    deptId: v.deptId,
    deptName: v.deptName,
    grade: v.grade,
    source: "existing",
    origin: `${v.title}（既存空席）`,
  }));
  const overfills: LedgerResult["overfills"] = [];
  const fillByAction = new Map<string, Slot>();

  for (const a of actions) {
    // Fill first: the person takes a slot that was open before this move.
    // Doing it before opening their own seat stops a person from
    // "filling" the vacancy they just created.
    const to = arrival(a);
    if (to) {
      // Prefer slots opened by earlier moves (the chain) over pre-existing ones,
      // then oldest first, so chains read in the order they were built.
      const candidates = slots.filter(
        (s) => !s.filledBy && s.deptId === to.deptId && s.grade === to.grade
      );
      const slot =
        candidates.find((s) => s.source === "generated") ?? candidates[0];
      if (slot) {
        slot.filledBy = a.id;
        slot.filledByName = a.employeeName;
        fillByAction.set(a.id, slot);
      } else {
        overfills.push({
          actionId: a.id,
          employeeName: a.employeeName,
          deptName: to.deptName,
          grade: to.grade,
        });
      }
    }

    // Then the seat they leave becomes open.
    slots.push({
      id: `gen:${a.id}`,
      deptId: a.fromDeptId,
      deptName: a.fromDeptName,
      grade: a.fromGrade,
      source: "generated",
      origin: `${a.employeeName}の${ACTION_VERB[a.type]}`,
      openedBy: a.id,
    });
  }

  return {
    open: slots.filter((s) => !s.filledBy),
    filled: slots.filter((s) => s.filledBy),
    overfills,
    fillByAction,
  };
}

export interface ChainStep {
  actionId: string;
  /** Slot this action filled (absent for the chain's first move) */
  filled?: Slot;
}

/**
 * Group actions into chains: a move that fills the seat opened by an
 * earlier move continues that move's chain. Each chain ends with the
 * seat its last move left open (or with a retirement).
 */
export function buildChains(actions: LedgerAction[], ledger: LedgerResult): ChainStep[][] {
  const chainOf = new Map<string, number>();
  const chains: ChainStep[][] = [];

  for (const a of actions) {
    const filled = ledger.fillByAction.get(a.id);
    const parent = filled?.openedBy;
    if (parent && chainOf.has(parent)) {
      const idx = chainOf.get(parent)!;
      chains[idx].push({ actionId: a.id, filled });
      chainOf.set(a.id, idx);
    } else {
      chains.push([{ actionId: a.id, filled }]);
      chainOf.set(a.id, chains.length - 1);
    }
  }
  return chains;
}
