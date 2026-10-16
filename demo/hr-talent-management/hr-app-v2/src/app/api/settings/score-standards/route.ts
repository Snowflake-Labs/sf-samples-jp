import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession, requireRole } from "@/lib/session";
import { recalculatePeriod } from "@/lib/recalculate";
import { SCORE_AXES, WEIGHT_SUM_EPSILON, type ScoreAxis } from "@/lib/scoring";

/**
 * Grade standards master.
 *
 * Editing a standard moves everyone's expectation gap, and therefore
 * everyone's rank. So a PUT always writes a history snapshot and, unless
 * told otherwise, immediately recalculates the affected periods.
 */

interface StandardApiRow {
  GRADE: string;
  SORT_ORDER: number;
  UPDATED_AT: string;
  UPDATED_BY: string | null;
  [key: string]: string | number | null;
}

const AXIS_COLUMNS = SCORE_AXES.flatMap((a) => [`${a}_expected`, `${a}_weight`]);

const SELECT_COLUMNS = `
  grade AS "GRADE", sort_order AS "SORT_ORDER",
  updated_at AS "UPDATED_AT", updated_by AS "UPDATED_BY",
  ${AXIS_COLUMNS.map((c) => `${c} AS "${c.toUpperCase()}"`).join(",\n  ")}`;

const SELECT_ALL = `SELECT ${SELECT_COLUMNS} FROM hr.grade_score_standards ORDER BY sort_order`;
const SELECT_ONE = `SELECT ${SELECT_COLUMNS} FROM hr.grade_score_standards WHERE grade = $1`;

/** Shape one DB row into the nested form the UI works with. */
function shape(r: StandardApiRow) {
  const axes: Record<string, { expected: number; weight: number }> = {};
  for (const a of SCORE_AXES) {
    axes[a] = {
      expected: Number(r[`${a.toUpperCase()}_EXPECTED`]),
      weight: Number(r[`${a.toUpperCase()}_WEIGHT`]),
    };
  }
  return {
    grade: r.GRADE,
    sort_order: r.SORT_ORDER,
    updated_at: r.UPDATED_AT,
    updated_by: r.UPDATED_BY,
    axes,
  };
}

export async function GET(request: Request) {
  const session = await getSession();
  const auth = requireRole(session, ["HR_ADMIN", "HR_MANAGER"]);
  if (!auth.ok) return NextResponse.json(auth.body, { status: auth.status });
  try {
    const url = new URL(request.url);
    const withHistory = url.searchParams.get("history") === "true";
    const historyGrade = url.searchParams.get("grade");

    const rows = await pgQuery<StandardApiRow>(SELECT_ALL);
    const standards = rows.map(shape);

    if (!withHistory) {
      return NextResponse.json({ standards });
    }

    const history = await pgQuery<{
      HISTORY_ID: number;
      GRADE: string;
      SNAPSHOT: unknown;
      CHANGED_BY: string;
      CHANGE_NOTE: string | null;
      CHANGED_AT: string;
    }>(
      `SELECT history_id AS "HISTORY_ID", grade AS "GRADE", snapshot AS "SNAPSHOT",
         changed_by AS "CHANGED_BY", change_note AS "CHANGE_NOTE", changed_at AS "CHANGED_AT"
       FROM hr.grade_score_standards_history
       WHERE ($1::text IS NULL OR grade = $1)
       ORDER BY changed_at DESC
       LIMIT 100`,
      [historyGrade]
    );

    return NextResponse.json({ standards, history });
  } catch (error) {
    console.error("Standards GET error:", error);
    return NextResponse.json({ error: "評価基準の取得に失敗しました" }, { status: 500 });
  }
}

interface PutBody {
  grade: string;
  axes: Record<ScoreAxis, { expected: number; weight: number }>;
  change_note?: string;
  /** When false, skip the automatic recalculation (used by the preview flow). */
  recalculate?: boolean;
}

export async function PUT(request: Request) {
  const session = await getSession();
  const auth = requireRole(session, ["HR_ADMIN"]);
  if (!auth.ok) return NextResponse.json(auth.body, { status: auth.status });
  const user = auth.user;
  try {
    const body = (await request.json()) as PutBody;
    const { grade, axes, change_note, recalculate = true } = body;

    if (!grade || !axes) {
      return NextResponse.json({ error: "grade と axes が必要です" }, { status: 400 });
    }

    // Validate before touching the DB so the error message is useful.
    let weightSum = 0;
    for (const axis of SCORE_AXES) {
      const a = axes[axis];
      if (!a || typeof a.expected !== "number" || typeof a.weight !== "number") {
        return NextResponse.json({ error: `${axis} の expected/weight が不正です` }, { status: 400 });
      }
      if (a.expected < 1 || a.expected > 5) {
        return NextResponse.json(
          { error: `${axis} の期待水準は1〜5の範囲で指定してください` },
          { status: 400 }
        );
      }
      if (a.weight < 0 || a.weight > 1) {
        return NextResponse.json(
          { error: `${axis} の重みは0〜1の範囲で指定してください` },
          { status: 400 }
        );
      }
      weightSum += a.weight;
    }
    if (Math.abs(weightSum - 1.0) >= WEIGHT_SUM_EPSILON) {
      return NextResponse.json(
        { error: `重みの合計が ${weightSum.toFixed(3)} です。1.000 にしてください` },
        { status: 400 }
      );
    }

    // Snapshot the current values before overwriting them.
    const before = await pgQuery<StandardApiRow>(SELECT_ONE, [grade]);
    if (before.length === 0) {
      return NextResponse.json({ error: `等級 ${grade} が見つかりません` }, { status: 404 });
    }

    await pgQuery(
      `INSERT INTO hr.grade_score_standards_history (grade, snapshot, changed_by, change_note)
       VALUES ($1, $2, $3, $4)`,
      [grade, JSON.stringify(shape(before[0])), user.username, change_note ?? null]
    );

    const setClause = SCORE_AXES.map(
      (a, i) => `${a}_expected = $${i * 2 + 2}, ${a}_weight = $${i * 2 + 3}`
    ).join(", ");
    const values = SCORE_AXES.flatMap((a) => [axes[a].expected, axes[a].weight]);

    await pgQuery(
      `UPDATE hr.grade_score_standards
       SET ${setClause}, updated_at = NOW(), updated_by = $${values.length + 2}
       WHERE grade = $1`,
      [grade, ...values, user.username]
    );

    let recalc = null;
    if (recalculate) {
      recalc = await recalculatePeriod(null);
    }

    console.log(`[standards] ${user.username} updated ${grade}` + (recalc ? ` and recalculated ${recalc.updated} scores` : ""));

    return NextResponse.json({ ok: true, grade, recalculated: recalc });
  } catch (error) {
    const msg = (error as Error).message;
    // Surface the DB CHECK as a readable message rather than a bare 500
    if (msg.includes("weights_sum_to_one")) {
      return NextResponse.json({ error: "重みの合計が1.0になっていません" }, { status: 400 });
    }
    console.error("Standards PUT error:", error);
    return NextResponse.json({ error: "評価基準の更新に失敗しました" }, { status: 500 });
  }
}
