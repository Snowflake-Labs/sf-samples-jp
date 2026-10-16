"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { useParams } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  ArrowLeft,
  Plus,
  Pencil,
  Trash2,
  Search,
  Loader2,
  ChevronDown,
  MessageSquare,
  Lock,
} from "lucide-react";
import Link from "next/link";
import { Breadcrumb } from "@/components/ui/breadcrumb";

interface Note {
  NOTE_ID: number;
  EMPLOYEE_ID: number;
  MANAGER_ID: number;
  NOTE_DATE: string;
  CONTENT: string;
  CATEGORY: string | null;
  IS_PRIVATE: boolean;
  CREATED_AT: string;
  MANAGER_NAME: string | null;
}

const CATEGORIES = ["performance", "career", "motivation", "concern", "other"];
const CATEGORY_LABELS: Record<string, string> = {
  performance: "業績", career: "キャリア", motivation: "モチベーション",
  concern: "懸念事項", other: "その他",
};
const CATEGORY_COLORS: Record<string, string> = {
  performance: "bg-blue-100 text-blue-700",
  career: "bg-purple-100 text-purple-700",
  motivation: "bg-green-100 text-green-700",
  concern: "bg-red-100 text-red-700",
  other: "bg-gray-100 text-gray-700",
};

export default function NotesManagePage() {
  const { id } = useParams<{ id: string }>();
  const [notes, setNotes] = useState<Note[]>([]);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [offset, setOffset] = useState(0);
  const [empName, setEmpName] = useState("");
  const [managerId, setManagerId] = useState<number | null>(null);

  const [categoryFilter, setCategoryFilter] = useState("");
  const [searchQuery, setSearchQuery] = useState("");

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editNote, setEditNote] = useState<Note | null>(null);
  const [formDate, setFormDate] = useState("");
  const [formContent, setFormContent] = useState("");
  const [formCategory, setFormCategory] = useState("performance");
  const [formPrivate, setFormPrivate] = useState(false);
  const [saving, setSaving] = useState(false);
  const [opError, setOpError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<number | null>(null);

  const fetchNotes = useCallback((off: number, append: boolean) => {
    if (append) setLoadingMore(true);
    else setLoading(true);
    const params = new URLSearchParams({ limit: "50", offset: String(off) });
    if (categoryFilter) params.set("category", categoryFilter);
    fetch(`/api/employees/${id}/notes?${params}`)
      .then((r) => r.json())
      .then((res) => {
        if (append) setNotes((prev) => [...prev, ...(res.notes || [])]);
        else setNotes(res.notes || []);
        setTotal(res.total || 0);
        setHasMore(res.hasMore || false);
        setOffset(off + (res.notes?.length || 0));
      })
      .finally(() => { setLoading(false); setLoadingMore(false); });
  }, [id, categoryFilter]);

  useEffect(() => {
    fetch(`/api/employees/${id}?section=basic`).then((r) => r.json()).then((res) => {
      const e = res.employee;
      if (e) {
        setEmpName(`${e.LAST_NAME}${e.FIRST_NAME}`);
        setManagerId(e.MANAGER_ID);
      }
    });
  }, [id]);

  useEffect(() => {
    setOffset(0);
    fetchNotes(0, false);
  }, [fetchNotes]);

  const filteredNotes = useMemo(() => {
    if (!searchQuery.trim()) return notes;
    const q = searchQuery.toLowerCase();
    return notes.filter((n) => n.CONTENT.toLowerCase().includes(q) || (n.MANAGER_NAME || "").toLowerCase().includes(q));
  }, [notes, searchQuery]);

  const openCreate = () => {
    setEditNote(null);
    setFormDate(new Date().toISOString().slice(0, 10));
    setFormContent("");
    setFormCategory("performance");
    setFormPrivate(false);
    setDialogOpen(true);
  };

  const openEdit = (note: Note) => {
    setEditNote(note);
    setFormDate(note.NOTE_DATE?.slice(0, 10) || "");
    setFormContent(note.CONTENT);
    setFormCategory(note.CATEGORY || "other");
    setFormPrivate(note.IS_PRIVATE);
    setDialogOpen(true);
  };

  const handleSave = async () => {
    if (!formContent.trim() || !formDate) return;
    setSaving(true);
    try {
      if (editNote) {
        const res = await fetch(`/api/employees/${id}/notes`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            note_id: editNote.NOTE_ID,
            content: formContent,
            category: formCategory,
            is_private: formPrivate,
          }),
        });
        if (!res.ok) throw new Error("Failed");
      } else {
        const res = await fetch(`/api/employees/${id}/notes`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            manager_id: managerId || Number(id),
            note_date: formDate,
            content: formContent,
            category: formCategory,
            is_private: formPrivate,
          }),
        });
        if (!res.ok) throw new Error("Failed");
      }
      setDialogOpen(false);
      setOffset(0);
      fetchNotes(0, false);
    } catch {
      setOpError("保存に失敗しました");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (noteId: number) => {
    try {
      const res = await fetch(`/api/employees/${id}/notes?note_id=${noteId}`, { method: "DELETE" });
      if (!res.ok) throw new Error("Failed");
      setDeleteTarget(null);
      setNotes((prev) => prev.filter((n) => n.NOTE_ID !== noteId));
      setTotal((t) => t - 1);
    } catch {
      setOpError("削除に失敗しました");
    }
  };

  return (
    <div className="p-6 space-y-4 max-w-4xl mx-auto">
      <Breadcrumb items={[
        { label: "社員一覧", href: "/employees" },
        { label: empName || `社員 #${id}`, href: `/employees/${id}` },
        { label: "1on1メモ管理" },
      ]} />
      <div className="flex items-center gap-3">
        <Link href={`/employees/${id}`}>
          <Button variant="ghost" size="icon" className="h-8 w-8">
            <ArrowLeft className="h-4 w-4" />
          </Button>
        </Link>
        <div>
          <h2 className="text-2xl font-bold tracking-tight">1on1メモ管理</h2>
          {empName && <p className="text-sm text-muted-foreground">{empName} — {total}件</p>}
        </div>
        <Button onClick={openCreate} className="ml-auto gap-1.5">
          <Plus className="h-4 w-4" />
          新規メモ
        </Button>
      </div>

      <div className="flex gap-3 items-center flex-wrap">
        <div className="relative">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="内容で検索"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9 w-48"
          />
        </div>
        <Select value={categoryFilter} onValueChange={(v) => setCategoryFilter(v === "all" ? "" : (v ?? ""))}>
          <SelectTrigger className="w-44">
            <SelectValue placeholder="全カテゴリ">
              {categoryFilter ? CATEGORY_LABELS[categoryFilter] || categoryFilter : "全カテゴリ"}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全カテゴリ</SelectItem>
            {CATEGORIES.map((c) => (
              <SelectItem key={c} value={c}>{CATEGORY_LABELS[c]}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {loading ? (
        <div className="space-y-2">{[...Array(5)].map((_, i) => <Skeleton key={i} className="h-24" />)}</div>
      ) : filteredNotes.length === 0 ? (
        <Card>
          <CardContent className="pt-6 flex items-center justify-center h-32 text-muted-foreground">
            メモなし
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {filteredNotes.map((n) => (
            <Card key={n.NOTE_ID} className="group">
              <CardContent className="pt-4 pb-3">
                <div className="flex items-start gap-3">
                  <MessageSquare className="h-4 w-4 text-muted-foreground mt-0.5 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                      <span className="text-xs font-mono text-muted-foreground">{n.NOTE_DATE?.slice(0, 10)}</span>
                      {n.CATEGORY && (
                        <Badge className={`text-[10px] ${CATEGORY_COLORS[n.CATEGORY] || ""}`}>
                          {CATEGORY_LABELS[n.CATEGORY] || n.CATEGORY}
                        </Badge>
                      )}
                      {n.IS_PRIVATE && (
                        <Badge variant="outline" className="text-[10px] gap-0.5">
                          <Lock className="h-2.5 w-2.5" /> 非公開
                        </Badge>
                      )}
                      {n.MANAGER_NAME && (
                        <span className="text-[11px] text-muted-foreground">by {n.MANAGER_NAME}</span>
                      )}
                    </div>
                    <p className="text-sm whitespace-pre-wrap">{n.CONTENT}</p>
                  </div>
                  <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                    <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => openEdit(n)}>
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                    <Button variant="ghost" size="icon" className="h-7 w-7 text-red-500" onClick={() => setDeleteTarget(n.NOTE_ID)}>
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}

          {hasMore && (
            <div className="flex justify-center pt-2">
              <Button
                variant="outline"
                onClick={() => fetchNotes(offset, true)}
                disabled={loadingMore}
                className="gap-2"
              >
                <ChevronDown className="h-4 w-4" />
                {loadingMore ? "読み込み中..." : `もっと見る（残り${total - offset}件）`}
              </Button>
            </div>
          )}
        </div>
      )}

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{editNote ? "メモ編集" : "新規1on1メモ"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            {!editNote && (
              <div className="space-y-2">
                <p className="text-sm font-medium">日付</p>
                <Input type="date" value={formDate} onChange={(e) => setFormDate(e.target.value)} />
              </div>
            )}
            <div className="space-y-2">
              <p className="text-sm font-medium">カテゴリ</p>
              <Select value={formCategory} onValueChange={(v) => v && setFormCategory(v)}>
                <SelectTrigger>
                  <SelectValue>{CATEGORY_LABELS[formCategory] ?? formCategory}</SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {CATEGORIES.map((c) => (
                    <SelectItem key={c} value={c}>{CATEGORY_LABELS[c]}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <p className="text-sm font-medium">内容</p>
              <Textarea
                value={formContent}
                onChange={(e) => setFormContent(e.target.value)}
                rows={6}
                placeholder="1on1の内容を記録してください..."
              />
            </div>
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="private"
                checked={formPrivate}
                onChange={(e) => setFormPrivate(e.target.checked)}
                className="rounded border-gray-300"
              />
              <label htmlFor="private" className="text-sm flex items-center gap-1">
                <Lock className="h-3.5 w-3.5" /> 非公開にする
              </label>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>キャンセル</Button>
            <Button onClick={handleSave} disabled={saving || !formContent.trim()}>
              {saving && <Loader2 className="h-4 w-4 animate-spin mr-1" />}
              {editNote ? "更新" : "作成"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={deleteTarget !== null} onOpenChange={() => setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>メモ削除</DialogTitle>
          </DialogHeader>
          <p className="text-sm">このメモを削除しますか？</p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>キャンセル</Button>
            <Button variant="destructive" onClick={() => deleteTarget && handleDelete(deleteTarget)}>削除</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
