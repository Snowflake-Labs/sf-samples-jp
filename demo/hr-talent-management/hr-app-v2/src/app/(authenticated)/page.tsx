"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Users, UserCheck, Clock, AlertTriangle, HeartHandshake, ExternalLink, GitBranch } from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Legend,
} from "recharts";
import { useHonbu } from "@/lib/honbu-context";

interface DashboardData {
  headcount: number;
  genderRatio: { male: number; female: number };
  avgTenure: number;
  deptDistribution: { DEPT_ID: number; DEPT_NAME: string; COUNT: number }[];
  gradeDistribution: { GRADE: string; COUNT: number }[];
  evalDistribution: { GRADE: string; COUNT: number }[];
  ageDistribution: { AGE_BUCKET: string; COUNT: number }[];
  recentEvals: { EMPLOYEE_ID: number; NAME: string; PERIOD: string; SCORE: number; GRADE: string; DEPT_NAME: string }[];
  attritionAlerts: { EMPLOYEE_ID: number; NAME: string; DEPT_NAME: string; GRADE: string; RISK_SCORE: number; RISK_LABEL: string }[];
}

interface HeatmapDept {
  DEPT_ID: number;
  DEPT_NAME: string;
  PAIR_COUNT: number;
  AVG_SCORE: number;
  GOOD_COUNT: number;
  WARN_COUNT: number;
  ALERT_COUNT: number;
}

interface AlertPair {
  MANAGER_NAME: string;
  EMPLOYEE_NAME: string;
  DEPT_NAME: string;
  RELATIONSHIP_SCORE: number;
  ONEONONE_FREQ: number | null;
  ONEONONE_SENTIMENT_AVG: number | null;
  EVAL_COMMENT_SENTIMENT: number | null;
  EVAL_GAP: number | null;
  PAIR_TENURE_MONTHS: number | null;
  SPAN_OF_CONTROL: number | null;
}

function formatFeatureFactors(p: AlertPair): string[] {
  const factors: string[] = [];
  if (p.ONEONONE_FREQ !== null && p.ONEONONE_FREQ < 0.3)
    factors.push(`1on1頻度: ${(p.ONEONONE_FREQ * 100).toFixed(0)}%（低）`);
  if (p.ONEONONE_SENTIMENT_AVG !== null && p.ONEONONE_SENTIMENT_AVG < 0)
    factors.push(`1on1感情: ${p.ONEONONE_SENTIMENT_AVG.toFixed(2)}（ネガティブ）`);
  if (p.EVAL_GAP !== null && Math.abs(p.EVAL_GAP) > 0.3)
    factors.push(`評価ギャップ: ${p.EVAL_GAP.toFixed(2)}`);
  if (p.EVAL_COMMENT_SENTIMENT !== null && p.EVAL_COMMENT_SENTIMENT < 0.3)
    factors.push(`評価コメント感情: ${p.EVAL_COMMENT_SENTIMENT.toFixed(2)}（低）`);
  if (p.PAIR_TENURE_MONTHS !== null && p.PAIR_TENURE_MONTHS < 6)
    factors.push(`ペア在籍: ${p.PAIR_TENURE_MONTHS}ヶ月（短）`);
  if (p.SPAN_OF_CONTROL !== null && p.SPAN_OF_CONTROL > 10)
    factors.push(`管理人数: ${p.SPAN_OF_CONTROL}人（過多）`);
  return factors;
}

const GRADE_HEX: Record<string, string> = {
  E1: "#f87171",
  D1: "#fb923c",
  D2: "#fbbf24",
  M1: "#facc15",
  M2: "#a3e635",
  S1: "#4ade80",
  S2: "#34d399",
  J1: "#22d3ee",
  J2: "#22d3ee",
  J3: "#22d3ee",
};

const EVAL_COLORS: Record<string, string> = {
  S: "#ef4444",
  A: "#f97316",
  B: "#3b82f6",
  C: "#6b7280",
  D: "#9ca3af",
};

const GRADE_SORT_ORDER: Record<string, number> = {
  J3: 0, J2: 1, J1: 2, S2: 3, S1: 4, M2: 5, M1: 6, D2: 7, D1: 8, E1: 9,
};

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

function scoreColor(score: number): string {
  if (score >= 0.6) return "bg-emerald-100 text-emerald-800";
  if (score >= 0.3) return "bg-amber-100 text-amber-800";
  return "bg-red-100 text-red-800";
}

function scoreBg(score: number): string {
  if (score >= 0.6) return "#10b981";
  if (score >= 0.3) return "#f59e0b";
  return "#ef4444";
}

export default function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [period, setPeriod] = useState(PERIODS[0]);
  const { honbu, setHonbu, honbuList } = useHonbu();
  const [heatmapDepts, setHeatmapDepts] = useState<HeatmapDept[]>([]);
  const [alertPairs, setAlertPairs] = useState<AlertPair[]>([]);
  const [heatmapLoading, setHeatmapLoading] = useState(false);
  const [drillDeptId, setDrillDeptId] = useState<number | null>(null);
  const [drillDeptName, setDrillDeptName] = useState<string>("");
  const [drillData, setDrillData] = useState<{ DEPT_ID: number; DEPT_NAME: string; COUNT: number }[] | null>(null);
  const [drillLoading, setDrillLoading] = useState(false);
  const [drillIsLeaf, setDrillIsLeaf] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);

  const fetchDashboard = useCallback((honbuId: string, p: string) => {
    if (!honbuId) return;
    setLoading(true);
    fetch(`/api/dashboard?honbu=${honbuId}&period=${encodeURIComponent(p)}`)
      .then((res) => {
        if (!res.ok) throw new Error("Failed to fetch dashboard");
        return res.json();
      })
      .then(setData)
      .catch(() => setFetchError("ダッシュボードデータの取得に失敗しました"))
      .finally(() => setLoading(false));
  }, []);

  const fetchHeatmap = useCallback((honbuId: string) => {
    if (!honbuId) return;
    setHeatmapLoading(true);
    fetch(`/api/dashboard/heatmap?honbu=${honbuId}`)
      .then((r) => {
        if (!r.ok) throw new Error("Failed");
        return r.json();
      })
      .then((res) => {
        setHeatmapDepts(res.departments || []);
        setAlertPairs(res.alertPairs || []);
      })
      .catch((err) => console.error("[dashboard heatmap fetch] failed:", err))
      .finally(() => setHeatmapLoading(false));
  }, []);

  useEffect(() => {
    if (honbu) {
      fetchDashboard(honbu, period);
      fetchHeatmap(honbu);
    }
    setDrillDeptId(null);
    setDrillData(null);
  }, [honbu, period, fetchDashboard, fetchHeatmap]);

  useEffect(() => {
    if (!drillDeptId) { setDrillData(null); setDrillIsLeaf(false); return; }
    setDrillLoading(true);
    fetch(`/api/dashboard?honbu=${honbu}&period=${encodeURIComponent(period)}&drillDept=${drillDeptId}`)
      .then((r) => r.ok ? r.json() : Promise.reject())
      .then((d) => {
        setDrillData(d.deptDistribution);
        setDrillIsLeaf(!!d.drillIsLeaf);
      })
      .catch(() => setDrillData([]))
      .finally(() => setDrillLoading(false));
  }, [drillDeptId, honbu, period]);

  const honbuName = (Array.isArray(honbuList) ? honbuList : []).find((d) => String(d.DEPT_ID) === honbu)?.DEPT_NAME || "";

  if (!honbuList.length) {
    return (
      <div className="p-6 space-y-6">
        <h2 className="text-2xl font-bold">ダッシュボード</h2>
        <Skeleton className="h-10 w-60" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center gap-4 flex-wrap">
        <h2 className="text-2xl font-bold tracking-tight">ダッシュボード</h2>
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
        <Select value={period} onValueChange={(v) => v && setPeriod(v)}>
          <SelectTrigger className="w-36">
            <SelectValue placeholder="期間" />
          </SelectTrigger>
          <SelectContent>
            {PERIODS.map((p) => (
              <SelectItem key={p} value={p}>{p}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="ml-auto flex items-center gap-2">
          <Link href="/simulation">
            <Button variant="outline" size="sm" className="gap-1.5">
              <GitBranch className="h-3.5 w-3.5" />
              異動シミュレーション
            </Button>
          </Link>
        </div>
      </div>

      {fetchError && (
        <Card className="border-red-200 bg-red-50">
          <CardContent className="py-3 flex items-center gap-2 text-sm text-red-700">
            <AlertTriangle className="h-4 w-4" />
            {fetchError}
            <Button variant="outline" size="sm" className="ml-auto" onClick={() => { setFetchError(null); fetchDashboard(honbu, period); }}>再試行</Button>
          </CardContent>
        </Card>
      )}

      {loading || !data ? (
        <>
          <div className="grid grid-cols-4 gap-4">
            {[...Array(4)].map((_, i) => (
              <Skeleton key={i} className="h-28" />
            ))}
          </div>
          <div className="grid grid-cols-2 gap-4">
            {[...Array(4)].map((_, i) => (
              <Skeleton key={i} className="h-72" />
            ))}
          </div>
        </>
      ) : (
        <>
          <div className="grid grid-cols-4 gap-4">
            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center gap-3">
                  <div className="p-2 bg-blue-50 rounded-lg">
                    <Users className="h-5 w-5 text-blue-600" />
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">社員数</p>
                    <p className="text-2xl font-bold">{data.headcount.toLocaleString()}</p>
                  </div>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center gap-3">
                  <div className="p-2 bg-purple-50 rounded-lg">
                    <UserCheck className="h-5 w-5 text-purple-600" />
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">男女比</p>
                    <p className="text-2xl font-bold">
                      {(() => {
                        const total = data.genderRatio.male + data.genderRatio.female;
                        const m = total > 0 ? Math.round((data.genderRatio.male / total) * 100) : 0;
                        return `${m}:${100 - m}`;
                      })()}
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center gap-3">
                  <div className="p-2 bg-emerald-50 rounded-lg">
                    <Clock className="h-5 w-5 text-emerald-600" />
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">平均勤続年数</p>
                    <p className="text-2xl font-bold">{data.avgTenure}年</p>
                  </div>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center gap-3">
                  <div className={`p-2 rounded-lg ${data.attritionAlerts.length > 0 ? "bg-red-50" : "bg-amber-50"}`}>
                    <AlertTriangle className={`h-5 w-5 ${data.attritionAlerts.length > 0 ? "text-red-600" : "text-amber-600"}`} />
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">離職リスク</p>
                    <p className="text-2xl font-bold">{data.attritionAlerts.length}名</p>
                    <p className="text-xs text-muted-foreground">ML予測 高/中リスク Top5</p>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <Card>
              <CardHeader className="pb-2">
                <div className="flex items-center gap-2">
                  <CardTitle className="text-base">部門別人員構成（Top 10）</CardTitle>
                  {drillDeptId && (
                    <Button variant="ghost" size="sm" className="text-xs h-6 px-2" onClick={() => { setDrillDeptId(null); setDrillDeptName(""); }}>
                      ← {drillDeptName} から戻る
                    </Button>
                  )}
                </div>
                <CardDescription>{drillDeptId ? (drillIsLeaf ? `${drillDeptName}の等級別内訳` : `${drillDeptName}配下 — クリックでドリルダウン`) : `${honbuName}管轄 — クリックでドリルダウン`}{drillLoading ? "（読み込み中…）" : ""}</CardDescription>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={300}>
                  <BarChart
                    data={drillDeptId && drillData ? drillData : data.deptDistribution}
                    layout="vertical"
                    margin={{ left: 100 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis type="number" />
                    <YAxis type="category" dataKey="DEPT_NAME" tick={{ fontSize: 11 }} width={100} />
                    <Tooltip />
                    <Bar
                      dataKey="COUNT"
                      fill="#60a5fa"
                      radius={[0, 4, 4, 0]}
                      className="cursor-pointer"
                      onClick={(entry: any) => {
                        const d = entry?.payload || entry;
                        if (d?.DEPT_ID && !drillIsLeaf) {
                          setDrillDeptId(d.DEPT_ID);
                          setDrillDeptName(d.DEPT_NAME);
                        }
                      }}
                    />
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">評価分布（{period}）</CardTitle>
                <CardDescription>選択期間のグレード別分布</CardDescription>
              </CardHeader>
              <CardContent>
                {data.evalDistribution.length > 0 ? (
                  <ResponsiveContainer width="100%" height={300}>
                    <PieChart>
                      <Pie
                        data={data.evalDistribution}
                        cx="50%"
                        cy="50%"
                        innerRadius={60}
                        outerRadius={100}
                        paddingAngle={2}
                        dataKey="COUNT"
                        nameKey="GRADE"
                        label={({ GRADE, COUNT }: { GRADE: string; COUNT: number }) => `${GRADE}: ${COUNT}名`}
                      >
                        {data.evalDistribution.map((entry, i) => (
                          <Cell key={i} fill={EVAL_COLORS[entry.GRADE] || "#94a3b8"} />
                        ))}
                      </Pie>
                      <Legend />
                      <Tooltip />
                    </PieChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="flex items-center justify-center h-[300px] text-muted-foreground">
                    評価データなし
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">年齢構成</CardTitle>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={300}>
                  <BarChart data={data.ageDistribution}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="AGE_BUCKET" tick={{ fontSize: 12 }} />
                    <YAxis />
                    <Tooltip />
                    <Bar dataKey="COUNT" fill="#818cf8" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">等級別人員</CardTitle>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={300}>
                  <BarChart data={[...data.gradeDistribution].sort((a, b) => (GRADE_SORT_ORDER[a.GRADE] ?? 99) - (GRADE_SORT_ORDER[b.GRADE] ?? 99))}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="GRADE" tick={{ fontSize: 12 }} />
                    <YAxis />
                    <Tooltip />
                    <Bar dataKey="COUNT" radius={[4, 4, 0, 0]}>
                      {[...data.gradeDistribution].sort((a, b) => (GRADE_SORT_ORDER[a.GRADE] ?? 99) - (GRADE_SORT_ORDER[b.GRADE] ?? 99)).map((d, i) => (
                        <Cell key={i} fill={GRADE_HEX[d.GRADE] || "#94a3b8"} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          </div>

          <Card className="border-indigo-200 bg-indigo-50/20">
            <CardHeader className="pb-2">
              <CardTitle className="text-base flex items-center gap-2 text-indigo-700">
                <HeartHandshake className="h-4 w-4" />
                組織関係性ヒートマップ（LightGBM予測）
              </CardTitle>
              <CardDescription>上司-部下ペアの関係性スコア平均を部署別に表示。3ペア以上の部署のみ</CardDescription>
            </CardHeader>
            <CardContent>
              {heatmapLoading ? (
                <Skeleton className="h-64" />
              ) : heatmapDepts.length > 0 ? (
                <>
                  <div className="mb-3 p-3 rounded-md bg-indigo-50 border border-indigo-100 text-xs text-indigo-800 space-y-1">
                    <p className="font-medium">スコア算出の根拠データ</p>
                    <p>LightGBMモデルが以下のデータを入力として上司-部下間の関係性スコアを予測しています:</p>
                    <ul className="list-disc pl-4 space-y-0.5 text-[11px]">
                      <li><strong>1on1ミーティング</strong>: 実施頻度、感情分析スコア（NLP）、感情トレンド</li>
                      <li><strong>人事評価</strong>: コメント感情分析、評価スコア推移、上司-本人の評価ギャップ</li>
                      <li><strong>組織構造</strong>: ペア在籍期間、管理人数（Span of Control）、年齢差</li>
                      <li><strong>スキル指標</strong>: 部下のリーダーシップスコア、コミュニケーションスコア</li>
                    </ul>
                  </div>

                  <ResponsiveContainer width="100%" height={Math.max(200, heatmapDepts.length * 32 + 40)}>
                    <BarChart
                      data={heatmapDepts.slice(0, 15)}
                      layout="vertical"
                      margin={{ left: 20, right: 20 }}
                    >
                      <XAxis type="number" domain={[0, 1]} tick={{ fontSize: 11 }} />
                      <YAxis type="category" dataKey="DEPT_NAME" width={130} tick={{ fontSize: 11 }} />
                      <Tooltip
                        content={({ active, payload }) => {
                          if (!active || !payload?.[0]) return null;
                          const d = payload[0].payload as HeatmapDept;
                          return (
                            <div className="bg-white border rounded-lg shadow-lg p-3 text-xs max-w-[240px]">
                              <p className="font-semibold mb-1">{d.DEPT_NAME}</p>
                              <p className="mb-2">平均関係性: <span className="font-mono font-bold">{(Number(d.AVG_SCORE) * 100).toFixed(1)}%</span></p>
                              <div className="space-y-1 border-t pt-1.5">
                                <p className="text-muted-foreground font-medium">ペア内訳（{d.PAIR_COUNT}組）</p>
                                <div className="flex items-center gap-1.5">
                                  <span className="w-2 h-2 rounded-sm bg-emerald-500" />
                                  <span>良好: {d.GOOD_COUNT}組 ({d.PAIR_COUNT > 0 ? ((d.GOOD_COUNT / d.PAIR_COUNT) * 100).toFixed(0) : 0}%)</span>
                                </div>
                                <div className="flex items-center gap-1.5">
                                  <span className="w-2 h-2 rounded-sm bg-amber-500" />
                                  <span>普通: {d.WARN_COUNT}組 ({d.PAIR_COUNT > 0 ? ((d.WARN_COUNT / d.PAIR_COUNT) * 100).toFixed(0) : 0}%)</span>
                                </div>
                                <div className="flex items-center gap-1.5">
                                  <span className="w-2 h-2 rounded-sm bg-red-500" />
                                  <span>要改善: {d.ALERT_COUNT}組 ({d.PAIR_COUNT > 0 ? ((d.ALERT_COUNT / d.PAIR_COUNT) * 100).toFixed(0) : 0}%)</span>
                                </div>
                              </div>
                            </div>
                          );
                        }}
                      />
                      <Bar dataKey="AVG_SCORE" name="関係性スコア" radius={[0, 4, 4, 0]}>
                        {heatmapDepts.slice(0, 15).map((d, i) => (
                          <Cell key={i} fill={scoreBg(Number(d.AVG_SCORE))} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>

                  <div className="flex gap-4 mt-3 text-xs text-muted-foreground justify-center">
                    <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-sm bg-emerald-500" /> 良好（60%以上）</span>
                    <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-sm bg-amber-500" /> 普通（30〜60%）</span>
                    <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-sm bg-red-500" /> 要改善（30%未満）</span>
                  </div>

                  {alertPairs.length > 0 && (
                    <div className="mt-4 border-t pt-3">
                      <p className="text-xs font-medium text-red-600 mb-2 flex items-center gap-1">
                        <AlertTriangle className="h-3 w-3" />
                        要注意ペア（スコア30%未満 — Top 10）
                      </p>
                      <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
                        {alertPairs.map((p, i) => {
                          const factors = formatFeatureFactors(p);
                          return (
                            <div key={i} className="p-2 rounded-md bg-red-50 border border-red-100 text-xs">
                              <div className="flex items-center gap-2">
                                <Badge variant="destructive" className="text-[9px] shrink-0">
                                  {(Number(p.RELATIONSHIP_SCORE) * 100).toFixed(0)}%
                                </Badge>
                                <span className="font-medium">{p.MANAGER_NAME}</span>
                                <span className="text-muted-foreground">×</span>
                                <span className="font-medium">{p.EMPLOYEE_NAME}</span>
                                <span className="text-muted-foreground ml-auto truncate">{p.DEPT_NAME}</span>
                              </div>
                              {factors.length > 0 && (
                                <div className="mt-1.5 pl-1 flex flex-wrap gap-1">
                                  {factors.map((f, fi) => (
                                    <span key={fi} className="inline-flex items-center px-1.5 py-0.5 rounded bg-red-100 text-red-700 text-[10px]">
                                      {f}
                                    </span>
                                  ))}
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </>
              ) : (
                <div className="flex items-center justify-center h-32 text-muted-foreground text-sm">
                  関係性データなし
                </div>
              )}
            </CardContent>
          </Card>

          {data.attritionAlerts.length > 0 && (
            <Card className="border-red-200 bg-red-50/30">
              <CardHeader className="pb-2">
                <CardTitle className="text-base flex items-center gap-2 text-red-700">
                  <AlertTriangle className="h-4 w-4" />
                  離職リスクアラート（ML予測 Top 5）
                </CardTitle>
                <CardDescription>XGBoostモデルによる離職予測スコア上位</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {data.attritionAlerts.map((a) => (
                    <div key={a.EMPLOYEE_ID} className="flex items-center gap-3 p-2 rounded-md bg-white border border-red-100 hover:bg-red-50/50 transition-colors">
                      <Badge variant={a.RISK_LABEL === "high" ? "destructive" : "default"} className="text-[10px] w-14 justify-center">
                        {a.RISK_LABEL === "high" ? "高" : "中"}
                      </Badge>
                      <Link href={`/employees/${a.EMPLOYEE_ID}`} className="font-medium text-sm text-blue-600 hover:underline">{a.NAME}</Link>
                      <Badge variant="secondary" className="text-[10px]">{a.GRADE}</Badge>
                      <span className="text-xs text-muted-foreground">{a.DEPT_NAME}</span>
                      <span className="text-sm font-mono ml-auto">{(Number(a.RISK_SCORE) * 100).toFixed(0)}%</span>
                      <Link href={`/simulation?employee=${a.EMPLOYEE_ID}`}>
                        <Badge variant="outline" className="text-[10px] cursor-pointer hover:bg-blue-50 border-blue-300 text-blue-600">
                          <GitBranch className="h-2.5 w-2.5 mr-0.5" />異動検討
                        </Badge>
                      </Link>
                      <Link href={`/employees/${a.EMPLOYEE_ID}`}>
                        <ExternalLink className="h-3 w-3 text-muted-foreground" />
                      </Link>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">最近の評価（{period}）</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-2">
                {data.recentEvals.map((ev, i) => (
                  <Link key={i} href={`/employees/${ev.EMPLOYEE_ID}`}>
                    <div className="flex items-center gap-3 p-2 rounded-md hover:bg-accent transition-colors cursor-pointer">
                      <Badge variant={ev.GRADE === "S" ? "destructive" : ev.GRADE === "A" ? "default" : "secondary"}>
                        {ev.GRADE}
                      </Badge>
                      <span className="font-medium text-sm text-blue-600 hover:underline">{ev.NAME}</span>
                      <span className="text-xs text-muted-foreground">{ev.DEPT_NAME}</span>
                      <span className="text-xs text-muted-foreground ml-auto">{ev.PERIOD}</span>
                      <span className="text-sm font-mono">{ev.SCORE != null ? Number(ev.SCORE).toFixed(1) : '—'}</span>
                    </div>
                  </Link>
                ))}
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
