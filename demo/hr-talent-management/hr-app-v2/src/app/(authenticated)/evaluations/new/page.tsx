"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { ArrowLeft, Search, Loader2, CheckCircle, Star } from "lucide-react";
import Link from "next/link";

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
const GRADE_DESC: Record<string, string> = {
  S: "卓越（5.0）",
  A: "優秀（4.0〜4.9）",
  B: "標準（3.0〜3.9）",
  C: "要改善（2.0〜2.9）",
  D: "不可（1.0〜1.9）",
};

interface EmployeeHit {
  EMPLOYEE_ID: number;
  EMPLOYEE_CODE: string;
  FIRST_NAME: string;
  LAST_NAME: string;
  DEPT_NAME: string;
  GRADE: string;
  POSITION_TITLE: string;
  MANAGER_ID: number | null;
}

export default function EvaluationNewPage() {
  const router = useRouter();
  const [step, setStep] = useState<"search" | "form">("search");

  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<EmployeeHit[]>([]);
  const [searching, setSearching] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [selectedEmp, setSelectedEmp] = useState<EmployeeHit | null>(null);
  const [period, setPeriod] = useState(PERIODS[0]);
  const [score, setScore] = useState("");
  const [grade, setGrade] = useState("");
  const [comment, setComment] = useState("");
  const [selfComment, setSelfComment] = useState("");
  const [selfScore, setSelfScore] = useState("");

  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState("");

  const doSearch = useCallback((q: string) => {
    if (q.trim().length < 2) {
      setSearchResults([]);
      return;
    }
    setSearching(true);
    fetch(`/api/employees?search=${encodeURIComponent(q.trim())}&limit=20&offset=0`)
      .then((r) => r.json())
      .then((res) => {
        const data = (res.data || []).map((e: Record<string, unknown>) => ({
          EMPLOYEE_ID: e.EMPLOYEE_ID,
          EMPLOYEE_CODE: e.EMPLOYEE_CODE,
          FIRST_NAME: e.FIRST_NAME,
          LAST_NAME: e.LAST_NAME,
          DEPT_NAME: e.DEPT_NAME,
          GRADE: e.GRADE,
          POSITION_TITLE: e.POSITION_TITLE,
          MANAGER_ID: e.MANAGER_ID,
        }));
        setSearchResults(data);
      })
      .catch(() => setSearchResults([]))
      .finally(() => setSearching(false));
  }, []);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => doSearch(searchQuery), 300);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [searchQuery, doSearch]);

  const selectEmployee = (emp: EmployeeHit) => {
    setSelectedEmp(emp);
    setStep("form");
  };

  const autoGrade = (s: number) => {
    if (s >= 4.5) return "S";
    if (s >= 4.0) return "A";
    if (s >= 3.0) return "B";
    if (s >= 2.0) return "C";
    return "D";
  };

  const handleScoreChange = (v: string) => {
    setScore(v);
    const n = parseFloat(v);
    if (!isNaN(n) && n >= 1 && n <= 5) {
      setGrade(autoGrade(n));
    }
  };

  const handleSubmit = async () => {
    if (!selectedEmp || !score || !grade || !period) return;
    setSubmitting(true);
    setError("");
    try {
      const res = await fetch("/api/evaluations/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          employee_id: selectedEmp.EMPLOYEE_ID,
          evaluator_id: selectedEmp.MANAGER_ID || selectedEmp.EMPLOYEE_ID,
          period,
          score: parseFloat(score),
          grade,
          comment: comment || null,
          self_comment: selfComment || null,
          self_score: selfScore ? parseFloat(selfScore) : null,
          status: "draft",
        }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.error || "Failed");
      }
      setSuccess(true);
      setTimeout(() => router.push("/evaluations"), 1500);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  if (success) {
    return (
      <div className="p-6 flex flex-col items-center justify-center min-h-[60vh] gap-4">
        <CheckCircle className="h-16 w-16 text-green-500" />
        <p className="text-xl font-bold">評価を作成しました</p>
        <p className="text-sm text-muted-foreground">評価管理画面に戻ります...</p>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6 max-w-3xl mx-auto">
      <div className="flex items-center gap-3">
        <Link href="/evaluations">
          <Button variant="ghost" size="icon" className="h-8 w-8">
            <ArrowLeft className="h-4 w-4" />
          </Button>
        </Link>
        <h2 className="text-2xl font-bold tracking-tight">新規評価入力</h2>
      </div>

      {step === "search" && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">評価対象社員を検索</CardTitle>
            <CardDescription>氏名または社員番号で検索してください</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="relative">
              <Search className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="氏名・社員番号を入力（2文字以上）"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-10"
                autoFocus
              />
            </div>
            {searching && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                検索中...
              </div>
            )}
            {searchResults.length > 0 && (
              <div className="space-y-1 max-h-80 overflow-y-auto">
                {searchResults.map((emp) => (
                  <div
                    key={emp.EMPLOYEE_ID}
                    className="flex items-center gap-3 p-3 rounded-lg border hover:bg-accent transition-colors cursor-pointer"
                    onClick={() => selectEmployee(emp)}
                  >
                    <div className="flex-1">
                      <span className="font-medium">{emp.LAST_NAME}{emp.FIRST_NAME}</span>
                      <span className="text-xs text-muted-foreground ml-2">{emp.EMPLOYEE_CODE}</span>
                    </div>
                    <Badge variant="outline" className="text-[10px]">{emp.GRADE}</Badge>
                    <span className="text-xs text-muted-foreground">{emp.DEPT_NAME}</span>
                  </div>
                ))}
              </div>
            )}
            {!searching && searchQuery.length >= 2 && searchResults.length === 0 && (
              <p className="text-sm text-muted-foreground text-center py-4">該当する社員が見つかりません</p>
            )}
          </CardContent>
        </Card>
      )}

      {step === "form" && selectedEmp && (
        <>
          <Card className="bg-blue-50/30 border-blue-200">
            <CardContent className="pt-4">
              <div className="flex items-center gap-4">
                <div className="flex-1">
                  <p className="font-bold text-lg">{selectedEmp.LAST_NAME}{selectedEmp.FIRST_NAME}</p>
                  <p className="text-sm text-muted-foreground">{selectedEmp.DEPT_NAME} / {selectedEmp.POSITION_TITLE}</p>
                </div>
                <Badge variant="outline">{selectedEmp.GRADE}</Badge>
                <Button variant="ghost" size="sm" className="text-xs" onClick={() => { setStep("search"); setSelectedEmp(null); }}>
                  変更
                </Button>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">評価内容</CardTitle>
            </CardHeader>
            <CardContent className="space-y-5">
              <div className="grid grid-cols-3 gap-4">
                <div className="space-y-2">
                  <p className="text-sm font-medium">評価期間 *</p>
                  <Select value={period} onValueChange={(v) => v && setPeriod(v)}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {PERIODS.map((p) => (
                        <SelectItem key={p} value={p}>{p}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-2">
                  <p className="text-sm font-medium">スコア（1.0〜5.0）*</p>
                  <div className="relative">
                    <Star className="absolute left-3 top-3 h-4 w-4 text-amber-500" />
                    <Input
                      type="number"
                      min={1}
                      max={5}
                      step={0.1}
                      placeholder="3.5"
                      value={score}
                      onChange={(e) => handleScoreChange(e.target.value)}
                      className="pl-10"
                    />
                  </div>
                </div>

                <div className="space-y-2">
                  <p className="text-sm font-medium">グレード *</p>
                  <Select value={grade} onValueChange={(v) => v && setGrade(v)}>
                    <SelectTrigger>
                      <SelectValue placeholder="自動設定">
                        {grade ? `${grade} — ${GRADE_DESC[grade]}` : "自動設定"}
                      </SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                      {GRADES.map((g) => (
                        <SelectItem key={g} value={g}>{g} — {GRADE_DESC[g]}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <Separator />

              <div className="space-y-2">
                <p className="text-sm font-medium">評価コメント</p>
                <Textarea
                  placeholder="業績評価・行動評価の所見を記入してください"
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  rows={4}
                />
                <p className="text-xs text-muted-foreground">Cortex AI_SENTIMENT で自動感情分析されます</p>
              </div>

              <Separator />

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <p className="text-sm font-medium">自己評価スコア（1.0〜5.0）</p>
                  <Input
                    type="number"
                    min={1}
                    max={5}
                    step={0.1}
                    placeholder="3.5"
                    value={selfScore}
                    onChange={(e) => setSelfScore(e.target.value)}
                  />
                </div>
              </div>

              <div className="space-y-2">
                <p className="text-sm font-medium">自己評価コメント</p>
                <Textarea
                  placeholder="本人による自己評価コメント"
                  value={selfComment}
                  onChange={(e) => setSelfComment(e.target.value)}
                  rows={3}
                />
              </div>

              {error && (
                <div className="p-3 rounded-md bg-red-50 border border-red-200 text-sm text-red-700">
                  {error}
                </div>
              )}

              <div className="flex gap-3 justify-end pt-2">
                <Button variant="outline" onClick={() => router.push("/evaluations")}>
                  キャンセル
                </Button>
                <Button
                  onClick={handleSubmit}
                  disabled={submitting || !score || !grade || !period}
                  className="gap-2"
                >
                  {submitting && <Loader2 className="h-4 w-4 animate-spin" />}
                  下書き保存
                </Button>
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
