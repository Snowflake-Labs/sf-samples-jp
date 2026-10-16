import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession } from "@/lib/session";

interface SnapshotAction {
  employee_code: string;
  employee_name: string;
  action_type: string;
  from_dept_code: string;
  from_dept_name: string;
  to_dept_code: string;
  to_dept_name: string;
  from_grade: string;
  to_grade?: string | null;
  grade?: string;
}

export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const session = await getSession();
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const { id } = await params;

  const [snap] = await pgQuery<{
    snapshot_id: number;
    label: string;
    effective_date: string;
    snapshot_type: string;
    data_json: { actions?: SnapshotAction[]; steps?: SnapshotAction[] };
  }>(
    `SELECT snapshot_id, label, effective_date::text AS effective_date, snapshot_type, data_json FROM hr.scenario_snapshots WHERE snapshot_id = $1`,
    [Number(id)]
  );
  if (!snap) return NextResponse.json({ error: "Not found" }, { status: 404 });

  const items = snap.snapshot_type === "whatif"
    ? (snap.data_json.actions || [])
    : (snap.data_json.steps || []);

  const typeLabels: Record<string, string> = { transfer: "異動", promote: "昇格", retire: "退職" };
  const effectiveDate = snap.effective_date;

  const header = "発令日,社員番号,氏名,異動種別,異動元部署コード,異動元部署名,異動先部署コード,異動先部署名,異動元等級,異動先等級,備考";

  const rows = items.map((item) => {
    const type = typeLabels[item.action_type] || item.action_type || "異動";
    const fromGrade = item.from_grade || item.grade || "";
    // 昇格先等級は確定時に保存される。古いスナップショット（未保存）は昇格先が分からないため空欄
    const toGrade = item.to_grade ?? (item.action_type === "promote" || item.action_type === "retire" ? "" : fromGrade);
    const note = snap.label;
    return [
      effectiveDate,
      item.employee_code || "",
      item.employee_name || "",
      type,
      item.from_dept_code || "",
      item.from_dept_name || "",
      item.to_dept_code || "",
      item.to_dept_name || "",
      fromGrade,
      toGrade,
      note,
    ]
      .map((v) => `"${String(v).replace(/"/g, '""')}"`)
      .join(",");
  });

  const bom = "\uFEFF";
  const csv = bom + header + "\n" + rows.join("\n");

  return new Response(csv, {
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": `attachment; filename="snapshot_${snap.snapshot_id}_${effectiveDate}.csv"`,
    },
  });
}
