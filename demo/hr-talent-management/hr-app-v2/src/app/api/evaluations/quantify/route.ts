import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession, requireRole } from "@/lib/session";
import { loadStandards, mergeWithOverrides, rerankPeriod, saveScores } from "@/lib/recalculate";
import { AI_MODEL, scoreChunk, toAxisScores, type AiScores } from "@/lib/ai-scoring";
import { type AxisScores } from "@/lib/scoring";

/** How many evaluations go into one Cortex COMPLETE round trip. */
const CHUNK_SIZE = 30;

interface EvalRow {
  EVALUATION_ID: number;
  EMPLOYEE_ID: number;
  PERIOD: string;
  SCORE: number | null;
  GRADE: string | null;
  COMMENT: string | null;
  SELF_COMMENT: string | null;
  NAME: string;
  DEPT_ID: number;
  POSITION_GRADE: string;
}

export async function POST(request: Request) {
  const session = await getSession();
  const auth = requireRole(session, ["HR_ADMIN", "HR_MANAGER"]);
  if (!auth.ok) return NextResponse.json(auth.body, { status: auth.status });
  const user = auth.user;
  try {
    const body = await request.json();
    const { evaluation_ids, dept_id, period } = body as {
      evaluation_ids?: number[];
      dept_id?: number;
      period?: string;
    };

    const SELECT_EVALS = `
      SELECT ev.evaluation_id AS "EVALUATION_ID", ev.employee_id AS "EMPLOYEE_ID",
        ev.period AS "PERIOD", ev.score AS "SCORE", ev.grade AS "GRADE",
        ev.comment AS "COMMENT", ev.self_comment AS "SELF_COMMENT",
        e.last_name || e.first_name AS "NAME", e.dept_id AS "DEPT_ID",
        p.grade AS "POSITION_GRADE"
      FROM hr.evaluations ev
      JOIN hr.employees e ON ev.employee_id = e.employee_id
      JOIN hr.positions p ON e.position_id = p.position_id`;

    let evals: EvalRow[];
    if (evaluation_ids && evaluation_ids.length > 0) {
      const placeholders = evaluation_ids.map((_, i) => `$${i + 1}`).join(",");
      evals = await pgQuery<EvalRow>(
        `${SELECT_EVALS} WHERE ev.evaluation_id IN (${placeholders})`,
        evaluation_ids
      );
    } else if (dept_id && period) {
      evals = await pgQuery<EvalRow>(
        `${SELECT_EVALS}
         WHERE e.dept_id IN (SELECT dept_id FROM hr.departments WHERE dept_id = $1 OR parent_dept_id = $1)
           AND ev.period = $2`,
        [dept_id, period]
      );
    } else {
      return NextResponse.json(
        { error: "evaluation_ids または dept_id+period が必要です" },
        { status: 400 }
      );
    }

    const scorable = evals.filter((ev) => ev.COMMENT || ev.SELF_COMMENT);
    if (scorable.length === 0) {
      return NextResponse.json({ processed: 0, skipped: evals.length, results: [] });
    }

    // Load every grade standard once; we need the next grade's too.
    const standards = await loadStandards();

    // Batch the LLM calls
    const aiByEvalId = new Map<number, AiScores>();
    const chunkErrors: string[] = [];
    for (let i = 0; i < scorable.length; i += CHUNK_SIZE) {
      const chunk = scorable.slice(i, i + CHUNK_SIZE);
      try {
        const scored = await scoreChunk(chunk);
        for (const [k, v] of scored) aiByEvalId.set(k, v);
      } catch (err) {
        const msg = (err as Error).message;
        console.error(`[quantify] chunk ${i / CHUNK_SIZE} failed:`, msg);
        chunkErrors.push(msg);
      }
    }

    const results: {
      evaluation_id: number;
      employee_id: number;
      name: string;
      position_grade: string;
      scores: AxisScores;
      expectation_gap: number;
      standard_grade: string;
    }[] = [];
    const missingStandards = new Set<string>();

    for (const ev of scorable) {
      const ai = aiByEvalId.get(ev.EVALUATION_ID);
      if (!ai) continue;

      if (!standards.has(ev.POSITION_GRADE)) {
        // No standard configured: record the raw scores but do not invent a gap.
        missingStandards.add(ev.POSITION_GRADE);
      }

      const actual = toAxisScores(ai);
      // A line manager's per-axis correction survives a re-score.
      const effective = await mergeWithOverrides(ev.EVALUATION_ID, actual);
      const saved = await saveScores(
        {
          evaluationId: ev.EVALUATION_ID, employeeId: ev.EMPLOYEE_ID, period: ev.PERIOD,
          positionGrade: ev.POSITION_GRADE, ai: actual, effective,
          reasoning: ai.reasoning, modelVersion: AI_MODEL,
        },
        standards
      );

      results.push({
        evaluation_id: ev.EVALUATION_ID,
        employee_id: ev.EMPLOYEE_ID,
        name: ev.NAME,
        position_grade: ev.POSITION_GRADE,
        scores: effective,
        expectation_gap: saved.expectationGap ?? 0,
        standard_grade: saved.standardGrade ?? "-",
      });
    }

    // Rank on the expectation gap. Because the gap is measured against each
    // grade's own bar, dept_rank is now comparable across grades.
    // NULLS LAST keeps un-scored rows from occupying the top slots.
    if (results.length > 0) {
      const periods = [...new Set(scorable.map((e) => e.PERIOD))];
      for (const p of periods) await rerankPeriod(p);
    }

    console.log(
      `[quantify] ${user.username} processed ${results.length}/${scorable.length} in ${Math.ceil(scorable.length / CHUNK_SIZE)} batches`
    );

    return NextResponse.json({
      processed: results.length,
      skipped: evals.length - scorable.length,
      failed: scorable.length - results.length,
      batches: Math.ceil(scorable.length / CHUNK_SIZE),
      missing_standards: [...missingStandards],
      chunk_errors: chunkErrors,
      results,
    });
  } catch (error) {
    console.error("Quantify error:", error);
    return NextResponse.json({ error: "定量化処理に失敗しました" }, { status: 500 });
  }
}
