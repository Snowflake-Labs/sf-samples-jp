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
            pr.shap_values
     FROM hr_lake.prediction_results pr
     JOIN hr.employees e ON pr.employee_id = e.employee_id
     LEFT JOIN hr.departments d ON e.dept_id = d.dept_id
     LEFT JOIN hr.positions p ON e.position_id = p.position_id
     WHERE pr.model_type = 'attrition'
       AND e.status = 'active'
       ${deptFilter}
     ORDER BY pr.risk_score DESC`,
    params
  );

  const header = "社員番号,氏名,部署,等級,リスクスコア,リスクレベル,主要因1,主要因2,主要因3\n";
  const BOM = "\uFEFF";

  const csvRows = rows.map((r) => {
    let factors: string[] = [];
    try {
      const shap = typeof r.shap_values === "string" ? JSON.parse(r.shap_values as string) : r.shap_values;
      if (Array.isArray(shap)) {
        factors = shap
          .sort((a: { shap_value: number }, b: { shap_value: number }) => Math.abs(b.shap_value) - Math.abs(a.shap_value))
          .slice(0, 3)
          .map((s: { feature: string }) => s.feature);
      }
    } catch { /* ignore */ }
    return [
      r.employee_code, r.name, r.dept_name || "", r.grade || "",
      typeof r.risk_score === "number" ? (r.risk_score as number).toFixed(3) : "",
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
