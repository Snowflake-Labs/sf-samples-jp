import { query } from "@/lib/sf-client";
import type { AxisScores } from "@/lib/scoring";

/**
 * Cortex scoring of evaluation comments, shared by HR's batch quantify and
 * the line manager's one-at-a-time "AIで採点".
 */

export const AI_MODEL = "claude-haiku-4-5";

export interface ScorableEval {
  EVALUATION_ID: number;
  COMMENT: string | null;
  SELF_COMMENT: string | null;
}

export interface AiScores {
  growth_score: number;
  expertise_score: number;
  leadership_score: number;
  problem_solving_score: number;
  collaboration_score: number;
  reasoning: string;
}

/**
 * Absolute-scale rubric. The LLM must NOT know the employee's grade:
 * if it did, it would silently grade on a curve ("good for a junior")
 * and the score would no longer mean the same thing across grades.
 * The grade comparison happens afterwards, against the stored standard.
 */
const RUBRIC = `全社共通の絶対スケールで採点してください。等級や役職による下駄履かせ・補正は一切しないでください。
同じ行動に対しては、新卒でも部長でも同じ点数をつけてください。

各軸のアンカー:
1 = ほぼ発揮されていない
2 = 部分的に発揮。担当業務の範囲内で受動的
3 = 担当業務を自律的に遂行できる標準的な水準
4 = チーム・複数案件に影響を与える水準
5 = 部門や全社に影響を与える卓越した水準`;

function clampScore(n: unknown): number {
  const v = typeof n === "number" ? n : Number(n);
  if (!Number.isFinite(v)) return 3;
  return Math.max(1, Math.min(5, Math.round(v)));
}

export function toAxisScores(s: AiScores): AxisScores {
  return {
    growth: s.growth_score,
    expertise: s.expertise_score,
    leadership: s.leadership_score,
    problem_solving: s.problem_solving_score,
    collaboration: s.collaboration_score,
  };
}

function buildPrompt(ev: ScorableEval): string {
  // Deliberately omits 等級 — see RUBRIC.
  return `あなたは人事評価の専門家です。以下の評価コメントを分析し、5軸のスコア(1-5)をJSON形式で回答してください。

${RUBRIC}

【上司コメント】
${ev.COMMENT || "(なし)"}

【自己評価コメント】
${ev.SELF_COMMENT || "(なし)"}

以下のJSONのみを出力してください。他のテキストは不要です:
{"growth_score":1-5,"expertise_score":1-5,"leadership_score":1-5,"problem_solving_score":1-5,"collaboration_score":1-5,"reasoning":"採点根拠を日本語1-2文で。軸は成長性・専門性・リーダーシップ・課題解決力・協調性と日本語で書き、英語のキー名は書かない"}`;
}

function parseAiJson(raw: string): AiScores | null {
  const match = raw.match(/\{[\s\S]*\}/);
  if (!match) return null;
  try {
    const parsed = JSON.parse(match[0]) as Partial<AiScores>;
    return {
      growth_score: clampScore(parsed.growth_score),
      expertise_score: clampScore(parsed.expertise_score),
      leadership_score: clampScore(parsed.leadership_score),
      problem_solving_score: clampScore(parsed.problem_solving_score),
      collaboration_score: clampScore(parsed.collaboration_score),
      reasoning: typeof parsed.reasoning === "string" ? parsed.reasoning : "",
    };
  } catch {
    return null;
  }
}

/**
 * Score a chunk of evaluations in a single Cortex round trip.
 * The prompts ride in as bind parameters, so comment text containing
 * quotes or backslashes cannot break out into the SQL.
 */
export async function scoreChunk(chunk: ScorableEval[]): Promise<Map<number, AiScores>> {
  const values = chunk.map((_, i) => `(${i + 1}::int, ?)`).join(", ");
  const binds = chunk.map((ev) => buildPrompt(ev));

  const rows = await query<{ IDX: number; RESPONSE: string }>(
    `SELECT idx AS "IDX", SNOWFLAKE.CORTEX.COMPLETE('${AI_MODEL}', prompt) AS "RESPONSE"
     FROM (VALUES ${values}) AS t(idx, prompt)`,
    binds
  );

  const out = new Map<number, AiScores>();
  for (const row of rows) {
    // idx is 1-based to keep the SQL readable
    const ev = chunk[Number(row.IDX) - 1];
    if (!ev) continue;
    const scores = parseAiJson(row.RESPONSE || "");
    if (!scores) {
      console.error(`[ai-scoring] LLM parse failed for eval ${ev.EVALUATION_ID}`);
      continue;
    }
    out.set(ev.EVALUATION_ID, scores);
  }
  return out;
}
