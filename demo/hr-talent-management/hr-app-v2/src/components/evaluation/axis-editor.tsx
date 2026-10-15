"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Loader2, Save } from "lucide-react";
import { MIN_REASON_LENGTH } from "@/lib/manager-override";

export const AXIS_FIELDS = [
  { axis: "growth", label: "成長性" },
  { axis: "expertise", label: "専門性" },
  { axis: "leadership", label: "リーダーシップ" },
  { axis: "problem_solving", label: "課題解決力" },
  { axis: "collaboration", label: "協調性" },
] as const;

export interface AxisValue {
  axis: string;
  /** The AI's own score (before any correction). */
  ai: number | null;
  /** The score in effect now (AI, or the correction). */
  score: number;
  reason: string | null;
}

/** HR edits the 5 axis scores. Axes that differ from the AI need a reason. */
export function AxisEditor({
  evaluationId,
  axes,
  onSaved,
}: {
  evaluationId: number;
  axes: AxisValue[];
  onSaved: () => void;
}) {
  const byAxis = new Map(axes.map((a) => [a.axis, a]));
  const initial = Object.fromEntries(AXIS_FIELDS.map((f) => {
    const a = byAxis.get(f.axis);
    return [f.axis, { ai: a?.ai ?? null, score: a?.score ?? 3, reason: a?.reason ?? "" }];
  })) as Record<string, { ai: number | null; score: number; reason: string }>;
  const [vals, setVals] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const dirty = AXIS_FIELDS.some((f) => vals[f.axis].score !== initial[f.axis].score || vals[f.axis].reason !== initial[f.axis].reason);

  async function save() {
    setBusy(true); setErr(null);
    try {
      const body = Object.fromEntries(AXIS_FIELDS.map((f) => [f.axis, { score: vals[f.axis].score, reason: vals[f.axis].reason }]));
      const r = await fetch(`/api/evaluations/${evaluationId}/axes`, {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ axes: body }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || "保存に失敗しました");
      onSaved();
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }

  return (
    <Card>
      <CardHeader className="pb-2"><CardTitle className="text-sm">5軸スコアを修正（人事）</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        {AXIS_FIELDS.map((f) => {
          const v = vals[f.axis];
          const changed = v.ai != null && v.score !== v.ai;
          return (
            <div key={f.axis} className="space-y-1">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="w-28 text-sm shrink-0">{f.label}</span>
                <div className="flex gap-1" role="radiogroup" aria-label={f.label}>
                  {[1, 2, 3, 4, 5].map((n) => (
                    <Button
                      key={n}
                      type="button"
                      size="sm"
                      variant={v.score === n ? "default" : "outline"}
                      className="h-7 w-7 p-0"
                      aria-pressed={v.score === n}
                      onClick={() => setVals((p) => ({ ...p, [f.axis]: { ...p[f.axis], score: n } }))}
                    >
                      {n}
                    </Button>
                  ))}
                </div>
                <span className="text-[10px] text-muted-foreground">AI {v.ai ?? "-"}</span>
                {changed && <Badge variant="outline" className="text-[9px] border-violet-400/60 text-violet-700">修正</Badge>}
              </div>
              {changed && (
                <Input
                  className="h-7 text-xs"
                  placeholder={`修正理由（${MIN_REASON_LENGTH}文字以上・必須）`}
                  value={v.reason}
                  onChange={(e) => setVals((p) => ({ ...p, [f.axis]: { ...p[f.axis], reason: e.target.value } }))}
                />
              )}
            </div>
          );
        })}
        {err && <p className="text-xs text-destructive">{err}</p>}
        <div className="flex justify-end">
          <Button size="sm" onClick={save} disabled={!dirty || busy} className="gap-1.5">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            5軸を保存して再計算
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
