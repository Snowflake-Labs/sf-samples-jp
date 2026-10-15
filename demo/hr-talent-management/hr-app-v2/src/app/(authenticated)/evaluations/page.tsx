"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

import { ChevronDown, ExternalLink, Search, Plus, ClipboardEdit, Pencil, X, Save, Loader2, CheckCircle2, XCircle, SendHorizonal } from "lucide-react";
import { useHonbu } from "@/lib/honbu-context";
import { AiScoringPanel, GradeTrail, useAiDetail } from "@/components/evaluation/ai-scoring-panel";
import { MIN_REASON_LENGTH } from "@/lib/manager-override";
import type { Department } from "@/lib/types";

interface EvalRow {
  EVALUATION_ID: number;
  EMPLOYEE_ID: number;
  PERIOD: string;
  SCORE: number;
  GRADE: string;
  COMMENT: string;
  STATUS: string;
  EMPLOYEE_NAME: string;
  EMPLOYEE_CODE: string;
  DEPT_NAME: string;
  POSITION_TITLE: string;
  EVALUATOR_NAME: string;
  RETURN_REASON?: string | null;
}

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
const GRADES = ["S", "A", "B", "C", "D"];
const PAGE_SIZE = 50;

/** Status label and color, shared by the list and the detail. */
const STATUS_VIEW: Record<string, { label: string; cls: string }> = {
  draft: { label: "下書き", cls: "" },
  pending: { label: "承認待ち", cls: "border-yellow-500 text-yellow-700 bg-yellow-50" },
  submitted: { label: "上長提出済", cls: "border-blue-500 text-blue-700 bg-blue-50" },
  approved: { label: "承認済", cls: "border-green-500 text-green-700 bg-green-50" },
  confirmed: { label: "確定", cls: "border-green-500 text-green-700 bg-green-50" },
  rejected: { label: "差戻し", cls: "border-red-500 text-red-700 bg-red-50" },
};
function statusView(ev: { STATUS: string; RETURN_REASON?: string | null }) {
  // A review HR sent back to the line manager is a draft with a return reason.
  if (ev.STATUS === "draft" && ev.RETURN_REASON) return STATUS_VIEW.rejected;
  return STATUS_VIEW[ev.STATUS] ?? STATUS_VIEW.draft;
}

function autoGrade(s: number): string {
  if (s >= 4.5) return "S";
  if (s >= 4.0) return "A";
  if (s >= 3.0) return "B";
  if (s >= 2.0) return "C";
  return "D";
}

export default function EvaluationsPage() {
  const [evals, setEvals] = useState<EvalRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [period, setPeriod] = useState(PERIODS[0]);
  const { honbu, setHonbu, honbuList } = useHonbu();
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [offset, setOffset] = useState(0);
  const [gradeFilter, setGradeFilter] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedEval, setSelectedEval] = useState<EvalRow | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [childDepts, setChildDepts] = useState<Department[]>([]);
  const [selectedDeptId, setSelectedDeptId] = useState("");

  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [opError, setOpError] = useState<string | null>(null);
  const [editForm, setEditForm] = useState({ score: "", grade: "", gradeReason: "", comment: "", status: "" });
  const ai = useAiDetail(modalOpen && selectedEval ? selectedEval.EVALUATION_ID : null);
  const recommended = ai.detail?.scored ? ai.detail.standardGrade : null;
  const gradeChoices = recommended && ai.detail ? ai.detail.allowedGrades : GRADES;
  const gradeNeedsReason = !!recommended && !!editForm.grade && editForm.grade !== recommended;

  useEffect(() => {
    if (debounceTimer.current) clearTimeout(debounceTimer.current);
    debounceTimer.current = setTimeout(() => {
      setDebouncedSearch(searchQuery);
    }, 300);
    return () => { if (debounceTimer.current) clearTimeout(debounceTimer.current); };
  }, [searchQuery]);

  useEffect(() => {
    if (!honbu) return;
    fetch(`/api/departments?parent_id=${honbu}`)
      .then((r) => { if (!r.ok) throw new Error("Failed"); return r.json(); })
      .then((depts) => {
        setChildDepts(Array.isArray(depts) ? depts : []);
        setSelectedDeptId("");
      })
      .catch(() => setChildDepts([]));
  }, [honbu]);

  const fetchEvals = useCallback((h: string, p: string, off: number, append: boolean, grade: string, search: string, deptId: string) => {
    if (!h) return;
    if (append) setLoadingMore(true);
    else setLoading(true);
    const params = new URLSearchParams();
    params.set("honbu", h);
    if (p) params.set("period", p);
    if (grade) params.set("grade", grade);
    if (search.trim()) params.set("search", search.trim());
    if (deptId) params.set("dept_id", deptId);
    params.set("limit", String(PAGE_SIZE));
    params.set("offset", String(off));
    fetch(`/api/evaluations?${params}`)
      .then((r) => {
        if (!r.ok) throw new Error("Failed");
        return r.json();
      })
      .then((res) => {
        if (append) {
          setEvals((prev) => [...prev, ...res.data]);
        } else {
          setEvals(res.data);
        }
        setTotal(res.total);
        setHasMore(res.hasMore);
        setOffset(off + res.data.length);
      })
      .finally(() => {
        setLoading(false);
        setLoadingMore(false);
      });
  }, []);

  useEffect(() => {
    if (honbu) {
      setOffset(0);
      fetchEvals(honbu, period, 0, false, gradeFilter, debouncedSearch, selectedDeptId);
    }
  }, [honbu, period, gradeFilter, debouncedSearch, selectedDeptId, fetchEvals]);

  const loadMore = () => {
    fetchEvals(honbu, period, offset, true, gradeFilter, debouncedSearch, selectedDeptId);
  };

  const openEvalModal = (ev: EvalRow) => {
    setSelectedEval(ev);
    setEditing(false);
    setEditForm({
      score: ev.SCORE != null ? String(Number(ev.SCORE)) : "",
      grade: ev.GRADE || "",
      gradeReason: "",
      comment: ev.COMMENT || "",
      status: ev.STATUS || "draft",
    });
    setModalOpen(true);
  };

  const startEditing = () => {
    if (!selectedEval) return;
    setEditForm({
      score: selectedEval.SCORE != null ? String(Number(selectedEval.SCORE)) : "",
      grade: selectedEval.GRADE || "",
      gradeReason: ai.detail?.gradeReason || "",
      comment: selectedEval.COMMENT || "",
      status: selectedEval.STATUS || "draft",
    });
    setEditing(true);
  };

  const handleScoreChange = (val: string) => {
    setEditForm((prev) => {
      const n = parseFloat(val);
      if (recommended) return { ...prev, score: val };
      return { ...prev, score: val, grade: !isNaN(n) && n >= 1 && n <= 5 ? autoGrade(n) : prev.grade };
    });
  };

  const saveEdit = async () => {
    if (!selectedEval) return;
    setSaving(true);
    setOpError(null);
    try {
      const body: Record<string, unknown> = {};
      if (editForm.score) body.SCORE = parseFloat(editForm.score);
      if (editForm.grade) {
        body.GRADE = editForm.grade;
        body.GRADE_REASON = gradeNeedsReason ? editForm.gradeReason.trim() : null;
      }
      body.COMMENT = editForm.comment;
      body.STATUS = editForm.status;
      const res = await fetch(`/api/evaluations/${selectedEval.EVALUATION_ID}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.error || "更新に失敗しました");
      }
      const updated = {
        ...selectedEval,
        SCORE: body.SCORE != null ? Number(body.SCORE) : selectedEval.SCORE,
        GRADE: (body.GRADE as string) || selectedEval.GRADE,
        COMMENT: editForm.comment,
        STATUS: editForm.status,
      };
      setSelectedEval(updated);
      setEvals((prev) =>
        prev.map((e) => e.EVALUATION_ID === selectedEval.EVALUATION_ID ? { ...e, ...updated } : e)
      );
      setEditing(false);
      ai.reload();
    } catch (e) {
      setOpError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const updateStatus = async (newStatus: string) => {
    if (!selectedEval) return;
    try {
      const res = await fetch(`/api/evaluations/${selectedEval.EVALUATION_ID}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ STATUS: newStatus }),
      });
      if (!res.ok) throw new Error("Failed");
      setSelectedEval({ ...selectedEval, STATUS: newStatus });
      setEvals((prev) =>
        prev.map((e) =>
          e.EVALUATION_ID === selectedEval.EVALUATION_ID
            ? { ...e, STATUS: newStatus }
            : e
        )
      );
    } catch {
      setOpError("ステータス更新に失敗しました");
    }
  };

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center gap-4 flex-wrap">
        <h2 className="text-2xl font-bold tracking-tight">評価管理</h2>
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
      </div>

      <div className="flex gap-3 flex-wrap items-center">
        <Select value={selectedDeptId || "all"} onValueChange={(v) => setSelectedDeptId(!v || v === "all" ? "" : v)}>
          <SelectTrigger className="w-56">
            <SelectValue placeholder="部署を選択">
              {selectedDeptId ? childDepts.find((d) => String(d.DEPT_ID) === selectedDeptId)?.DEPT_NAME || "部署を選択" : "全部署"}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部署</SelectItem>
            {childDepts.map((d) => (
              <SelectItem key={d.DEPT_ID} value={String(d.DEPT_ID)}>
                {d.DEPT_NAME}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={period} onValueChange={(v) => v && setPeriod(v)}>
          <SelectTrigger className="w-40">
            <SelectValue placeholder="期間" />
          </SelectTrigger>
          <SelectContent>
            {PERIODS.map((p) => (
              <SelectItem key={p} value={p}>{p}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={gradeFilter} onValueChange={(v) => setGradeFilter(v === "all" ? "" : (v ?? ""))}>
          <SelectTrigger className="w-36">
            <SelectValue placeholder="グレード">
              {gradeFilter ? `グレード: ${gradeFilter}` : "全グレード"}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全グレード</SelectItem>
            {GRADES.map((g) => (
              <SelectItem key={g} value={g}>{g}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="relative">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="社員名で検索"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9 w-48"
          />
        </div>
        <Link href="/evaluations/new" className="ml-auto">
          <Button variant="outline" className="gap-1.5">
            <Plus className="h-4 w-4" />
            個別入力
          </Button>
        </Link>
        <Link href="/evaluations/batch">
          <Button className="gap-1.5">
            <ClipboardEdit className="h-4 w-4" />
            一括評価入力
          </Button>
        </Link>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">
            {loading ? "読み込み中..." : `${evals.length} / ${total.toLocaleString()}件の評価`}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-2">
              {[...Array(8)].map((_, i) => <Skeleton key={i} className="h-12" />)}
            </div>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>期間</TableHead>
                    <TableHead>社員</TableHead>
                    <TableHead>部署</TableHead>
                    <TableHead>評価者</TableHead>
                    <TableHead>スコア</TableHead>
                    <TableHead>グレード</TableHead>
                    <TableHead>ステータス</TableHead>
                    <TableHead>コメント</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {evals.map((ev) => (
                    <TableRow key={ev.EVALUATION_ID} className="cursor-pointer" onClick={() => openEvalModal(ev)}>
                      <TableCell className="font-mono text-xs">{ev.PERIOD}</TableCell>
                      <TableCell>
                        <span className="text-blue-600 hover:underline">
                          {ev.EMPLOYEE_NAME}
                        </span>
                      </TableCell>
                      <TableCell className="text-sm">{ev.DEPT_NAME}</TableCell>
                      <TableCell className="text-sm">{ev.EVALUATOR_NAME}</TableCell>
                      <TableCell className="font-mono">{ev.SCORE != null ? Number(ev.SCORE).toFixed(1) : '—'}</TableCell>
                      <TableCell>
                        <Badge variant={ev.GRADE === "S" ? "destructive" : ev.GRADE === "A" ? "default" : "secondary"}>
                          {ev.GRADE}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline" className={`text-[10px] ${statusView(ev).cls}`}>
                          {statusView(ev).label}
                        </Badge>
                      </TableCell>
                      <TableCell className="max-w-xs truncate text-sm text-muted-foreground">
                        {ev.COMMENT || "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {hasMore && (
                <div className="flex justify-center pt-4">
                  <Button
                    variant="outline"
                    onClick={loadMore}
                    disabled={loadingMore}
                    className="gap-2"
                  >
                    <ChevronDown className="h-4 w-4" />
                    {loadingMore ? "読み込み中..." : `もっと見る（残り${(total - offset).toLocaleString()}件）`}
                  </Button>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      <Dialog open={modalOpen} onOpenChange={(o) => { setModalOpen(o); if (!o) setEditing(false); }}>
        <DialogContent className="sm:max-w-2xl max-h-[90vh] overflow-y-auto">
          {selectedEval && (
            <>
              <DialogHeader className="pr-10">
                <DialogTitle className="flex items-center gap-2">
                  {selectedEval.EMPLOYEE_NAME} の評価詳細
                  {!editing && (
                    <Button variant="outline" size="sm" className="h-7 gap-1 text-xs" onClick={startEditing}>
                      <Pencil className="h-3.5 w-3.5" />
                      編集
                    </Button>
                  )}
                </DialogTitle>
                <DialogDescription>
                  {selectedEval.PERIOD} / {selectedEval.DEPT_NAME} / {selectedEval.POSITION_TITLE}
                </DialogDescription>
              </DialogHeader>

              {editing ? (
                <div className="space-y-4">
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-1.5">
                      <p className="text-xs text-muted-foreground">上長入力スコア (1.0〜5.0)</p>
                      <Input
                        type="number"
                        min={1}
                        max={5}
                        step={0.1}
                        value={editForm.score}
                        onChange={(e) => handleScoreChange(e.target.value)}
                        className="h-9"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <p className="text-xs text-muted-foreground">
                        最終グレード{recommended ? `（AI推奨 ${recommended}・前後1段階まで）` : ""}
                      </p>
                      <Select value={editForm.grade} onValueChange={(v) => setEditForm((f) => ({ ...f, grade: v || "" }))}>
                        <SelectTrigger className="h-9">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {gradeChoices.map((g) => (
                            <SelectItem key={g} value={g}>{g}{g === recommended ? "（推奨）" : ""}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                  {gradeNeedsReason && (
                    <div className="space-y-1.5">
                      <p className="text-xs text-muted-foreground">推奨 {recommended} から変える理由（{MIN_REASON_LENGTH}文字以上・必須）</p>
                      <Input
                        value={editForm.gradeReason}
                        onChange={(e) => setEditForm((f) => ({ ...f, gradeReason: e.target.value }))}
                        className="h-9"
                      />
                    </div>
                  )}
                  <div className="space-y-1.5">
                    <p className="text-xs text-muted-foreground">コメント</p>
                    <Textarea
                      value={editForm.comment}
                      onChange={(e) => setEditForm((f) => ({ ...f, comment: e.target.value }))}
                      rows={3}
                      placeholder="評価コメント..."
                    />
                  </div>
                  <div className="space-y-1.5">
                    <p className="text-xs text-muted-foreground">ステータス</p>
                    <div className="flex gap-2 flex-wrap">
                      <Button size="sm" variant={editForm.status === "draft" ? "default" : "outline"}
                        onClick={() => setEditForm((f) => ({ ...f, status: "draft" }))}>
                        下書き
                      </Button>
                      <Button size="sm" variant={editForm.status === "pending" ? "default" : "outline"}
                        className={editForm.status === "pending" ? "bg-yellow-600" : ""}
                        onClick={() => setEditForm((f) => ({ ...f, status: "pending" }))}>
                        承認申請
                      </Button>
                    </div>
                  </div>
                  {opError && <p className="text-xs text-destructive">{opError}</p>}
                  <div className="flex gap-2 justify-end">
                    <Button variant="outline" size="sm" onClick={() => setEditing(false)} className="gap-1.5">
                      <X className="h-3.5 w-3.5" />
                      キャンセル
                    </Button>
                    <Button size="sm" onClick={saveEdit}
                      disabled={saving || (gradeNeedsReason && editForm.gradeReason.trim().length < MIN_REASON_LENGTH)}
                      className="gap-1.5">
                      {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
                      保存
                    </Button>
                  </div>
                  <Separator />
                  <GradeTrail finalGrade={editForm.grade || null} detail={ai.detail} />
                  <AiScoringPanel
                    evaluationId={selectedEval.EVALUATION_ID}
                    hasComment={!!selectedEval.COMMENT?.trim()}
                    detail={ai.detail}
                    error={ai.error}
                    onChanged={ai.reload}
                  />
                </div>
              ) : (
                <div className="space-y-4">
                  <div className="grid grid-cols-3 gap-3">
                    <div>
                      <p className="text-xs text-muted-foreground">上長入力スコア</p>
                      <p className="text-2xl font-bold font-mono">{selectedEval.SCORE != null ? Number(selectedEval.SCORE).toFixed(1) : '—'}</p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">最終グレード</p>
                      <Badge
                        className="mt-1"
                        variant={selectedEval.GRADE === "S" ? "destructive" : selectedEval.GRADE === "A" ? "default" : "secondary"}
                      >
                        {selectedEval.GRADE}
                      </Badge>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">評価者</p>
                      <p className="text-sm font-medium mt-1">{selectedEval.EVALUATOR_NAME}</p>
                    </div>
                  </div>

                  <Separator />

                  <div>
                    <p className="text-xs text-muted-foreground mb-1">コメント</p>
                    <p className="text-sm bg-muted/50 rounded-md p-3 whitespace-pre-wrap">
                      {selectedEval.COMMENT || "コメントなし"}
                    </p>
                  </div>

                  <GradeTrail finalGrade={selectedEval.GRADE} detail={ai.detail} />

                  {ai.detail?.gradeReason && (
                    <p className="text-xs">
                      最終グレード <b>{selectedEval.GRADE}</b>（推奨 {ai.detail.standardGrade} から変更）:
                      <span className="text-muted-foreground"> {ai.detail.gradeReason}</span>
                    </p>
                  )}

                  <AiScoringPanel
                    evaluationId={selectedEval.EVALUATION_ID}
                    hasComment={!!selectedEval.COMMENT?.trim()}
                    detail={ai.detail}
                    error={ai.error}
                    onChanged={ai.reload}
                  />

                  <Separator />

                  <div>
                    <p className="text-xs text-muted-foreground mb-2">ステータス管理</p>
                    <div className="flex gap-2 flex-wrap">
                      {selectedEval.STATUS === "draft" && (
                        <Button size="sm" onClick={() => updateStatus("pending")} className="gap-1.5 bg-yellow-600 hover:bg-yellow-700">
                          <SendHorizonal className="h-3.5 w-3.5" />
                          承認申請
                        </Button>
                      )}
                      {selectedEval.STATUS === "pending" && (
                        <>
                          <Button size="sm" onClick={() => updateStatus("approved")} className="gap-1.5 bg-green-600 hover:bg-green-700">
                            <CheckCircle2 className="h-3.5 w-3.5" />
                            承認
                          </Button>
                          <Button size="sm" variant="destructive" onClick={() => updateStatus("rejected")} className="gap-1.5">
                            <XCircle className="h-3.5 w-3.5" />
                            差戻し
                          </Button>
                        </>
                      )}
                      {selectedEval.STATUS === "rejected" && (
                        <Button size="sm" variant="outline" onClick={() => updateStatus("draft")} className="gap-1.5">
                          下書きに戻す
                        </Button>
                      )}
                      {selectedEval.STATUS === "approved" && (
                        <Badge variant="outline" className="border-green-500 text-green-700 bg-green-50 py-1.5 px-3">
                          <CheckCircle2 className="h-3.5 w-3.5 mr-1" />
                          承認済み
                        </Badge>
                      )}
                    </div>
                  </div>
                </div>
              )}

              <DialogFooter>
                <Link href={`/employees/${selectedEval.EMPLOYEE_ID}`}>
                  <Button variant="outline" size="sm" className="gap-1.5">
                    <ExternalLink className="h-3.5 w-3.5" />
                    社員詳細を表示
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
