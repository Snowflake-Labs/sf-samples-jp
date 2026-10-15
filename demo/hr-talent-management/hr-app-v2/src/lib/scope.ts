import { pgQuery } from "@/lib/postgres";
import { isHonbuAllowed } from "@/lib/session";
import type { SessionUser } from "@/lib/types";

/**
 * 部署スコープ（session.deptScope = 見てよい本部の dept_id）の判定。
 * deptScope が null の人（人事管理者など）は全社が対象。
 */

/**
 * 一覧 API の honbu パラメータを、絞り込みに使う本部 ID の配列に変える。
 * - honbu 指定あり: スコープ外なら拒否、スコープ内ならその本部だけ
 * - 指定なし: スコープのある人はスコープ全体、ない人は null（全社）
 */
export function resolveHonbuScope(
  session: SessionUser,
  honbu: number | null
): { ok: true; honbuIds: number[] | null } | { ok: false } {
  if (honbu !== null) {
    if (!isHonbuAllowed(session, honbu)) return { ok: false };
    return { ok: true, honbuIds: [honbu] };
  }
  return { ok: true, honbuIds: session.deptScope && session.deptScope.length > 0 ? session.deptScope : null };
}

/** 部署（本部そのもの、または本部の下の部署）がスコープ内か */
export async function isDeptInScope(session: SessionUser, deptId: number): Promise<boolean> {
  if (!session.deptScope) return true;
  const rows = await pgQuery(
    `SELECT 1 FROM hr.departments
     WHERE dept_id = $1 AND (dept_id = ANY($2::int[]) OR parent_dept_id = ANY($2::int[]))`,
    [deptId, session.deptScope]
  );
  return rows.length > 0;
}

/** 社員の所属部署がスコープ内か。社員がいない場合も false */
export async function isEmployeeInScope(session: SessionUser, employeeId: number): Promise<boolean> {
  if (!session.deptScope) return true;
  const rows = await pgQuery(
    `SELECT 1 FROM hr.employees e
     JOIN hr.departments d ON e.dept_id = d.dept_id
     WHERE e.employee_id = $1
       AND (d.dept_id = ANY($2::int[]) OR d.parent_dept_id = ANY($2::int[]))`,
    [employeeId, session.deptScope]
  );
  return rows.length > 0;
}

/** 評価の対象社員がスコープ内か。評価がない場合も false */
export async function isEvaluationInScope(session: SessionUser, evaluationId: number): Promise<boolean> {
  if (!session.deptScope) return true;
  const rows = await pgQuery(
    `SELECT 1 FROM hr.evaluations ev
     JOIN hr.employees e ON ev.employee_id = e.employee_id
     JOIN hr.departments d ON e.dept_id = d.dept_id
     WHERE ev.evaluation_id = $1
       AND (d.dept_id = ANY($2::int[]) OR d.parent_dept_id = ANY($2::int[]))`,
    [evaluationId, session.deptScope]
  );
  return rows.length > 0;
}
