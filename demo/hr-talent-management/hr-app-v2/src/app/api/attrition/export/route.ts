import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession } from "@/lib/session";
import { resolveHonbuScope } from "@/lib/scope";

export async function GET(req: Request) {
  const session = await getSession();
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const { searchParams } = new URL(req.url);
  const honbu = searchParams.get("honbu");
  if (!honbu) return NextResponse.json({ error: "honbu required" }, { status: 400 });

  const scope = resolveHonbuScope(session, Number(honbu));
  if (!scope.ok) return NextResponse.json({ error: "アクセス権限がありません" }, { status: 403 });
  const params: unknown[] = [scope.honbuIds ?? [Number(honbu)]];
  const deptFilter = `AND (d.dept_id = ANY($1::int[]) OR d.parent_dept_id = ANY($1::int[]))`;

  const rows = await pgQuery<Record<string, unknown>>(
    `SELECT e.employee_code, e.last_name || ' ' || e.first_name AS name,
            d.dept_name, p.grade,
            pr.risk_score, pr.risk_label,
            top.factors
     FROM hr_lake.prediction_results pr
     JOIN hr.employees e ON pr.employee_id = e.employee_id
     LEFT JOIN hr.departments d ON e.dept_id = d.dept_id
     LEFT JOIN hr.positions p ON e.position_id = p.position_id
     -- 主要因は SHAP の絶対値の大きい順に 3 つ（model_type は shap_results 側の列）
     LEFT JOIN LATERAL (
       SELECT array_agg(f.feature_name ORDER BY f.abs_shap DESC) AS factors
       FROM (SELECT s.feature_name, ABS(s.shap_value) AS abs_shap
             FROM hr_lake.shap_results s
             WHERE s.prediction_id = pr.id AND s.model_type = 'attrition'
             ORDER BY ABS(s.shap_value) DESC LIMIT 3) f
     ) top ON TRUE
     WHERE e.status = 'active'
       ${deptFilter}
     ORDER BY pr.risk_score DESC`,
    params
  );

  const header = "社員番号,氏名,部署,等級,リスクスコア,リスクレベル,主要因1,主要因2,主要因3\n";
  const BOM = "\uFEFF";

  const csvRows = rows.map((r) => {
    const factors = Array.isArray(r.factors) ? (r.factors as string[]) : [];
    return [
      r.employee_code, r.name, r.dept_name || "", r.grade || "",
      r.risk_score != null ? Number(r.risk_score).toFixed(3) : "",
      r.risk_label || "",
      factors[0] || "", factors[1] || "", factors[2] || ""
    ].map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",");
  });

  const csv = BOM + header + csvRows.join("\n");

  return new NextResponse(csv, {
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": `attachment; filename="attrition_risk_${new Date().toISOString().slice(0, 10)}.csv"`,
    },
  });
}
