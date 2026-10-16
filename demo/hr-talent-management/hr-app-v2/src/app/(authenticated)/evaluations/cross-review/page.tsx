"use client";

import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { useHonbu } from "@/lib/honbu-context";
import { useAuth } from "@/lib/auth-context";
import { AXIS_FIELDS, AxisEditor, type AxisValue } from "@/components/evaluation/axis-editor";
import { Brain, Save, ChevronUp, ChevronDown, Loader2, Pencil } from "lucide-react";
import Link from "next/link";

interface EmpRow {
  EMPLOYEE_ID: number;
  NAME: string;
  EMPLOYEE_CODE: string;
  DEPT_NAME: string;
  GRADE: string;
  POSITION_TITLE: string;
  EVALUATION_ID: number;
  EVAL_SCORE: number | null;
  EVAL_GRADE: string | null;
  COMMENT: string | null;
  SELF_COMMENT: string | null;
  GROWTH: number | null;
  EXPERTISE: number | null;
  LEADERSHIP: number | null;
  PROBLEM_SOLVING: number | null;
  COLLABORATION: number | null;
  AI_COMPOSITE: number | null;
  AI_GRADE: string | null;
  AI_REASONING: string | null;
  MANUAL_COMPOSITE: number | null;
  MANUAL_GRADE: string | null;
  MANUAL_NOTE: string | null;
  DEPT_RANK: number | null;
  GRADE_RANK: number | null;
  COMPOSITE_RAW: number | null;
  EXPECTATION_GAP: number | null;
  STANDARD_GRADE: string | null;
  NEXT_GRADE: string | null;
  NEXT_GRADE_AXES_MET: number | null;
  PROMOTION_READINESS: string | null;
  PROMOTION_SHORTFALLS: { axis: string; actual: number; required: number; gap: number }[] | null;
  EXP_GROWTH: number | null;
  EXP_EXPERTISE: number | null;
  EXP_LEADERSHIP: number | null;
  EXP_PROBLEM_SOLVING: number | null;
  EXP_COLLABORATION: number | null;
  STRENGTHS: string[] | null;
  IMPROVEMENTS: string[] | null;
  SENTIMENT: number | null;
  CATEGORY: string | null;
  EVAL_STATUS: string | null;
  MANAGER_GRADE_REASON: string | null;
  RETURN_REASON: string | null;
  MANAGER_OVERRIDES: { axis: string; ai: number | null; manager: number; reason: string; by: string }[] | null;
}

interface Summary {
  total: number;
  gradeDistribution: Record<string, number>;
  readinessDistribution: Record<string, number>;
  avgComposite: number | null;
  avgExpectationGap: number | null;
  quantified: number;
  unquantified: number;
}

interface ManualEdit {
  manual_composite: number | null;
  manual_grade: string | null;
  manual_note: string | null;
  dirty: boolean;
}

const GRADES = ["S", "A", "B", "C", "D"];

const READINESS_LABELS: Record<string, string> = {
  ready: "昇格可", conditional: "条件付き", not_ready: "時期尚早", n_a: "対象外",
};
const READINESS_COLOR: Record<string, string> = {
  ready: "border-emerald-500/60 text-emerald-700 dark:text-emerald-400",
  conditional: "border-amber-500/60 text-amber-700 dark:text-amber-400",
  not_ready: "text-muted-foreground",
  n_a: "text-muted-foreground",
};

const AXIS_JA: Record<string, string> = {
  growth: "成長性", expertise: "専門性", leadership: "リーダーシップ",
  problem_solving: "課題解決力", collaboration: "協調性",
};

const SORT_OPTIONS = [
  { value: "gap", label: "期待比" },
  { value: "composite", label: "AI総合" },
  { value: "eval_score", label: "評価スコア" },
  { value: "growth", label: "成長性" },
  { value: "expertise", label: "専門性" },
  { value: "leadership", label: "リーダーシップ" },
  { value: "problem_solving", label: "課題解決" },
  { value: "collaboration", label: "協調性" },
  { value: "dept_rank", label: "部門順位" },
  { value: "grade_rank", label: "等級順位" },
];

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

function ScoreBar({ value, max = 5 }: { value: number | null; max?: number }) {
  if (value == null) return <span className="text-muted-foreground text-xs">-</span>;
  const pct = (value / max) * 100;
  const color = value >= 4 ? "bg-emerald-500" : value >= 3 ? "bg-blue-500" : value >= 2 ? "bg-amber-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-1.5">
      <div className="w-16 h-2 bg-muted rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-mono w-4">{value}</span>
    </div>
  );
}

export default function CrossReviewPage() {
  const { user } = useAuth();
  const { honbu, honbuList } = useHonbu();
  const [period, setPeriod] = useState(PERIODS[0]);
  const [periodTouched, setPeriodTouched] = useState(false);
  const [availablePeriods, setAvailablePeriods] = useState<string[]>([]);
  const [quantifiedPeriods, setQuantifiedPeriods] = useState<string[]>([]);
  // データのある期間を優先し、足りない分は直近の暦上の期間で補う
  const periodOptions = [...new Set([...availablePeriods, ...PERIODS])].sort().reverse();
  const [sortBy, setSortBy] = useState("gap");
  const [sortOrder, setSortOrder] = useState<"desc" | "asc">("desc");
  const [data, setData] = useState<EmpRow[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(false);
  const [quantifying, setQuantifying] = useState(false);
  const [saving, setSaving] = useState(false);
  const [edits, setEdits] = useState<Record<number, ManualEdit>>({});
  const [detailRow, setDetailRow] = useState<EmpRow | null>(null);

  const fetchData = useCallback(() => {
    if (!honbu || !period) return;
    setLoading(true);
    fetch(`/api/evaluations/cross-review?honbu=${honbu}&period=${encodeURIComponent(period)}&sort_by=${sortBy}&order=${sortOrder}`)
      .then((r) => r.ok ? r.json() : Promise.reject())
      .then((d) => {
        if (Array.isArray(d.availablePeriods) && d.availablePeriods.length > 0) {
          setAvailablePeriods(d.availablePeriods);
          setQuantifiedPeriods(d.quantifiedPeriods || []);
          // 初回だけ、定量化済みの最新期間へ寄せる（なければデータのある最新期間）
          if (!periodTouched) {
            const preferred = (d.quantifiedPeriods || [])[0] ?? d.availablePeriods[0];
            if (preferred && preferred !== period) {
              setPeriodTouched(true);
              setPeriod(preferred);
              return;
            }
          }
        }
        setData(d.employees || []);
        setSummary(d.summary || null);
        const editMap: Record<number, ManualEdit> = {};
        for (const e of (d.employees || []) as EmpRow[]) {
          editMap[e.EVALUATION_ID] = {
            manual_composite: e.MANUAL_COMPOSITE,
            manual_grade: e.MANUAL_GRADE,
            manual_note: e.MANUAL_NOTE,
            dirty: false,
          };
        }
        setEdits(editMap);
      })
      .catch(() => { setData([]); setSummary(null); })
      .finally(() => setLoading(false));
  }, [honbu, period, sortBy, sortOrder, periodTouched]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleQuantify = async () => {
    if (!honbu || !period) return;
    setQuantifying(true);
    try {
      const evalIds = data.map((d) => d.EVALUATION_ID).filter(Boolean);
      if (evalIds.length === 0) return;
      await fetch("/api/evaluations/quantify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ evaluation_ids: evalIds }),
      });
      fetchData();
    } finally {
      setQuantifying(false);
    }
  };

  const handleSave = async () => {
    const dirtyUpdates = Object.entries(edits)
      .filter(([, v]) => v.dirty)
      .map(([evalId, v]) => ({
        evaluation_id: Number(evalId),
        manual_composite: v.manual_composite,
        manual_grade: v.manual_grade,
        manual_note: v.manual_note,
      }));
    if (dirtyUpdates.length === 0) return;
    setSaving(true);
    try {
      await fetch("/api/evaluations/cross-review", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ updates: dirtyUpdates }),
      });
      fetchData();
    } finally {
      setSaving(false);
    }
  };

  const updateEdit = (evalId: number, field: keyof ManualEdit, value: unknown) => {
    setEdits((prev) => ({
      ...prev,
      [evalId]: { ...prev[evalId], [field]: value, dirty: true },
    }));
  };

  const dirtyCount = Object.values(edits).filter((e) => e.dirty).length;
  const canEdit = user?.role === "HR_ADMIN" || user?.role === "HR_MANAGER";

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center gap-4 flex-wrap">
        <h2 className="text-2xl font-bold tracking-tight">評価横断レビュー</h2>
        <Select value={period} onValueChange={(v) => { if (v) { setPeriod(v); setPeriodTouched(true); } }}>
          <SelectTrigger className="w-32"><SelectValue>{period}</SelectValue></SelectTrigger>
          <SelectContent>
            {periodOptions.map((p) => <SelectItem key={p} value={p}>{p}{!availablePeriods.includes(p) ? "（データなし）" : quantifiedPeriods.includes(p) ? "" : "（未定量化）"}</SelectItem>)}
          </SelectContent>
        </Select>
        <Select value={sortBy} onValueChange={(v) => v && setSortBy(v)}>
          <SelectTrigger className="w-36"><SelectValue placeholder="ソート">{SORT_OPTIONS.find((o) => o.value === sortBy)?.label ?? "ソート"}</SelectValue></SelectTrigger>
          <SelectContent>
            {SORT_OPTIONS.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
          </SelectContent>
        </Select>
        <Button variant="ghost" size="icon" onClick={() => setSortOrder((o) => o === "asc" ? "desc" : "asc")}>
          {sortOrder === "asc" ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </Button>
        <div className="ml-auto flex gap-2">
          {canEdit && (
            <Button onClick={handleQuantify} disabled={quantifying || data.length === 0} variant="outline" className="gap-1.5">
              {quantifying ? <Loader2 className="h-4 w-4 animate-spin" /> : <Brain className="h-4 w-4" />}
              AI定量化
            </Button>
          )}
          {canEdit && dirtyCount > 0 && (
            <Button onClick={handleSave} disabled={saving} className="gap-1.5">
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              保存 ({dirtyCount}件)
            </Button>
          )}
        </div>
      </div>

      {summary && (
        <div className="grid grid-cols-5 gap-3">
          <Card><CardContent className="pt-4 text-center"><p className="text-2xl font-bold">{summary.total}</p><p className="text-xs text-muted-foreground">対象者</p></CardContent></Card>
          <Card><CardContent className="pt-4 text-center"><p className="text-2xl font-bold">{summary.quantified}</p><p className="text-xs text-muted-foreground">AI定量化済</p></CardContent></Card>
          <Card><CardContent className="pt-4 text-center"><p className="text-2xl font-bold text-amber-600">{summary.unquantified}</p><p className="text-xs text-muted-foreground">未定量化</p></CardContent></Card>
          <Card><CardContent className="pt-4 text-center"><p className={`text-2xl font-bold ${(summary.avgExpectationGap ?? 0) > 0 ? "text-emerald-600" : (summary.avgExpectationGap ?? 0) < 0 ? "text-amber-600" : ""}`}>{summary.avgExpectationGap === null ? "—" : (summary.avgExpectationGap > 0 ? "+" : "") + summary.avgExpectationGap.toFixed(2)}</p><p className="text-xs text-muted-foreground">平均期待比</p></CardContent></Card>
          <Card><CardContent className="pt-4 text-center">
            <div className="flex gap-1 justify-center flex-wrap">
              {GRADES.map((g) => (
                <Badge key={g} variant="secondary" className="text-[10px]">
                  {g}: {summary.gradeDistribution[g] || 0}
                </Badge>
              ))}
            </div>
            <p className="text-xs text-muted-foreground mt-1">グレード分布</p>
          </CardContent></Card>
        </div>
      )}

      {loading ? (
        <Skeleton className="h-96" />
      ) : data.length === 0 ? (
        <Card><CardContent className="py-12 text-center text-muted-foreground">該当する評価データがありません</CardContent></Card>
      ) : (
        <div className="overflow-x-auto border rounded-lg">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="sticky left-0 bg-background z-10 min-w-[140px]">社員</TableHead>
                <TableHead>等級</TableHead>
                <TableHead>評価</TableHead>
                <TableHead>コメント</TableHead>
                <TableHead>成長性</TableHead>
                <TableHead>専門性</TableHead>
                <TableHead>リーダー</TableHead>
                <TableHead>課題解決</TableHead>
                <TableHead>協調性</TableHead>
                <TableHead>期待比</TableHead>
                <TableHead>AI総合</TableHead>
                <TableHead>AI推薦</TableHead>
                <TableHead>昇格適性</TableHead>
                {canEdit && <TableHead>手動上書</TableHead>}
                {canEdit && <TableHead>手動G</TableHead>}
                <TableHead>部門順位</TableHead>
                <TableHead>等級順位</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.map((row) => (
                <TableRow key={row.EVALUATION_ID} className="cursor-pointer hover:bg-accent/50" onClick={() => setDetailRow(row)}>
                  <TableCell className="sticky left-0 bg-background z-10 font-medium text-sm">
                    {row.NAME}
                    {row.EVAL_STATUS === "draft" && (
                      <Badge variant="outline" className="ml-1 text-[9px] text-muted-foreground" title="上長がまだ提出していません">
                        {row.RETURN_REASON ? "差し戻し中" : "上長未提出"}
                      </Badge>
                    )}
                    {row.EVAL_STATUS === "submitted" && (
                      <Badge variant="outline" className="ml-1 text-[9px] border-emerald-500/50 text-emerald-700 dark:text-emerald-300">提出済</Badge>
                    )}
                    {row.MANAGER_OVERRIDES && row.MANAGER_OVERRIDES.length > 0 && (
                      <Badge variant="outline" className="ml-1 text-[9px] border-violet-400/60 text-violet-700 dark:text-violet-300">
                        上長修正 {row.MANAGER_OVERRIDES.length}
                      </Badge>
                    )}
                    <span className="block text-[10px] text-muted-foreground">{row.DEPT_NAME}</span>
                  </TableCell>
                  <TableCell><Badge variant="secondary" className="text-[10px]">{row.GRADE}</Badge></TableCell>
                  <TableCell>
                    <span className="font-mono text-sm">{row.EVAL_SCORE != null ? Number(row.EVAL_SCORE).toFixed(1) : "—"}</span>
                    {row.EVAL_GRADE && <Badge variant="outline" className="ml-1 text-[9px]">{row.EVAL_GRADE}</Badge>}
                  </TableCell>
                  <TableCell className="max-w-[200px] truncate text-xs text-muted-foreground">{row.COMMENT || "—"}</TableCell>
                  <TableCell><ScoreBar value={row.GROWTH} /></TableCell>
                  <TableCell><ScoreBar value={row.EXPERTISE} /></TableCell>
                  <TableCell><ScoreBar value={row.LEADERSHIP} /></TableCell>
                  <TableCell><ScoreBar value={row.PROBLEM_SOLVING} /></TableCell>
                  <TableCell><ScoreBar value={row.COLLABORATION} /></TableCell>
                  <TableCell>
                    <span className={`font-mono font-bold text-sm ${
                      row.EXPECTATION_GAP == null ? "" :
                      Number(row.EXPECTATION_GAP) > 0 ? "text-emerald-600" :
                      Number(row.EXPECTATION_GAP) < 0 ? "text-amber-600" : ""
                    }`}>
                      {row.EXPECTATION_GAP == null
                        ? "—"
                        : (Number(row.EXPECTATION_GAP) > 0 ? "+" : "") + Number(row.EXPECTATION_GAP).toFixed(2)}
                    </span>
                  </TableCell>
                  <TableCell>
                    <span className="font-mono font-bold text-sm">
                      {row.AI_COMPOSITE != null ? Number(row.AI_COMPOSITE).toFixed(1) : "—"}
                    </span>
                  </TableCell>
                  <TableCell>
                    {row.STANDARD_GRADE ? <Badge className="text-[10px]">{row.STANDARD_GRADE}</Badge> : "—"}
                  </TableCell>
                  <TableCell>
                    {row.PROMOTION_READINESS ? (
                      <Badge variant="outline" className={`text-[10px] ${READINESS_COLOR[row.PROMOTION_READINESS] ?? ""}`}>
                        {READINESS_LABELS[row.PROMOTION_READINESS] ?? row.PROMOTION_READINESS}
                        {row.PROMOTION_READINESS !== "n_a" && row.NEXT_GRADE_AXES_MET != null && (
                          <span className="ml-1">{row.NEXT_GRADE_AXES_MET}/5</span>
                        )}
                      </Badge>
                    ) : "—"}
                  </TableCell>
                  {canEdit && (
                    <TableCell onClick={(e) => e.stopPropagation()}>
                      <Input
                        type="number"
                        min={1} max={5} step={0.1}
                        className="w-16 h-7 text-xs"
                        value={edits[row.EVALUATION_ID]?.manual_composite ?? ""}
                        onChange={(e) => updateEdit(row.EVALUATION_ID, "manual_composite", e.target.value ? Number(e.target.value) : null)}
                        placeholder={row.AI_COMPOSITE != null ? String(row.AI_COMPOSITE) : "—"}
                      />
                    </TableCell>
                  )}
                  {canEdit && (
                    <TableCell onClick={(e) => e.stopPropagation()}>
                      <Select
                        value={edits[row.EVALUATION_ID]?.manual_grade || ""}
                        onValueChange={(v) => updateEdit(row.EVALUATION_ID, "manual_grade", v || null)}
                      >
                        <SelectTrigger className="w-16 h-7 text-xs"><SelectValue placeholder={row.AI_GRADE || "—"} /></SelectTrigger>
                        <SelectContent>
                          {GRADES.map((g) => <SelectItem key={g} value={g}>{g}</SelectItem>)}
                        </SelectContent>
                      </Select>
                    </TableCell>
                  )}
                  <TableCell className="text-center font-mono text-sm">{row.DEPT_RANK ?? "—"}</TableCell>
                  <TableCell className="text-center font-mono text-sm">{row.GRADE_RANK ?? "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <Dialog open={!!detailRow} onOpenChange={(open) => !open && setDetailRow(null)}>
        <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
          {detailRow && (
            <>
              <DialogHeader className="pr-10">
                <DialogTitle className="flex items-center gap-2">
                  {detailRow.NAME} — {detailRow.GRADE} {detailRow.POSITION_TITLE}
                  {canEdit && (
                    <Link href={`/evaluations?edit=${detailRow.EVALUATION_ID}`}>
                      <Button variant="outline" size="sm" className="h-7 gap-1 text-xs">
                        <Pencil className="h-3.5 w-3.5" />
                        評価管理で編集
                      </Button>
                    </Link>
                  )}
                </DialogTitle>
              </DialogHeader>
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <Card>
                    <CardHeader className="pb-2"><CardTitle className="text-sm">上司コメント</CardTitle></CardHeader>
                    <CardContent><p className="text-sm whitespace-pre-wrap">{detailRow.COMMENT || "コメントなし"}</p></CardContent>
                  </Card>
                  <Card>
                    <CardHeader className="pb-2"><CardTitle className="text-sm">自己評価コメント</CardTitle></CardHeader>
                    <CardContent><p className="text-sm whitespace-pre-wrap">{detailRow.SELF_COMMENT || "コメントなし"}</p></CardContent>
                  </Card>
                </div>
                {detailRow.AI_COMPOSITE != null && (
                  <Card>
                    <CardHeader className="pb-2"><CardTitle className="text-sm flex items-center gap-2"><Brain className="h-4 w-4" />{(detailRow.MANAGER_OVERRIDES?.length ?? 0) > 0 ? "5軸スコア（AI採点＋上長修正）" : "AI定量化スコア"}</CardTitle></CardHeader>
                    <CardContent>
                      <div className="grid grid-cols-5 gap-3 mb-3">
                        {[
                          { label: "成長性", value: detailRow.GROWTH, expected: detailRow.EXP_GROWTH },
                          { label: "専門性", value: detailRow.EXPERTISE, expected: detailRow.EXP_EXPERTISE },
                          { label: "リーダーシップ", value: detailRow.LEADERSHIP, expected: detailRow.EXP_LEADERSHIP },
                          { label: "課題解決力", value: detailRow.PROBLEM_SOLVING, expected: detailRow.EXP_PROBLEM_SOLVING },
                          { label: "協調性", value: detailRow.COLLABORATION, expected: detailRow.EXP_COLLABORATION },
                        ].map((s) => {
                          const gap = s.value != null && s.expected != null ? Number(s.value) - Number(s.expected) : null;
                          return (
                            <div key={s.label} className="text-center">
                              <p className="text-2xl font-bold">{s.value ?? "—"}</p>
                              {s.expected != null && (
                                <p className="text-[10px] text-muted-foreground">
                                  期待 {Number(s.expected).toFixed(1)}
                                </p>
                              )}
                              {gap !== null && (
                                <p className={`text-[10px] font-medium ${
                                  gap > 0 ? "text-emerald-600" : gap < 0 ? "text-amber-600" : "text-muted-foreground"
                                }`}>
                                  {gap > 0 ? "+" : ""}{gap.toFixed(1)}
                                </p>
                              )}
                              <p className="text-[10px] text-muted-foreground">{s.label}</p>
                            </div>
                          );
                        })}
                      </div>
                      <div className="flex items-center gap-4 text-sm flex-wrap">
                        <span>
                          期待比:{" "}
                          <strong className={
                            detailRow.EXPECTATION_GAP == null ? "" :
                            Number(detailRow.EXPECTATION_GAP) > 0 ? "text-emerald-600" :
                            Number(detailRow.EXPECTATION_GAP) < 0 ? "text-amber-600" : ""
                          }>
                            {detailRow.EXPECTATION_GAP == null
                              ? "—"
                              : (Number(detailRow.EXPECTATION_GAP) > 0 ? "+" : "") + Number(detailRow.EXPECTATION_GAP).toFixed(2)}
                          </strong>
                        </span>
                        <span>AI総合: <strong>{Number(detailRow.AI_COMPOSITE).toFixed(1)}</strong></span>
                        <span>推薦: <Badge>{detailRow.STANDARD_GRADE ?? detailRow.AI_GRADE}</Badge></span>
                        <span>部門順位: <strong>{detailRow.DEPT_RANK ?? "—"}</strong></span>
                        <span>等級順位: <strong>{detailRow.GRADE_RANK ?? "—"}</strong></span>
                      </div>
                      {detailRow.PROMOTION_READINESS && detailRow.PROMOTION_READINESS !== "n_a" && (
                        <div className="mt-3 rounded-md border p-2 text-sm">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-muted-foreground text-xs">昇格適性</span>
                            <Badge variant="outline" className={READINESS_COLOR[detailRow.PROMOTION_READINESS] ?? ""}>
                              {READINESS_LABELS[detailRow.PROMOTION_READINESS]}
                            </Badge>
                            <span className="text-xs">
                              次等級 {detailRow.NEXT_GRADE} の期待水準を {detailRow.NEXT_GRADE_AXES_MET}/5 軸で達成
                            </span>
                          </div>
                          {detailRow.PROMOTION_SHORTFALLS && detailRow.PROMOTION_SHORTFALLS.length > 0 && (
                            <p className="text-xs text-muted-foreground mt-1">
                              不足:{" "}
                              {detailRow.PROMOTION_SHORTFALLS.map(
                                (s) => `${AXIS_JA[s.axis] ?? s.axis} ${s.actual}→${s.required}`
                              ).join(" / ")}
                            </p>
                          )}
                        </div>
                      )}
                      {detailRow.AI_REASONING && <p className="text-sm text-muted-foreground mt-2">{detailRow.AI_REASONING}</p>}
                    </CardContent>
                  </Card>
                )}
                {(detailRow.STRENGTHS || detailRow.IMPROVEMENTS) && (
                  <div className="grid grid-cols-2 gap-4">
                    {detailRow.STRENGTHS && detailRow.STRENGTHS.length > 0 && (
                      <Card>
                        <CardHeader className="pb-2"><CardTitle className="text-sm text-emerald-600">強み</CardTitle></CardHeader>
                        <CardContent><ul className="text-sm space-y-1">{detailRow.STRENGTHS.map((s, i) => <li key={i}>{s}</li>)}</ul></CardContent>
                      </Card>
                    )}
                    {detailRow.IMPROVEMENTS && detailRow.IMPROVEMENTS.length > 0 && (
                      <Card>
                        <CardHeader className="pb-2"><CardTitle className="text-sm text-amber-600">改善点</CardTitle></CardHeader>
                        <CardContent><ul className="text-sm space-y-1">{detailRow.IMPROVEMENTS.map((s, i) => <li key={i}>{s}</li>)}</ul></CardContent>
                      </Card>
                    )}
                  </div>
                )}
                {((detailRow.MANAGER_OVERRIDES && detailRow.MANAGER_OVERRIDES.length > 0) || detailRow.MANAGER_GRADE_REASON) && (
                  <Card className="border-violet-400/50">
                    <CardHeader className="pb-2"><CardTitle className="text-sm">AI採点からの修正</CardTitle></CardHeader>
                    <CardContent className="space-y-2 text-sm">
                      {(detailRow.MANAGER_OVERRIDES ?? []).map((o) => (
                        <div key={o.axis} className="flex gap-2">
                          <span className="w-28 shrink-0">{AXIS_JA[o.axis] ?? o.axis}</span>
                          <span className="font-mono shrink-0">AI {o.ai ?? "-"} → {Number(o.manager)}</span>
                          <span className="text-muted-foreground">{o.reason}<span className="ml-1 text-[10px]">（修正者: {o.by}）</span></span>
                        </div>
                      ))}
                      {detailRow.MANAGER_GRADE_REASON && (
                        <p>最終グレード <b>{detailRow.EVAL_GRADE}</b>（推奨から変更）: <span className="text-muted-foreground">{detailRow.MANAGER_GRADE_REASON}</span></p>
                      )}
                      <p className="text-xs text-muted-foreground">上の5軸スコアと期待比は、修正を反映した値です。</p>
                    </CardContent>
                  </Card>
                )}
                {canEdit && detailRow.AI_COMPOSITE != null && (
                  <AxisEditor
                    key={detailRow.EVALUATION_ID}
                    evaluationId={detailRow.EVALUATION_ID}
                    axes={axisValuesOf(detailRow)}
                    onSaved={() => { setDetailRow(null); fetchData(); }}
                  />
                )}
                {canEdit && detailRow.EVAL_STATUS === "submitted" && (
                  <ReturnToManager evaluationId={detailRow.EVALUATION_ID} onDone={() => { setDetailRow(null); fetchData(); }} />
                )}
                {canEdit && (
                  <Card>
                    <CardHeader className="pb-2"><CardTitle className="text-sm">手動修正メモ</CardTitle></CardHeader>
                    <CardContent>
                      <Textarea
                        value={edits[detailRow.EVALUATION_ID]?.manual_note || ""}
                        onChange={(e) => updateEdit(detailRow.EVALUATION_ID, "manual_note", e.target.value || null)}
                        placeholder="修正理由をメモ..."
                        rows={2}
                      />
                    </CardContent>
                  </Card>
                )}
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

const AXIS_KEYS: Record<string, keyof EmpRow> = {
  growth: "GROWTH", expertise: "EXPERTISE", leadership: "LEADERSHIP",
  problem_solving: "PROBLEM_SOLVING", collaboration: "COLLABORATION",
};

/** The editor wants AI vs effective per axis; the row has effective scores plus the override list. */
function axisValuesOf(row: EmpRow): AxisValue[] {
  const overrides = new Map((row.MANAGER_OVERRIDES ?? []).map((o) => [o.axis, o]));
  return AXIS_FIELDS.map((f) => {
    const o = overrides.get(f.axis);
    const eff = Number(row[AXIS_KEYS[f.axis]]);
    return { axis: f.axis, ai: o ? o.ai : eff, score: eff, reason: o?.reason ?? null };
  });
}

/** Send a submitted review back to the line manager with a reason. */
function ReturnToManager({ evaluationId, onDone }: { evaluationId: number; onDone: () => void }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function send() {
    setBusy(true); setErr(null);
    try {
      const r = await fetch(`/api/evaluations/${evaluationId}/return`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || "差し戻しに失敗しました");
      onDone();
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  return (
    <Card>
      <CardHeader className="pb-2"><CardTitle className="text-sm">上長に差し戻す</CardTitle></CardHeader>
      <CardContent className="space-y-2">
        <Textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)}
          placeholder="例: リーダーシップを4に上げた根拠を、具体的な行動で追記してください" />
        {err && <p className="text-xs text-destructive">{err}</p>}
        <div className="flex justify-end">
          <Button size="sm" variant="outline" onClick={send} disabled={busy || reason.trim().length < 5}>
            {busy && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}差し戻す
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
