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
  if (!detail) return <p className="text-xs text-muted-foreground">AI採点を読み込み中...</p>;

  const scoreButton = (
    <Button size="sm" variant={detail.scored && !detail.stale ? "outline" : "default"} onClick={score}
      disabled={busy || !hasComment} className="gap-1.5">
      {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Brain className="h-3.5 w-3.5" />}
      {detail.scored ? "AIで再採点" : "AIで採点"}
    </Button>
  );

  if (!detail.scored) {
    return (
      <Card>
        <CardHeader className="pb-2"><CardTitle className="text-sm">AI採点（5軸）</CardTitle></CardHeader>
        <CardContent className="space-y-2">
          <p className="text-xs text-muted-foreground">
            {hasComment ? "まだAI採点していません。コメントから5軸のスコアと推奨グレードを出します。" : "コメントを入力してから採点してください。"}
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
  const label = new Map<string, string>(AXIS_FIELDS.map((f) => [f.axis, f.label]));

  return (
    <div className="space-y-3">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            AI採点（5軸）
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
              <div key={v.axis}>
                <p className="text-[10px] text-muted-foreground">{label.get(v.axis) ?? v.axis}</p>
                <p className="font-mono font-semibold">{v.score}</p>
                {v.ai != null && v.score !== v.ai && <p className="text-[9px] text-violet-700">AI {v.ai}</p>}
              </div>
            ))}
          </div>
          {detail.reasoning && <p className="text-xs text-muted-foreground whitespace-pre-wrap">{detail.reasoning}</p>}
          {err && <p className="text-xs text-destructive">{err}</p>}
          <div className="flex justify-end">{scoreButton}</div>
        </CardContent>
      </Card>
      <AxisEditor key={JSON.stringify(values)} evaluationId={evaluationId} axes={values} onSaved={onChanged} />
    </div>
  );
}
