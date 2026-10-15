"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  CheckCircle2,
  XCircle,
  ArrowLeft,
  FileCheck,
  Clock,
  AlertTriangle,
  Loader2,
  ArrowRight,
  ExternalLink,
  GitBranch,
  Zap,
  Edit,
} from "lucide-react";

type ReviewItemType = "whatif" | "chain";

interface ReviewItem {
  id: number;
  name: string;
  type: ReviewItemType;
  status: string;
  created_at: string;
  item_count: number;
  rejected_count: number;
  approved_count: number;
}

interface ActionDetail {
  action_id: number;
  employee_id: number;
  employee_name: string;
  employee_code: string;
  action_type: string;
  from_dept_name: string;
  to_dept_name: string;
  grade: string;
  action_status: string;
  reviewer_comment: string | null;
  avg_eval?: number;
  tenure_years?: number;
  attrition_risk?: number;
  step_order?: number;
}

const STATUS_CONFIG: Record<string, { label: string; color: string }> = {
  draft: { label: "下書き", color: "bg-gray-100 text-gray-700" },
  pending_review: { label: "レビュー待ち", color: "bg-yellow-100 text-yellow-700" },
  revision_requested: { label: "差し戻しあり", color: "bg-red-100 text-red-700" },
  approved: { label: "承認済み", color: "bg-green-100 text-green-700" },
  confirmed: { label: "確定済み", color: "bg-blue-100 text-blue-700" },
};

const ACTION_STATUS_CONFIG: Record<string, { label: string; color: string }> = {
  pending: { label: "未レビュー", color: "bg-yellow-100 text-yellow-700" },
  approved: { label: "承認", color: "bg-green-100 text-green-700" },
  rejected: { label: "差し戻し", color: "bg-red-100 text-red-700" },
};

export default function ReviewPage() {
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [selectedType, setSelectedType] = useState<ReviewItemType | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selectedName, setSelectedName] = useState("");
  const [selectedStatus, setSelectedStatus] = useState("");
  const [actions, setActions] = useState<ActionDetail[]>([]);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [filterType, setFilterType] = useState<"all" | ReviewItemType>("all");

  const [rejectDialog, setRejectDialog] = useState<{ id: number; name: string; type: ReviewItemType } | null>(null);
  const [rejectComment, setRejectComment] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [approveConfirm, setApproveConfirm] = useState<{ id: number; name: string; type: ReviewItemType } | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setFetchError(null);
    try {
      const [scenRes, chainRes] = await Promise.all([
        fetch("/api/simulation/scenarios"),
        fetch("/api/chain-simulation/list"),
      ]);
      const scenarios = scenRes.ok ? await scenRes.json() : [];
      const chains = chainRes.ok ? await chainRes.json() : [];

      const merged: ReviewItem[] = [
        ...scenarios
          .filter((s: Record<string, unknown>) => s.status !== "draft")
          .map((s: Record<string, unknown>) => ({
            id: s.scenario_id as number,
            name: s.scenario_name as string,
            type: "whatif" as ReviewItemType,
            status: s.status as string,
            created_at: s.created_at as string,
            item_count: Number(s.action_count),
            rejected_count: Number(s.rejected_count || 0),
            approved_count: Number(s.approved_count || 0),
          })),
        ...chains
          .filter((c: Record<string, unknown>) => c.status !== "draft")
          .map((c: Record<string, unknown>) => ({
            id: c.simulation_id as number,
            name: c.simulation_name as string,
            type: "chain" as ReviewItemType,
            status: c.status as string,
            created_at: c.created_at as string,
            item_count: Number(c.step_count),
            rejected_count: Number(c.rejected_count || 0),
            approved_count: Number(c.approved_count || 0),
          })),
      ].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());

      setItems(merged);
    } catch {
      setFetchError("レビューデータの取得に失敗しました");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const loadDetail = async (type: ReviewItemType, id: number, name: string, status: string) => {
    setDetailLoading(true);
    setSelectedType(type);
    setSelectedId(id);
    setSelectedName(name);
    setSelectedStatus(status);
    try {
      if (type === "whatif") {
        const res = await fetch(`/api/simulation/scenarios/${id}`);
        if (!res.ok) return;
        const data = await res.json();
        setSelectedStatus(data.scenario.status);
        setActions(data.actions.map((a: Record<string, unknown>) => ({
          action_id: a.action_id,
          employee_id: a.employee_id,
          employee_name: a.employee_name,
          employee_code: a.employee_code,
          action_type: a.action_type,
          from_dept_name: a.from_dept_name,
          to_dept_name: a.to_dept_name,
          grade: a.grade,
          action_status: a.action_status,
          reviewer_comment: a.reviewer_comment,
          avg_eval: Number(a.avg_eval) || 0,
          tenure_years: Number(a.tenure_years) || 0,
          attrition_risk: Number(a.attrition_risk) || 0,
        })));
      } else {
        const res = await fetch(`/api/chain-simulation/${id}`);
        if (!res.ok) return;
        const data = await res.json();
        setSelectedStatus(data.simulation.status);
        setActions(data.steps.map((s: Record<string, unknown>) => ({
          action_id: s.step_order,
          step_order: s.step_order as number,
          employee_id: s.employee_id,
          employee_name: s.employee_name,
          employee_code: s.employee_code,
          action_type: "transfer",
          from_dept_name: s.from_dept_name,
          to_dept_name: s.to_dept_name,
          grade: s.grade,
          action_status: s.step_status,
          reviewer_comment: s.reviewer_comment,
        })));
      }
    } finally {
      setDetailLoading(false);
    }
  };

  const handleApproveAction = async (item: ActionDetail) => {
    setApproveConfirm({ id: item.action_id, name: item.employee_name, type: selectedType! });
  };

  const confirmApprove = async () => {
    if (!approveConfirm || !selectedId || !selectedType) return;
    setSubmitting(true);
    setActionError(null);
    try {
      const res = selectedType === "whatif"
        ? await fetch("/api/simulation/review-action", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ actionId: approveConfirm.id, decision: "approved" }),
          })
        : await fetch("/api/chain-simulation/review-step", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ simulationId: selectedId, stepOrder: approveConfirm.id, decision: "approved" }),
          });
      if (!res.ok) { setActionError("承認に失敗しました"); return; }
      setApproveConfirm(null);
      await loadDetail(selectedType, selectedId, selectedName, selectedStatus);
    } finally {
      setSubmitting(false);
    }
  };

  const handleRejectAction = async () => {
    if (!rejectDialog || !rejectComment.trim() || !selectedId) return;
    setSubmitting(true);
    setActionError(null);
    try {
      const res = rejectDialog.type === "whatif"
        ? await fetch("/api/simulation/review-action", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ actionId: rejectDialog.id, decision: "rejected", comment: rejectComment }),
          })
        : await fetch("/api/chain-simulation/review-step", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ simulationId: selectedId, stepOrder: rejectDialog.id, decision: "rejected", comment: rejectComment }),
          });
      if (!res.ok) { setActionError("差し戻しに失敗しました"); return; }
      setRejectDialog(null);
      setRejectComment("");
      await loadDetail(selectedType!, selectedId, selectedName, selectedStatus);
      await fetchAll();
    } finally {
      setSubmitting(false);
    }
  };

  const handleFinalApprove = async () => {
    if (!selectedId || !selectedType) return;
    setSubmitting(true);
    try {
      const url = selectedType === "whatif" ? "/api/simulation/approve-scenario" : "/api/chain-simulation/approve";
      const body = selectedType === "whatif" ? { scenarioId: selectedId } : { simulationId: selectedId };
      const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      if (!res.ok) {
        const err = await res.json();
        setActionError(err.error || "承認に失敗しました");
        return;
      }
      setActionError(null);
      await loadDetail(selectedType, selectedId, selectedName, selectedStatus);
      await fetchAll();
    } finally {
      setSubmitting(false);
    }
  };

  const allApproved = actions.length > 0 && actions.every((a) => a.action_status === "approved");
  const editHref = selectedType === "whatif" ? `/simulation?load=${selectedId}` : `/chain-simulation?load=${selectedId}`;

  const filteredItems = filterType === "all" ? items : items.filter((i) => i.type === filterType);

  // Detail view
  if (selectedId && selectedType) {
    return (
      <div className="p-6 space-y-4">
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={() => { setSelectedId(null); setSelectedType(null); fetchAll(); }}>
            <ArrowLeft className="h-4 w-4 mr-1" /> 一覧に戻る
          </Button>
          <Link href={editHref} className="text-xs text-blue-600 hover:underline flex items-center gap-1">
            <Edit className="h-3 w-3" /> 編集画面で開く
          </Link>
        </div>

        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Badge variant="outline" className="text-[10px]">
              {selectedType === "whatif" ? <><GitBranch className="h-3 w-3 mr-1" />シナリオ</> : <><Zap className="h-3 w-3 mr-1" />玉突き</>}
            </Badge>
            <h1 className="text-xl font-bold">{selectedName}</h1>
          </div>
          <div className="flex items-center gap-2">
            <Badge className={STATUS_CONFIG[selectedStatus]?.color || ""}>{STATUS_CONFIG[selectedStatus]?.label || selectedStatus}</Badge>
            {actionError && <span className="text-xs text-red-600">{actionError}</span>}
            {selectedStatus === "pending_review" && allApproved && (
              <Button onClick={handleFinalApprove} disabled={submitting} className="bg-green-600 hover:bg-green-700">
                <FileCheck className="h-4 w-4 mr-1" /> 最終承認
              </Button>
            )}
            {selectedStatus === "approved" && (
              <Link href="/snapshots">
                <Button variant="outline" size="sm">確定済み異動へ →</Button>
              </Link>
            )}
          </div>
        </div>

        {detailLoading ? (
          <div className="flex justify-center py-12"><Loader2 className="h-6 w-6 animate-spin" /></div>
        ) : (
          <Card>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>社員</TableHead>
                    <TableHead>等級</TableHead>
                    <TableHead>評価/リスク</TableHead>
                    <TableHead>異動</TableHead>
                    <TableHead>ステータス</TableHead>
                    <TableHead>コメント</TableHead>
                    <TableHead className="text-right">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {actions.map((a, i) => (
                    <TableRow key={i} className={a.action_status === "rejected" ? "bg-red-50" : ""}>
                      <TableCell className="font-medium">
                        <Link href={`/employees/${a.employee_id}`} target="_blank" className="hover:underline text-blue-700 flex items-center gap-1">
                          {a.employee_name}
                          <ExternalLink className="h-3 w-3" />
                        </Link>
                        <div className="text-xs text-muted-foreground">{a.employee_code}</div>
                      </TableCell>
                      <TableCell><Badge variant="outline">{a.grade}</Badge></TableCell>
                      <TableCell>
                        <div className="text-xs space-y-0.5">
                          <div>評価 <span className="font-mono font-medium">{a.avg_eval ? Number(a.avg_eval).toFixed(1) : "-"}</span></div>
                          <div>勤続 <span className="font-mono">{a.tenure_years ?? "-"}年</span></div>
                          {a.attrition_risk != null && a.attrition_risk > 0.5 && (
                            <div className="text-red-600 font-medium">離職リスク {Math.round(Number(a.attrition_risk) * 100)}%</div>
                          )}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-1 text-sm">
                          <span className="truncate max-w-24">{a.from_dept_name}</span>
                          <ArrowRight className="h-3 w-3 shrink-0" />
                          <span className="truncate max-w-24">{a.to_dept_name || "-"}</span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge className={ACTION_STATUS_CONFIG[a.action_status]?.color || ""}>{ACTION_STATUS_CONFIG[a.action_status]?.label || a.action_status}</Badge>
                      </TableCell>
                      <TableCell className="max-w-48 truncate text-sm text-muted-foreground">{a.reviewer_comment || "-"}</TableCell>
                      <TableCell className="text-right">
                        {a.action_status === "pending" && selectedStatus === "pending_review" && (
                          <div className="flex gap-1 justify-end">
                            <Button size="sm" variant="outline" className="text-green-700 border-green-300 hover:bg-green-50" onClick={() => handleApproveAction(a)} disabled={submitting}>
                              <CheckCircle2 className="h-3 w-3 mr-1" /> 承認
                            </Button>
                            <Button size="sm" variant="outline" className="text-red-700 border-red-300 hover:bg-red-50"
                              onClick={() => setRejectDialog({ id: a.step_order || a.action_id, name: a.employee_name, type: selectedType })}
                              disabled={submitting}>
                              <XCircle className="h-3 w-3 mr-1" /> 差し戻し
                            </Button>
                          </div>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        )}

        <Dialog open={!!approveConfirm} onOpenChange={() => setApproveConfirm(null)}>
          <DialogContent>
            <DialogHeader><DialogTitle>承認確認</DialogTitle></DialogHeader>
            <p className="text-sm">{approveConfirm?.name} の異動を承認しますか？</p>
            <DialogFooter>
              <Button variant="outline" onClick={() => setApproveConfirm(null)}>キャンセル</Button>
              <Button onClick={confirmApprove} disabled={submitting} className="bg-green-600 hover:bg-green-700">
                {submitting ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : <CheckCircle2 className="h-4 w-4 mr-1" />}
                承認
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        <Dialog open={!!rejectDialog} onOpenChange={() => { setRejectDialog(null); setRejectComment(""); }}>
          <DialogContent>
            <DialogHeader><DialogTitle>差し戻し: {rejectDialog?.name}</DialogTitle></DialogHeader>
            <div className="space-y-2">
              <p className="text-sm text-muted-foreground">差し戻し理由を入力してください（必須）</p>
              <Textarea value={rejectComment} onChange={(e) => setRejectComment(e.target.value)} placeholder="例: 営業2部は現在プロジェクト進行中のため異動時期を再検討してください" rows={4} />
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => { setRejectDialog(null); setRejectComment(""); }}>キャンセル</Button>
              <Button variant="destructive" onClick={handleRejectAction} disabled={!rejectComment.trim() || submitting}>
                {submitting ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : <XCircle className="h-4 w-4 mr-1" />}
                差し戻し
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    );
  }

  // List view
  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">異動案レビュー</h1>
          <p className="text-sm text-muted-foreground mt-1">シナリオ・玉突きチェーンの承認・差し戻し</p>
        </div>
        <div className="flex gap-1">
          {(["all", "whatif", "chain"] as const).map((t) => (
            <Button key={t} size="sm" variant={filterType === t ? "default" : "outline"} onClick={() => setFilterType(t)}>
              {t === "all" ? "全て" : t === "whatif" ? "シナリオ" : "玉突き"}
            </Button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="flex justify-center py-12"><Loader2 className="h-6 w-6 animate-spin" /></div>
      ) : filteredItems.length === 0 ? (
        <Card><CardContent className="py-12 text-center text-muted-foreground">レビュー対象はありません</CardContent></Card>
      ) : (
        <div className="grid gap-3">
          {filteredItems.map((item) => (
            <Card key={`${item.type}-${item.id}`} className="cursor-pointer hover:border-primary/50 transition-colors" onClick={() => loadDetail(item.type, item.id, item.name, item.status)}>
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="text-[10px]">
                      {item.type === "whatif" ? <><GitBranch className="h-3 w-3 mr-0.5" />シナリオ</> : <><Zap className="h-3 w-3 mr-0.5" />玉突き</>}
                    </Badge>
                    <CardTitle className="text-base">{item.name}</CardTitle>
                  </div>
                  <Badge className={STATUS_CONFIG[item.status]?.color || ""}>{STATUS_CONFIG[item.status]?.label || item.status}</Badge>
                </div>
              </CardHeader>
              <CardContent>
                <div className="flex items-center gap-4 text-sm text-muted-foreground">
                  <span>{new Date(item.created_at).toLocaleDateString("ja-JP")}</span>
                  <span>{item.item_count}件</span>
                  {item.approved_count > 0 && <span className="flex items-center gap-1 text-green-600"><CheckCircle2 className="h-3 w-3" />{item.approved_count}件承認</span>}
                  {item.rejected_count > 0 && <span className="flex items-center gap-1 text-red-600"><AlertTriangle className="h-3 w-3" />{item.rejected_count}件差し戻し</span>}
                  {item.status === "pending_review" && <span className="flex items-center gap-1 text-yellow-600"><Clock className="h-3 w-3" />レビュー待ち</span>}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
