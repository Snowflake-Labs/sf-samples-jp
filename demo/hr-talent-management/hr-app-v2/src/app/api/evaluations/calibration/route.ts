import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession, requireRole } from "@/lib/session";
import { validateTargetDistribution } from "@/lib/scoring";

/**
 * Calibration sessions: the meeting where managers align grade
 * distributions across departments before evaluations are finalized.
 */

const DEFAULT_TARGET = { S: 0.05, A: 0.2, B: 0.5, C: 0.2, D: 0.05 };

interface SessionRow {
  SESSION_ID: number;
  SESSION_NAME: string;
  PERIOD: string;
  SCOPE_DEPT_ID: number | null;
  DEPT_NAME: string | null;
  SCOPE_GRADE: string | null;
  TARGET_DISTRIBUTION: Record<string, number>;
  STATUS: string;
  FACILITATOR: string | null;
  NOTES: string | null;
  CREATED_AT: string;
  FINALIZED_AT: string | null;
  ADJUSTMENT_COUNT: number;
}

export async function GET(request: Request) {
  const session = await getSession();
  const auth = requireRole(session, ["HR_ADMIN", "HR_MANAGER"]);
  if (!auth.ok) return NextResponse.json(auth.body, { status: auth.status });
  try {
    const url = new URL(request.url);
    const period = url.searchParams.get("period");
    const status = url.searchParams.get("status");

    const rows = await pgQuery<SessionRow>(
      `SELECT cs.session_id AS "SESSION_ID", cs.session_name AS "SESSION_NAME",
         cs.period AS "PERIOD", cs.scope_dept_id AS "SCOPE_DEPT_ID",
         d.dept_name AS "DEPT_NAME", cs.scope_grade AS "SCOPE_GRADE", cs.target_distribution AS "TARGET_DISTRIBUTION",
         cs.status AS "STATUS", cs.facilitator AS "FACILITATOR", cs.notes AS "NOTES",
         cs.created_at AS "CREATED_AT", cs.finalized_at AS "FINALIZED_AT",
         (SELECT COUNT(*)::int FROM hr.calibration_adjustments ca
          WHERE ca.session_id = cs.session_id) AS "ADJUSTMENT_COUNT"
       FROM hr.calibration_sessions cs
       LEFT JOIN hr.departments d ON cs.scope_dept_id = d.dept_id
       WHERE ($1::text IS NULL OR cs.period = $1)
         AND ($2::text IS NULL OR cs.status = $2)
       ORDER BY cs.created_at DESC`,
      [period, status]
    );

    // 会議作成ダイアログの等級選択肢
    // 1つの等級に複数の役職名があるため、ポジション数の多い順に並べて見せる
    const grades = await pgQuery<{ GRADE: string; TITLE: string }>(
      `SELECT grade AS "GRADE", string_agg(title, '・' ORDER BY n DESC, title) AS "TITLE"
       FROM (SELECT grade, title, COUNT(*) AS n FROM hr.positions
             WHERE grade IS NOT NULL AND title IS NOT NULL GROUP BY grade, title) t
       GROUP BY grade ORDER BY grade`
    );

    return NextResponse.json({ sessions: rows, grades });
  } catch (error) {
    console.error("Calibration GET error:", error);
    return NextResponse.json({ error: "調整会議の取得に失敗しました" }, { status: 500 });
  }
}

export async function POST(request: Request) {
  const session = await getSession();
  const auth = requireRole(session, ["HR_ADMIN"]);
  if (!auth.ok) return NextResponse.json(auth.body, { status: auth.status });
  const user = auth.user;
  try {
    const body = await request.json();
    const { session_name, period, scope_dept_id, scope_grade, target_distribution, notes } = body as {
      session_name?: string;
      period?: string;
      scope_dept_id?: number | null;
      scope_grade?: string | null;
      target_distribution?: Record<string, number>;
      notes?: string;
    };

    if (!session_name || !period) {
      return NextResponse.json({ error: "会議名と対象期間は必須です" }, { status: 400 });
    }
    if (!/^\d{4}-H[12]$/.test(period)) {
      return NextResponse.json({ error: "対象期間は 2025-H1 の形式で入力してください" }, { status: 400 });
    }

    if (scope_grade) {
      const known = await pgQuery(`SELECT 1 FROM hr.positions WHERE grade = $1 LIMIT 1`, [scope_grade]);
      if (known.length === 0) {
        return NextResponse.json({ error: `等級 ${scope_grade} は存在しません` }, { status: 400 });
      }
    }

    const target = target_distribution ?? DEFAULT_TARGET;
    if (!validateTargetDistribution(target)) {
      const sum = Object.values(target).reduce((a, b) => a + b, 0);
      return NextResponse.json(
        { error: `目標分布の合計が ${sum.toFixed(3)} です。1.000 にしてください` },
        { status: 400 }
      );
    }

    const rows = await pgQuery<{ SESSION_ID: number }>(
      `INSERT INTO hr.calibration_sessions
         (session_name, period, scope_dept_id, scope_grade, target_distribution, facilitator, notes)
       VALUES ($1, $2, $3, $4, $5, $6, $7)
       RETURNING session_id AS "SESSION_ID"`,
      [session_name, period, scope_dept_id ?? null, scope_grade || null, JSON.stringify(target), user.username, notes ?? null]
    );

    console.log(`[calibration] ${user.username} created session ${rows[0].SESSION_ID} for ${period}`);
    return NextResponse.json({ session_id: rows[0].SESSION_ID }, { status: 201 });
  } catch (error) {
    console.error("Calibration POST error:", error);
    return NextResponse.json({ error: "調整会議の作成に失敗しました" }, { status: 500 });
  }
}
