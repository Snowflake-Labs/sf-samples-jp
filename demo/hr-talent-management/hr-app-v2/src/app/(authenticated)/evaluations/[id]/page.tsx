"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ArrowLeft, User, Building2, ClipboardCheck, TrendingUp, Pencil, Save, X, Loader2 } from "lucide-react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";

interface EvalDetail {
  EVALUATION_ID: number;
  EMPLOYEE_ID: number;
  PERIOD: string;
  SCORE: number;
  GRADE: string;
  COMMENT: string;
  SELF_COMMENT: string;
  STATUS: string;
  EMPLOYEE_NAME: string;
  DEPT_NAME: string;
  POSITION_TITLE: string;
  EVALUATOR_NAME: string;
}

interface HistoryEntry {
  EVALUATION_ID: number;
  PERIOD: string;
  SCORE: number;
  GRADE: string;
  STATUS: string;
}

const GRADE_COLORS: Record<string, string> = {
  S: "#ef4444",
  A: "#f97316",
  B: "#3b82f6",
  C: "#6b7280",
  D: "#9ca3af",
};

const EVAL_GRADES = ["S", "A", "B", "C", "D"];

export default function EvaluationDetailPage() {
  const params = useParams();
  const [evaluation, setEvaluation] = useState<EvalDetail | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editForm, setEditForm] = useState({ SCORE: 0, GRADE: "", COMMENT: "", SELF_COMMENT: "", STATUS: "" });

  useEffect(() => {
    fetch(`/api/evaluations/${params.id}`)
      .then((r) => {
        if (!r.ok) throw new Error(r.status === 404 ? "not_found" : "error");
        return r.json();
      })
      .then((data) => setEvaluation(data))
      .catch((err) => setError(err.message === "not_found" ? "評価が見つかりません" : "取得に失敗しました"))
      .finally(() => setLoading(false));
  }, [params.id]);

  const fetchHistory = useCallback((employeeId: number) => {
    setHistoryLoading(true);
    fetch(`/api/evaluations?employee_id=${employeeId}&limit=20&offset=0`)
      .then((r) => {
        if (!r.ok) throw new Error("Failed");
        return r.json();
      })
      .then((res) => {
        const empEvals = (res.data || [])
          .map((ev: EvalDetail) => ({
            EVALUATION_ID: ev.EVALUATION_ID,
            PERIOD: ev.PERIOD,
            SCORE: ev.SCORE,
            GRADE: ev.GRADE,
            STATUS: ev.STATUS,
          }))
          .sort((a: HistoryEntry, b: HistoryEntry) => a.PERIOD.localeCompare(b.PERIOD));
        setHistory(empEvals);
      })
      .catch(() => setHistory([]))
      .finally(() => setHistoryLoading(false));
  }, []);

  useEffect(() => {
    if (evaluation) fetchHistory(evaluation.EMPLOYEE_ID);
  }, [evaluation, fetchHistory]);

  const startEditing = () => {
    if (!evaluation) return;
    setEditForm({
      SCORE: evaluation.SCORE,
      GRADE: evaluation.GRADE,
      COMMENT: evaluation.COMMENT || "",
      SELF_COMMENT: evaluation.SELF_COMMENT || "",
      STATUS: evaluation.STATUS,
    });
    setEditing(true);
  };

  const cancelEditing = () => {
    setEditing(false);
  };

  const saveEvaluation = async () => {
    if (!evaluation) return;
    setSaving(true);
    try {
      const res = await fetch(`/api/evaluations/${evaluation.EVALUATION_ID}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          SCORE: Number(editForm.SCORE),
          GRADE: editForm.GRADE,
          COMMENT: editForm.COMMENT,
          SELF_COMMENT: editForm.SELF_COMMENT,
          STATUS: editForm.STATUS,
        }),
      });
      if (!res.ok) throw new Error("Failed");
      const updated = await res.json();
      setEvaluation(updated);
      setEditing(false);
      fetchHistory(updated.EMPLOYEE_ID);
    } catch {
      setError("保存に失敗しました");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="p-6 space-y-4">
        <Skeleton className="h-8 w-48" />
        <div className="grid grid-cols-2 gap-4">
          <Skeleton className="h-64" />
          <Skeleton className="h-64" />
        </div>
        <Skeleton className="h-48" />
      </div>
    );
  }

  if (error || !evaluation) {
    return (
      <div className="p-6 space-y-4">
        <Link href="/evaluations" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-4 w-4" />
          評価一覧に戻る
        </Link>
        <p className="text-muted-foreground">{error || "評価が見つかりません"}</p>
      </div>
    );
  }

  const statusBadge = evaluation.STATUS === "confirmed" ? (
    <Badge className="bg-emerald-100 text-emerald-800 hover:bg-emerald-100">確定</Badge>
  ) : (
    <Badge className="bg-amber-100 text-amber-800 hover:bg-amber-100">下書き</Badge>
  );

  const gradeBadge = (
    <Badge
      style={{ backgroundColor: GRADE_COLORS[evaluation.GRADE] || "#6b7280", color: "#fff" }}
    >
      {evaluation.GRADE}
    </Badge>
  );

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <Link href="/evaluations" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-4 w-4" />
          評価一覧に戻る
        </Link>
        <div className="flex items-center gap-2">
          {!editing ? (
            <>
              {statusBadge}
              {gradeBadge}
              <Button variant="outline" size="sm" onClick={startEditing} className="gap-1.5">
                <Pencil className="h-3.5 w-3.5" />
                編集
              </Button>
            </>
          ) : (
            <>
              <Button variant="outline" size="sm" onClick={cancelEditing} disabled={saving} className="gap-1.5">
                <X className="h-3.5 w-3.5" />
                キャンセル
              </Button>
              <Button size="sm" onClick={saveEvaluation} disabled={saving} className="gap-1.5">
                {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
                保存
              </Button>
            </>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm flex items-center gap-2">
              <User className="h-4 w-4 text-muted-foreground" />
              対象者
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Link href={`/employees/${evaluation.EMPLOYEE_ID}`} className="text-lg font-bold text-blue-600 hover:underline">
              {evaluation.EMPLOYEE_NAME}
            </Link>
            <p className="text-sm text-muted-foreground mt-1">{evaluation.PERIOD}</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm flex items-center gap-2">
              <Building2 className="h-4 w-4 text-muted-foreground" />
              所属
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-lg font-bold">{evaluation.DEPT_NAME}</p>
            <p className="text-sm text-muted-foreground mt-1">{evaluation.POSITION_TITLE}</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm flex items-center gap-2">
              <ClipboardCheck className="h-4 w-4 text-muted-foreground" />
              スコア
            </CardTitle>
          </CardHeader>
          <CardContent>
            {editing ? (
              <div className="space-y-3">
                <div>
                  <label className="text-xs text-muted-foreground">スコア (0.0 - 5.0)</label>
                  <Input
                    type="number"
                    step="0.1"
                    min="0"
                    max="5"
                    value={editForm.SCORE}
                    onChange={(e) => setEditForm((f) => ({ ...f, SCORE: Number(e.target.value) }))}
                    className="mt-1 font-mono"
                  />
                </div>
                <div>
                  <label className="text-xs text-muted-foreground">グレード</label>
                  <Select value={editForm.GRADE} onValueChange={(v) => setEditForm((f) => ({ ...f, GRADE: v ?? f.GRADE }))}>
                    <SelectTrigger className="mt-1">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {EVAL_GRADES.map((g) => (
                        <SelectItem key={g} value={g}>{g}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <label className="text-xs text-muted-foreground">ステータス</label>
                  <Select value={editForm.STATUS} onValueChange={(v) => setEditForm((f) => ({ ...f, STATUS: v ?? f.STATUS }))}>
                    <SelectTrigger className="mt-1">
                      <SelectValue>{({ draft: "下書き", confirmed: "確定" } as Record<string, string>)[editForm.STATUS as string] ?? editForm.STATUS}</SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="draft">下書き</SelectItem>
                      <SelectItem value="confirmed">確定</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
            ) : (
              <>
                <div className="flex items-baseline gap-3">
                  <span className="text-3xl font-bold font-mono">{evaluation.SCORE != null ? Number(evaluation.SCORE).toFixed(1) : '—'}</span>
                  {gradeBadge}
                </div>
                <p className="text-sm text-muted-foreground mt-1">評価者: {evaluation.EVALUATOR_NAME}</p>
              </>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">評価コメント</CardTitle>
          </CardHeader>
          <CardContent>
            {editing ? (
              <Textarea
                rows={5}
                value={editForm.COMMENT}
                onChange={(e) => setEditForm((f) => ({ ...f, COMMENT: e.target.value }))}
                placeholder="評価コメントを入力"
              />
            ) : (
              <div className="p-4 rounded-lg bg-muted text-sm whitespace-pre-wrap">
                {evaluation.COMMENT || "コメントなし"}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">自己評価コメント</CardTitle>
          </CardHeader>
          <CardContent>
            {editing ? (
              <Textarea
                rows={5}
                value={editForm.SELF_COMMENT}
                onChange={(e) => setEditForm((f) => ({ ...f, SELF_COMMENT: e.target.value }))}
                placeholder="自己評価コメントを入力"
              />
            ) : (
              <div className="p-4 rounded-lg bg-muted text-sm whitespace-pre-wrap">
                {evaluation.SELF_COMMENT || "コメントなし"}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base flex items-center gap-2">
            <TrendingUp className="h-4 w-4" />
            評価履歴
          </CardTitle>
          <CardDescription>
            {evaluation.EMPLOYEE_NAME}の過去の評価スコア推移
          </CardDescription>
        </CardHeader>
        <CardContent>
          {historyLoading ? (
            <Skeleton className="h-48" />
          ) : history.length > 1 ? (
            <div className="space-y-4">
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={history} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="PERIOD" tick={{ fontSize: 11 }} />
                  <YAxis domain={[0, 5]} tick={{ fontSize: 11 }} />
                  <Tooltip
                    formatter={(value: number, _name: string) => [`${Number(value).toFixed(1)}`, "スコア"]}
                    labelFormatter={(label: string) => `期間: ${label}`}
                  />
                  <ReferenceLine y={evaluation.SCORE} stroke="hsl(var(--chart-1))" strokeDasharray="3 3" />
                  <Line
                    type="monotone"
                    dataKey="SCORE"
                    stroke="hsl(var(--chart-1))"
                    strokeWidth={2}
                    dot={(props: { cx: number; cy: number; payload: HistoryEntry }) => {
                      const { cx, cy, payload } = props;
                      const isCurrent = payload.EVALUATION_ID === evaluation.EVALUATION_ID;
                      return (
                        <circle
                          key={payload.EVALUATION_ID}
                          cx={cx}
                          cy={cy}
                          r={isCurrent ? 6 : 4}
                          fill={isCurrent ? "hsl(var(--chart-1))" : "#fff"}
                          stroke="hsl(var(--chart-1))"
                          strokeWidth={2}
                        />
                      );
                    }}
                  />
                </LineChart>
              </ResponsiveContainer>

              <Separator />

              <div className="flex flex-wrap gap-2">
                {history.map((h) => (
                  <Link
                    key={h.EVALUATION_ID}
                    href={`/evaluations/${h.EVALUATION_ID}`}
                    className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs border transition-colors hover:bg-accent ${
                      h.EVALUATION_ID === evaluation.EVALUATION_ID
                        ? "border-primary bg-primary/5 font-bold"
                        : ""
                    }`}
                  >
                    <span className="font-mono">{h.PERIOD}</span>
                    <Badge
                      className="text-[10px] px-1.5 py-0"
                      style={{ backgroundColor: GRADE_COLORS[h.GRADE] || "#6b7280", color: "#fff" }}
                    >
                      {h.GRADE}
                    </Badge>
                    <span className="font-mono">{h.SCORE != null ? Number(h.SCORE).toFixed(1) : '—'}</span>
                  </Link>
                ))}
              </div>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground py-4 text-center">
              他の期間の評価データがありません
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
