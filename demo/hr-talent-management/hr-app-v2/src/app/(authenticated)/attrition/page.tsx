"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import Link from "next/link";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
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
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Progress } from "@/components/ui/progress";
import { AlertTriangle, TrendingDown, Info, ChevronDown, ExternalLink, Brain, Loader2, Lightbulb, Download, BarChart3, GitBranch } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { GRADE_LABELS, ML_MODEL_METRICS, FEATURE_LABELS, FEATURE_DESCRIPTIONS } from "@/lib/types";
import { shapToHumanText, aucToStars, renderStars, riskScoreToText } from "@/lib/ml-display";
import { useHonbu } from "@/lib/honbu-context";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Legend,
  LineChart,
  Line,
  CartesianGrid,
  Area,
  AreaChart,
} from "recharts";

interface AttritionPrediction {
  EMPLOYEE_ID: number;
  RISK_SCORE: number;
  RISK_LABEL: string;
  MODEL_VERSION: string;
  LAST_NAME: string;
  FIRST_NAME: string;
  DEPT_NAME: string;
  POSITION_TITLE: string;
  GRADE: string;
  TENURE_YEARS: number;
}

interface ShapFactor {
  FEATURE_NAME: string;
  SHAP_VALUE: number;
  FEATURE_VALUE: number;
}

interface AttritionDetail {
  prediction: { RISK_SCORE: number; RISK_LABEL: string; MODEL_VERSION: string; RUN_DATE: string } | null;
  shapValues: ShapFactor[];
  evidence: { ai_summary?: string; shap_factors?: { feature: string; shap: number; value: number }[] } | null;
  featureSummary: { FEATURE_NAME: string; FEATURE_VALUE: number }[];
}

const PAGE_SIZE = 50;

export default function AttritionPage() {
  const [predictions, setPredictions] = useState<AttritionPrediction[]>([]);
  const { honbu, setHonbu, honbuList } = useHonbu();
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [displayCount, setDisplayCount] = useState(PAGE_SIZE);
  const [total, setTotal] = useState(0);
  const [riskDist, setRiskDist] = useState({ high: 0, medium: 0, low: 0 });
  const [selectedEmp, setSelectedEmp] = useState<AttritionPrediction | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [detail, setDetail] = useState<AttritionDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [riskFilter, setRiskFilter] = useState<string>("all");
  const [deptFilter, setDeptFilter] = useState<string>("");
  const [retentionLoading, setRetentionLoading] = useState(false);
  const [retentionSuggestion, setRetentionSuggestion] = useState<string>("");
  const [activeTab, setActiveTab] = useState<"list" | "trend">("list");
  const [trendData, setTrendData] = useState<{ month: string; high: number; medium: number; low: number }[]>([]);
  const [trendLoading, setTrendLoading] = useState(false);



  const fetchData = useCallback((h: string) => {
    if (!h) return;
    setLoading(true);
    setDisplayCount(PAGE_SIZE);
    fetch(`/api/attrition?honbu=${h}&limit=500`)
      .then((r) => {
        if (!r.ok) throw new Error("Failed");
        return r.json();
      })
      .then((res) => {
        setPredictions(res.data || []);
        setTotal(res.total || 0);
        setRiskDist(res.riskDistribution || { high: 0, medium: 0, low: 0 });
      })
      .catch(() => setFetchError("離職予測データの取得に失敗しました"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (honbu) fetchData(honbu);
  }, [honbu, fetchData]);

  useEffect(() => {
    if (!honbu || activeTab !== "trend") return;
    setTrendLoading(true);
    fetch(`/api/attrition/trend?honbu=${honbu}`)
      .then((r) => r.json())
      .then(setTrendData)
      .catch(() => setTrendData([]))
      .finally(() => setTrendLoading(false));
  }, [honbu, activeTab]);

  const openRiskModal = (emp: AttritionPrediction) => {
    setSelectedEmp(emp);
    setModalOpen(true);
    setDetail(null);
    setDetailLoading(true);
    setRetentionSuggestion("");
    fetch(`/api/attrition/${emp.EMPLOYEE_ID}`)
      .then((r) => r.json())
      .then(setDetail)
      .catch(() => setDetail(null))
      .finally(() => setDetailLoading(false));
  };

  const filtered = predictions.filter((p) => {
    if (riskFilter !== "all" && p.RISK_LABEL !== riskFilter) return false;
    if (deptFilter && p.DEPT_NAME !== deptFilter) return false;
    return true;
  });
  const displayed = filtered.slice(0, displayCount);
  const hasMoreToShow = displayCount < filtered.length;

  const deptRiskData = useMemo(() => {
    const map = new Map<string, { dept: string; high: number; medium: number; low: number }>();
    for (const p of predictions) {
      const d = p.DEPT_NAME;
      if (!map.has(d)) map.set(d, { dept: d, high: 0, medium: 0, low: 0 });
      const entry = map.get(d)!;
      if (p.RISK_LABEL === "high") entry.high++;
      else if (p.RISK_LABEL === "medium") entry.medium++;
      else entry.low++;
    }
    return [...map.values()]
      .sort((a, b) => (b.high + b.medium) - (a.high + a.medium))
      .slice(0, 10);
  }, [predictions]);

  if (loading) {
    return (
      <div className="p-6 space-y-4">
        <h2 className="text-2xl font-bold">離職予測</h2>
        <div className="grid grid-cols-3 gap-4">
          {[...Array(3)].map((_, i) => <Skeleton key={i} className="h-28" />)}
        </div>
        <Skeleton className="h-96" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center gap-4 flex-wrap">
        <h2 className="text-2xl font-bold tracking-tight">離職予測</h2>
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
        <Badge variant="outline" className="text-xs gap-1">
          <Brain className="h-3 w-3" />
          予測の信頼度: {renderStars(aucToStars(ML_MODEL_METRICS.ATTRITION_AUC).stars)} ({aucToStars(ML_MODEL_METRICS.ATTRITION_AUC).label})
        </Badge>
        <div className="ml-auto flex gap-2">
          <Button
            variant="outline"
            size="sm"
            className="gap-1.5"
            onClick={() => setActiveTab(activeTab === "list" ? "trend" : "list")}
          >
            <BarChart3 className="h-3.5 w-3.5" />
            {activeTab === "list" ? "トレンド" : "一覧"}
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="gap-1.5"
            onClick={() => {
              window.open(`/api/attrition/export?honbu=${honbu}`, "_blank");
            }}
          >
            <Download className="h-3.5 w-3.5" />
            CSVエクスポート
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <Card
          className={`border-red-200 bg-red-50/50 cursor-pointer transition-all ${riskFilter === "high" ? "ring-2 ring-red-500 shadow-md" : "hover:shadow-sm"}`}
          onClick={() => { setRiskFilter(riskFilter === "high" ? "all" : "high"); setDisplayCount(PAGE_SIZE); }}
        >
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <AlertTriangle className="h-6 w-6 text-red-600" />
              <div>
                <p className="text-sm text-red-600">高リスク</p>
                <p className="text-3xl font-bold text-red-700">{riskDist.high}名</p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card
          className={`border-amber-200 bg-amber-50/50 cursor-pointer transition-all ${riskFilter === "medium" ? "ring-2 ring-amber-500 shadow-md" : "hover:shadow-sm"}`}
          onClick={() => { setRiskFilter(riskFilter === "medium" ? "all" : "medium"); setDisplayCount(PAGE_SIZE); }}
        >
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <TrendingDown className="h-6 w-6 text-amber-600" />
              <div>
                <p className="text-sm text-amber-600">中リスク</p>
                <p className="text-3xl font-bold text-amber-700">{riskDist.medium}名</p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card
          className={`cursor-pointer transition-all ${riskFilter === "low" ? "ring-2 ring-green-500 shadow-md" : "hover:shadow-sm"}`}
          onClick={() => { setRiskFilter(riskFilter === "low" ? "all" : "low"); setDisplayCount(PAGE_SIZE); }}
        >
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <Info className="h-6 w-6 text-green-600" />
              <div>
                <p className="text-sm text-green-600">低リスク</p>
                <p className="text-3xl font-bold text-green-700">{riskDist.low}名</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {activeTab === "trend" && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">リスクレベル推移（直近6ヶ月）</CardTitle>
            <CardDescription className="text-xs">各リスクレベルの人数推移を表示</CardDescription>
          </CardHeader>
          <CardContent>
            {trendLoading ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="h-5 w-5 animate-spin mr-2" />
                <span className="text-sm text-muted-foreground">トレンドデータ取得中...</span>
              </div>
            ) : trendData.length > 0 ? (
              <ResponsiveContainer width="100%" height={320}>
                <AreaChart data={trendData} margin={{ left: 10, right: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="month" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Area type="monotone" dataKey="high" name="高リスク" stackId="1" fill="hsl(0 80% 55%)" stroke="hsl(0 80% 45%)" />
                  <Area type="monotone" dataKey="medium" name="中リスク" stackId="1" fill="hsl(45 90% 50%)" stroke="hsl(45 90% 40%)" />
                  <Area type="monotone" dataKey="low" name="低リスク" stackId="1" fill="hsl(142 70% 45%)" stroke="hsl(142 70% 35%)" />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-sm text-muted-foreground text-center py-8">トレンドデータがありません</p>
            )}
          </CardContent>
        </Card>
      )}

      {activeTab === "list" && (<>

      {deptRiskData.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <div className="flex items-center gap-3">
              <CardTitle className="text-base">部署別リスク分布（Top 10）</CardTitle>
              {deptFilter && (
                <Button variant="ghost" size="sm" className="text-xs h-6 px-2" onClick={() => { setDeptFilter(""); setDisplayCount(PAGE_SIZE); }}>
                  {deptFilter} ✕
                </Button>
              )}
            </div>
            <CardDescription className="text-xs">バーをクリックして部署でフィルタ</CardDescription>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={deptRiskData} layout="vertical" margin={{ left: 20, right: 20 }} onClick={(e: any) => { if (e?.activeLabel) { setDeptFilter((prev) => prev === e.activeLabel ? "" : e.activeLabel); setDisplayCount(PAGE_SIZE); } }}>
                <XAxis type="number" tick={{ fontSize: 11 }} />
                <YAxis type="category" dataKey="dept" width={120} tick={{ fontSize: 11 }} />
                <Tooltip />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey="high" name="高リスク" stackId="a" fill="hsl(0 80% 55%)" className="cursor-pointer" />
                <Bar dataKey="medium" name="中リスク" stackId="a" fill="hsl(45 90% 50%)" className="cursor-pointer" />
                <Bar dataKey="low" name="低リスク" stackId="a" fill="hsl(142 70% 45%)" radius={[0, 4, 4, 0]} className="cursor-pointer" />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-center gap-3">
            <CardTitle className="text-base">リスクスコア一覧（{filtered.length.toLocaleString()}名）</CardTitle>
            {(riskFilter !== "all" || deptFilter) && (
              <Button variant="ghost" size="sm" className="text-xs h-6 px-2" onClick={() => { setRiskFilter("all"); setDeptFilter(""); setDisplayCount(PAGE_SIZE); }}>
                フィルタ解除
              </Button>
            )}
          </div>
          <CardDescription>ML モデル（MODEL()!PREDICT_PROBA）によるリスクスコア — クリックでSHAP要因表示</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            {displayed.map((emp) => (
              <div
                key={emp.EMPLOYEE_ID}
                className="flex items-center gap-3 p-3 rounded-lg border hover:bg-accent transition-colors cursor-pointer"
                onClick={() => openRiskModal(emp)}
              >
                <div
                  className={`h-10 w-10 rounded-full flex items-center justify-center text-sm font-bold ${
                    emp.RISK_LABEL === "high"
                      ? "bg-red-100 text-red-700"
                      : emp.RISK_LABEL === "medium"
                        ? "bg-amber-100 text-amber-700"
                        : "bg-green-100 text-green-700"
                  }`}
                >
                  {(Number(emp.RISK_SCORE) * 100).toFixed(0)}
                </div>
                <div className="flex-1">
                  <span className="font-medium text-sm text-blue-600 hover:underline">
                    {emp.LAST_NAME}{emp.FIRST_NAME}
                  </span>
                  <div className="text-xs text-muted-foreground">
                    {emp.DEPT_NAME} / {emp.POSITION_TITLE}
                  </div>
                </div>
                <Badge variant="outline" className="text-[10px]">
                  {emp.GRADE} {GRADE_LABELS[emp.GRADE]}
                </Badge>
                <div className="text-right">
                  <div className="text-xs text-muted-foreground">
                    勤続: {emp.TENURE_YEARS}年
                  </div>
                </div>
                <Badge
                  variant={emp.RISK_LABEL === "high" ? "destructive" : emp.RISK_LABEL === "medium" ? "default" : "secondary"}
                >
                  {emp.RISK_LABEL === "high" ? "高" : emp.RISK_LABEL === "medium" ? "中" : "低"}
                </Badge>
              </div>
            ))}
          </div>
          {hasMoreToShow && (
            <div className="flex justify-center pt-4">
              <Button
                variant="outline"
                onClick={() => setDisplayCount((c) => c + PAGE_SIZE)}
                className="gap-2"
              >
                <ChevronDown className="h-4 w-4" />
                次の{PAGE_SIZE}件
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      </>)}

      <Dialog open={modalOpen} onOpenChange={setModalOpen}>
        <DialogContent className="sm:max-w-2xl max-h-[85vh] overflow-y-auto">
          {selectedEmp && (
            <>
              <DialogHeader>
                <DialogTitle className="flex items-center gap-2">
                  <div
                    className={`h-8 w-8 rounded-full flex items-center justify-center text-xs font-bold ${
                      selectedEmp.RISK_LABEL === "high"
                        ? "bg-red-100 text-red-700"
                        : selectedEmp.RISK_LABEL === "medium"
                          ? "bg-amber-100 text-amber-700"
                          : "bg-green-100 text-green-700"
                    }`}
                  >
                    {(Number(selectedEmp.RISK_SCORE) * 100).toFixed(0)}
                  </div>
                  {selectedEmp.LAST_NAME}{selectedEmp.FIRST_NAME}
                </DialogTitle>
                <DialogDescription>
                  {selectedEmp.DEPT_NAME} / {selectedEmp.POSITION_TITLE} / {selectedEmp.GRADE} {GRADE_LABELS[selectedEmp.GRADE]}
                </DialogDescription>
              </DialogHeader>

              <div className="space-y-4">
                <div className="grid grid-cols-3 gap-3">
                  <div>
                    <p className="text-xs text-muted-foreground">リスクスコア</p>
                    <p className="text-2xl font-bold font-mono">{(Number(selectedEmp.RISK_SCORE) * 100).toFixed(1)}%</p>
                    <Progress value={selectedEmp.RISK_SCORE * 100} className="h-1.5 mt-1" />
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">リスクレベル</p>
                    <Badge variant={selectedEmp.RISK_LABEL === "high" ? "destructive" : selectedEmp.RISK_LABEL === "medium" ? "default" : "secondary"} className="mt-1">
                      {selectedEmp.RISK_LABEL === "high" ? "高リスク" : selectedEmp.RISK_LABEL === "medium" ? "中リスク" : "低リスク"}
                    </Badge>
                    <p className="text-xs text-muted-foreground mt-1">{riskScoreToText(selectedEmp.RISK_SCORE)}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">勤続年数</p>
                    <p className="text-2xl font-bold">{selectedEmp.TENURE_YEARS}年</p>
                  </div>
                </div>

                <Separator />

                {detailLoading ? (
                  <div className="flex items-center justify-center py-6 gap-2">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    <span className="text-sm text-muted-foreground">SHAP要因を取得中...</span>
                  </div>
                ) : detail ? (
                  <>
                    {detail.evidence?.ai_summary && (
                      <div className="p-3 rounded-md bg-blue-50 border border-blue-200 mb-3">
                        <p className="text-xs text-blue-700 font-medium mb-1">AI分析結果</p>
                        <div className="text-sm text-blue-900 prose prose-sm max-w-none prose-headings:text-blue-800 prose-strong:text-blue-800 prose-headings:text-base prose-headings:mt-2 prose-headings:mb-1">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>{detail.evidence.ai_summary}</ReactMarkdown>
                        </div>
                      </div>
                    )}

                    {(detail.shapValues?.length ?? 0) > 0 && (
                      <div>
                        <p className="text-xs text-muted-foreground mb-2 flex items-center gap-1">
                          <Brain className="h-3 w-3" />
                          主な影響要因
                        </p>
                        <div className="space-y-2">
                          {detail.shapValues.slice(0, 5).map((sv, i) => {
                            const h = shapToHumanText(Number(sv.SHAP_VALUE), sv.FEATURE_NAME, FEATURE_LABELS);
                            return (
                              <div key={i} className={`flex items-center gap-3 p-2 rounded-md ${h.direction === "up" ? "bg-red-50" : "bg-green-50"}`}>
                                <span className="text-lg w-6 text-center">{h.icon}</span>
                                <div className="flex-1">
                                  <p className="text-sm font-medium">{h.label}</p>
                                  <p className={`text-xs ${h.direction === "up" ? "text-red-600" : "text-green-600"}`}>{h.text}</p>
                                </div>
                                <Badge variant={h.impact === "large" ? "destructive" : h.impact === "medium" ? "default" : "secondary"} className="text-[10px]">
                                  {h.impact === "large" ? "影響大" : h.impact === "medium" ? "影響中" : "影響小"}
                                </Badge>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )}

                    {!detail.shapValues?.length && !detail.evidence && !detail.featureSummary?.length && (
                      <p className="text-sm text-muted-foreground text-center py-2">
                        詳細データなし
                      </p>
                    )}
                  </>
                ) : null}
              </div>

              {retentionSuggestion && (
                <div className="p-3 rounded-md bg-emerald-50 border border-emerald-200">
                  <p className="text-xs text-emerald-700 font-medium mb-2 flex items-center gap-1">
                    <Lightbulb className="h-3 w-3" />
                    リテンション施策提案（Cortex AI_COMPLETE）
                  </p>
                  <div className="text-sm text-emerald-900 prose prose-sm max-w-none prose-strong:text-emerald-800">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{retentionSuggestion}</ReactMarkdown>
                  </div>
                </div>
              )}

              <DialogFooter className="gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  className="gap-1.5 border-emerald-300 text-emerald-700 hover:bg-emerald-50"
                  disabled={retentionLoading}
                  onClick={async () => {
                    setRetentionLoading(true);
                    setRetentionSuggestion("");
                    try {
                      const res = await fetch("/api/attrition/retention", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ employeeId: selectedEmp.EMPLOYEE_ID }),
                      });
                      const data = await res.json();
                      setRetentionSuggestion(data.suggestion || "施策を生成できませんでした");
                    } catch {
                      setRetentionSuggestion("エラーが発生しました");
                    } finally {
                      setRetentionLoading(false);
                    }
                  }}
                >
                  {retentionLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Lightbulb className="h-3.5 w-3.5" />}
                  リテンション施策を提案
                </Button>
                <Link href={`/employees/${selectedEmp.EMPLOYEE_ID}`}>
                  <Button variant="outline" size="sm" className="gap-1.5">
                    <ExternalLink className="h-3.5 w-3.5" />
                    社員詳細を表示
                  </Button>
                </Link>
                <Link href={`/simulation?employee=${selectedEmp.EMPLOYEE_ID}`}>
                  <Button variant="outline" size="sm" className="gap-1.5 text-blue-600 border-blue-300">
                    <GitBranch className="h-3.5 w-3.5" />
                    異動シミュレーション
                  </Button>
                </Link>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
