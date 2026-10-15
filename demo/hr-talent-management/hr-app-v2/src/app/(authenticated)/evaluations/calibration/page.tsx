"use client";

import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import {
  Radar, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, ResponsiveContainer,
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Legend, Tooltip,
} from "recharts";
import {
  AlertTriangle, Loader2, Plus, ArrowLeft, CheckCircle2, Lock, Users, Scale,
} from "lucide-react";
import { AXIS_LABELS, SCORE_AXES } from "@/lib/scoring";

interface SessionSummary {
  SESSION_ID: number;
  SESSION_NAME: string;
  PERIOD: string;
  SCOPE_DEPT_ID: number | null;
  SCOPE_GRADE: string | null;
  DEPT_NAME: string | null;
  TARGET_DISTRIBUTION: Record<string, number>;
  STATUS: string;
  FACILITATOR: string | null;
  NOTES: string | null;
  CREATED_AT: string;
  FINALIZED_AT: string | null;
  ADJUSTMENT_COUNT: number;
}

interface Member {
  EVALUATION_ID: number;
  EMPLOYEE_ID: number;
  NAME: string;
  EMPLOYEE_CODE: string;
  DEPT_NAME: string;
  POSITION_GRADE: string;
  POSITION_TITLE: string;
  GROWTH_SCORE: number | null;
  EXPERTISE_SCORE: number | null;
  LEADERSHIP_SCORE: number | null;
  PROBLEM_SOLVING_SCORE: number | null;
  COLLABORATION_SCORE: number | null;
  COMPOSITE_SCORE: string | null;
  COMPOSITE_RAW: string | null;
  EXPECTATION_GAP: string | null;
  STANDARD_GRADE: string | null;
  MANUAL_GRADE: string | null;
  DEPT_RANK: number | null;
  GRADE_RANK: number | null;
  NEXT_GRADE: string | null;
  NEXT_GRADE_AXES_MET: number | null;
  PROMOTION_READINESS: string | null;
  AI_REASONING: string | null;
  COMMENT: string | null;
  ADJUSTED_GRADE: string | null;
  ADJUSTMENT_REASON: string | null;
  MANAGER_GRADE_REASON: string | null;
  MANAGER_OVERRIDES: { axis: string; ai: number | null; manager: number; reason: string }[] | null;
}

interface DistRow {
  grade: string;
  targetRatio: number;
  targetCount: number;
  actualCount: number;
  delta: number;
}

interface Detail {
  session: SessionSummary;
  members: Member[];
  distribution: DistRow[];
  summary: { total: number; graded: number; ungraded: number; adjusted: number; aligned: boolean };
  readiness_labels: Record<string, string>;
}

const STATUS_LABELS: Record<string, string> = {
  draft: "準備中", in_review: "調整中", finalized: "確定済み",
};
const READINESS_COLOR: Record<string, string> = {
  ready: "border-emerald-500/50 text-emerald-700 dark:text-emerald-400",
  conditional: "border-amber-500/50 text-amber-700 dark:text-amber-400",
  not_ready: "border-muted text-muted-foreground",
  n_a: "border-muted text-muted-foreground",
};

function effectiveGrade(m: Member): string | null {
  return m.ADJUSTED_GRADE ?? m.MANUAL_GRADE ?? m.STANDARD_GRADE;
}

function scopeLabel(s: SessionSummary): string {
  const dept = s.DEPT_NAME ?? "全社";
  return s.SCOPE_GRADE ? `${dept}・等級 ${s.SCOPE_GRADE}` : `${dept}・全等級`;
}

export default function CalibrationPage() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [newPeriod, setNewPeriod] = useState("2025-H1");
  const [newGrade, setNewGrade] = useState("");
  const [grades, setGrades] = useState<{ GRADE: string; TITLE: string }[]>([]);

  const [adjustTarget, setAdjustTarget] = useState<Member | null>(null);
  const [adjustGrade, setAdjustGrade] = useState("B");
  const [adjustReason, setAdjustReason] = useState("");

  const loadList = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/evaluations/calibration");
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "取得に失敗しました");
      setSessions(data.sessions ?? []);
      setGrades(data.grades ?? []);
      // 既定は先頭の等級（全等級一括は非推奨）
      setNewGrade((prev) => prev || data.grades?.[0]?.GRADE || "");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadList(); }, [loadList]);

  const openDetail = useCallback(async (id: number) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/evaluations/calibration/${id}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "取得に失敗しました");
      setDetail(data);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  async function createSession() {
    if (!newName.trim()) { setError("会議名を入力してください"); return; }
    setBusy(true);
    try {
      const res = await fetch("/api/evaluations/calibration", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_name: newName, period: newPeriod, scope_grade: newGrade }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "作成に失敗しました");
      setCreateOpen(false);
      setNewName("");
      await loadList();
      await openDetail(data.session_id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function submitAdjustment() {
    if (!detail || !adjustTarget) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/evaluations/calibration/${detail.session.SESSION_ID}/adjust`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          evaluation_id: adjustTarget.EVALUATION_ID,
          after_grade: adjustGrade,
          reason: adjustReason,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "調整に失敗しました");
      setAdjustTarget(null);
      setAdjustReason("");
      await openDetail(detail.session.SESSION_ID);
      setMessage(`${adjustTarget.NAME} のグレードを ${data.before_grade ?? "-"} → ${data.after_grade} に調整しました`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function setStatus(status: string) {
    if (!detail) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/evaluations/calibration/${detail.session.SESSION_ID}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "更新に失敗しました");
      await openDetail(detail.session.SESSION_ID);
      await loadList();
      setMessage(`ステータスを「${STATUS_LABELS[status]}」に変更しました`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const banner = (
    <>
      {error && (
        <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm">
          <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0 text-destructive" />
          <span>{error}</span>
        </div>
      )}
      {message && (
        <div className="rounded-md border border-emerald-500/40 bg-emerald-500/10 p-3 text-sm">{message}</div>
      )}
    </>
  );

  // ---- List view ----
  if (!detail) {
    return (
      <div className="space-y-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold">評価調整会議</h1>
            <p className="text-sm text-muted-foreground mt-1">
              部門をまたいでグレード分布を揃える工程です。個別の調整は理由付きで記録され、監査できます。
            </p>
          </div>
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4 mr-1" />会議を作成
          </Button>
        </div>
        {banner}

        <Card>
          <CardHeader><CardTitle className="text-base">会議一覧</CardTitle></CardHeader>
          <CardContent>
            {loading ? (
              <div className="space-y-2">{[...Array(4)].map((_, i) => <Skeleton key={i} className="h-9 w-full" />)}</div>
            ) : sessions.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                調整会議はまだありません。「会議を作成」から始めてください。
              </p>
            ) : (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>会議名</TableHead>
                      <TableHead>対象期間</TableHead>
                      <TableHead>範囲</TableHead>
                      <TableHead>ステータス</TableHead>
                      <TableHead className="text-right">調整件数</TableHead>
                      <TableHead className="text-right">操作</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {sessions.map((s) => (
                      <TableRow key={s.SESSION_ID}>
                        <TableCell className="font-medium">{s.SESSION_NAME}</TableCell>
                        <TableCell>{s.PERIOD}</TableCell>
                        <TableCell className="text-sm text-muted-foreground">
                          {scopeLabel(s)}
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline" className={s.STATUS === "finalized" ? "border-emerald-500/50" : ""}>
                            {STATUS_LABELS[s.STATUS] ?? s.STATUS}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right tabular-nums">{s.ADJUSTMENT_COUNT}</TableCell>
                        <TableCell className="text-right">
                          <Button size="sm" variant="outline" onClick={() => openDetail(s.SESSION_ID)}>
                            開く
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </CardContent>
        </Card>

        <Dialog open={createOpen} onOpenChange={setCreateOpen}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>調整会議を作成</DialogTitle>
              <DialogDescription>
                目標分布は S 5% / A 20% / B 50% / C 20% / D 5% で初期化されます。作成後に変更できます。
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-3">
              <div>
                <label className="text-sm font-medium">会議名</label>
                <Input className="mt-1" value={newName} onChange={(e) => setNewName(e.target.value)}
                  placeholder="例: 2025年度上期 M1課長 調整会議" />
              </div>
              <div>
                <label className="text-sm font-medium">対象期間</label>
                <Input className="mt-1" value={newPeriod} onChange={(e) => setNewPeriod(e.target.value)}
                  placeholder="例: 2025-H1" />
                {!/^\d{4}-H[12]$/.test(newPeriod) && (
                  <p className="text-xs text-destructive mt-1">2025-H1 / 2025-H2 の形式で入力してください</p>
                )}
              </div>
              <div>
                <label className="text-sm font-medium">対象等級</label>
                <Select value={newGrade || "__all"} onValueChange={(v) => setNewGrade(!v || v === "__all" ? "" : v)}>
                  <SelectTrigger className="mt-1 w-full">
                    <SelectValue>
                      {newGrade
                        ? `${newGrade}（${grades.find((g) => g.GRADE === newGrade)?.TITLE ?? ""}）`
                        : "全等級（非推奨）"}
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {grades.map((g) => (
                      <SelectItem key={g.GRADE} value={g.GRADE}>{g.GRADE}（{g.TITLE}）</SelectItem>
                    ))}
                    <SelectItem value="__all">全等級（非推奨）</SelectItem>
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground mt-1">
                  調整は同じ等級の中で分布を揃えるのが基本です。等級ごとに会議を作成してください。
                </p>
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <Button variant="ghost" onClick={() => setCreateOpen(false)}>キャンセル</Button>
                <Button onClick={createSession} disabled={busy || !/^\d{4}-H[12]$/.test(newPeriod)}>
                  {busy && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}作成
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </div>
    );
  }

  // ---- Detail view ----
  const s = detail.session;
  const locked = s.STATUS === "finalized";
  const distChart = detail.distribution.map((d) => ({
    grade: d.grade, 目標: d.targetCount, 実際: d.actualCount,
  }));

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <Button variant="ghost" size="sm" className="mb-2 -ml-2" onClick={() => { setDetail(null); setMessage(null); setError(null); }}>
            <ArrowLeft className="h-4 w-4 mr-1" />一覧に戻る
          </Button>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            {s.SESSION_NAME}
            {locked && <Lock className="h-4 w-4 text-muted-foreground" />}
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            {s.PERIOD} / {scopeLabel(s)} / {STATUS_LABELS[s.STATUS] ?? s.STATUS}
          </p>
        </div>
        {!locked && (
          <div className="flex gap-2">
            {s.STATUS === "draft" && (
              <Button variant="outline" onClick={() => setStatus("in_review")} disabled={busy}>
                調整を開始
              </Button>
            )}
            <Button onClick={() => setStatus("finalized")} disabled={busy}>
              <CheckCircle2 className="h-4 w-4 mr-1" />確定
            </Button>
          </div>
        )}
      </div>
      {banner}

      {locked && (
        <div className="flex items-start gap-2 rounded-md border bg-muted/50 p-3 text-sm">
          <Lock className="h-4 w-4 mt-0.5 shrink-0 text-muted-foreground" />
          <span>この調整会議は確定済みです。これ以上の変更はできません。</span>
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardContent className="pt-6">
            <div className="text-xs text-muted-foreground flex items-center gap-1">
              <Users className="h-3.5 w-3.5" />対象人数
            </div>
            <div className="text-2xl font-bold tabular-nums">{detail.summary.total}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div className="text-xs text-muted-foreground">定量化済み</div>
            <div className="text-2xl font-bold tabular-nums">{detail.summary.graded}</div>
            {detail.summary.ungraded > 0 && (
              <div className="text-xs text-amber-600 mt-1">未定量化 {detail.summary.ungraded}名</div>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div className="text-xs text-muted-foreground">調整済み</div>
            <div className="text-2xl font-bold tabular-nums">{detail.summary.adjusted}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div className="text-xs text-muted-foreground flex items-center gap-1">
              <Scale className="h-3.5 w-3.5" />分布
            </div>
            <div className={`text-2xl font-bold ${detail.summary.aligned ? "text-emerald-600" : "text-amber-600"}`}>
              {detail.summary.aligned ? "整合" : "乖離あり"}
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader><CardTitle className="text-base">目標分布との乖離</CardTitle></CardHeader>
        <CardContent>
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={distChart}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="grade" tick={{ fontSize: 12 }} />
                  <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                  <Tooltip />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Bar dataKey="目標" fill="#94a3b8" />
                  <Bar dataKey="実際" fill="#29b5e8" />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>グレード</TableHead>
                    <TableHead className="text-right">目標比率</TableHead>
                    <TableHead className="text-right">目標人数</TableHead>
                    <TableHead className="text-right">実際</TableHead>
                    <TableHead className="text-right">乖離</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {detail.distribution.map((d) => (
                    <TableRow key={d.grade}>
                      <TableCell className="font-medium">{d.grade}</TableCell>
                      <TableCell className="text-right tabular-nums">{(d.targetRatio * 100).toFixed(0)}%</TableCell>
                      <TableCell className="text-right tabular-nums">{d.targetCount}</TableCell>
                      <TableCell className="text-right tabular-nums">{d.actualCount}</TableCell>
                      <TableCell className={`text-right tabular-nums font-medium ${
                        d.delta > 0 ? "text-amber-600" : d.delta < 0 ? "text-sky-600" : "text-muted-foreground"
                      }`}>
                        {d.delta > 0 ? "+" : ""}{d.delta}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">対象者一覧（定量化済み・期待比の高い順）</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>氏名</TableHead>
                  <TableHead>部署</TableHead>
                  <TableHead>等級</TableHead>
                  <TableHead className="text-right">期待比</TableHead>
                  <TableHead>グレード</TableHead>
                  <TableHead>昇格適性</TableHead>
                  <TableHead className="text-right">部内順位</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {detail.members.map((m) => {
                  const eff = effectiveGrade(m);
                  const gap = m.EXPECTATION_GAP === null ? null : Number(m.EXPECTATION_GAP);
                  return (
                    <TableRow key={m.EVALUATION_ID}>
                      <TableCell className="whitespace-nowrap">
                        {m.NAME}
                        <span className="ml-2 text-xs text-muted-foreground">{m.EMPLOYEE_CODE}</span>
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">{m.DEPT_NAME}</TableCell>
                      <TableCell className="text-sm">
                        {m.POSITION_GRADE}
                        <span className="ml-1 text-xs text-muted-foreground">{m.POSITION_TITLE}</span>
                      </TableCell>
                      <TableCell className={`text-right tabular-nums font-medium ${
                        gap === null ? "" : gap > 0 ? "text-emerald-600" : gap < 0 ? "text-amber-600" : ""
                      }`}>
                        {gap === null ? "-" : (gap > 0 ? "+" : "") + gap.toFixed(2)}
                      </TableCell>
                      <TableCell>
                        {m.ADJUSTED_GRADE ? (
                          <Badge variant="outline" className="border-sky-500/50">
                            {m.STANDARD_GRADE ?? "-"} → {m.ADJUSTED_GRADE}
                          </Badge>
                        ) : (
                          <span className="text-sm">{eff ?? "未定量化"}</span>
                        )}
                      </TableCell>
                      <TableCell>
                        {m.PROMOTION_READINESS ? (
                          <Badge variant="outline" className={READINESS_COLOR[m.PROMOTION_READINESS] ?? ""}>
                            {detail.readiness_labels[m.PROMOTION_READINESS] ?? m.PROMOTION_READINESS}
                            {m.NEXT_GRADE && m.PROMOTION_READINESS !== "n_a" && (
                              <span className="ml-1 text-xs">
                                {m.NEXT_GRADE} {m.NEXT_GRADE_AXES_MET}/5
                              </span>
                            )}
                          </Badge>
                        ) : (
                          <span className="text-sm text-muted-foreground">-</span>
                        )}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{m.DEPT_RANK ?? "-"}</TableCell>
                      <TableCell className="text-right">
                        <Button
                          size="sm" variant="outline" disabled={locked || !m.STANDARD_GRADE}
                          onClick={() => {
                            setAdjustTarget(m);
                            setAdjustGrade(eff ?? "B");
                            setAdjustReason("");
                          }}
                        >
                          調整
                        </Button>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
          {detail.members.length === 0 && (
            <p className="text-sm text-muted-foreground mt-3">
              {detail.summary.total === 0
                ? `対象期間 ${s.PERIOD} の評価がありません。`
                : `定量化済みの評価がありません（未定量化 ${detail.summary.ungraded}名）。評価横断レビューで定量化してください。`}
            </p>
          )}
          <p className="text-xs text-muted-foreground mt-3">
            期待比は「実績 − 等級の期待水準」の重み付き合計。0 が期待通りで、等級をまたいで比較できます。
          </p>
        </CardContent>
      </Card>

      <Dialog open={!!adjustTarget} onOpenChange={(o) => !o && setAdjustTarget(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>グレードを調整</DialogTitle>
            <DialogDescription>
              {adjustTarget?.NAME}（{adjustTarget?.POSITION_GRADE} / {adjustTarget?.DEPT_NAME}）
            </DialogDescription>
          </DialogHeader>
          {adjustTarget && (
            <div className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="h-52">
                  <ResponsiveContainer width="100%" height="100%">
                    <RadarChart data={SCORE_AXES.map((a) => ({
                      axis: AXIS_LABELS[a],
                      スコア: Number(
                        adjustTarget[`${a.toUpperCase()}_SCORE` as keyof Member] ?? 0
                      ),
                    }))}>
                      <PolarGrid />
                      <PolarAngleAxis dataKey="axis" tick={{ fontSize: 10 }} />
                      <PolarRadiusAxis domain={[0, 5]} tick={{ fontSize: 9 }} />
                      <Radar dataKey="スコア" stroke="#29b5e8" fill="#29b5e8" fillOpacity={0.35} />
                    </RadarChart>
                  </ResponsiveContainer>
                </div>
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">期待比</span>
                    <span className="tabular-nums font-medium">
                      {adjustTarget.EXPECTATION_GAP === null ? "-" : Number(adjustTarget.EXPECTATION_GAP).toFixed(2)}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">AI推薦グレード</span>
                    <span className="font-medium">{adjustTarget.STANDARD_GRADE ?? "-"}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">単純平均</span>
                    <span className="tabular-nums">
                      {adjustTarget.COMPOSITE_RAW === null ? "-" : Number(adjustTarget.COMPOSITE_RAW).toFixed(1)}
                    </span>
                  </div>
                  {adjustTarget.AI_REASONING && (
                    <div className="pt-2">
                      <div className="text-xs text-muted-foreground mb-1">AI採点根拠</div>
                      <p className="text-xs leading-relaxed">{adjustTarget.AI_REASONING}</p>
                    </div>
                  )}
                </div>
              </div>

              {adjustTarget.COMMENT && (
                <div>
                  <div className="text-xs text-muted-foreground mb-1">上司コメント</div>
                  <p className="text-sm leading-relaxed rounded-md bg-muted/50 p-2">{adjustTarget.COMMENT}</p>
                </div>
              )}

              {((adjustTarget.MANAGER_OVERRIDES?.length ?? 0) > 0 || adjustTarget.MANAGER_GRADE_REASON) && (
                <div className="rounded-md border border-violet-400/50 p-2 text-sm">
                  <div className="text-xs text-muted-foreground mb-1">上長による修正（スコアは修正後の値）</div>
                  {(adjustTarget.MANAGER_OVERRIDES ?? []).map((o) => (
                    <div key={o.axis} className="flex gap-2 text-xs">
                      <span className="w-24 shrink-0">{AXIS_LABELS[o.axis as keyof typeof AXIS_LABELS] ?? o.axis}</span>
                      <span className="font-mono shrink-0">AI {o.ai ?? "-"} → {Number(o.manager)}</span>
                      <span className="text-muted-foreground">{o.reason}</span>
                    </div>
                  ))}
                  {adjustTarget.MANAGER_GRADE_REASON && (
                    <p className="text-xs mt-1">グレード変更の理由: <span className="text-muted-foreground">{adjustTarget.MANAGER_GRADE_REASON}</span></p>
                  )}
                </div>
              )}

              <div className="grid gap-3 sm:grid-cols-[140px_1fr]">
                <div>
                  <label className="text-sm font-medium">調整後グレード</label>
                  <Select value={adjustGrade} onValueChange={(v) => v && setAdjustGrade(v)}>
                    <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {["S", "A", "B", "C", "D"].map((g) => (
                        <SelectItem key={g} value={g}>{g}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <label className="text-sm font-medium">調整理由（必須・5文字以上）</label>
                  <Textarea
                    className="mt-1" rows={3} value={adjustReason}
                    onChange={(e) => setAdjustReason(e.target.value)}
                    placeholder="例: 部門間で基準差があったため、他部門の同水準者に合わせてBに調整"
                  />
                </div>
              </div>

              <div className="flex justify-end gap-2">
                <Button variant="ghost" onClick={() => setAdjustTarget(null)}>キャンセル</Button>
                {adjustGrade === effectiveGrade(adjustTarget) && (
                  <span className="mr-auto self-center text-xs text-muted-foreground">
                    現在と同じグレードです。変更するグレードを選んでください
                  </span>
                )}
                <Button onClick={submitAdjustment}
                  disabled={busy || adjustReason.trim().length < 5 || adjustGrade === effectiveGrade(adjustTarget)}>
                  {busy && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}調整を記録
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
