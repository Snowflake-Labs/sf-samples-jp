"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { ArrowLeft, UserPlus, Save, Loader2 } from "lucide-react";
import type { Department } from "@/lib/types";
import { EmployeeSearch } from "@/components/ui/employee-search";

interface Position {
  POSITION_ID: number;
  TITLE: string;
  DEPT_ID: number;
  GRADE: string;
  DEPT_NAME: string;
}

export default function NewEmployeePage() {
  const router = useRouter();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const [honbuList, setHonbuList] = useState<Department[]>([]);
  const [childDepts, setChildDepts] = useState<Department[]>([]);
  const [positions, setPositions] = useState<Position[]>([]);

  const [form, setForm] = useState({
    EMPLOYEE_CODE: "",
    LAST_NAME: "",
    FIRST_NAME: "",
    EMAIL: "",
    PHONE: "",
    HIRE_DATE: "",
    BIRTH_DATE: "",
    GENDER: "",
    HONBU: "",
    DEPT_ID: "",
    POSITION_ID: "",
    MANAGER_ID: "",
    MANAGER_LABEL: "",
    SALARY: "",
    EMPLOYMENT_TYPE: "",
    COMMUTE_TIME_MINUTES: "",
  });

  useEffect(() => {
    fetch("/api/departments?level=1&order_by=emp_count")
      .then((r) => r.json())
      .then((depts: Department[]) => setHonbuList(depts))
      .catch((err) => console.error("[honbu list fetch] failed:", err));
  }, []);

  useEffect(() => {
    if (!form.HONBU) {
      setChildDepts([]);
      return;
    }
    fetch(`/api/departments?parent_id=${form.HONBU}`)
      .then((r) => r.json())
      .then((depts: Department[]) => setChildDepts(depts))
      .catch((err) => console.error("[child depts fetch] failed:", err));
  }, [form.HONBU]);

  useEffect(() => {
    fetch("/api/positions")
      .then((r) => r.json())
      .then((data: Position[]) => setPositions(data))
      .catch((err) => console.error("[positions fetch] failed:", err));
  }, []);

  const updateField = (key: string, value: string | null) => {
    setForm((prev) => ({ ...prev, [key]: value || "" }));
    setError("");
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (!form.EMPLOYEE_CODE || !form.LAST_NAME || !form.FIRST_NAME || !form.HIRE_DATE || !form.DEPT_ID) {
      setError("必須項目を入力してください");
      return;
    }

    setSubmitting(true);
    try {
      const res = await fetch("/api/employees", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          EMPLOYEE_CODE: form.EMPLOYEE_CODE,
          LAST_NAME: form.LAST_NAME,
          FIRST_NAME: form.FIRST_NAME,
          EMAIL: form.EMAIL || undefined,
          PHONE: form.PHONE || undefined,
          HIRE_DATE: form.HIRE_DATE,
          BIRTH_DATE: form.BIRTH_DATE || undefined,
          GENDER: form.GENDER || undefined,
          DEPT_ID: Number(form.DEPT_ID),
          POSITION_ID: form.POSITION_ID ? Number(form.POSITION_ID) : undefined,
          MANAGER_ID: form.MANAGER_ID ? Number(form.MANAGER_ID) : undefined,
          SALARY: form.SALARY ? Number(form.SALARY) : undefined,
          EMPLOYMENT_TYPE: form.EMPLOYMENT_TYPE || undefined,
          COMMUTE_TIME_MINUTES: form.COMMUTE_TIME_MINUTES ? Number(form.COMMUTE_TIME_MINUTES) : undefined,
        }),
      });

      const data = await res.json();

      if (!res.ok) {
        setError(data.error || "登録に失敗しました");
        return;
      }

      router.push(`/employees/${data.EMPLOYEE_ID}`);
    } catch {
      setError("通信エラーが発生しました");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="p-6 space-y-4">
      <Link
        href="/employees"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" />
        戻る
      </Link>

      <div className="flex items-center gap-3">
        <UserPlus className="h-6 w-6" />
        <h2 className="text-2xl font-bold tracking-tight">社員登録</h2>
      </div>

      {error && (
        <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-6">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Badge variant="outline">基本情報</Badge>
              個人情報
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <label className="text-sm font-medium">
                  社員番号 <span className="text-destructive">*</span>
                </label>
                <Input
                  value={form.EMPLOYEE_CODE}
                  onChange={(e) => updateField("EMPLOYEE_CODE", e.target.value)}
                  placeholder="例: EMP001"
                  required
                />
              </div>
              <div />
              <div className="space-y-1.5">
                <label className="text-sm font-medium">
                  姓 <span className="text-destructive">*</span>
                </label>
                <Input
                  value={form.LAST_NAME}
                  onChange={(e) => updateField("LAST_NAME", e.target.value)}
                  placeholder="山田"
                  required
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-sm font-medium">
                  名 <span className="text-destructive">*</span>
                </label>
                <Input
                  value={form.FIRST_NAME}
                  onChange={(e) => updateField("FIRST_NAME", e.target.value)}
                  placeholder="太郎"
                  required
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-sm font-medium">メール</label>
                <Input
                  type="email"
                  value={form.EMAIL}
                  onChange={(e) => updateField("EMAIL", e.target.value)}
                  placeholder="taro.yamada@example.com"
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-sm font-medium">電話番号</label>
                <Input
                  value={form.PHONE}
                  onChange={(e) => updateField("PHONE", e.target.value)}
                  placeholder="090-1234-5678"
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-sm font-medium">
                  入社日 <span className="text-destructive">*</span>
                </label>
                <Input
                  type="date"
                  value={form.HIRE_DATE}
                  onChange={(e) => updateField("HIRE_DATE", e.target.value)}
                  required
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-sm font-medium">生年月日</label>
                <Input
                  type="date"
                  value={form.BIRTH_DATE}
                  onChange={(e) => updateField("BIRTH_DATE", e.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-sm font-medium">性別</label>
                <Select
                  value={form.GENDER}
                  onValueChange={(v) => updateField("GENDER", !v || v === "__none__" ? "" : v)}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="選択してください" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__none__">未選択</SelectItem>
                    <SelectItem value="M">男性</SelectItem>
                    <SelectItem value="F">女性</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Badge variant="outline">所属情報</Badge>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <label className="text-sm font-medium">
                  本部 <span className="text-destructive">*</span>
                </label>
                <Select
                  value={form.HONBU}
                  onValueChange={(v) => {
                    updateField("HONBU", v);
                    updateField("DEPT_ID", "");
                  }}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="本部を選択" />
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
              <div className="space-y-1.5">
                <label className="text-sm font-medium">
                  部署 <span className="text-destructive">*</span>
                </label>
                <Select
                  value={form.DEPT_ID}
                  onValueChange={(v) => updateField("DEPT_ID", v)}
                  disabled={!form.HONBU}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder={form.HONBU ? "部署を選択" : "先に本部を選択"} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={form.HONBU}>
                      {honbuList.find((d) => String(d.DEPT_ID) === form.HONBU)?.DEPT_NAME || "本部直下"}
                    </SelectItem>
                    {childDepts.map((d) => (
                      <SelectItem key={d.DEPT_ID} value={String(d.DEPT_ID)}>
                        {d.DEPT_NAME}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <label className="text-sm font-medium">役職</label>
                <Select
                  value={form.POSITION_ID}
                  onValueChange={(v) => updateField("POSITION_ID", !v || v === "__none__" ? "" : v)}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="役職を選択" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__none__">未選択</SelectItem>
                    {positions.map((p) => (
                      <SelectItem key={p.POSITION_ID} value={String(p.POSITION_ID)}>
                        {p.TITLE}（{p.DEPT_NAME}）
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <label className="text-sm font-medium">上司</label>
                <EmployeeSearch
                  value={form.MANAGER_ID}
                  selectedLabel={form.MANAGER_LABEL}
                  onSelect={(id, label) => {
                    setForm((prev) => ({ ...prev, MANAGER_ID: String(id), MANAGER_LABEL: label }));
                  }}
                  onClear={() => setForm((prev) => ({ ...prev, MANAGER_ID: "", MANAGER_LABEL: "" }))}
                  placeholder="上司の名前を検索"
                />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Badge variant="outline">その他</Badge>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <label className="text-sm font-medium">給与</label>
                <Input
                  type="number"
                  value={form.SALARY}
                  onChange={(e) => updateField("SALARY", e.target.value)}
                  placeholder="年収（円）"
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-sm font-medium">雇用形態</label>
                <Select
                  value={form.EMPLOYMENT_TYPE}
                  onValueChange={(v) => updateField("EMPLOYMENT_TYPE", !v || v === "__none__" ? "" : v)}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="選択してください" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__none__">未選択</SelectItem>
                    <SelectItem value="正社員">正社員</SelectItem>
                    <SelectItem value="契約社員">契約社員</SelectItem>
                    <SelectItem value="パート">パート</SelectItem>
                    <SelectItem value="派遣">派遣</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <label className="text-sm font-medium">通勤時間（分）</label>
                <Input
                  type="number"
                  value={form.COMMUTE_TIME_MINUTES}
                  onChange={(e) => updateField("COMMUTE_TIME_MINUTES", e.target.value)}
                  placeholder="例: 45"
                />
              </div>
            </div>
          </CardContent>
        </Card>

        <div className="flex justify-end gap-3">
          <Link href="/employees">
            <Button type="button" variant="outline">キャンセル</Button>
          </Link>
          <Button type="submit" disabled={submitting} className="gap-2">
            {submitting ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Save className="h-4 w-4" />
            )}
            {submitting ? "登録中..." : "登録する"}
          </Button>
        </div>
      </form>
    </div>
  );
}
