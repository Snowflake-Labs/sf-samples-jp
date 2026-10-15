"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Progress } from "@/components/ui/progress";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Users,
  Briefcase,
  AlertTriangle,
  ShieldAlert,
  ArrowUpDown,
  TrendingDown,
  ChevronRight,
  Activity,
  BarChart3,
  ArrowRightLeft,
  ArrowUp,
  LogOut,
  ArrowDownRight,
  ArrowUpRight,
  GitBranch,
  Download,
} from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RTooltip,
  ResponsiveContainer,
  Cell,
  PieChart,
  Pie,
  Legend,
} from "recharts";
import { useHonbu } from "@/lib/honbu-context";
import { GRADE_LABELS } from "@/lib/types";

interface Summary {
  headcount: number;
  avgTenure: number;
  vacantCount: number;
  riskHigh: number;
  riskMedium: number;
  riskLow: number;
}

interface GradeRow {
  grade: string;
  empCount: number;
  vacantCount: number;
}

interface DeptHeat {
  DEPT_ID: number;
  DEPT_NAME: string;
  EMP_COUNT: number;
  AVG_TENURE: number;
  VACANT_COUNT: number;
  AVG_EVAL: number;
  RISK_HIGH: number;
  RISK_MEDIUM: number;
}

interface WatchItem {
  EMPLOYEE_ID: number;
  NAME: string;
  DEPT_NAME: string;
  GRADE: string;
  POSITION_TITLE: string;
  TENURE_YEARS: number;
  RISK_SCORE: number;
  RISK_LABEL: string;
  REL_SCORE: number;
  AVG_EVAL: number;
}

interface CareerEvent {
  ID: number;
  DATE: string;
  TYPE: string;
  NAME: string;
  GRADE: string;
  FROM_DEPT: string | null;
  TO_DEPT: string | null;
  FROM_POS: string | null;
  TO_POS: string | null;
  NOTES: string;
}

interface MonthlyFlow {
  MONTH: string;
  TYPE: string;
  COUNT: number;
}

interface DeptFlow {
  FLOW_TYPE: string;
  DEPT: string;
  TO_DEPT: string | null;
  COUNT: number;
}

interface CareerHistory {
  recentChanges: CareerEvent[];
  monthlyFlow: MonthlyFlow[];
  deptFlow: DeptFlow[];
}

interface OverviewData {
  summary: Summary;
  gradePyramid: GradeRow[];
  deptHeatmap: DeptHeat[];
  watchList: WatchItem[];
  careerHistory: CareerHistory;
}

const GRADE_HEX: Record<string, string> = {
  E1: "#dc2626", D1: "#ea580c", D2: "#d97706",
  M1: "#ca8a04", M2: "#65a30d", S1: "#16a34a",
  S2: "#0d9488", J1: "#0891b2", J2: "#2563eb", J3: "#7c3aed",
};

const RISK_COLORS = { high: "#ef4444", medium: "#f97316", low: "#22c55e" };

function evalColor(score: number): string {
  if (score >= 4.0) return "text-green-700";
  if (score >= 3.0) return "text-amber-700";
  return "text-red-700";
}

function riskBadge(label: string, score?: number) {
  const variant = label === "high" ? "destructive" : label === "medium" ? "default" : "secondary";
  const text = label === "high" ? "高" : label === "medium" ? "中" : "低";
  return (
    <Badge variant={variant} className="text-[10px] gap-0.5">
      {text}
      {score !== undefined && <span className="font-mono ml-0.5">{(score * 100).toFixed(0)}%</span>}
    </Badge>
  );
}

function relScoreBar(score: number) {
  const pct = Math.round(score * 100);
  const color = score < 0.3 ? "bg-red-500" : score < 0.6 ? "bg-amber-500" : "bg-green-500";
  return (
    <div className="flex items-center gap-1.5">
      <div className="w-16 h-1.5 bg-muted rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className={`text-[10px] font-mono tabular-nums ${score < 0.3 ? "text-red-600" : score < 0.6 ? "text-amber-600" : "text-green-600"}`}>
        {pct}%
      </span>
    </div>
  );
}

export default function WorkforceOverviewPage() {
  const [data, setData] = useState<OverviewData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { honbu, setHonbu, honbuList } = useHonbu();
  const [sortCol, setSortCol] = useState<string>("EMP_COUNT");
  const [sortAsc, setSortAsc] = useState(false);

  const fetchData = useCallback((h: string) => {
    if (!h) return;
    setLoading(true);
    setError(null);
    fetch(`/api/workforce-overview?honbu=${h}`)
      .then((r) => {
        if (!r.ok) throw new Error("Failed");
        return r.json();
      })
      .then(setData)
      .catch(() => setError("データの取得に失敗しました"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (honbu) fetchData(honbu);
  }, [honbu, fetchData]);

  const sortedDepts = useMemo(() => {
    if (!data?.deptHeatmap) return [];
    return [...data.deptHeatmap].sort((a, b) => {
      const aVal = Number(a[sortCol as keyof DeptHeat]) || 0;
      const bVal = Number(b[sortCol as keyof DeptHeat]) || 0;
      return sortAsc ? aVal - bVal : bVal - aVal;
    });
  }, [data?.deptHeatmap, sortCol, sortAsc]);

  const riskPieData = useMemo(() => {
    if (!data) return [];
    return [
      { name: "高リスク", value: data.summary.riskHigh, fill: RISK_COLORS.high },
      { name: "中リスク", value: data.summary.riskMedium, fill: RISK_COLORS.medium },
      { name: "低リスク", value: data.summary.riskLow, fill: RISK_COLORS.low },
    ].filter((d) => d.value > 0);
  }, [data]);

  const handleSort = (col: string) => {
    if (sortCol === col) setSortAsc(!sortAsc);
    else { setSortCol(col); setSortAsc(false); }
  };

  const honbuName = honbuList.find((d) => String(d.DEPT_ID) === honbu)?.DEPT_NAME || "本部を選択";

  return (
    <TooltipProvider>
      <div className="p-6 space-y-5 max-w-[1400px] mx-auto">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-gradient-to-br from-blue-500 to-indigo-600">
              <BarChart3 className="h-5 w-5 text-white" />
            </div>
            <div>
              <h2 className="text-xl font-bold tracking-tight">異動ダッシュボード</h2>
              <p className="text-xs text-muted-foreground">要員・リスク・組織の俯瞰ビュー</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Select value={honbu} onValueChange={(v) => v && setHonbu(v)}>
              <SelectTrigger className="w-64">
                <SelectValue placeholder="本部を選択">
                  {honbuName}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {honbuList.map((h) => (
                  <SelectItem key={h.DEPT_ID} value={String(h.DEPT_ID)}>
                    {h.DEPT_NAME}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <DropdownMenu>
              <DropdownMenuTrigger className="inline-flex items-center gap-1.5 h-9 px-3 rounded-md border text-sm hover:bg-accent disabled:opacity-50" disabled={!honbu}>
                <Download className="h-3.5 w-3.5" />
                CSV出力
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => { window.location.href = `/api/workforce-overview/export?honbu=${honbu}&section=roster`; }}>
                  全社員リスト (ML付)
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => { window.location.href = `/api/workforce-overview/export?honbu=${honbu}&section=grade_pyramid`; }}>
                  等級ピラミッド集計
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => { window.location.href = `/api/workforce-overview/export?honbu=${honbu}&section=dept_summary`; }}>
                  部門サマリ
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>

        {error && (
          <Card className="border-red-200 bg-red-50">
            <CardContent className="py-3">
              <p className="text-sm text-red-700">{error}</p>
              <Button variant="outline" size="sm" className="mt-2" onClick={() => honbu && fetchData(honbu)}>再試行</Button>
            </CardContent>
          </Card>
        )}

        {loading || !data ? (
          <div className="space-y-4">
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
              {[...Array(5)].map((_, i) => <Skeleton key={i} className="h-24 rounded-xl" />)}
            </div>
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              <Skeleton className="lg:col-span-2 h-80 rounded-xl" />
              <Skeleton className="h-80 rounded-xl" />
            </div>
            <Skeleton className="h-64 rounded-xl" />
          </div>
        ) : (
          <>
            {/* Summary Cards */}
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
              <Card className="bg-gradient-to-br from-blue-50 to-white border-blue-100">
                <CardContent className="pt-4 pb-3">
                  <div className="flex items-center gap-2.5">
                    <div className="p-1.5 rounded-md bg-blue-100">
                      <Users className="h-4 w-4 text-blue-700" />
                    </div>
                    <div>
                      <p className="text-[10px] text-muted-foreground tracking-wide uppercase">在籍人数</p>
                      <p className="text-2xl font-bold tabular-nums">{data.summary.headcount.toLocaleString()}</p>
                    </div>
                  </div>
                  <p className="text-[10px] text-muted-foreground mt-1">平均勤続 {data.summary.avgTenure}年</p>
                </CardContent>
              </Card>

              <Card className="bg-gradient-to-br from-amber-50 to-white border-amber-100">
                <CardContent className="pt-4 pb-3">
                  <div className="flex items-center gap-2.5">
                    <div className="p-1.5 rounded-md bg-amber-100">
                      <Briefcase className="h-4 w-4 text-amber-700" />
                    </div>
                    <div>
                      <p className="text-[10px] text-muted-foreground tracking-wide uppercase">空席</p>
                      <p className="text-2xl font-bold tabular-nums">{data.summary.vacantCount}</p>
                    </div>
                  </div>
                  <div className="mt-1.5">
                    <Progress
                      value={data.summary.headcount > 0 ? (1 - data.summary.vacantCount / (data.summary.headcount + data.summary.vacantCount)) * 100 : 100}
                      className="h-1"
                    />
                    <p className="text-[10px] text-muted-foreground mt-0.5">充足率 {data.summary.headcount > 0 ? ((1 - data.summary.vacantCount / (data.summary.headcount + data.summary.vacantCount)) * 100).toFixed(1) : 100}%</p>
                  </div>
                </CardContent>
              </Card>

              <Card className="bg-gradient-to-br from-red-50 to-white border-red-100">
                <CardContent className="pt-4 pb-3">
                  <div className="flex items-center gap-2.5">
                    <div className="p-1.5 rounded-md bg-red-100">
                      <AlertTriangle className="h-4 w-4 text-red-700" />
                    </div>
                    <div>
                      <p className="text-[10px] text-muted-foreground tracking-wide uppercase">離職リスク高</p>
                      <p className="text-2xl font-bold tabular-nums text-red-700">{data.summary.riskHigh}</p>
                    </div>
                  </div>
                  <p className="text-[10px] text-muted-foreground mt-1">{data.summary.headcount > 0 ? ((data.summary.riskHigh / data.summary.headcount) * 100).toFixed(1) : 0}%</p>
                </CardContent>
              </Card>

              <Card className="bg-gradient-to-br from-orange-50 to-white border-orange-100">
                <CardContent className="pt-4 pb-3">
                  <div className="flex items-center gap-2.5">
                    <div className="p-1.5 rounded-md bg-orange-100">
                      <ShieldAlert className="h-4 w-4 text-orange-700" />
                    </div>
                    <div>
                      <p className="text-[10px] text-muted-foreground tracking-wide uppercase">離職リスク中</p>
                      <p className="text-2xl font-bold tabular-nums text-orange-700">{data.summary.riskMedium}</p>
                    </div>
                  </div>
                  <p className="text-[10px] text-muted-foreground mt-1">{data.summary.headcount > 0 ? ((data.summary.riskMedium / data.summary.headcount) * 100).toFixed(1) : 0}%</p>
                </CardContent>
              </Card>

              <Card className="bg-gradient-to-br from-green-50 to-white border-green-100">
                <CardContent className="pt-4 pb-3">
                  <div className="flex items-center gap-2.5">
                    <div className="p-1.5 rounded-md bg-green-100">
                      <Activity className="h-4 w-4 text-green-700" />
                    </div>
                    <div>
                      <p className="text-[10px] text-muted-foreground tracking-wide uppercase">安定</p>
                      <p className="text-2xl font-bold tabular-nums text-green-700">{data.summary.riskLow}</p>
                    </div>
                  </div>
                  <p className="text-[10px] text-muted-foreground mt-1">{data.summary.headcount > 0 ? ((data.summary.riskLow / data.summary.headcount) * 100).toFixed(1) : 0}%</p>
                </CardContent>
              </Card>
            </div>

            {/* Main Charts Row */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              <Card className="lg:col-span-2">
                <CardHeader className="pb-1">
                  <CardTitle className="text-sm font-semibold flex items-center gap-2">
                    等級別人員構成
                    <Badge variant="secondary" className="text-[10px]">{data.gradePyramid.reduce((s, g) => s + g.empCount, 0).toLocaleString()}名</Badge>
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <ResponsiveContainer width="100%" height={320}>
                    <BarChart
                      data={data.gradePyramid}
                      layout="vertical"
                      margin={{ top: 5, right: 30, left: 5, bottom: 5 }}
                    >
                      <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                      <XAxis type="number" tick={{ fontSize: 10 }} />
                      <YAxis
                        dataKey="grade"
                        type="category"
                        width={35}
                        tick={{ fontSize: 11 }}
                        tickFormatter={(v: string) => v}
                      />
                      <RTooltip
                        formatter={(value: number, name: string) => [
                          value.toLocaleString() + "名",
                          name === "empCount" ? "在籍" : "空席",
                        ]}
                        labelFormatter={(label: string) => `${label} ${GRADE_LABELS[label] || ""}`}
                      />
                      <Bar dataKey="empCount" name="empCount" stackId="a" radius={[0, 0, 0, 0]}>
                        {data.gradePyramid.map((entry) => (
                          <Cell key={entry.grade} fill={GRADE_HEX[entry.grade] || "#6b7280"} />
                        ))}
                      </Bar>
                      <Bar dataKey="vacantCount" name="vacantCount" stackId="a" fill="#e5e7eb" radius={[0, 4, 4, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                  <div className="flex flex-wrap gap-x-3 gap-y-1 mt-1 justify-center">
                    {data.gradePyramid.map((g) => (
                      <div key={g.grade} className="flex items-center gap-1 text-[10px]">
                        <div className="w-2 h-2 rounded-sm" style={{ background: GRADE_HEX[g.grade] }} />
                        <span className="font-medium">{g.grade}</span>
                        <span className="text-muted-foreground">{GRADE_LABELS[g.grade]}</span>
                        <span className="tabular-nums">{g.empCount}</span>
                        {g.vacantCount > 0 && <span className="text-amber-600">(+{g.vacantCount}空席)</span>}
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-1">
                  <CardTitle className="text-sm font-semibold">リスク分布</CardTitle>
                </CardHeader>
                <CardContent>
                  <ResponsiveContainer width="100%" height={220}>
                    <PieChart>
                      <Pie
                        data={riskPieData}
                        cx="50%"
                        cy="50%"
                        innerRadius={50}
                        outerRadius={80}
                        paddingAngle={3}
                        dataKey="value"
                      >
                        {riskPieData.map((entry, idx) => (
                          <Cell key={idx} fill={entry.fill} />
                        ))}
                      </Pie>
                      <RTooltip formatter={(value: number, name: string) => [`${value}名`, name]} />
                      <Legend
                        iconSize={8}
                        formatter={(value: string) => <span className="text-xs">{value}</span>}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="grid grid-cols-3 gap-2 mt-2 text-center">
                    <div className="rounded-md bg-red-50 py-1.5">
                      <p className="text-lg font-bold text-red-700">{data.summary.riskHigh}</p>
                      <p className="text-[10px] text-red-600">高リスク</p>
                    </div>
                    <div className="rounded-md bg-orange-50 py-1.5">
                      <p className="text-lg font-bold text-orange-700">{data.summary.riskMedium}</p>
                      <p className="text-[10px] text-orange-600">中リスク</p>
                    </div>
                    <div className="rounded-md bg-green-50 py-1.5">
                      <p className="text-lg font-bold text-green-700">{data.summary.riskLow}</p>
                      <p className="text-[10px] text-green-600">安定</p>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </div>

            {/* Tabs */}
            <Tabs defaultValue="changes">
              <TabsList>
                <TabsTrigger value="changes">
                  異動履歴
                  <Badge variant="secondary" className="ml-1 text-[10px]">{data.careerHistory.recentChanges.length}</Badge>
                </TabsTrigger>
                <TabsTrigger value="dept">
                  部署別分析
                  <Badge variant="secondary" className="ml-1 text-[10px]">{sortedDepts.length}</Badge>
                </TabsTrigger>
                <TabsTrigger value="watch">
                  要注意人材
                  <Badge variant="destructive" className="ml-1 text-[10px]">{data.watchList.length}</Badge>
                </TabsTrigger>
              </TabsList>

              <TabsContent value="changes">
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                  <Card className="lg:col-span-2">
                    <CardHeader className="pb-2">
                      <CardTitle className="text-sm flex items-center gap-2">
                        <ArrowRightLeft className="h-4 w-4 text-blue-600" />
                        最近の異動・昇格・退職
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      {data.careerHistory.recentChanges.length === 0 ? (
                        <p className="text-sm text-muted-foreground text-center py-8">該当する履歴はありません</p>
                      ) : (
                        <div className="overflow-auto max-h-[450px]">
                          <table className="w-full text-xs">
                            <thead className="sticky top-0 bg-card z-10">
                              <tr className="border-b">
                                <th className="text-left py-2 px-2 font-medium text-muted-foreground w-20">日付</th>
                                <th className="text-center py-2 px-2 font-medium text-muted-foreground w-16">種別</th>
                                <th className="text-left py-2 px-2 font-medium text-muted-foreground">氏名</th>
                                <th className="text-left py-2 px-2 font-medium text-muted-foreground">異動前</th>
                                <th className="text-center py-2 px-1 font-medium text-muted-foreground w-6"></th>
                                <th className="text-left py-2 px-2 font-medium text-muted-foreground">異動後</th>
                                <th className="text-left py-2 px-2 font-medium text-muted-foreground">備考</th>
                              </tr>
                            </thead>
                            <tbody>
                              {data.careerHistory.recentChanges.map((ev) => {
                                const typeIcon = ev.TYPE === "transfer" ? <ArrowRightLeft className="h-3 w-3" /> : ev.TYPE === "promotion" ? <ArrowUp className="h-3 w-3" /> : <LogOut className="h-3 w-3" />;
                                const typeColor = ev.TYPE === "transfer" ? "bg-blue-50 text-blue-700" : ev.TYPE === "promotion" ? "bg-green-50 text-green-700" : "bg-gray-100 text-gray-700";
                                const typeLabel = ev.TYPE === "transfer" ? "異動" : ev.TYPE === "promotion" ? "昇格" : "退職";
                                const isCrossDept = ev.TYPE === "transfer" && ev.FROM_DEPT !== ev.TO_DEPT;
                                return (
                                  <tr key={ev.ID} className="border-b hover:bg-accent/50 transition-colors">
                                    <td className="py-2 px-2 tabular-nums text-muted-foreground">{new Date(ev.DATE).toLocaleDateString("ja-JP", { month: "short", day: "numeric" })}</td>
                                    <td className="py-2 px-2 text-center">
                                      <Badge variant="outline" className={`text-[10px] gap-0.5 ${typeColor}`}>
                                        {typeIcon}{typeLabel}
                                      </Badge>
                                    </td>
                                    <td className="py-2 px-2">
                                      <span className="font-medium">{ev.NAME}</span>
                                      <Badge variant="outline" className="ml-1 text-[9px]">{ev.GRADE}</Badge>
                                    </td>
                                    <td className="py-2 px-2">
                                      <div className="text-muted-foreground">{ev.FROM_DEPT || "-"}</div>
                                      <div className="text-[10px] text-muted-foreground/70">{ev.FROM_POS || ""}</div>
                                    </td>
                                    <td className="py-2 px-1 text-center">
                                      {ev.TYPE !== "retirement" && (
                                        <ChevronRight className={`h-3 w-3 ${isCrossDept ? "text-blue-500" : "text-muted-foreground/40"}`} />
                                      )}
                                    </td>
                                    <td className="py-2 px-2">
                                      {ev.TYPE === "retirement" ? (
                                        <span className="text-muted-foreground">-</span>
                                      ) : (
                                        <>
                                          <div className={isCrossDept ? "text-blue-700 font-medium" : ""}>{ev.TO_DEPT || "-"}</div>
                                          <div className="text-[10px] text-muted-foreground/70">{ev.TO_POS || ""}</div>
                                        </>
                                      )}
                                    </td>
                                    <td className="py-2 px-2 text-muted-foreground text-[10px]">{ev.NOTES}</td>
                                  </tr>
                                );
                              })}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </CardContent>
                  </Card>

                  <div className="space-y-4">
                    <Card>
                      <CardHeader className="pb-2">
                        <CardTitle className="text-sm">月別異動件数</CardTitle>
                      </CardHeader>
                      <CardContent>
                        {(() => {
                          const monthMap = new Map<string, { transfer: number; promotion: number; retirement: number }>();
                          for (const mf of data.careerHistory.monthlyFlow) {
                            if (!monthMap.has(mf.MONTH)) monthMap.set(mf.MONTH, { transfer: 0, promotion: 0, retirement: 0 });
                            const entry = monthMap.get(mf.MONTH)!;
                            if (mf.TYPE === "transfer") entry.transfer = mf.COUNT;
                            else if (mf.TYPE === "promotion") entry.promotion = mf.COUNT;
                            else entry.retirement = mf.COUNT;
                          }
                          const chartData = Array.from(monthMap.entries())
                            .sort(([a], [b]) => a.localeCompare(b))
                            .map(([month, counts]) => ({ month: month.slice(5), ...counts }));
                          if (chartData.length === 0) return <p className="text-xs text-muted-foreground text-center py-4">データなし</p>;
                          return (
                            <ResponsiveContainer width="100%" height={180}>
                              <BarChart data={chartData} margin={{ top: 5, right: 5, left: -15, bottom: 5 }}>
                                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                                <XAxis dataKey="month" tick={{ fontSize: 10 }} />
                                <YAxis tick={{ fontSize: 10 }} allowDecimals={false} />
                                <RTooltip
                                  formatter={(value: number, name: string) => [
                                    `${value}件`,
                                    name === "transfer" ? "異動" : name === "promotion" ? "昇格" : "退職",
                                  ]}
                                />
                                <Bar dataKey="transfer" stackId="a" fill="#3b82f6" radius={[0, 0, 0, 0]} />
                                <Bar dataKey="promotion" stackId="a" fill="#22c55e" />
                                <Bar dataKey="retirement" stackId="a" fill="#9ca3af" radius={[4, 4, 0, 0]} />
                              </BarChart>
                            </ResponsiveContainer>
                          );
                        })()}
                        <div className="flex gap-3 justify-center mt-1">
                          {[{ color: "bg-blue-500", label: "異動" }, { color: "bg-green-500", label: "昇格" }, { color: "bg-gray-400", label: "退職" }].map((l) => (
                            <div key={l.label} className="flex items-center gap-1 text-[10px]">
                              <div className={`w-2 h-2 rounded-sm ${l.color}`} />
                              <span>{l.label}</span>
                            </div>
                          ))}
                        </div>
                      </CardContent>
                    </Card>

                    <Card>
                      <CardHeader className="pb-2">
                        <CardTitle className="text-sm">人材フロー</CardTitle>
                      </CardHeader>
                      <CardContent>
                        {data.careerHistory.deptFlow.length === 0 ? (
                          <p className="text-xs text-muted-foreground text-center py-4">データなし</p>
                        ) : (
                          <div className="space-y-2">
                            {data.careerHistory.deptFlow.map((f, idx) => (
                              <div key={idx} className="flex items-center gap-2 text-xs">
                                {f.FLOW_TYPE === "inflow" ? (
                                  <Badge variant="outline" className="text-[10px] bg-green-50 text-green-700 border-green-200 gap-0.5 shrink-0">
                                    <ArrowDownRight className="h-2.5 w-2.5" />流入
                                  </Badge>
                                ) : f.FLOW_TYPE === "outflow" ? (
                                  <Badge variant="outline" className="text-[10px] bg-red-50 text-red-700 border-red-200 gap-0.5 shrink-0">
                                    <ArrowUpRight className="h-2.5 w-2.5" />流出
                                  </Badge>
                                ) : (
                                  <Badge variant="outline" className="text-[10px] bg-blue-50 text-blue-700 border-blue-200 gap-0.5 shrink-0">
                                    <ArrowRightLeft className="h-2.5 w-2.5" />内部
                                  </Badge>
                                )}
                                <span className="truncate">
                                  {f.DEPT}
                                  {f.TO_DEPT && <span className="text-muted-foreground"> → {f.TO_DEPT}</span>}
                                </span>
                                <span className="ml-auto font-bold tabular-nums">{f.COUNT}</span>
                              </div>
                            ))}
                          </div>
                        )}
                      </CardContent>
                    </Card>
                  </div>
                </div>
              </TabsContent>


              <TabsContent value="dept">
                <Card>
                  <CardContent className="pt-4">
                    <div className="overflow-auto max-h-[500px]">
                      <table className="w-full text-xs">
                        <thead className="sticky top-0 bg-card z-10">
                          <tr className="border-b">
                            <th className="text-left py-2 px-3 font-medium text-muted-foreground">部署名</th>
                            {[
                              { key: "EMP_COUNT", label: "人数" },
                              { key: "VACANT_COUNT", label: "空席" },
                              { key: "AVG_EVAL", label: "平均評価" },
                              { key: "AVG_TENURE", label: "勤続年数" },
                              { key: "RISK_HIGH", label: "高リスク" },
                              { key: "RISK_MEDIUM", label: "中リスク" },
                            ].map((col) => (
                              <th key={col.key} className="text-right py-2 px-3 font-medium text-muted-foreground">
                                <button className="inline-flex items-center gap-0.5 hover:text-foreground transition-colors" onClick={() => handleSort(col.key)}>
                                  {col.label}
                                  <ArrowUpDown className={`h-3 w-3 ${sortCol === col.key ? "text-foreground" : "text-muted-foreground/50"}`} />
                                </button>
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {sortedDepts.map((d) => {
                            const vacantRate = d.EMP_COUNT > 0 ? (d.VACANT_COUNT / (d.EMP_COUNT + d.VACANT_COUNT)) * 100 : 0;
                            return (
                              <tr key={d.DEPT_ID} className="border-b hover:bg-accent/50 transition-colors group">
                                <td className="py-2 px-3">
                                  <span className="font-medium">{d.DEPT_NAME}</span>
                                </td>
                                <td className="text-right py-2 px-3 tabular-nums font-medium">{d.EMP_COUNT}</td>
                                <td className="text-right py-2 px-3">
                                  {d.VACANT_COUNT > 0 ? (
                                    <Badge
                                      variant="outline"
                                      className={`text-[10px] ${vacantRate >= 10 ? "bg-red-50 text-red-700 border-red-200" : vacantRate >= 5 ? "bg-amber-50 text-amber-700 border-amber-200" : "bg-green-50 text-green-700 border-green-200"}`}
                                    >
                                      {d.VACANT_COUNT} ({vacantRate.toFixed(0)}%)
                                    </Badge>
                                  ) : (
                                    <span className="text-muted-foreground">-</span>
                                  )}
                                </td>
                                <td className={`text-right py-2 px-3 tabular-nums ${evalColor(Number(d.AVG_EVAL))}`}>
                                  {Number(d.AVG_EVAL).toFixed(2)}
                                </td>
                                <td className="text-right py-2 px-3 tabular-nums text-muted-foreground">
                                  {d.AVG_TENURE}年
                                </td>
                                <td className="text-right py-2 px-3">
                                  {d.RISK_HIGH > 0 ? (
                                    <span className="text-red-700 font-medium tabular-nums">{d.RISK_HIGH}</span>
                                  ) : (
                                    <span className="text-muted-foreground">-</span>
                                  )}
                                </td>
                                <td className="text-right py-2 px-3">
                                  {d.RISK_MEDIUM > 0 ? (
                                    <span className="text-orange-700 font-medium tabular-nums">{d.RISK_MEDIUM}</span>
                                  ) : (
                                    <span className="text-muted-foreground">-</span>
                                  )}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </CardContent>
                </Card>
              </TabsContent>

              <TabsContent value="watch">
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm flex items-center gap-2">
                      <TrendingDown className="h-4 w-4 text-red-600" />
                      離職リスクが高い、または上司との関係性スコアが低い社員
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    {data.watchList.length === 0 ? (
                      <p className="text-sm text-muted-foreground text-center py-12">要注意人材はいません</p>
                    ) : (
                      <div className="overflow-auto max-h-[500px]">
                        <table className="w-full text-xs">
                          <thead className="sticky top-0 bg-card z-10">
                            <tr className="border-b">
                              <th className="text-left py-2 px-3 font-medium text-muted-foreground">社員名</th>
                              <th className="text-left py-2 px-3 font-medium text-muted-foreground">部署</th>
                              <th className="text-left py-2 px-3 font-medium text-muted-foreground">等級</th>
                              <th className="text-left py-2 px-3 font-medium text-muted-foreground">役職</th>
                              <th className="text-right py-2 px-3 font-medium text-muted-foreground">勤続</th>
                              <th className="text-right py-2 px-3 font-medium text-muted-foreground">評価</th>
                              <th className="text-center py-2 px-3 font-medium text-muted-foreground">離職リスク</th>
                              <th className="text-right py-2 px-3 font-medium text-muted-foreground">上司関係性</th>
                              <th className="py-2 px-1 w-8"></th>
                            </tr>
                          </thead>
                          <tbody>
                            {data.watchList.map((w) => (
                              <tr key={w.EMPLOYEE_ID} className="border-b hover:bg-accent/50 transition-colors group">
                                <td className="py-2 px-3 font-medium">{w.NAME}</td>
                                <td className="py-2 px-3 text-muted-foreground truncate max-w-[120px]">{w.DEPT_NAME}</td>
                                <td className="py-2 px-3">
                                  <Tooltip>
                                    <TooltipTrigger>
                                      <Badge variant="outline" className={`text-[10px] cursor-default ${
                                        w.GRADE.startsWith("E") ? "bg-red-50 text-red-800" :
                                        w.GRADE.startsWith("D") ? "bg-orange-50 text-orange-800" :
                                        w.GRADE.startsWith("M") ? "bg-yellow-50 text-yellow-800" :
                                        w.GRADE.startsWith("S") ? "bg-green-50 text-green-800" :
                                        "bg-blue-50 text-blue-800"
                                      }`}>{w.GRADE}</Badge>
                                    </TooltipTrigger>
                                    <TooltipContent><p>{GRADE_LABELS[w.GRADE] || w.GRADE}</p></TooltipContent>
                                  </Tooltip>
                                </td>
                                <td className="py-2 px-3 text-muted-foreground truncate max-w-[100px]">{w.POSITION_TITLE}</td>
                                <td className="text-right py-2 px-3 tabular-nums">{w.TENURE_YEARS}年</td>
                                <td className={`text-right py-2 px-3 tabular-nums font-medium ${evalColor(Number(w.AVG_EVAL))}`}>
                                  {Number(w.AVG_EVAL).toFixed(1)}
                                </td>
                                <td className="text-center py-2 px-3">
                                  {riskBadge(w.RISK_LABEL, Number(w.RISK_SCORE))}
                                </td>
                                <td className="text-right py-2 px-3">
                                  {Number(w.REL_SCORE) > 0 ? relScoreBar(Number(w.REL_SCORE)) : (
                                    <span className="text-muted-foreground text-[10px]">-</span>
                                  )}
                                </td>
                                <td className="py-2 px-1">
                                  <div className="flex gap-0.5">
                                    <Link href={`/simulation?employee=${w.EMPLOYEE_ID}`}>
                                      <Button variant="ghost" size="icon" className="h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity" title="異動検討">
                                        <GitBranch className="h-3.5 w-3.5 text-blue-600" />
                                      </Button>
                                    </Link>
                                    <Link href={`/employees/${w.EMPLOYEE_ID}`}>
                                      <Button variant="ghost" size="icon" className="h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity">
                                        <ChevronRight className="h-3.5 w-3.5" />
                                      </Button>
                                    </Link>
                                  </div>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </CardContent>
                </Card>
              </TabsContent>
            </Tabs>
          </>
        )}
      </div>
    </TooltipProvider>
  );
}
