"use client";

import { use, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AlertTriangle, ArrowLeft, CheckCircle2, Info, Loader2, Lock, RotateCcw, Sparkles } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { PROGRESS_META, type Progress } from "@/lib/my-team-ui";
import {
  AXIS_LABELS, SCORE_AXES, computeExpectationGap, gapToGrade, gapToLabel,
  type AxisScores, type GradeStandard, type ScoreAxis,
} from "@/lib/scoring";
import { allowedGrades, MIN_REASON_LENGTH } from "@/lib/manager-override";

interface AxisView { axis: ScoreAxis; ai: number | null; effective: number | null; reason: string | null; aiChanged: boolean }
interface Detail {
  evaluation: {
    EVALUATION_ID: number; PERIOD: string; NAME: string; EMPLOYEE_CODE: string;
    POSITION_GRADE: string; POSITION_TITLE: string; DEPT_NAME: string | null;
    COMMENT: string | null; SELF_COMMENT: string | null; SELF_SCORE: string | null;
    GRADE: string | null; GRADE_REASON: string | null; RETURN_REASON: string | null;
    SUBMITTED_AT: string | null;
  };
  progress: Progress;
  editable: boolean;
  axes: AxisView[];
  reasoning: string | null;
  aiInputComment: string | null;
  standardGrade: string | null;
  standard: GradeStandard | null;
  previous: { PERIOD: string; GRADE: string | null; COMMENT: string | null } | null;
}

// 1〜5 のアンカー（AI に渡している基準と同じ文言）。上長が同じ物差しで直せるように表示する
const ANCHORS: Record<number, string> = {
  1: "ほぼ発揮されていない",
  2: "部分的・受動的",
  3: "担当業務を自律的に遂行",
  4: "チーム・複数案件に影響",
  5: "部門・全社に影響",
};

type AxisEdit = { score: number; reason: string };

export default function MyTeamEvaluationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const [d, setD] = useState<Detail | null>(null);
  const [comment, setComment] = useState("");
  const [savedComment, setSavedComment] = useState("");
  const [edits, setEdits] = useState<Partial<Record<ScoreAxis, AxisEdit>>>({});
  const [finalGrade, setFinalGrade] = useState<string>("");
  const [gradeReason, setGradeReason] = useState("");
  const [busy, setBusy] = useState<null | "ai" | "save" | "submit">(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    const r = await fetch(`/api/my-team/evaluations/${id}`);
    const data = await r.json();
    if (!r.ok) { setError(data.error || "取得に失敗しました"); return; }
    setD(data);
    setComment(data.evaluation.COMMENT ?? "");
    setSavedComment(data.evaluation.COMMENT ?? "");
    const e: Partial<Record<ScoreAxis, AxisEdit>> = {};
    for (const a of data.axes as AxisView[]) {
      if (a.effective !== null) e[a.axis] = { score: a.effective, reason: a.reason ?? "" };
    }
    setEdits(e);
    setFinalGrade(data.evaluation.GRADE ?? "");
    setGradeReason(data.evaluation.GRADE_REASON ?? "");
  }, [id]);

  useEffect(() => { load(); }, [load]);

  const aiScored = !!d && d.axes.every((a) => a.ai !== null);
  const aiOf = (axis: ScoreAxis) => d?.axes.find((a) => a.axis === axis)?.ai ?? null;

  // Recompute the gap and recommended grade on the client as the manager moves an axis.
  const live = useMemo(() => {
    if (!d?.standard || !aiScored) return null;
    const eff = Object.fromEntries(SCORE_AXES.map((a) => [a, edits[a]?.score ?? aiOf(a)!])) as AxisScores;
    const ai = Object.fromEntries(SCORE_AXES.map((a) => [a, aiOf(a)!])) as AxisScores;
    const e = computeExpectationGap(eff, d.standard);
    const aiGap = computeExpectationGap(ai, d.standard).expectationGap;
    return { gap: e.expectationGap, grade: gapToGrade(e.expectationGap), perAxis: e.perAxis, aiGap, aiGrade: gapToGrade(aiGap) };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [d, edits, aiScored]);

  const changedAxes = SCORE_AXES.filter((a) => aiScored && edits[a] && edits[a]!.score !== aiOf(a));
  const missingReasons = changedAxes.filter((a) => (edits[a]?.reason ?? "").trim().length < MIN_REASON_LENGTH);
  const recommended = live?.grade ?? null;
  const gradeChoices = recommended ? allowedGrades(recommended) : [];
  const gradeMoved = !!finalGrade && !!recommended && finalGrade !== recommended;
  const gradeReasonMissing = gradeMoved && gradeReason.trim().length < MIN_REASON_LENGTH;
  const commentDirty = aiScored && comment.trim() !== (d?.aiInputComment ?? savedComment).trim();

  // 推奨グレードが動いて、選んでいたグレードが±1段階の外に出たら推奨に戻す
  useEffect(() => {
    if (recommended && finalGrade && !allowedGrades(recommended).includes(finalGrade)) setFinalGrade(recommended);
  }, [recommended, finalGrade]);

  async function call(path: string, method: string, body?: unknown) {
    const r = await fetch(path, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || "処理に失敗しました");
    return data;
  }

  async function runAi() {
    setBusy("ai"); setError(null); setMessage(null);
    try {
      await call(`/api/my-team/evaluations/${id}/ai-score`, "POST", { comment });
      await load();
      setMessage("AIが採点しました。実態と違う軸があれば直してください。");
    } catch (e) { setError((e as Error).message); } finally { setBusy(null); }
  }

  function buildSaveBody() {
    const body: Record<string, unknown> = { comment };
    if (aiScored) {
      body.axes = Object.fromEntries(SCORE_AXES.map((a) => [a, { score: edits[a]?.score ?? aiOf(a), reason: edits[a]?.reason ?? "" }]));
      body.final_grade = finalGrade || recommended;
      body.grade_reason = gradeReason;
    }
    return body;
  }

  async function save(): Promise<boolean> {
    setBusy("save"); setError(null); setMessage(null);
    try {
      await call(`/api/my-team/evaluations/${id}`, "PUT", buildSaveBody());
      await load();
      setMessage("下書きを保存しました。");
      return true;
    } catch (e) { setError((e as Error).message); return false; } finally { setBusy(null); }
  }

  async function submit() {
    setBusy("submit"); setError(null); setMessage(null);
    try {
      await call(`/api/my-team/evaluations/${id}`, "PUT", buildSaveBody());
      await call(`/api/my-team/evaluations/${id}/submit`, "POST");
      router.push("/my-team");
    } catch (e) { setError((e as Error).message); setBusy(null); }
  }

  if (error && !d) {
    return (
      <div className="p-6 space-y-3">
        <Link href="/my-team"><Button variant="ghost" size="sm"><ArrowLeft className="h-4 w-4 mr-1" />マイチームに戻る</Button></Link>
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm">{error}</div>
      </div>
    );
  }
  if (!d) return <div className="p-6 space-y-3">{[...Array(6)].map((_, i) => <Skeleton key={i} className="h-12 w-full" />)}</div>;

  const ev = d.evaluation;
  const locked = !d.editable;
  const canSubmit = !locked && aiScored && !commentDirty && missingReasons.length === 0 && !gradeReasonMissing && !busy;
  const submitBlocker = locked ? null
    : !comment.trim() ? "上長コメントを書いてください"
    : !aiScored ? "「AIで採点」を実行してください"
    : commentDirty ? "コメントを変更したので、もう一度「AIで採点」してください"
    : missingReasons.length ? `${missingReasons.map((a) => AXIS_LABELS[a]).join("・")}を変えた理由を入力してください`
    : gradeReasonMissing ? "推奨からグレードを変えた理由を入力してください"
    : null;

  return (
    <div className="p-6 space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <Link href="/my-team"><Button variant="ghost" size="sm" className="-ml-2 mb-1"><ArrowLeft className="h-4 w-4 mr-1" />マイチームに戻る</Button></Link>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            {ev.NAME} さんの評価
            <Badge variant="outline" className={PROGRESS_META[d.progress].cls}>{PROGRESS_META[d.progress].label}</Badge>
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            {ev.PERIOD} / {ev.POSITION_GRADE} {ev.POSITION_TITLE} / {ev.DEPT_NAME} / {ev.EMPLOYEE_CODE}
          </p>
        </div>
      </div>

      {d.progress === "returned" && ev.RETURN_REASON && (
        <div className="flex items-start gap-2 rounded-md border border-red-500/40 bg-red-50 p-3 text-sm dark:bg-red-950">
          <RotateCcw className="h-4 w-4 mt-0.5 text-red-600" />
          <div><b>人事から差し戻されました：</b>{ev.RETURN_REASON}</div>
        </div>
      )}
      {locked && (
        <div className="flex items-start gap-2 rounded-md border bg-muted/50 p-3 text-sm">
          <Lock className="h-4 w-4 mt-0.5 text-muted-foreground" />
          提出済みです（{ev.SUBMITTED_AT ? new Date(ev.SUBMITTED_AT).toLocaleString("ja-JP") : ""}）。人事が差し戻した場合のみ編集できます。
        </div>
      )}
      {error && (
        <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm">
          <AlertTriangle className="h-4 w-4 mt-0.5 text-destructive" />{error}
        </div>
      )}
      {message && <div className="rounded-md border border-emerald-500/40 bg-emerald-500/10 p-3 text-sm">{message}</div>}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        {/* 左: 判断材料 */}
        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-2"><CardTitle className="text-sm">本人の自己評価</CardTitle></CardHeader>
            <CardContent className="text-sm leading-relaxed">
              {ev.SELF_COMMENT ? <p className="whitespace-pre-wrap">{ev.SELF_COMMENT}</p> : <p className="text-amber-600">自己評価が提出されていません。</p>}
              {ev.SELF_SCORE && <p className="mt-2 text-xs text-muted-foreground">自己採点 {Number(ev.SELF_SCORE).toFixed(1)} / 5</p>}
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2"><CardTitle className="text-sm">前期の評価{d.previous ? `（${d.previous.PERIOD}）` : ""}</CardTitle></CardHeader>
            <CardContent className="text-sm leading-relaxed">
              {d.previous ? (
                <>
                  <p>グレード <b>{d.previous.GRADE ?? "-"}</b></p>
                  {d.previous.COMMENT && <p className="mt-1 text-muted-foreground">{d.previous.COMMENT}</p>}
                </>
              ) : <p className="text-muted-foreground">前期の評価はありません。</p>}
            </CardContent>
          </Card>
          {d.standard && (
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-sm">{ev.POSITION_GRADE} に期待される水準</CardTitle></CardHeader>
              <CardContent>
                <table className="w-full text-sm">
                  <tbody>
                    {SCORE_AXES.map((a) => (
                      <tr key={a} className="border-b last:border-0">
                        <td className="py-1">{AXIS_LABELS[a]}</td>
                        <td className="py-1 text-right tabular-nums">期待 {d.standard![a].expected}</td>
                        <td className="py-1 text-right tabular-nums text-muted-foreground">重み {Math.round(d.standard![a].weight * 100)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="mt-2 text-xs text-muted-foreground">スコアは全社共通の絶対評価です。等級による上乗せはせず、期待水準との差でグレードが決まります。</p>
              </CardContent>
            </Card>
          )}
        </div>

        {/* 右: 入力 */}
        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-2"><CardTitle className="text-sm">① 上長コメント</CardTitle></CardHeader>
            <CardContent className="space-y-2">
              <Textarea
                rows={5} value={comment} disabled={locked}
                onChange={(e) => setComment(e.target.value)}
                placeholder="今期の具体的な行動と成果、周囲への影響、課題を書いてください。例: 休職者が出た際に4名の案件を再配分し、納期遅延ゼロで乗り切った。"
              />
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs text-muted-foreground">
                  {comment.trim().length} 文字{comment.trim().length < 20 && "（AI採点には20文字以上）"}
                  {commentDirty && <span className="ml-2 text-amber-600">AIが読んだ内容からコメントが変わりました。再採点してください</span>}
                </span>
                {!locked && (
                  <Button size="sm" onClick={runAi} disabled={!!busy || comment.trim().length < 20}>
                    {busy === "ai" ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <Sparkles className="h-4 w-4 mr-1" />}
                    {aiScored ? "AIで再採点" : "AIで採点"}
                  </Button>
                )}
              </div>
            </CardContent>
          </Card>

          <Card className={aiScored ? "" : "opacity-60"}>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">② 5軸スコア（AIの採点を確認し、実態と違えば直す）</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {!aiScored && <p className="text-sm text-muted-foreground">コメントを書いて「AIで採点」すると、ここに AI のスコアが出ます。</p>}
              {aiScored && d.reasoning && (
                <div className="flex items-start gap-2 rounded-md bg-muted/50 p-2 text-xs">
                  <Info className="h-3.5 w-3.5 mt-0.5 shrink-0" /><span><b>AIの採点根拠：</b>{d.reasoning}</span>
                </div>
              )}
              {aiScored && SCORE_AXES.map((axis) => {
                const ai = aiOf(axis)!;
                const cur = edits[axis]?.score ?? ai;
                const changed = cur !== ai;
                const view = d.axes.find((a) => a.axis === axis)!;
                const expected = d.standard?.[axis].expected;
                return (
                  <div key={axis} className={`rounded-md border p-3 ${changed ? "border-violet-400/60 bg-violet-50/50 dark:bg-violet-950/30" : ""}`}>
                    <div className="flex items-center justify-between gap-2 flex-wrap">
                      <div className="text-sm font-medium">
                        {AXIS_LABELS[axis]}
                        <span className="ml-2 text-xs text-muted-foreground">AI {ai}{expected !== undefined && ` / 期待 ${expected}`}</span>
                        {changed && <span className="ml-2 text-xs text-violet-700 dark:text-violet-300">AI {ai} → あなた {cur}</span>}
                        {view.aiChanged && <span className="ml-2 text-xs text-amber-600">再採点でAIの値が変わりました</span>}
                      </div>
                      <div className="flex gap-1" role="radiogroup" aria-label={AXIS_LABELS[axis]}>
                        {[1, 2, 3, 4, 5].map((n) => (
                          <button
                            key={n} type="button" role="radio" aria-checked={cur === n} disabled={locked}
                            title={ANCHORS[n]}
                            onClick={() => setEdits((p) => ({ ...p, [axis]: { score: n, reason: p[axis]?.reason ?? "" } }))}
                            className={`h-8 w-8 rounded-md border text-sm tabular-nums transition-colors ${
                              cur === n ? "bg-primary text-primary-foreground border-primary"
                                : n === ai ? "border-dashed border-primary/60" : "hover:bg-accent"
                            } disabled:opacity-60`}
                          >{n}</button>
                        ))}
                      </div>
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">{cur}: {ANCHORS[cur]}</p>
                    {changed && (
                      <Input
                        className="mt-2" disabled={locked}
                        value={edits[axis]?.reason ?? ""}
                        onChange={(e) => setEdits((p) => ({ ...p, [axis]: { score: cur, reason: e.target.value } }))}
                        placeholder={`AI の ${ai} から ${cur} に変えた理由（必須・${MIN_REASON_LENGTH}文字以上）例: コメントに書いていないが後輩2名のOJTを担当`}
                      />
                    )}
                    {changed && !locked && (
                      <button type="button" className="mt-1 text-xs text-muted-foreground underline"
                        onClick={() => setEdits((p) => ({ ...p, [axis]: { score: ai, reason: "" } }))}>
                        AI の値に戻す
                      </button>
                    )}
                  </div>
                );
              })}
            </CardContent>
          </Card>

          <Card className={aiScored ? "" : "opacity-60"}>
            <CardHeader className="pb-2"><CardTitle className="text-sm">③ 最終グレード</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              {live ? (
                <>
                  <div className="grid grid-cols-2 gap-3 text-sm">
                    <div className="rounded-md border p-3">
                      <div className="text-xs text-muted-foreground">期待水準との差（期待比）</div>
                      <div className="text-xl font-bold tabular-nums">{live.gap > 0 ? "+" : ""}{live.gap.toFixed(2)}</div>
                      <div className="text-xs text-muted-foreground">{gapToLabel(live.gap)}</div>
                      {changedAxes.length > 0 && (
                        <div className="text-xs text-violet-700 dark:text-violet-300 mt-1">
                          AIのみ {live.aiGap > 0 ? "+" : ""}{live.aiGap.toFixed(2)} から変化
                        </div>
                      )}
                    </div>
                    <div className="rounded-md border p-3">
                      <div className="text-xs text-muted-foreground">推奨グレード</div>
                      <div className="text-xl font-bold">{live.grade}</div>
                      {live.grade !== live.aiGrade && (
                        <div className="text-xs text-violet-700 dark:text-violet-300">AIのみなら {live.aiGrade}</div>
                      )}
                    </div>
                  </div>
                  <div>
                    <div className="text-sm font-medium mb-1">提出するグレード（推奨から1段階まで変更可）</div>
                    <div className="flex gap-2">
                      {gradeChoices.map((g) => (
                        <Button key={g} type="button" size="sm" disabled={locked}
                          variant={(finalGrade || recommended) === g ? "default" : "outline"}
                          onClick={() => setFinalGrade(g)}>
                          {g}{g === recommended && <span className="ml-1 text-[10px] opacity-80">推奨</span>}
                        </Button>
                      ))}
                    </div>
                    {gradeMoved && (
                      <Input className="mt-2" disabled={locked} value={gradeReason}
                        onChange={(e) => setGradeReason(e.target.value)}
                        placeholder={`推奨 ${recommended} から ${finalGrade} に変える理由（必須）`} />
                    )}
                    <p className="mt-2 text-xs text-muted-foreground">2段階以上変えたい場合は、グレードではなく軸のスコアを見直してください。</p>
                  </div>
                </>
              ) : <p className="text-sm text-muted-foreground">AI採点後に、期待比と推奨グレードが表示されます。</p>}
            </CardContent>
          </Card>

          {!locked && (
            <div className="sticky bottom-0 flex items-center justify-between gap-3 rounded-md border bg-background/95 p-3 backdrop-blur">
              <span className="text-xs text-muted-foreground">{submitBlocker ?? "提出できます。提出後は人事が差し戻すまで編集できません。"}</span>
              <div className="flex gap-2">
                <Button variant="outline" onClick={save} disabled={!!busy}>
                  {busy === "save" && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}下書き保存
                </Button>
                <Button onClick={submit} disabled={!canSubmit}>
                  {busy === "submit" ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <CheckCircle2 className="h-4 w-4 mr-1" />}提出
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
