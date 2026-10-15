"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, CalendarClock, ChevronRight } from "lucide-react";
import { PROGRESS_META, type Progress } from "@/lib/my-team-ui";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

interface Member {
  EVALUATION_ID: number;
  NAME: string;
  EMPLOYEE_CODE: string;
  POSITION_GRADE: string;
  POSITION_TITLE: string;
  PROGRESS: Progress;
  HAS_SELF: boolean;
  HAS_COMMENT: boolean;
  RETURN_REASON: string | null;
  FINAL_GRADE: string | null;
  STANDARD_GRADE: string | null;
  OVERRIDES: number;
}
// 手を付けるべき順に並べる（差し戻し→途中→未着手→提出済み）
const ORDER: Progress[] = ["returned", "ai_scored", "draft", "not_started", "submitted", "completed"];

// 締切日までの暦日数（JST）。9/29 に 10/2 締切なら「あと3日」と数える
function daysLeft(deadline: string | null): number | null {
  if (!deadline) return null;
  const todayJst = new Date(Date.now() + 9 * 3_600_000).toISOString().slice(0, 10);
  return Math.round((Date.parse(deadline) - Date.parse(todayJst)) / 86_400_000);
}

export default function MyTeamPage() {
  const [data, setData] = useState<{ period: string; deadline: string | null; members: Member[]; counts: Record<string, number> } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/my-team/evaluations")
      .then(async (r) => {
        const d = await r.json();
        if (!r.ok) throw new Error(d.error || "取得に失敗しました");
        setData(d);
      })
      .catch((e) => setError((e as Error).message));
  }, []);

  if (error) {
    return (
      <div className="p-6">
        <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm">
          <AlertTriangle className="h-4 w-4 mt-0.5 text-destructive" />{error}
        </div>
      </div>
    );
  }
  if (!data) {
    return <div className="p-6 space-y-3">{[...Array(5)].map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}</div>;
  }

  const left = daysLeft(data.deadline);
  const members = [...data.members].sort((a, b) => ORDER.indexOf(a.PROGRESS) - ORDER.indexOf(b.PROGRESS));
  const done = (data.counts.submitted ?? 0) + (data.counts.completed ?? 0);
  const nextUp = members.find((m) => m.PROGRESS !== "submitted" && m.PROGRESS !== "completed");

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">マイチーム評価</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {data.period} の評価。あなたが評価者になっている部下 {data.members.length} 名です。
          </p>
        </div>
        {data.deadline && (
          <div className={`rounded-md border px-4 py-2 text-right ${left !== null && left <= 3 ? "border-amber-500/60 bg-amber-50 dark:bg-amber-950" : ""}`}>
            <div className="flex items-center gap-1 text-xs text-muted-foreground justify-end">
              <CalendarClock className="h-3.5 w-3.5" />提出締切 {data.deadline}
            </div>
            <div className="text-lg font-bold tabular-nums">
              {left === null ? "-" : left < 0 ? "締切超過" : left === 0 ? "今日が締切" : `あと ${left} 日`}
            </div>
          </div>
        )}
      </div>

      <Card>
        <CardContent className="pt-6">
          <div className="flex items-center justify-between gap-4 flex-wrap">
            <div className="flex gap-2 flex-wrap">
              {ORDER.filter((p) => data.counts[p]).map((p) => (
                <Badge key={p} variant="outline" className={PROGRESS_META[p].cls}>
                  {PROGRESS_META[p].label} {data.counts[p]}
                </Badge>
              ))}
            </div>
            <div className="text-sm">
              提出 <span className="font-bold tabular-nums">{done}</span> / {data.members.length}
            </div>
          </div>
          <div className="mt-3 h-2 rounded-full bg-muted overflow-hidden">
            <div className="h-full bg-emerald-500" style={{ width: `${(done / Math.max(1, data.members.length)) * 100}%` }} />
          </div>
          {nextUp && (
            <div className="mt-4 flex items-center justify-between rounded-md bg-muted/50 p-3 text-sm">
              <span>
                次は <b>{nextUp.NAME}</b> さん（{PROGRESS_META[nextUp.PROGRESS].label}：{PROGRESS_META[nextUp.PROGRESS].next}）
              </span>
              <Link href={`/my-team/evaluations/${nextUp.EVALUATION_ID}`}>
                <Button size="sm">続きから入力<ChevronRight className="h-4 w-4 ml-1" /></Button>
              </Link>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">部下一覧（対応が必要な順）</CardTitle></CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>氏名</TableHead>
                  <TableHead>等級</TableHead>
                  <TableHead>状況</TableHead>
                  <TableHead>次にやること</TableHead>
                  <TableHead>グレード</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {members.map((m) => (
                  <TableRow key={m.EVALUATION_ID}>
                    <TableCell className="whitespace-nowrap">
                      {m.NAME}<span className="ml-2 text-xs text-muted-foreground">{m.EMPLOYEE_CODE}</span>
                    </TableCell>
                    <TableCell className="text-sm">{m.POSITION_GRADE} {m.POSITION_TITLE}</TableCell>
                    <TableCell>
                      <Badge variant="outline" className={PROGRESS_META[m.PROGRESS].cls}>{PROGRESS_META[m.PROGRESS].label}</Badge>
                      {!m.HAS_SELF && <span className="ml-2 text-xs text-amber-600">自己評価なし</span>}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {m.PROGRESS === "returned" ? <span className="text-red-700 dark:text-red-300">{m.RETURN_REASON}</span> : PROGRESS_META[m.PROGRESS].next}
                    </TableCell>
                    <TableCell className="text-sm">
                      {/* AI採点前のグレードは古い値なので出さない */}
                      {m.PROGRESS === "not_started" || m.PROGRESS === "draft" ? "-" : (m.FINAL_GRADE ?? m.STANDARD_GRADE ?? "-")}
                      {m.OVERRIDES > 0 && <span className="ml-2 text-xs text-muted-foreground">軸修正 {m.OVERRIDES}</span>}
                    </TableCell>
                    <TableCell className="text-right">
                      <Link href={`/my-team/evaluations/${m.EVALUATION_ID}`}>
                        <Button size="sm" variant={m.PROGRESS === "submitted" || m.PROGRESS === "completed" ? "ghost" : "outline"}>
                          {m.PROGRESS === "submitted" || m.PROGRESS === "completed" ? "見る" : "入力"}
                        </Button>
                      </Link>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          {data.members.length === 0 && (
            <p className="text-sm text-muted-foreground">この期間にあなたが評価者の評価はありません。</p>
          )}
        </CardContent>
      </Card>
      <p className="text-xs text-muted-foreground">
        評価の流れ: コメントを書く → AIで採点 → 納得できない軸を直す（理由必須）→ 最終グレードを決めて提出 → 人事の確認
      </p>
    </div>
  );
}
