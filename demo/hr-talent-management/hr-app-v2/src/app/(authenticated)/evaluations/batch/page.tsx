"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  ArrowLeft,
  Search,
  Save,
  Loader2,
  CheckCircle,
  AlertTriangle,
  TrendingDown,
  TrendingUp,
  BarChart3,
  ChevronDown,
  ChevronRight,
  History,
  Users,
  FileCheck,
  FilePen,
  Brain,
} from "lucide-react";
import Link from "next/link";
import { useHonbu } from "@/lib/honbu-context";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  ResponsiveContainer,
  Cell,
  LineChart,
  Line,
  CartesianGrid,
  Tooltip as RTooltip,
} from "recharts";

function generatePeriods(): string[] {
  const now = new Date();
  const year = now.getFullYear();
  const half = now.getMonth() >= 6 ? "H2" : "H1";
  const periods: string[] = [];
  let y = year;
  let h = half;
  for (let i = 0; i < 6; i++) {
    periods.push(`${y}-${h}`);
    if (h === "H1") { h = "H2"; y--; } else { h = "H1"; }
  }
  return periods;
}
const PERIODS = generatePeriods();
const GRADES = ["S", "A", "B", "C", "D"];
const GRADE_COLORS: Record<string, string> = {
  S: "#ef4444", A: "#f97316", B: "#3b82f6", C: "#6b7280", D: "#9ca3af",
};

interface Employee {
  EMPLOYEE_ID: number;
  NAME: string;
  EMPLOYEE_CODE: string;
  DEPT_ID: number;
  DEPT_NAME: string;
  GRADE: string;
  POSITION_TITLE: string;
  MANAGER_ID: number | null;
  MANAGER_NAME: string | null;
}

interface CurrentEval {
  EVALUATION_ID: number;
  EMPLOYEE_ID: number;
  SCORE: number | null;
  GRADE: string | null;
  COMMENT: string | null;
  SELF_SCORE: number | null;
  SELF_COMMENT: string | null;
  STATUS: string;
  EVALUATOR_NAME: string | null;
}

interface EvalHistory {
  EMPLOYEE_ID: number;
  PERIOD: string;
  SCORE: number | null;
  GRADE: string | null;
}

interface Distribution {
  DEPT_ID: number;
  DEPT_NAME: string;
  GRADE: string;
  COUNT: number;
}

interface AttritionRisk {
  EMPLOYEE_ID: number;
  RISK_SCORE: number;
  RISK_LABEL: string;
}

interface DeptOption {
  DEPT_ID: number;
  DEPT_NAME: string;
}

interface EditState {
  score: string;
  grade: string;
  comment: string;
  dirty: boolean;
}

function autoGrade(s: number): string {
  if (s >= 4.5) return "S";
  if (s >= 4.0) return "A";
  if (s >= 3.0) return "B";
  if (s >= 2.0) return "C";
  return "D";
}

function riskBadge(label: string) {
  if (label === "high") return <Badge variant="destructive" className="text-[9px]">高</Badge>;
  if (label === "medium") return <Badge className="text-[9px] bg-amber-100 text-amber-800">中</Badge>;
  return null;
}

export default function EvaluationBatchPage() {
  const { honbu, setHonbu, honbuList } = useHonbu();

  const [mode, setMode] = useState<"primary" | "secondary">("primary");
  const [period, setPeriod] = useState(PERIODS[0]);
  const [selectedDeptId, setSelectedDeptId] = useState<string>("");


  const [employees, setEmployees] = useState<Employee[]>([]);
  const [currentEvals, setCurrentEvals] = useState<CurrentEval[]>([]);
  const [history, setHistory] = useState<EvalHistory[]>([]);
  const [distribution, setDistribution] = useState<Distribution[]>([]);
  const [attritionRisks, setAttritionRisks] = useState<AttritionRisk[]>([]);
  const [depts, setDepts] = useState<DeptOption[]>([]);
  const [childDepts, setChildDepts] = useState<DeptOption[]>([]);

  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [expandedDepts, setExpandedDepts] = useState<Set<number>>(new Set());

  const [edits, setEdits] = useState<Record<number, EditState>>({});
  const [historyDialogEmp, setHistoryDialogEmp] = useState<Employee | null>(null);

  useEffect(() => {
    if (honbu) {
      const params = new URLSearchParams({ honbu_id: honbu, depts_only: "true" });
      fetch(`/api/evaluations/batch?${params}`)
        .then((r) => r.json())
        .then((res) => {
          if (res.depts) setChildDepts(res.depts);
          if (res.depts?.length > 0 && !selectedDeptId) {
            setSelectedDeptId(String(res.depts[0].DEPT_ID));
          }
        })
        .catch((err) => console.error("[child depts fetch] failed:", err));
    }
  }, [honbu]);

  const fetchData = useCallback(() => {
    if (mode === "primary" && !selectedDeptId) return;
    if (mode === "secondary" && !honbu) return;
    setLoading(true);

    const params = new URLSearchParams({ period, mode });
    if (mode === "primary") params.set("dept_id", selectedDeptId);
    else params.set("honbu_id", honbu);

    fetch(`/api/evaluations/batch?${params}`)
      .then((r) => r.json())
      .then((res) => {
        setEmployees(res.employees || []);
        setCurrentEvals(res.currentEvals || []);
        setHistory(res.history || []);
        setDistribution(res.distribution || []);
        setAttritionRisks(res.attritionRisks || []);
        if (res.depts) setDepts(res.depts);

        const editMap: Record<number, EditState> = {};
        for (const emp of res.employees || []) {
          const ev = (res.currentEvals || []).find((e: CurrentEval) => e.EMPLOYEE_ID === emp.EMPLOYEE_ID);
          editMap[emp.EMPLOYEE_ID] = {
            score: ev?.SCORE != null ? String(Number(ev.SCORE)) : "",
            grade: ev?.GRADE || "",
            comment: ev?.COMMENT || "",
            dirty: false,
          };
        }
        setEdits(editMap);

        if (mode === "secondary" && res.depts?.length) {
          setExpandedDepts(new Set(res.depts.map((d: DeptOption) => d.DEPT_ID)));
        }
      })
      .finally(() => setLoading(false));
  }, [mode, selectedDeptId, honbu, period]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const evalMap = useMemo(() => {
    const m = new Map<number, CurrentEval>();
    currentEvals.forEach((e) => m.set(e.EMPLOYEE_ID, e));
    return m;
  }, [currentEvals]);

  const riskMap = useMemo(() => {
    const m = new Map<number, AttritionRisk>();
    attritionRisks.forEach((r) => m.set(r.EMPLOYEE_ID, r));
    return m;
  }, [attritionRisks]);

  const historyMap = useMemo(() => {
    const m = new Map<number, EvalHistory[]>();
    history.forEach((h) => {
      if (!m.has(h.EMPLOYEE_ID)) m.set(h.EMPLOYEE_ID, []);
      m.get(h.EMPLOYEE_ID)!.push(h);
    });
    return m;
  }, [history]);

  const groupedByDept = useMemo(() => {
    const groups = new Map<number, { dept: string; employees: Employee[] }>();
    for (const emp of employees) {
      if (!groups.has(emp.DEPT_ID)) groups.set(emp.DEPT_ID, { dept: emp.DEPT_NAME, employees: [] });
      groups.get(emp.DEPT_ID)!.employees.push(emp);
    }
    return groups;
  }, [employees]);

  const filteredEmployees = useMemo(() => {
    if (!searchQuery.trim()) return employees;
    const q = searchQuery.toLowerCase();
    return employees.filter((e) =>
      e.NAME.toLowerCase().includes(q) ||
      e.EMPLOYEE_CODE.toLowerCase().includes(q) ||
      e.DEPT_NAME.toLowerCase().includes(q)
    );
  }, [employees, searchQuery]);

  const overallDistribution = useMemo(() => {
    const counts: Record<string, number> = { S: 0, A: 0, B: 0, C: 0, D: 0 };
    Object.values(edits).forEach((e) => {
      if (e.grade && counts[e.grade] !== undefined) counts[e.grade]++;
    });
    return GRADES.map((g) => ({ grade: g, count: counts[g] || 0 }));
  }, [edits]);

  const deptDistribution = useMemo(() => {
    const byDept = new Map<number, Record<string, number>>();
    for (const emp of employees) {
      if (!byDept.has(emp.DEPT_ID)) byDept.set(emp.DEPT_ID, { S: 0, A: 0, B: 0, C: 0, D: 0 });
      const edit = edits[emp.EMPLOYEE_ID];
      if (edit?.grade) {
        const counts = byDept.get(emp.DEPT_ID)!;
        if (counts[edit.grade] !== undefined) counts[edit.grade]++;
      }
    }
    return byDept;
  }, [employees, edits]);

  const dirtyCount = useMemo(() => Object.values(edits).filter((e) => e.dirty).length, [edits]);

  const updateEdit = (empId: number, field: keyof EditState, value: string) => {
    setEdits((prev) => {
      const current = prev[empId] || { score: "", grade: "", comment: "", dirty: false };
      const updated = { ...current, [field]: value, dirty: true };
      if (field === "score") {
        const n = parseFloat(value);
        if (!isNaN(n) && n >= 1 && n <= 5) {
          updated.grade = autoGrade(n);
        }
      }
      return { ...prev, [empId]: updated };
    });
  };

  const handleSave = async (status: "draft" | "confirmed") => {
    const dirtyEdits = Object.entries(edits)
      .filter(([, e]) => e.dirty && e.score && e.grade)
      .map(([empIdStr, e]) => {
        const empId = Number(empIdStr);
        const emp = employees.find((em) => em.EMPLOYEE_ID === empId);
        return {
          employee_id: empId,
          evaluator_id: emp?.MANAGER_ID || empId,
          score: parseFloat(e.score),
          grade: e.grade,
          comment: e.comment || undefined,
          status,
        };
      });

    if (dirtyEdits.length === 0) return;

    setSaving(true);
    try {
      const res = await fetch("/api/evaluations/batch", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ evaluations: dirtyEdits, period }),
      });
      if (!res.ok) throw new Error("Failed");
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
      setEdits((prev) => {
        const next = { ...prev };
        for (const de of dirtyEdits) {
          if (next[de.employee_id]) next[de.employee_id] = { ...next[de.employee_id], dirty: false };
        }
        return next;
      });
    } catch {
      setSaveError("保存に失敗しました");
    } finally {
      setSaving(false);
    }
  };

  const toggleDept = (deptId: number) => {
    setExpandedDepts((prev) => {
      const next = new Set(prev);
      if (next.has(deptId)) next.delete(deptId);
      else next.add(deptId);
      return next;
    });
  };

  const dashboardStats = useMemo(() => {
    const totalEmps = employees.length;
    const evaluated = currentEvals.length;
    const confirmed = currentEvals.filter((e) => e.STATUS === "confirmed").length;
    const draft = currentEvals.filter((e) => e.STATUS === "draft").length;
    const notStarted = totalEmps - evaluated;
    const completionRate = totalEmps > 0 ? ((confirmed / totalEmps) * 100).toFixed(0) : "0";
    return { totalEmps, evaluated, confirmed, draft, notStarted, completionRate };
  }, [employees, currentEvals]);

  const empHistory = historyDialogEmp ? historyMap.get(historyDialogEmp.EMPLOYEE_ID) || [] : [];
  const empRisk = historyDialogEmp ? riskMap.get(historyDialogEmp.EMPLOYEE_ID) : undefined;

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center gap-4 flex-wrap">
        <Link href="/evaluations">
          <Button variant="ghost" size="icon" className="h-8 w-8">
            <ArrowLeft className="h-4 w-4" />
          </Button>
        </Link>
        <h2 className="text-2xl font-bold tracking-tight">評価入力</h2>
        <Select value={honbu} onValueChange={(v) => v && setHonbu(v)}>
          <SelectTrigger className="w-64">
            <SelectValue placeholder="本部を選択">
              {honbuList.find((d) => String(d.DEPT_ID) === honbu)?.DEPT_NAME || "本部を選択"}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            {honbuList.map((d) => (
              <SelectItem key={d.DEPT_ID} value={String(d.DEPT_ID)}>
                {d.DEPT_NAME}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="ml-auto flex gap-2 items-center">
          <Link href={`/evaluations/cross-review`}>
            <Button variant="outline" size="sm" className="gap-1.5">
              <Brain className="h-3.5 w-3.5" />
              横断レビュー
            </Button>
          </Link>
          {saveSuccess && (
            <span className="flex items-center gap-1 text-sm text-green-600">
              <CheckCircle className="h-4 w-4" />
              保存しました
            </span>
          )}
          {dirtyCount > 0 && (
            <Badge variant="secondary">{dirtyCount}件 未保存</Badge>
          )}
          <Button
            variant="outline"
            onClick={() => handleSave("draft")}
            disabled={saving || dirtyCount === 0}
            className="gap-1.5"
          >
            {saving && <Loader2 className="h-4 w-4 animate-spin" />}
            <Save className="h-4 w-4" />
            下書き保存
          </Button>
          <Button
            onClick={() => handleSave("confirmed")}
            disabled={saving || dirtyCount === 0}
            className="gap-1.5"
          >
            {saving && <Loader2 className="h-4 w-4 animate-spin" />}
            確定保存
          </Button>
        </div>
      </div>

      <div className="flex gap-3 flex-wrap items-center">
        <div className="flex rounded-lg border overflow-hidden">
          <button
            className={`px-4 py-2 text-sm font-medium transition-colors ${mode === "primary" ? "bg-primary text-primary-foreground" : "hover:bg-accent"}`}
            onClick={() => setMode("primary")}
          >
            一次評価（部署）
          </button>
          <button
            className={`px-4 py-2 text-sm font-medium transition-colors ${mode === "secondary" ? "bg-primary text-primary-foreground" : "hover:bg-accent"}`}
            onClick={() => setMode("secondary")}
          >
            二次評価（本部）
          </button>
        </div>

        <Select value={period} onValueChange={(v) => v && setPeriod(v)}>
          <SelectTrigger className="w-36">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {PERIODS.map((p) => (
              <SelectItem key={p} value={p}>{p}</SelectItem>
            ))}
          </SelectContent>
        </Select>

        {mode === "primary" && (
          <Select value={selectedDeptId} onValueChange={(v) => v && setSelectedDeptId(v)}>
            <SelectTrigger className="w-56">
              <SelectValue placeholder="部署を選択">
                {childDepts.find((d) => String(d.DEPT_ID) === selectedDeptId)?.DEPT_NAME || "部署を選択"}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {childDepts.map((d) => (
                <SelectItem key={d.DEPT_ID} value={String(d.DEPT_ID)}>
                  {d.DEPT_NAME}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}

        <div className="relative">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="社員名で検索"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9 w-48"
          />
        </div>
      </div>

      {employees.length > 0 && (
        <div className="grid grid-cols-4 gap-3">
          <Card>
            <CardContent className="pt-4 pb-3">
              <div className="flex items-center gap-2 mb-1">
                <Users className="h-4 w-4 text-muted-foreground" />
                <p className="text-xs text-muted-foreground">対象社員</p>
              </div>
              <p className="text-2xl font-bold">{dashboardStats.totalEmps}<span className="text-sm font-normal text-muted-foreground ml-1">名</span></p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-4 pb-3">
              <div className="flex items-center gap-2 mb-1">
                <FileCheck className="h-4 w-4 text-green-600" />
                <p className="text-xs text-muted-foreground">確定済み</p>
              </div>
              <p className="text-2xl font-bold text-green-600">{dashboardStats.confirmed}<span className="text-sm font-normal text-muted-foreground ml-1">名</span></p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-4 pb-3">
              <div className="flex items-center gap-2 mb-1">
                <FilePen className="h-4 w-4 text-blue-600" />
                <p className="text-xs text-muted-foreground">下書き / 未着手</p>
              </div>
              <p className="text-2xl font-bold">
                <span className="text-blue-600">{dashboardStats.draft}</span>
                <span className="text-muted-foreground mx-1">/</span>
                <span className="text-orange-500">{dashboardStats.notStarted}</span>
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-4 pb-3">
              <div className="flex items-center gap-2 mb-1">
                <BarChart3 className="h-4 w-4 text-muted-foreground" />
                <p className="text-xs text-muted-foreground">完了率</p>
              </div>
              <div className="flex items-end gap-2">
                <p className="text-2xl font-bold">{dashboardStats.completionRate}<span className="text-sm font-normal text-muted-foreground">%</span></p>
                <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden mb-1.5">
                  <div
                    className="h-full bg-green-500 rounded-full transition-all"
                    style={{ width: `${dashboardStats.completionRate}%` }}
                  />
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      <div className="grid grid-cols-12 gap-4">
        <div className="col-span-9">
          {loading ? (
            <Card>
              <CardContent className="pt-6 space-y-2">
                {[...Array(8)].map((_, i) => <Skeleton key={i} className="h-12" />)}
              </CardContent>
            </Card>
          ) : employees.length === 0 ? (
            <Card>
              <CardContent className="pt-6 flex items-center justify-center h-40 text-muted-foreground">
                部署を選択してください
              </CardContent>
            </Card>
          ) : mode === "primary" ? (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">
                  {employees[0]?.DEPT_NAME} — {filteredEmployees.length}名
                </CardTitle>
              </CardHeader>
              <CardContent>
                <EvalTable
                  employees={filteredEmployees}
                  edits={edits}
                  evalMap={evalMap}
                  riskMap={riskMap}
                  historyMap={historyMap}
                  onEdit={updateEdit}
                  onShowHistory={setHistoryDialogEmp}
                />
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-2">
              {Array.from(groupedByDept.entries()).map(([deptId, group]) => {
                const isExpanded = expandedDepts.has(deptId);
                const deptEmps = searchQuery.trim()
                  ? group.employees.filter((e) =>
                      e.NAME.toLowerCase().includes(searchQuery.toLowerCase()) ||
                      e.EMPLOYEE_CODE.toLowerCase().includes(searchQuery.toLowerCase())
                    )
                  : group.employees;
                if (searchQuery.trim() && deptEmps.length === 0) return null;
                const deptDist = deptDistribution.get(deptId);
                return (
                  <Card key={deptId}>
                    <button
                      className="w-full flex items-center gap-3 p-4 hover:bg-accent/50 transition-colors text-left"
                      onClick={() => toggleDept(deptId)}
                    >
                      {isExpanded ? <ChevronDown className="h-4 w-4 shrink-0" /> : <ChevronRight className="h-4 w-4 shrink-0" />}
                      <span className="font-semibold">{group.dept}</span>
                      <Badge variant="secondary" className="text-xs">{deptEmps.length}名</Badge>
                      {deptDist && (
                        <div className="flex gap-1 ml-auto">
                          {GRADES.map((g) => (
                            deptDist[g] > 0 && (
                              <span key={g} className="text-[10px] px-1.5 py-0.5 rounded" style={{ backgroundColor: GRADE_COLORS[g] + "20", color: GRADE_COLORS[g] }}>
                                {g}:{deptDist[g]}
                              </span>
                            )
                          ))}
                        </div>
                      )}
                    </button>
                    {isExpanded && (
                      <CardContent className="pt-0 pb-3">
                        <EvalTable
                          employees={deptEmps}
                          edits={edits}
                          evalMap={evalMap}
                          riskMap={riskMap}
                          historyMap={historyMap}
                          onEdit={updateEdit}
                          onShowHistory={setHistoryDialogEmp}
                        />
                      </CardContent>
                    )}
                  </Card>
                );
              })}
            </div>
          )}
        </div>

        <div className="col-span-3 space-y-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-1.5">
                <BarChart3 className="h-4 w-4" />
                評価分布（現在の入力）
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={160}>
                <BarChart data={overallDistribution}>
                  <XAxis dataKey="grade" tick={{ fontSize: 12 }} />
                  <YAxis tick={{ fontSize: 10 }} width={30} />
                  <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                    {overallDistribution.map((d, i) => (
                      <Cell key={i} fill={GRADE_COLORS[d.grade] || "#ccc"} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
              <div className="text-[11px] text-muted-foreground mt-2 space-y-0.5">
                {overallDistribution.map((d) => (
                  <div key={d.grade} className="flex justify-between">
                    <span>{d.grade}</span>
                    <span>{d.count}名 ({employees.length > 0 ? ((d.count / employees.length) * 100).toFixed(0) : 0}%)</span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          {mode === "secondary" && Array.from(groupedByDept.entries()).length > 0 && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">部署別 評価分布（入力中）</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {Array.from(groupedByDept.entries()).map(([deptId, group]) => {
                  const dist = deptDistribution.get(deptId);
                  if (!dist) return null;
                  const total = group.employees.length;
                  const chartData = GRADES.map((g) => ({ grade: g, count: dist[g] || 0 }));
                  return (
                    <div key={deptId}>
                      <p className="text-[11px] font-medium mb-1">{group.dept} ({total}名)</p>
                      <ResponsiveContainer width="100%" height={80}>
                        <BarChart data={chartData} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
                          <XAxis dataKey="grade" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                          <YAxis tick={{ fontSize: 9 }} width={30} allowDecimals={false} />
                          <Bar dataKey="count" radius={[3, 3, 0, 0]}>
                            {chartData.map((d, i) => (
                              <Cell key={i} fill={GRADE_COLORS[d.grade] || "#ccc"} />
                            ))}
                          </Bar>
                        </BarChart>
                      </ResponsiveContainer>
                      <div className="flex gap-2 text-[10px] text-muted-foreground mt-0.5">
                        {GRADES.map((g) => dist[g] > 0 && (
                          <span key={g} style={{ color: GRADE_COLORS[g] }}>{g}:{dist[g]}</span>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </CardContent>
            </Card>
          )}

          {distribution.length > 0 && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">前回確定分布</CardTitle>
                <CardDescription className="text-[11px]">DBに保存済みの{period}評価</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {Array.from(new Set(distribution.map((d) => d.DEPT_NAME))).map((deptName) => {
                    const deptDist = distribution.filter((d) => d.DEPT_NAME === deptName);
                    const total = deptDist.reduce((s, d) => s + d.COUNT, 0);
                    return (
                      <div key={deptName}>
                        <p className="text-[11px] font-medium mb-0.5">{deptName} ({total}名)</p>
                        <div className="flex h-4 rounded-full overflow-hidden">
                          {GRADES.map((g) => {
                            const d = deptDist.find((dd) => dd.GRADE === g);
                            if (!d || d.COUNT === 0) return null;
                            const pct = (d.COUNT / total) * 100;
                            return (
                              <div
                                key={g}
                                title={`${g}: ${d.COUNT}名 (${pct.toFixed(0)}%)`}
                                style={{ width: `${pct}%`, backgroundColor: GRADE_COLORS[g] }}
                                className="h-full"
                              />
                            );
                          })}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </CardContent>
            </Card>
          )}

          <Card className="border-amber-200 bg-amber-50/30">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-1.5 text-amber-700">
                <AlertTriangle className="h-4 w-4" />
                離職リスク注意
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-1">
                {employees
                  .filter((e) => {
                    const r = riskMap.get(e.EMPLOYEE_ID);
                    return r && (r.RISK_LABEL === "high" || r.RISK_LABEL === "medium");
                  })
                  .sort((a, b) => (riskMap.get(b.EMPLOYEE_ID)?.RISK_SCORE || 0) - (riskMap.get(a.EMPLOYEE_ID)?.RISK_SCORE || 0))
                  .slice(0, 10)
                  .map((e) => {
                    const r = riskMap.get(e.EMPLOYEE_ID)!;
                    return (
                      <div key={e.EMPLOYEE_ID} className="flex items-center gap-2 text-xs p-1.5 rounded bg-white border">
                        {riskBadge(r.RISK_LABEL)}
                        <Link href={`/employees/${e.EMPLOYEE_ID}`} className="font-medium hover:underline text-blue-600">{e.NAME}</Link>
                        <span className="text-muted-foreground ml-auto font-mono">{(r.RISK_SCORE * 100).toFixed(0)}%</span>
                      </div>
                    );
                  })}
                {employees.filter((e) => {
                  const r = riskMap.get(e.EMPLOYEE_ID);
                  return r && (r.RISK_LABEL === "high" || r.RISK_LABEL === "medium");
                }).length === 0 && (
                  <p className="text-xs text-muted-foreground">リスク対象者なし</p>
                )}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>

      <Dialog open={!!historyDialogEmp} onOpenChange={(o) => !o && setHistoryDialogEmp(null)}>
        <DialogContent className="sm:max-w-lg">
          {historyDialogEmp && (
            <>
              <DialogHeader>
                <DialogTitle className="flex items-center gap-2">
                  <History className="h-4 w-4" />
                  {historyDialogEmp.NAME} — 評価推移
                </DialogTitle>
              </DialogHeader>
              <div className="space-y-4">
                {empRisk && (
                  <div className="flex items-center gap-2 p-2 rounded-md bg-amber-50 border border-amber-200 text-sm">
                    <AlertTriangle className="h-4 w-4 text-amber-600" />
                    離職リスク: {riskBadge(empRisk.RISK_LABEL)}
                    <span className="font-mono ml-auto">{(empRisk.RISK_SCORE * 100).toFixed(0)}%</span>
                  </div>
                )}

                {empHistory.length > 0 ? (
                  <>
                    <ResponsiveContainer width="100%" height={180}>
                      <LineChart data={empHistory.sort((a, b) => a.PERIOD.localeCompare(b.PERIOD))}>
                        <CartesianGrid strokeDasharray="3 3" />
                        <XAxis dataKey="PERIOD" tick={{ fontSize: 11 }} />
                        <YAxis domain={[1, 5]} tick={{ fontSize: 11 }} width={30} />
                        <RTooltip formatter={(v: number) => [Number(v).toFixed(1), "スコア"]} />
                        <Line
                          type="monotone"
                          dataKey="SCORE"
                          stroke="var(--color-chart-1)"
                          strokeWidth={2}
                          dot={{ r: 4 }}
                          connectNulls
                        />
                      </LineChart>
                    </ResponsiveContainer>

                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>期間</TableHead>
                          <TableHead>スコア</TableHead>
                          <TableHead>グレード</TableHead>
                          <TableHead>推移</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {empHistory
                          .sort((a, b) => b.PERIOD.localeCompare(a.PERIOD))
                          .map((h, i, arr) => {
                            const prev = arr[i + 1];
                            const diff = prev?.SCORE != null && h.SCORE != null ? Number(h.SCORE) - Number(prev.SCORE) : null;
                            return (
                              <TableRow key={h.PERIOD}>
                                <TableCell className="font-mono text-xs">{h.PERIOD}</TableCell>
                                <TableCell className="font-mono">{h.SCORE != null ? Number(h.SCORE).toFixed(1) : "—"}</TableCell>
                                <TableCell>
                                  {h.GRADE && (
                                    <Badge
                                      variant={h.GRADE === "S" ? "destructive" : h.GRADE === "A" ? "default" : "secondary"}
                                    >
                                      {h.GRADE}
                                    </Badge>
                                  )}
                                </TableCell>
                                <TableCell>
                                  {diff !== null && (
                                    <span className={`flex items-center gap-1 text-xs ${diff > 0 ? "text-green-600" : diff < 0 ? "text-red-600" : "text-muted-foreground"}`}>
                                      {diff > 0 ? <TrendingUp className="h-3 w-3" /> : diff < 0 ? <TrendingDown className="h-3 w-3" /> : null}
                                      {diff > 0 ? "+" : ""}{diff.toFixed(1)}
                                    </span>
                                  )}
                                </TableCell>
                              </TableRow>
                            );
                          })}
                      </TableBody>
                    </Table>
                  </>
                ) : (
                  <p className="text-sm text-muted-foreground text-center py-4">評価履歴なし</p>
                )}

                <div className="flex justify-end">
                  <Link href={`/employees/${historyDialogEmp.EMPLOYEE_ID}`}>
                    <Button variant="outline" size="sm" className="gap-1.5 text-xs">
                      社員詳細を表示
                    </Button>
                  </Link>
                </div>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function EvalTable({
  employees,
  edits,
  evalMap,
  riskMap,
  historyMap,
  onEdit,
  onShowHistory,
}: {
  employees: Employee[];
  edits: Record<number, EditState>;
  evalMap: Map<number, CurrentEval>;
  riskMap: Map<number, AttritionRisk>;
  historyMap: Map<number, EvalHistory[]>;
  onEdit: (empId: number, field: keyof EditState, value: string) => void;
  onShowHistory: (emp: Employee) => void;
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-[140px]">社員</TableHead>
          <TableHead className="w-[60px]">等級</TableHead>
          <TableHead className="w-[60px]">リスク</TableHead>
          <TableHead className="w-[110px]">前期実績</TableHead>
          <TableHead className="w-[90px]">スコア</TableHead>
          <TableHead className="w-[80px]">グレード</TableHead>
          <TableHead>コメント</TableHead>
          <TableHead className="w-[50px]">履歴</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {employees.map((emp) => {
          const edit = edits[emp.EMPLOYEE_ID] || { score: "", grade: "", comment: "", dirty: false };
          const risk = riskMap.get(emp.EMPLOYEE_ID);
          const hist = historyMap.get(emp.EMPLOYEE_ID) || [];
          const prevEval = hist.sort((a, b) => b.PERIOD.localeCompare(a.PERIOD))[0];
          const existing = evalMap.get(emp.EMPLOYEE_ID);

          return (
            <TableRow key={emp.EMPLOYEE_ID} className={edit.dirty ? "bg-blue-50/50" : ""}>
              <TableCell>
                <Link href={`/employees/${emp.EMPLOYEE_ID}`} className="text-blue-600 hover:underline text-sm font-medium">
                  {emp.NAME}
                </Link>
                <p className="text-[10px] text-muted-foreground">{emp.POSITION_TITLE}</p>
              </TableCell>
              <TableCell>
                <Badge variant="outline" className="text-[10px]">{emp.GRADE}</Badge>
              </TableCell>
              <TableCell>
                {risk && (risk.RISK_LABEL === "high" || risk.RISK_LABEL === "medium") ? (
                  riskBadge(risk.RISK_LABEL)
                ) : (
                  <span className="text-[10px] text-muted-foreground">—</span>
                )}
              </TableCell>
              <TableCell>
                {prevEval?.GRADE || prevEval?.SCORE != null ? (
                  <div className="flex items-center gap-1.5">
                    {prevEval.GRADE && (
                      <Badge
                        variant={prevEval.GRADE === "S" ? "destructive" : prevEval.GRADE === "A" ? "default" : "secondary"}
                        className="text-[10px]"
                      >
                        {prevEval.GRADE}
                      </Badge>
                    )}
                    {prevEval.SCORE != null && (
                      <span className="text-[11px] font-mono text-muted-foreground">
                        {Number(prevEval.SCORE).toFixed(1)}
                      </span>
                    )}
                    {(() => {
                      const cur = parseFloat(edit.score);
                      if (prevEval.SCORE == null || isNaN(cur)) return null;
                      const delta = cur - Number(prevEval.SCORE);
                      if (Math.abs(delta) < 0.05) {
                        return <span className="text-[10px] text-muted-foreground">±0</span>;
                      }
                      const up = delta > 0;
                      return (
                        <span className={`inline-flex items-center text-[10px] font-medium ${up ? "text-emerald-600" : "text-red-600"}`}>
                          {up ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
                          {up ? "+" : ""}{delta.toFixed(1)}
                        </span>
                      );
                    })()}
                  </div>
                ) : (
                  <span className="text-[10px] text-muted-foreground">—</span>
                )}
              </TableCell>
              <TableCell>
                <Input
                  type="number"
                  min={1}
                  max={5}
                  step={0.1}
                  value={edit.score}
                  onChange={(e) => onEdit(emp.EMPLOYEE_ID, "score", e.target.value)}
                  className="h-8 text-sm w-20"
                  placeholder="3.5"
                />
              </TableCell>
              <TableCell>
                <Select value={edit.grade} onValueChange={(v) => v && onEdit(emp.EMPLOYEE_ID, "grade", v)}>
                  <SelectTrigger className="h-8 text-xs w-16">
                    <SelectValue placeholder="—" />
                  </SelectTrigger>
                  <SelectContent>
                    {GRADES.map((g) => (
                      <SelectItem key={g} value={g}>{g}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </TableCell>
              <TableCell>
                <Input
                  value={edit.comment}
                  onChange={(e) => onEdit(emp.EMPLOYEE_ID, "comment", e.target.value)}
                  className="h-8 text-xs"
                  placeholder="コメント..."
                />
              </TableCell>
              <TableCell>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7"
                  onClick={() => onShowHistory(emp)}
                >
                  <History className="h-3.5 w-3.5" />
                </Button>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
