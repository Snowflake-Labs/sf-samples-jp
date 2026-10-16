import { NextResponse } from "next/server";
import { pgQuery } from "@/lib/postgres";
import { getSession, getAllowedDeptIds } from "@/lib/session";

const BOM = "\uFEFF";

function csvEscape(v: unknown): string {
  return `"${String(v ?? "").replace(/"/g, '""')}"`;
}

function toCsv(header: string[], rows: unknown[][]): string {
  return BOM + header.join(",") + "\n" + rows.map((r) => r.map(csvEscape).join(",")).join("\n");
}

export async function GET(req: Request) {
  const session = await getSession();
  if (!session) return NextResponse.json({ error: "認証が必要です" }, { status: 401 });

  try {
    const { searchParams } = new URL(req.url);
    const honbu = searchParams.get("honbu");
    const section = searchParams.get("section") || "roster";
    if (!honbu) return NextResponse.json({ error: "honbu required" }, { status: 400 });

    const hId = Number(honbu);
    if (isNaN(hId)) return NextResponse.json({ error: "Invalid honbu" }, { status: 400 });

    const params: unknown[] = [hId, hId];
    let idx = 3;
    let scopeFilter = "";
    const allowed = getAllowedDeptIds(session);
    if (allowed) {
      const ph = allowed.map((d) => { params.push(d); return `$${idx++}`; }).join(",");
      scopeFilter = `AND e.dept_id IN (${ph})`;
    }

    const deptFilter = `e.dept_id IN (SELECT dept_id FROM hr.departments WHERE dept_id = $1 OR parent_dept_id = $2)`;

    if (section === "grade_pyramid") {
      const rows = await pgQuery<Record<string, unknown>>(`
        SELECT pos.grade AS grade, COUNT(*)::int AS headcount,
          ROUND(AVG(EXTRACT(YEAR FROM AGE(CURRENT_DATE, e.birth_date)))::numeric, 1) AS avg_age,
          ROUND(AVG(EXTRACT(YEAR FROM AGE(CURRENT_DATE, e.hire_date)))::numeric, 1) AS avg_tenure,
          COUNT(CASE WHEN e.gender = 'M' THEN 1 END)::int AS male,
          COUNT(CASE WHEN e.gender = 'F' THEN 1 END)::int AS female
        FROM hr.employees e
        JOIN hr.positions pos ON e.position_id = pos.position_id
        WHERE ${deptFilter} AND e.status = 'active' ${scopeFilter}
        GROUP BY pos.grade
        ORDER BY CASE pos.grade
          WHEN 'E1' THEN 1 WHEN 'D1' THEN 2 WHEN 'D2' THEN 3 WHEN 'M1' THEN 4
          WHEN 'M2' THEN 5 WHEN 'S1' THEN 6 WHEN 'S2' THEN 7 WHEN 'J1' THEN 8
          WHEN 'J2' THEN 9 WHEN 'J3' THEN 10 ELSE 99 END
      `, params);
      const csv = toCsv(
        ["等級", "人員数", "平均年齢", "平均勤続年数", "男性", "女性"],
        rows.map((r) => [r.grade, r.headcount, r.avg_age, r.avg_tenure, r.male, r.female])
      );
      return new NextResponse(csv, {
        headers: {
          "Content-Type": "text/csv; charset=utf-8",
          "Content-Disposition": `attachment; filename="grade_pyramid_${new Date().toISOString().slice(0, 10)}.csv"`,
        },
      });
    }

    if (section === "dept_summary") {
      const rows = await pgQuery<Record<string, unknown>>(`
        SELECT d.dept_name AS dept_name, COUNT(*)::int AS headcount,
          ROUND(AVG(ev.score)::numeric, 2) AS avg_eval,
          ROUND(AVG(EXTRACT(YEAR FROM AGE(CURRENT_DATE, e.hire_date)))::numeric, 1) AS avg_tenure,
          COUNT(CASE WHEN pl.risk_label = 'high' THEN 1 END)::int AS high_risk,
          COUNT(CASE WHEN pl.risk_label = 'medium' THEN 1 END)::int AS medium_risk
        FROM hr.employees e
        JOIN hr.departments d ON e.dept_id = d.dept_id
        LEFT JOIN (
          SELECT employee_id, AVG(score) AS score FROM hr.evaluations GROUP BY employee_id
        ) ev ON ev.employee_id = e.employee_id
        LEFT JOIN hr_lake.prediction_results pl ON pl.employee_id = e.employee_id
        WHERE ${deptFilter} AND e.status = 'active' ${scopeFilter}
        GROUP BY d.dept_name
        ORDER BY headcount DESC
      `, params);
      const csv = toCsv(
        ["部門", "人員数", "平均評価", "平均勤続年数", "高リスク", "中リスク"],
        rows.map((r) => [r.dept_name, r.headcount, r.avg_eval, r.avg_tenure, r.high_risk, r.medium_risk])
      );
      return new NextResponse(csv, {
        headers: {
          "Content-Type": "text/csv; charset=utf-8",
          "Content-Disposition": `attachment; filename="dept_summary_${new Date().toISOString().slice(0, 10)}.csv"`,
        },
      });
    }

    // Default: full roster with ML signals
    const rows = await pgQuery<Record<string, unknown>>(`
      SELECT e.employee_code, e.last_name || ' ' || e.first_name AS name,
        d.dept_name, pos.grade, pos.title,
        e.hire_date, e.employment_type,
        EXTRACT(YEAR FROM AGE(CURRENT_DATE, e.birth_date))::int AS age,
        ROUND(EXTRACT(YEAR FROM AGE(CURRENT_DATE, e.hire_date))::numeric, 1) AS tenure_years,
        mgr.last_name || ' ' || mgr.first_name AS manager_name,
        ev.avg_score, ev.latest_grade,
        pl.risk_score, pl.risk_label,
        rr.relationship_score
      FROM hr.employees e
      JOIN hr.departments d ON e.dept_id = d.dept_id
      JOIN hr.positions pos ON e.position_id = pos.position_id
      LEFT JOIN hr.employees mgr ON e.manager_id = mgr.employee_id
      LEFT JOIN (
        SELECT employee_id, ROUND(AVG(score)::numeric, 2) AS avg_score,
          (ARRAY_AGG(grade ORDER BY period DESC))[1] AS latest_grade
        FROM hr.evaluations GROUP BY employee_id
      ) ev ON ev.employee_id = e.employee_id
      LEFT JOIN hr_lake.prediction_results pl ON pl.employee_id = e.employee_id
      LEFT JOIN hr_lake.relationship_results rr ON rr.employee_id = e.employee_id
      WHERE ${deptFilter} AND e.status = 'active' ${scopeFilter}
      ORDER BY d.dept_name, CASE pos.grade
        WHEN 'E1' THEN 1 WHEN 'D1' THEN 2 WHEN 'D2' THEN 3 WHEN 'M1' THEN 4
        WHEN 'M2' THEN 5 WHEN 'S1' THEN 6 WHEN 'S2' THEN 7 WHEN 'J1' THEN 8
        WHEN 'J2' THEN 9 WHEN 'J3' THEN 10 ELSE 99 END, e.last_name
    `, params);

    const isAdmin = session.role === "HR_ADMIN";
    const csv = toCsv(
      ["社員番号", "氏名", "部門", "等級", "役職", "入社日", "雇用区分", "年齢", "勤続年数", "上司", "平均評価", "最新グレード", "離職リスク", "リスクレベル", "関係性スコア"],
      rows.map((r) => [
        r.employee_code, r.name, r.dept_name, r.grade, r.title,
        r.hire_date ? String(r.hire_date).slice(0, 10) : "",
        r.employment_type, r.age, r.tenure_years, r.manager_name || "",
        isAdmin ? (r.avg_score ?? "") : "***",
        isAdmin ? (r.latest_grade ?? "") : "***",
        r.risk_score != null ? Number(r.risk_score).toFixed(3) : "",
        r.risk_label || "",
        r.relationship_score != null ? Number(r.relationship_score).toFixed(3) : "",
      ])
    );

    return new NextResponse(csv, {
      headers: {
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": `attachment; filename="workforce_roster_${new Date().toISOString().slice(0, 10)}.csv"`,
      },
    });
  } catch (error) {
    console.error("Workforce export error:", error);
    return NextResponse.json({ error: "エクスポートに失敗しました" }, { status: 500 });
  }
}
