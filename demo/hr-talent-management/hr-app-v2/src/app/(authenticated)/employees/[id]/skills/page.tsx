"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { useParams } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Progress } from "@/components/ui/progress";
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
import { ArrowLeft, Plus, Pencil, Trash2, Search, Loader2, Star } from "lucide-react";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import Link from "next/link";

interface EmployeeSkill {
  ID: number;
  SKILL_ID: number;
  SKILL_NAME: string;
  CATEGORY: string;
  PROFICIENCY: number;
  CERTIFIED_AT: string | null;
}

interface SkillMaster {
  SKILL_ID: number;
  SKILL_NAME: string;
  CATEGORY: string;
}

const CATEGORY_LABELS: Record<string, string> = {
  technical: "技術", management: "マネジメント", language: "語学", certification: "資格",
};

const PROFICIENCY_LABELS = ["", "初級", "基礎", "中級", "上級", "エキスパート"];

export default function SkillsManagePage() {
  const { id } = useParams<{ id: string }>();
  const [skills, setSkills] = useState<EmployeeSkill[]>([]);
  const [allSkills, setAllSkills] = useState<SkillMaster[]>([]);
  const [loading, setLoading] = useState(true);
  const [empName, setEmpName] = useState("");

  const [addOpen, setAddOpen] = useState(false);
  const [editSkill, setEditSkill] = useState<EmployeeSkill | null>(null);
  const [formSkillId, setFormSkillId] = useState("");
  const [formProficiency, setFormProficiency] = useState("3");
  const [formCertifiedAt, setFormCertifiedAt] = useState("");
  const [saving, setSaving] = useState(false);
  const [opError, setOpError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<number | null>(null);

  const fetchData = useCallback(() => {
    setLoading(true);
    Promise.all([
      fetch(`/api/employees/${id}/skills`).then((r) => r.json()),
      fetch(`/api/employees/${id}?section=basic`).then((r) => r.json()),
    ]).then(([skillRes, empRes]) => {
      setSkills(skillRes.skills || []);
      setAllSkills(skillRes.allSkills || []);
      const e = empRes.employee;
      if (e) setEmpName(`${e.LAST_NAME}${e.FIRST_NAME}`);
    }).finally(() => setLoading(false));
  }, [id]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const existingSkillIds = useMemo(() => new Set(skills.map((s) => s.SKILL_ID)), [skills]);

  const availableSkills = useMemo(() => {
    return allSkills.filter((s) => !existingSkillIds.has(s.SKILL_ID));
  }, [allSkills, existingSkillIds]);

  const filteredSkills = useMemo(() => {
    let list = skills;
    if (categoryFilter) list = list.filter((s) => s.CATEGORY === categoryFilter);
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      list = list.filter((s) => s.SKILL_NAME.toLowerCase().includes(q));
    }
    return list;
  }, [skills, categoryFilter, searchQuery]);

  const groupedSkills = useMemo(() => {
    const groups = new Map<string, EmployeeSkill[]>();
    for (const s of filteredSkills) {
      if (!groups.has(s.CATEGORY)) groups.set(s.CATEGORY, []);
      groups.get(s.CATEGORY)!.push(s);
    }
    return groups;
  }, [filteredSkills]);

  const openAdd = () => {
    setFormSkillId("");
    setFormProficiency("3");
    setFormCertifiedAt("");
    setEditSkill(null);
    setAddOpen(true);
  };

  const openEdit = (skill: EmployeeSkill) => {
    setFormSkillId(String(skill.SKILL_ID));
    setFormProficiency(String(skill.PROFICIENCY));
    setFormCertifiedAt(skill.CERTIFIED_AT?.slice(0, 10) || "");
    setEditSkill(skill);
    setAddOpen(true);
  };

  const handleSave = async () => {
    if (!formSkillId || !formProficiency) return;
    setSaving(true);
    try {
      const method = editSkill ? "PUT" : "POST";
      const res = await fetch(`/api/employees/${id}/skills`, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          skill_id: Number(formSkillId),
          proficiency: Number(formProficiency),
          certified_at: formCertifiedAt || null,
        }),
      });
      if (!res.ok) throw new Error("Failed");
      setAddOpen(false);
      fetchData();
    } catch {
      setOpError("保存に失敗しました");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (skillId: number) => {
    try {
      const res = await fetch(`/api/employees/${id}/skills?skill_id=${skillId}`, { method: "DELETE" });
      if (!res.ok) throw new Error("Failed");
      setDeleteTarget(null);
      fetchData();
    } catch {
      setOpError("削除に失敗しました");
    }
  };

  return (
    <div className="p-6 space-y-4 max-w-4xl mx-auto">
      <Breadcrumb items={[
        { label: "社員一覧", href: "/employees" },
        { label: empName || `社員 #${id}`, href: `/employees/${id}` },
        { label: "スキル管理" },
      ]} />
      <div className="flex items-center gap-3">
        <Link href={`/employees/${id}`}>
          <Button variant="ghost" size="icon" className="h-8 w-8">
            <ArrowLeft className="h-4 w-4" />
          </Button>
        </Link>
        <div>
          <h2 className="text-2xl font-bold tracking-tight">スキル管理</h2>
          {empName && <p className="text-sm text-muted-foreground">{empName}</p>}
        </div>
        <Button onClick={openAdd} className="ml-auto gap-1.5">
          <Plus className="h-4 w-4" />
          スキル追加
        </Button>
      </div>

      <div className="flex gap-3 items-center">
        <div className="relative">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="スキル名で検索"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9 w-48"
          />
        </div>
        <Select value={categoryFilter} onValueChange={(v) => setCategoryFilter(v === "all" ? "" : (v ?? ""))}>
          <SelectTrigger className="w-40">
            <SelectValue placeholder="全カテゴリ">
              {categoryFilter ? CATEGORY_LABELS[categoryFilter] || categoryFilter : "全カテゴリ"}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全カテゴリ</SelectItem>
            {Object.entries(CATEGORY_LABELS).map(([k, v]) => (
              <SelectItem key={k} value={k}>{v}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <span className="text-sm text-muted-foreground">{filteredSkills.length}件</span>
      </div>

      {loading ? (
        <div className="space-y-2">{[...Array(6)].map((_, i) => <Skeleton key={i} className="h-16" />)}</div>
      ) : filteredSkills.length === 0 ? (
        <Card>
          <CardContent className="pt-6 flex items-center justify-center h-32 text-muted-foreground">
            スキルデータなし
          </CardContent>
        </Card>
      ) : (
        Array.from(groupedSkills.entries()).map(([cat, catSkills]) => (
          <Card key={cat}>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">{CATEGORY_LABELS[cat] || cat}</CardTitle>
              <CardDescription className="text-xs">{catSkills.length}件</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {catSkills.map((s) => (
                <div key={s.SKILL_ID} className="flex items-center gap-3 group">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-sm font-medium">{s.SKILL_NAME}</span>
                      <span className="text-[10px] text-muted-foreground">Lv.{s.PROFICIENCY} ({PROFICIENCY_LABELS[s.PROFICIENCY]})</span>
                      {s.CERTIFIED_AT && (
                        <Badge variant="outline" className="text-[9px]">
                          取得: {s.CERTIFIED_AT.slice(0, 10)}
                        </Badge>
                      )}
                    </div>
                    <Progress value={s.PROFICIENCY * 20} className="h-2" />
                  </div>
                  <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => openEdit(s)}>
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                    <Button variant="ghost" size="icon" className="h-7 w-7 text-red-500" onClick={() => setDeleteTarget(s.SKILL_ID)}>
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        ))
      )}

      <Dialog open={addOpen} onOpenChange={setAddOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{editSkill ? "スキル編集" : "スキル追加"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            {!editSkill && (
              <div className="space-y-2">
                <p className="text-sm font-medium">スキル</p>
                <Select value={formSkillId} onValueChange={(v) => v && setFormSkillId(v)}>
                  <SelectTrigger>
                    <SelectValue placeholder="スキルを選択">
                      {formSkillId ? allSkills.find((s) => String(s.SKILL_ID) === formSkillId)?.SKILL_NAME || "選択" : "スキルを選択"}
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {Object.entries(CATEGORY_LABELS).map(([cat, label]) => {
                      const catSkills = availableSkills.filter((s) => s.CATEGORY === cat);
                      if (catSkills.length === 0) return null;
                      return catSkills.map((s) => (
                        <SelectItem key={s.SKILL_ID} value={String(s.SKILL_ID)}>
                          [{label}] {s.SKILL_NAME}
                        </SelectItem>
                      ));
                    })}
                  </SelectContent>
                </Select>
              </div>
            )}
            {editSkill && (
              <div>
                <p className="text-sm font-medium">スキル</p>
                <p className="text-sm mt-1">{editSkill.SKILL_NAME}</p>
              </div>
            )}
            <div className="space-y-2">
              <p className="text-sm font-medium">習熟度（1〜5）</p>
              <div className="flex gap-1">
                {[1, 2, 3, 4, 5].map((lv) => (
                  <button
                    key={lv}
                    className={`flex-1 py-2 rounded-md text-sm font-medium border transition-colors ${
                      String(lv) === formProficiency
                        ? "bg-primary text-primary-foreground border-primary"
                        : "hover:bg-accent"
                    }`}
                    onClick={() => setFormProficiency(String(lv))}
                  >
                    <Star className={`h-4 w-4 mx-auto ${String(lv) === formProficiency ? "fill-current" : ""}`} />
                    <span className="text-[10px] block mt-0.5">{PROFICIENCY_LABELS[lv]}</span>
                  </button>
                ))}
              </div>
            </div>
            <div className="space-y-2">
              <p className="text-sm font-medium">取得日（任意）</p>
              <Input
                type="date"
                value={formCertifiedAt}
                onChange={(e) => setFormCertifiedAt(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAddOpen(false)}>キャンセル</Button>
            <Button onClick={handleSave} disabled={saving || (!editSkill && !formSkillId)}>
              {saving && <Loader2 className="h-4 w-4 animate-spin mr-1" />}
              {editSkill ? "更新" : "追加"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={deleteTarget !== null} onOpenChange={() => setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>スキル削除</DialogTitle>
          </DialogHeader>
          <p className="text-sm">このスキルを削除しますか？</p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>キャンセル</Button>
            <Button variant="destructive" onClick={() => deleteTarget && handleDelete(deleteTarget)}>削除</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
