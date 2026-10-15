"use client";

import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
} from "@/components/ui/dialog";
import {
  Archive,
  Download,
  GitCompare,
  Loader2,
  ArrowRight,
  GitBranch,
  Zap,
  CheckCircle2,
} from "lucide-react";

interface Snapshot {
  snapshot_id: number;
  label: string;
  effective_date: string;
  snapshot_type: string;
  source_id: number;
  confirmed_by: string;
  confirmed_at: string;
  item_count: number;
}

interface SnapshotDetail {
  snapshot_id: number;
  label: string;
  effective_date: string;
  snapshot_type: string;
  confirmed_by: string;
  confirmed_at: string;
  data_json: {
    actions?: Record<string, unknown>[];
    steps?: Record<string, unknown>[];
  };
}

export default function SnapshotsPage() {
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedForCompare, setSelectedForCompare] = useState<number[]>([]);
  const [compareOpen, setCompareOpen] = useState(false);
  const [compareData, setCompareData] = useState<{ a: SnapshotDetail; b: SnapshotDetail } | null>(null);
  const [compareLoading, setCompareLoading] = useState(false);

  const fetchSnapshots = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/snapshots");
      if (res.ok) setSnapshots(await res.json());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchSnapshots(); }, [fetchSnapshots]);

  const toggleSelect = (id: number) => {
    setSelectedForCompare((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id);
      if (prev.length >= 2) return [prev[1], id];
      return [...prev, id];
    });
  };

  const handleCompare = async () => {
    if (selectedForCompare.length !== 2) return;
    setCompareLoading(true);
    setCompareOpen(true);
    try {
      const res = await fetch(`/api/snapshots/compare?a=${selectedForCompare[0]}&b=${selectedForCompare[1]}`);
      if (res.ok) setCompareData(await res.json());
    } finally {
      setCompareLoading(false);
    }
  };

  const handleExport = (id: number) => {
    window.open(`/api/snapshots/${id}/export`, "_blank");
  };

  const getItems = (snap: SnapshotDetail) => {
    if (snap.snapshot_type === "whatif") return snap.data_json.actions || [];
    return snap.data_json.steps || [];
  };

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">確定済み異動</h1>
          <p className="text-sm text-muted-foreground mt-1">確定済みスナップショットの比較・CSV出力</p>
        </div>
        {selectedForCompare.length === 2 && (
          <Button onClick={handleCompare} disabled={compareLoading}>
            <GitCompare className="h-4 w-4 mr-1" />
            選択した2件を比較
          </Button>
        )}
      </div>

      {selectedForCompare.length > 0 && (
        <div className="text-sm text-muted-foreground">
          {selectedForCompare.length}/2 件選択中
          <Button variant="ghost" size="sm" className="ml-2" onClick={() => setSelectedForCompare([])}>クリア</Button>
        </div>
      )}

      {loading ? (
        <div className="flex justify-center py-12"><Loader2 className="h-6 w-6 animate-spin" /></div>
      ) : snapshots.length === 0 ? (
        <Card><CardContent className="py-12 text-center text-muted-foreground">確定済みデータはありません</CardContent></Card>
      ) : (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-10">選択</TableHead>
                  <TableHead>ラベル</TableHead>
                  <TableHead>発令日</TableHead>
                  <TableHead>種別</TableHead>
                  <TableHead>件数</TableHead>
                  <TableHead>確定者</TableHead>
                  <TableHead>確定日時</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {snapshots.map((s) => (
                  <TableRow key={s.snapshot_id} className={selectedForCompare.includes(s.snapshot_id) ? "bg-blue-50" : ""}>
                    <TableCell>
                      <input
                        type="checkbox"
                        checked={selectedForCompare.includes(s.snapshot_id)}
                        onChange={() => toggleSelect(s.snapshot_id)}
                        className="h-4 w-4"
                      />
                    </TableCell>
                    <TableCell className="font-medium">{s.label}</TableCell>
                    <TableCell>{s.effective_date}</TableCell>
                    <TableCell>
                      <Badge variant="outline" className="text-[10px]">
                        {s.snapshot_type === "whatif" ? <><GitBranch className="h-3 w-3 mr-0.5" />シナリオ</> : <><Zap className="h-3 w-3 mr-0.5" />玉突き</>}
                      </Badge>
                    </TableCell>
                    <TableCell>{s.item_count}件</TableCell>
                    <TableCell className="text-sm">{s.confirmed_by}</TableCell>
                    <TableCell className="text-sm">{new Date(s.confirmed_at).toLocaleDateString("ja-JP")}</TableCell>
                    <TableCell className="text-right">
                      <Button size="sm" variant="outline" onClick={() => handleExport(s.snapshot_id)}>
                        <Download className="h-3 w-3 mr-1" />CSV
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      <Dialog open={compareOpen} onOpenChange={setCompareOpen}>
        <DialogContent className="max-w-4xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <GitCompare className="h-5 w-5" />
              スナップショット比較
            </DialogTitle>
          </DialogHeader>
          {compareLoading ? (
            <div className="flex justify-center py-12"><Loader2 className="h-6 w-6 animate-spin" /></div>
          ) : compareData ? (
            <div className="grid grid-cols-2 gap-4">
              {[compareData.a, compareData.b].map((snap) => {
                const items = getItems(snap);
                return (
                  <div key={snap.snapshot_id}>
                    <div className="mb-2">
                      <h3 className="font-semibold text-sm">{snap.label}</h3>
                      <p className="text-xs text-muted-foreground">発令日: {snap.effective_date} / {items.length}件</p>
                    </div>
                    <div className="space-y-1">
                      {items.map((item, i) => (
                        <div key={i} className="flex items-center gap-2 text-xs p-2 rounded bg-muted/50 border">
                          <span className="font-medium">{String(item.employee_name || "")}</span>
                          <span className="text-muted-foreground truncate">
                            {String(item.from_dept_name || "")}
                            <ArrowRight className="h-3 w-3 inline mx-1" />
                            {String(item.to_dept_name || "")}
                          </span>
                          <Badge variant="outline" className="text-[9px] ml-auto">{String(item.from_grade || item.grade || "")}{item.to_grade && item.to_grade !== item.from_grade ? ` → ${String(item.to_grade)}` : ""}</Badge>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}
