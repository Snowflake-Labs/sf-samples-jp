"use client";

import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import {
  Radar, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, ResponsiveContainer, Legend,
} from "recharts";
import { AlertTriangle, Save, Loader2, RotateCcw, History, Eye } from "lucide-react";
import { SCORE_AXES, AXIS_LABELS, type ScoreAxis } from "@/lib/scoring";

interface AxisValue { expected: number; weight: number }
interface Standard {
  grade: string;
  sort_order: number;
  updated_at: string;
  updated_by: string | null;
  axes: Record<ScoreAxis, AxisValue>;
}
interface HistoryRow {
  HISTORY_ID: number;
  GRADE: string;
  SNAPSHOT: { axes: Record<ScoreAxis, AxisValue> };
  CHANGED_BY: string;
  CHANGE_NOTE: string | null;
  CHANGED_AT: string;
}
interface PreviewChange {
  employee_id: number;
  name: string;
  dept_name: string;
  before_gap: number | null;
  after_gap: number;
  gap_delta: number | null;
  before_grade: string | null;
  after_grade: string;
  grade_changed: boolean;
}
interface Preview {
  grade: string;
  affected_count: number;
  grade_change_count: number;
  distribution_before: Record<string, number>;
  distribution_after: Record<string, number>;
  changes: PreviewChange[];
}

const GRADE_LABELS: Record<string, string> = {
  E1: "本部長", D1: "部長", D2: "副部長", M1: "課長", M2: "課長補佐",
  S1: "主任", S2: "上級担当", J1: "担当", J2: "担当(初級)", J3: "新卒",
};

export default function ScoreStandardsPage() {
  const [standards, setStandards] = useState<Standard[]>([]);
  const [history, setHistory] = useState<HistoryRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const [draft, setDraft] = useState<Record<ScoreAxis, AxisValue> | null>(null);
  const [note, setNote] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/settings/score-standards?history=true");
      if (!res.ok) throw new Error((await res.json()).error || "取得に失敗しました");
      const data = await res.json();
      setStandards(data.standards ?? []);
      setHistory(data.history ?? []);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const current = standards.find((s) => s.grade === selected) ?? null;
  const weightSum = draft ? SCORE_AXES.reduce((a, k) => a + (draft[k]?.weight ?? 0), 0) : 0;
  const weightValid = Math.abs(weightSum - 1.0) < 0.001;
  const dirty = !!(current && draft && SCORE_AXES.some(
    (k) => draft[k].expected !== current.axes[k].expected || draft[k].weight !== current.axes[k].weight
  ));

  function startEdit(s: Standard) {
    setSelected(s.grade);
    setDraft(JSON.parse(JSON.stringify(s.axes)));
    setNote("");
    setPreview(null);
    setError(null);
    setMessage(null);
  }

  function setAxis(axis: ScoreAxis, field: keyof AxisValue, raw: string) {
    if (!draft) return;
    const v = Number(raw);
    if (!Number.isFinite(v)) return;
    setDraft({ ...draft, [axis]: { ...draft[axis], [field]: v } });
  }

  async function runPreview() {
    if (!selected || !draft) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/settings/score-standards/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ grade: selected, axes: draft }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "プレビューに失敗しました");
      setPreview(data);
      setPreviewOpen(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!selected || !draft) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/settings/score-standards", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ grade: selected, axes: draft, change_note: note || null }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "保存に失敗しました");
      const n = data.recalculated?.updated ?? 0;
      setMessage(`${selected} の基準を保存しました。${n}件のスコアを再計算しました（LLMは再実行していません）`);
      setPreviewOpen(false);
      setPreview(null);
      await load();
      setDraft(null);
      setSelected(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const radarData = current && draft
    ? SCORE_AXES.map((a) => ({
        axis: AXIS_LABELS[a],
        現行: current.axes[a].expected,
        変更後: draft[a].expected,
      }))
    : [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">評価基準マスタ</h1>
        <p className="text-sm text-muted-foreground mt-1">
          等級ごとの期待水準と重みを管理します。AIは全社共通の絶対スケールで採点し、ここで設定した期待水準との差分が順位の主指標になります。
        </p>
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm">
          <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0 text-destructive" />
          <span>{error}</span>
        </div>
      )}
      {message && (
        <div className="rounded-md border border-emerald-500/40 bg-emerald-500/10 p-3 text-sm">{message}</div>
      )}

      <Tabs defaultValue="standards">
        <TabsList>
          <TabsTrigger value="standards">期待水準</TabsTrigger>
          <TabsTrigger value="history">
            <History className="h-3.5 w-3.5 mr-1" />変更履歴
          </TabsTrigger>
        </TabsList>

        <TabsContent value="standards" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">等級一覧</CardTitle>
            </CardHeader>
            <CardContent>
              {loading ? (
                <div className="space-y-2">
                  {[...Array(5)].map((_, i) => <Skeleton key={i} className="h-9 w-full" />)}
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>等級</TableHead>
                        {SCORE_AXES.map((a) => (
                          <TableHead key={a} className="text-right whitespace-nowrap">
                            {AXIS_LABELS[a]}
                          </TableHead>
                        ))}
                        <TableHead className="text-right">操作</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {standards.map((s) => (
                        <TableRow key={s.grade} className={selected === s.grade ? "bg-muted/50" : ""}>
                          <TableCell className="font-medium whitespace-nowrap">
                            {s.grade}
                            <span className="ml-2 text-xs text-muted-foreground">
                              {GRADE_LABELS[s.grade] ?? ""}
                            </span>
                          </TableCell>
                          {SCORE_AXES.map((a) => (
                            <TableCell key={a} className="text-right tabular-nums whitespace-nowrap">
                              {s.axes[a].expected.toFixed(1)}
                              <span className="text-xs text-muted-foreground ml-1">
                                ×{s.axes[a].weight.toFixed(2)}
                              </span>
                            </TableCell>
                          ))}
                          <TableCell className="text-right">
                            <Button size="sm" variant="outline" onClick={() => startEdit(s)}>編集</Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
              <p className="text-xs text-muted-foreground mt-3">
                各セルは「期待水準 ×重み」。重みは等級ごとに合計1.00になります。
              </p>
            </CardContent>
          </Card>

          {current && draft && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">
                  {current.grade}（{GRADE_LABELS[current.grade] ?? ""}）の基準を編集
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid gap-4 lg:grid-cols-2">
                  <div className="space-y-3">
                    {SCORE_AXES.map((a) => (
                      <div key={a} className="grid grid-cols-[1fr_auto_auto] items-center gap-3">
                        <label className="text-sm">{AXIS_LABELS[a]}</label>
                        <div className="flex items-center gap-1">
                          <span className="text-xs text-muted-foreground">期待</span>
                          <Input
                            type="number" min={1} max={5} step={0.1}
                            className="w-20 text-right tabular-nums"
                            value={draft[a].expected}
                            onChange={(e) => setAxis(a, "expected", e.target.value)}
                          />
                        </div>
                        <div className="flex items-center gap-1">
                          <span className="text-xs text-muted-foreground">重み</span>
                          <Input
                            type="number" min={0} max={1} step={0.01}
                            className="w-20 text-right tabular-nums"
                            value={draft[a].weight}
                            onChange={(e) => setAxis(a, "weight", e.target.value)}
                          />
                        </div>
                      </div>
                    ))}
                    <div className={`text-sm rounded-md px-3 py-2 ${weightValid ? "bg-muted" : "bg-destructive/10 text-destructive"}`}>
                      重み合計: <span className="tabular-nums font-medium">{weightSum.toFixed(3)}</span>
                      {!weightValid && " — 1.000 にしてください"}
                    </div>
                  </div>

                  <div className="h-64">
                    <ResponsiveContainer width="100%" height="100%">
                      <RadarChart data={radarData}>
                        <PolarGrid />
                        <PolarAngleAxis dataKey="axis" tick={{ fontSize: 11 }} />
                        <PolarRadiusAxis domain={[0, 5]} tick={{ fontSize: 10 }} />
                        <Radar name="現行" dataKey="現行" stroke="#94a3b8" fill="#94a3b8" fillOpacity={0.25} />
                        <Radar name="変更後" dataKey="変更後" stroke="#29b5e8" fill="#29b5e8" fillOpacity={0.35} />
                        <Legend wrapperStyle={{ fontSize: 12 }} />
                      </RadarChart>
                    </ResponsiveContainer>
                  </div>
                </div>

                <div>
                  <label className="text-sm font-medium">変更理由（履歴に残ります）</label>
                  <Textarea
                    className="mt-1" rows={2} value={note}
                    onChange={(e) => setNote(e.target.value)}
                    placeholder="例: 課長層のリーダーシップ期待値を引き上げ（2026年度方針）"
                  />
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <Button variant="outline" onClick={runPreview} disabled={busy || !weightValid || !dirty}>
                    {busy ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <Eye className="h-4 w-4 mr-1" />}
                    影響をプレビュー
                  </Button>
                  <Button onClick={save} disabled={busy || !weightValid || !dirty}>
                    <Save className="h-4 w-4 mr-1" />保存して再計算
                  </Button>
                  <Button variant="ghost" onClick={() => { setDraft(null); setSelected(null); setPreview(null); }}>
                    <RotateCcw className="h-4 w-4 mr-1" />キャンセル
                  </Button>
                  {!dirty && <span className="text-xs text-muted-foreground">変更がありません</span>}
                </div>
              </CardContent>
            </Card>
          )}
        </TabsContent>

        <TabsContent value="history">
          <Card>
            <CardHeader><CardTitle className="text-base">変更履歴（最新100件）</CardTitle></CardHeader>
            <CardContent>
              {history.length === 0 ? (
                <p className="text-sm text-muted-foreground">変更履歴はまだありません。</p>
              ) : (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>変更日時</TableHead>
                        <TableHead>等級</TableHead>
                        <TableHead>変更者</TableHead>
                        <TableHead>変更前の期待水準</TableHead>
                        <TableHead>理由</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {history.map((h) => (
                        <TableRow key={h.HISTORY_ID}>
                          <TableCell className="whitespace-nowrap text-sm">
                            {new Date(h.CHANGED_AT).toLocaleString("ja-JP")}
                          </TableCell>
                          <TableCell className="font-medium">{h.GRADE}</TableCell>
                          <TableCell className="text-sm">{h.CHANGED_BY}</TableCell>
                          <TableCell className="text-xs tabular-nums">
                            {h.SNAPSHOT?.axes
                              ? SCORE_AXES.map((a) => `${AXIS_LABELS[a]} ${h.SNAPSHOT.axes[a].expected}`).join(" / ")
                              : "-"}
                          </TableCell>
                          <TableCell className="text-sm">{h.CHANGE_NOTE ?? "-"}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      <Dialog open={previewOpen} onOpenChange={setPreviewOpen}>
        <DialogContent className="max-w-4xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>変更の影響プレビュー</DialogTitle>
            <DialogDescription>
              保存前の試算です。この時点ではまだ何も変更されていません。
            </DialogDescription>
          </DialogHeader>
          {preview && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                <div className="rounded-md border p-3">
                  <div className="text-xs text-muted-foreground">対象人数</div>
                  <div className="text-xl font-bold tabular-nums">{preview.affected_count}</div>
                </div>
                <div className="rounded-md border p-3">
                  <div className="text-xs text-muted-foreground">グレードが変わる人数</div>
                  <div className={`text-xl font-bold tabular-nums ${preview.grade_change_count > 0 ? "text-amber-600" : ""}`}>
                    {preview.grade_change_count}
                  </div>
                </div>
                <div className="rounded-md border p-3">
                  <div className="text-xs text-muted-foreground">対象等級</div>
                  <div className="text-xl font-bold">{preview.grade}</div>
                </div>
              </div>

              {preview.affected_count === 0 ? (
                <p className="text-sm text-muted-foreground">
                  この等級には定量化済みの評価がまだないため、影響を受ける社員はいません。
                </p>
              ) : (
                <>
                  <div className="text-sm">
                    <span className="font-medium">グレード分布: </span>
                    {["S", "A", "B", "C", "D"].map((g) => {
                      const b = preview.distribution_before[g] ?? 0;
                      const a = preview.distribution_after[g] ?? 0;
                      return (
                        <span key={g} className="inline-block mr-3 tabular-nums">
                          {g}: {b}
                          {a !== b && <span className={a > b ? "text-emerald-600" : "text-amber-600"}> → {a}</span>}
                        </span>
                      );
                    })}
                  </div>

                  <div className="overflow-x-auto">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>氏名</TableHead>
                          <TableHead>部署</TableHead>
                          <TableHead className="text-right">現在の期待比</TableHead>
                          <TableHead className="text-right">変更後</TableHead>
                          <TableHead className="text-right">差分</TableHead>
                          <TableHead>グレード</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {preview.changes.map((c) => (
                          <TableRow key={c.employee_id}>
                            <TableCell className="whitespace-nowrap">{c.name}</TableCell>
                            <TableCell className="text-sm text-muted-foreground">{c.dept_name}</TableCell>
                            <TableCell className="text-right tabular-nums">
                              {c.before_gap === null ? "-" : c.before_gap.toFixed(2)}
                            </TableCell>
                            <TableCell className="text-right tabular-nums">{c.after_gap.toFixed(2)}</TableCell>
                            <TableCell className={`text-right tabular-nums ${
                              (c.gap_delta ?? 0) > 0 ? "text-emerald-600" : (c.gap_delta ?? 0) < 0 ? "text-amber-600" : ""
                            }`}>
                              {c.gap_delta === null ? "-" : (c.gap_delta > 0 ? "+" : "") + c.gap_delta.toFixed(2)}
                            </TableCell>
                            <TableCell>
                              {c.grade_changed ? (
                                <Badge variant="outline" className="border-amber-500/50">
                                  {c.before_grade} → {c.after_grade}
                                </Badge>
                              ) : (
                                <span className="text-sm text-muted-foreground">{c.after_grade}</span>
                              )}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    差分の大きい順に最大100件を表示しています。
                  </p>
                </>
              )}

              <div className="flex justify-end gap-2 pt-2">
                <Button variant="ghost" onClick={() => setPreviewOpen(false)}>閉じる</Button>
                <Button onClick={save} disabled={busy}>
                  {busy ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <Save className="h-4 w-4 mr-1" />}
                  この内容で保存
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
