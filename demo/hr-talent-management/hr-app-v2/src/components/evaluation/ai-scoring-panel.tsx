"use client";

import { useCallback, useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { AlertTriangle, Brain, Loader2 } from "lucide-react";
import { AXIS_FIELDS, AxisEditor, type AxisValue } from "@/components/evaluation/axis-editor";

export interface AiDetail {
  scored: boolean;
  stale: boolean;
  axes: { axis: string; ai: number | null; effective: number | null; reason: string | null }[];
  reasoning: string | null;
  standardGrade: string | null;
  expectationGap: number | null;
  allowedGrades: string[];
  gradeReason: string | null;
  reviewNote: string | null;
  calibration: { grade: string | null; reason: string; sessionName: string; finalized: boolean } | null;
}

/**
 * AI recommendation → calibration-meeting adjustment → final grade, side by side,
 * so a difference from the 評価調整会議 screen is visible where it comes from.
 */
export function GradeTrail({ finalGrade, detail }: { finalGrade: string | null; detail: AiDetail | null }) {
  const cal = detail?.calibration;
  const steps = [
    { label: "推奨グレード（5軸から）", value: detail?.standardGrade ?? null, note: null },
    { label: "調整会議", value: cal?.grade ?? null, note: cal ? `${cal.sessionName}${cal.finalized ? "" : "（未確定）"}` : null },
    { label: "最終グレード", value: finalGrade, note: null },
  ];
  return (
    <div className="space-y-1">
      <div className="grid grid-cols-3 gap-2">
        {steps.map((s) => (
          <div key={s.label} className="rounded-md border p-2">
            <p className="text-[10px] text-muted-foreground">{s.label}</p>
            {s.value ? <p className="font-mono font-semibold">{s.value}</p> : <p className="text-xs text-muted-foreground mt-1">データなし</p>}
            {s.note && <p className="text-[10px] text-muted-foreground truncate">{s.note}</p>}
          </div>
        ))}
      </div>
      {cal?.reason && <p className="text-xs">調整理由: <span className="text-muted-foreground">{cal.reason}</span></p>}
      {cal?.grade && finalGrade && cal.grade !== finalGrade && (
        <p className="text-xs flex items-start gap-1.5 text-amber-700 bg-amber-50 rounded p-2">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
          最終グレードが調整会議の結果（{cal.grade}）と違います。
        </p>
      )}
    </div>
  );
}

/** Load the AI scoring for one evaluation; reload() after anything that changes it. */
export function useAiDetail(evaluationId: number | null) {
  const [detail, setDetail] = useState<AiDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(async () => {
    if (evaluationId == null) return;
    setError(null);
    try {
      const r = await fetch(`/api/evaluations/${evaluationId}/axes`);
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || "AI採点の取得に失敗しました");
      setDetail(d);
    } catch (e) {
      setDetail(null);
      setError((e as Error).message);
    }
  }, [evaluationId]);
  useEffect(() => { setDetail(null); reload(); }, [reload]);
  return { detail, error, reload };
}

/**
 * The cross-review items on the 評価管理 detail: AI 5-axis scores, the
 * recommendation, and HR's per-axis correction. Re-scoring uses the same
 * API as the cross-review screen's 「AI定量化」.
 */
export function AiScoringPanel({
  evaluationId,
  hasComment,
  detail,
  error,
  onChanged,
}: {
  evaluationId: number;
  hasComment: boolean;
  detail: AiDetail | null;
  error: string | null;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function score() {
    setBusy(true); setErr(null);
    try {
      const r = await fetch("/api/evaluations/quantify", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ evaluation_ids: [evaluationId] }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || "AI採点に失敗しました");
      if (!d.processed) throw new Error("AI採点できませんでした（コメントを確認してください）");
      onChanged();
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }

  if (error) return <p className="text-xs text-destructive">{error}</p>;
  if (!detail) return <p className="text-xs text-muted-foreground">評価項目を読み込み中...</p>;

  const scoreButton = (
    <Button size="sm" variant={detail.scored && !detail.stale ? "outline" : "default"} onClick={score}
      disabled={busy || !hasComment} className="gap-1.5">
      {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Brain className="h-3.5 w-3.5" />}
      {detail.scored ? "AIで再採点" : "AIで採点"}
    </Button>
  );

  const label = new Map<string, string>(AXIS_FIELDS.map((f) => [f.axis, f.label]));

  if (!detail.scored) {
    return (
      <Card>
        <CardHeader className="pb-2"><CardTitle className="text-sm">評価項目（5軸）</CardTitle></CardHeader>
        <CardContent className="space-y-2">
          <div className="grid grid-cols-5 gap-2 text-center">
            {AXIS_FIELDS.map((f) => (
              <div key={f.axis} className="rounded-md border p-2">
                <p className="text-[10px] text-muted-foreground">{f.label}</p>
                <p className="text-xs text-muted-foreground mt-1">データなし</p>
              </div>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">
            {hasComment ? "コメントからAIで5軸を採点できます。採点後は軸ごとに修正できます。" : "コメントを入力すると、AIで5軸を採点できます。"}
          </p>
          {err && <p className="text-xs text-destructive">{err}</p>}
          <div className="flex justify-end">{scoreButton}</div>
        </CardContent>
      </Card>
    );
  }

  const values: AxisValue[] = detail.axes.map((a) => ({
    axis: a.axis, ai: a.ai, score: Number(a.effective), reason: a.reason,
  }));

  return (
    <div className="space-y-3">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            評価項目（5軸）
            {detail.standardGrade && <Badge variant="outline">推奨 {detail.standardGrade}</Badge>}
            {detail.expectationGap != null && (
              <span className="text-xs font-normal text-muted-foreground">期待比 {detail.expectationGap > 0 ? "+" : ""}{detail.expectationGap.toFixed(2)}</span>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {detail.stale && (
            <p className="text-xs flex items-start gap-1.5 text-amber-700 bg-amber-50 rounded p-2">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
              コメントが採点後に変わっています。再採点してください。
            </p>
          )}
          <div className="grid grid-cols-5 gap-2 text-center">
            {values.map((v) => (
              <div key={v.axis} className="rounded-md border p-2">
                <p className="text-[10px] text-muted-foreground">{label.get(v.axis) ?? v.axis}</p>
                <p className="font-mono font-semibold">{v.score}</p>
                {v.ai != null && v.score !== v.ai && <p className="text-[9px] text-violet-700">AI {v.ai}</p>}
              </div>
            ))}
          </div>
          {detail.reasoning && <p className="text-xs text-muted-foreground whitespace-pre-wrap">AIの採点根拠: {detail.reasoning}</p>}
          {err && <p className="text-xs text-destructive">{err}</p>}
          <div className="flex justify-end">{scoreButton}</div>
        </CardContent>
      </Card>
      <AxisEditor key={JSON.stringify(values)} evaluationId={evaluationId} axes={values} onSaved={onChanged} />
    </div>
  );
}
