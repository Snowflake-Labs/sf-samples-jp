"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import {
  ArrowLeft, Mail, Calendar, Building, Briefcase, Brain,
  AlertTriangle, Users, ArrowRightLeft, ChevronRight, History,
  Pencil, Save, X, Loader2, GitBranch, List,
} from "lucide-react";
import { GRADE_LABELS, ML_MODEL_METRICS, FEATURE_LABELS, FEATURE_DESCRIPTIONS } from "@/lib/types";
import { shapToHumanText, aucToStars, renderStars, riskScoreToText } from "@/lib/ml-display";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";

interface ShapFactor {
  FEATURE_NAME: string;
  SHAP_VALUE: number;
  FEATURE_VALUE: number;
}

interface SimilarCase {
  SIMILAR_EMPLOYEE_ID: number;
  SIMILARITY_SCORE: number;
  OUTCOME: string;
  COMMON_FACTORS: string;
  SIM_NAME: string;
  SIM_CODE: string;
}

interface EvidenceData {
  ai_summary: string;
  score: number;
  risk_label?: string;
  label?: string;
  manager_id?: number;
  shap_factors?: { feature: string; shap: number; value: number }[];
}

interface OrgMember {
  EMPLOYEE_ID: number;
  NAME: string;
  EMPLOYEE_CODE: string;
  GRADE: string;
  TITLE: string;
  MANAGER_ID: number | null;
  DEPT_ID?: number;
  DEPT_NAME?: string;
}

interface MLInsights {
  attrition: { RISK_SCORE: number; RISK_LABEL: string; MODEL_VERSION: string } | null;
  relationship: { RELATIONSHIP_SCORE: number; COMPOSITE_LABEL: number; MANAGER_NAME: string } | null;
  transferFit: { FIT_SCORE: number; TARGET_POSITION_ID: number; TARGET_POSITION_TITLE: string; TARGET_DEPT_NAME: string }[];
  shapFactors: ShapFactor[];
  relationshipShap: ShapFactor[];
  attritionEvidence: EvidenceData | null;
  relationshipEvidence: EvidenceData | null;
  similarCases: SimilarCase[];
}

interface EmployeeDetail {
  employee: {
    EMPLOYEE_ID: number;
    EMPLOYEE_CODE: string;
    FIRST_NAME: string;
    LAST_NAME: string;
    EMAIL: string;
    HIRE_DATE: string;
    BIRTH_DATE: string;
    GENDER: string;
    DEPT_ID: number;
    MANAGER_ID: number;
    STATUS: string;
    SALARY: number;
    DEPT_NAME: string;
    POSITION_TITLE: string;
    GRADE: string;
    MANAGER_NAME: string;
  };
  skills: { SKILL_NAME: string; CATEGORY: string; PROFICIENCY: number }[];
  evaluations: {
    EVALUATION_ID: number;
    PERIOD: string;
    SCORE: number;
    GRADE: string;
    COMMENT: string;
    STATUS: string;
  }[];
  notes: {
    NOTE_ID: number;
    NOTE_DATE: string;
    CONTENT: string;
    CATEGORY: string;
  }[];
  careerHistory: {
    HISTORY_ID: number;
    DEPT_ID: number;
    POSITION_ID: number;
    MANAGER_ID: number;
    START_DATE: string;
    END_DATE: string | null;
    TRANSFER_TYPE: string;
    REASON: string;
    PERFORMANCE_AFTER: number | null;
    DEPT_NAME: string;
    POSITION_TITLE: string;
    MANAGER_NAME: string;
  }[];
  mlInsights: MLInsights;
  orgChart: {
    deptColleagues: OrgMember[];
    subDeptColleagues: OrgMember[];
  };
}

const CATEGORY_LABELS: Record<string, string> = {
  career: "キャリア",
  concern: "懸念",
  motivation: "モチベーション",
  technical: "技術",
  management: "マネジメント",
  language: "語学",
  certification: "資格",
};

const CATEGORY_COLORS: Record<string, string> = {
  career: "bg-blue-100 text-blue-700",
  concern: "bg-red-100 text-red-700",
  motivation: "bg-green-100 text-green-700",
};

const GRADE_COLORS: Record<string, string> = {
  E1: "bg-purple-100 text-purple-800",
  D1: "bg-indigo-100 text-indigo-800",
  D2: "bg-blue-100 text-blue-800",
  M1: "bg-cyan-100 text-cyan-800",
  M2: "bg-teal-100 text-teal-800",
  S1: "bg-green-100 text-green-800",
  S2: "bg-lime-100 text-lime-800",
  J1: "bg-amber-100 text-amber-800",
  J2: "bg-orange-100 text-orange-800",
  J3: "bg-gray-100 text-gray-700",
};

export default function EmployeeDetailPage() {
  const params = useParams();
  const router = useRouter();
  const [data, setData] = useState<EmployeeDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [mlLoading, setMlLoading] = useState(true);
  const [attritionOpen, setAttritionOpen] = useState(false);
  const [relationshipOpen, setRelationshipOpen] = useState(false);
  const [transferFitOpen, setTransferFitOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [orgViewMode, setOrgViewMode] = useState<"list" | "tree">("list");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<Record<string, unknown>>({});

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setMlLoading(true);

    fetch(`/api/employees/${params.id}?section=basic`)
      .then((r) => r.json())
      .then((basic) => {
        if (cancelled) return;
        setData({
          ...basic,
          mlInsights: { attrition: null, relationship: null, transferFit: [], shapFactors: [], relationshipShap: [], attritionEvidence: null, relationshipEvidence: null, similarCases: [] },
        });
        setLoading(false);

        fetch(`/api/employees/${params.id}?section=ml`)
          .then((r) => {
            if (!r.ok) throw new Error(`ML API error: ${r.status}`);
            return r.json();
          })
          .then((ml) => {
            if (!cancelled) {
              setData((prev) => prev ? { ...prev, mlInsights: ml } : prev);
            }
          })
          .catch((err) => console.error("ML fetch error:", err))
          .finally(() => { if (!cancelled) setMlLoading(false); });
      })
      .catch(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  }, [params.id]);

  if (loading) {
    return (
      <div className="p-6 space-y-4">
        <Skeleton className="h-8 w-48" />
        <div className="grid grid-cols-3 gap-4">
          <Skeleton className="h-64 col-span-1" />
          <Skeleton className="h-64 col-span-2" />
        </div>
      </div>
    );
  }

  if (!data?.employee) {
    return (
      <div className="p-6">
        <p className="text-muted-foreground">社員が見つかりません</p>
      </div>
    );
  }

  const { employee: emp, skills, evaluations, notes, careerHistory, mlInsights, orgChart } = data;
  const age = emp.BIRTH_DATE
    ? Math.floor((Date.now() - new Date(emp.BIRTH_DATE).getTime()) / (365.25 * 24 * 60 * 60 * 1000))
    : null;
  const tenure = emp.HIRE_DATE
    ? Math.floor((Date.now() - new Date(emp.HIRE_DATE).getTime()) / (365.25 * 24 * 60 * 60 * 1000))
    : null;

  const formatSalary = (s: number) => {
    if (!s || s === 0) return "***";
    return `¥${s.toLocaleString()}`;
  };

  const evalChartData = [...evaluations].reverse().map((ev) => ({
    period: ev.PERIOD,
    score: Number(ev.SCORE),
    grade: ev.GRADE,
  }));

  const startEdit = () => {
    setEditForm({
      FIRST_NAME: emp.FIRST_NAME,
      LAST_NAME: emp.LAST_NAME,
      EMAIL: emp.EMAIL,
      PHONE: (emp as Record<string, unknown>).PHONE || "",
      BIRTH_DATE: emp.BIRTH_DATE?.slice(0, 10) || "",
      GENDER: emp.GENDER,
      SALARY: emp.SALARY,
      STATUS: emp.STATUS,
      DEPT_ID: emp.DEPT_ID,
      POSITION_ID: (emp as Record<string, unknown>).POSITION_ID || "",
      MANAGER_ID: emp.MANAGER_ID || "",
      _transferReason: "",
    });
    setEditing(true);
  };

  const saveEdit = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      const res = await fetch(`/api/employees/${params.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(editForm),
      });
      if (!res.ok) throw new Error("Update failed");
      setEditing(false);
      const refreshed = await fetch(`/api/employees/${params.id}?section=basic`).then(r => r.json());
      setData(refreshed);
    } catch {
      setSaveError("更新に失敗しました");
    } finally {
      setSaving(false);
    }
  };

  const relLabel = mlInsights?.relationship
    ? Number(mlInsights.relationship.RELATIONSHIP_SCORE) >= 0.7 ? "良好"
    : Number(mlInsights.relationship.RELATIONSHIP_SCORE) >= 0.4 ? "普通" : "要改善"
    : null;

  const renderShapBar = (shap: number, maxAbs: number, invertColor = false) => {
    const pct = Math.min(Math.abs(shap) / maxAbs * 100, 100);
    const posColor = invertColor ? "bg-green-400" : "bg-red-400";
    const negColor = invertColor ? "bg-red-400" : "bg-green-400";
    return (
      <div className="relative h-3 w-full bg-muted rounded">
        {shap > 0 ? (
          <div className={`absolute left-1/2 h-full ${posColor} rounded-r`} style={{ width: `${pct / 2}%` }} />
        ) : (
          <div className={`absolute right-1/2 h-full ${negColor} rounded-l`} style={{ width: `${pct / 2}%` }} />
        )}
        <div className="absolute left-1/2 top-0 bottom-0 w-px bg-foreground/20" />
      </div>
    );
  };

  const maxShapAbs = mlInsights?.shapFactors?.length
    ? Math.max(...mlInsights.shapFactors.map((s) => Math.abs(Number(s.SHAP_VALUE))))
    : 1;
  const maxRelShapAbs = mlInsights?.relationshipShap?.length
    ? Math.max(...mlInsights.relationshipShap.map((s) => Math.abs(Number(s.SHAP_VALUE))))
    : 1;

  const subDeptGroups = orgChart?.subDeptColleagues?.reduce<Record<string, OrgMember[]>>((acc, m) => {
    const key = m.DEPT_NAME || "不明";
    if (!acc[key]) acc[key] = [];
    acc[key].push(m);
    return acc;
  }, {}) || {};

  interface OrgTreeNode extends OrgMember {
    children: OrgTreeNode[];
  }

  const buildOrgTree = (): OrgTreeNode[] => {
    if (!orgChart) return [];
    const allMembers = [
      ...(orgChart.deptColleagues || []),
      ...(orgChart.subDeptColleagues || []),
    ];
    const memberMap = new Map<number, OrgTreeNode>();
    allMembers.forEach((m) => memberMap.set(m.EMPLOYEE_ID, { ...m, children: [] }));
    const roots: OrgTreeNode[] = [];
    memberMap.forEach((node) => {
      if (node.MANAGER_ID && memberMap.has(node.MANAGER_ID)) {
        memberMap.get(node.MANAGER_ID)!.children.push(node);
      } else {
        roots.push(node);
      }
    });
    return roots;
  };

  const orgTree = buildOrgTree();

  const renderTreeNode = (node: OrgTreeNode, isLast: boolean, depth: number) => (
    <div key={node.EMPLOYEE_ID} className="relative">
      <div className="flex items-start">
        {depth > 0 && (
          <div className="flex items-center mr-1 shrink-0">
            <div className={`w-4 border-t border-muted-foreground/30 ${isLast ? "" : ""}`} />
          </div>
        )}
        <Link
          href={`/employees/${node.EMPLOYEE_ID}`}
          className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-md border text-xs hover:bg-accent transition-colors shrink-0 ${
            node.EMPLOYEE_ID === emp.EMPLOYEE_ID ? "ring-2 ring-primary bg-primary/5" : ""
          }`}
        >
          <Badge className={`text-[9px] px-1 py-0 ${GRADE_COLORS[node.GRADE] || "bg-gray-100 text-gray-700"}`}>
            {node.GRADE}
          </Badge>
          <span className="font-medium">{node.NAME}</span>
          <span className="text-muted-foreground text-[10px]">{node.TITLE}</span>
          {node.children.length > 0 && (
            <span className="text-muted-foreground text-[9px]">({node.children.length})</span>
          )}
        </Link>
      </div>
      {node.children.length > 0 && (
        <div className="ml-4 pl-2 border-l border-muted-foreground/20 mt-1 space-y-1">
          {node.children.map((child, i) => renderTreeNode(child, i === node.children.length - 1, depth + 1))}
        </div>
      )}
    </div>
  );

  return (
    <div className="p-6 space-y-4">
      <Link href="/employees" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-4 w-4" />
        社員一覧に戻る
      </Link>

      <div className="flex items-center gap-4">
        <div className="h-14 w-14 rounded-full bg-primary/10 flex items-center justify-center text-xl font-bold">
          {emp.LAST_NAME.charAt(0)}
        </div>
        <div>
          <h2 className="text-2xl font-bold">
            {emp.LAST_NAME}{emp.FIRST_NAME}
          </h2>
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <span>{emp.EMPLOYEE_CODE}</span>
            <Badge variant="outline">{emp.GRADE} {GRADE_LABELS[emp.GRADE]}</Badge>
            <Badge variant={emp.STATUS === "active" ? "default" : "secondary"}>
              {emp.STATUS === "active" ? "在籍" : emp.STATUS}
            </Badge>
          </div>
        </div>
        {!editing ? (
          <div className="flex gap-2 ml-auto items-center">
            {saveError && <span className="text-xs text-red-600">{saveError}</span>}
            <Link href={`/simulation?employee=${emp.EMPLOYEE_ID}`}>
              <Button variant="outline" size="sm" className="gap-1.5">
                <ArrowRightLeft className="h-3.5 w-3.5" />
                異動シミュレーション
              </Button>
            </Link>
            <Button variant="outline" size="sm" className="gap-1.5" onClick={startEdit}>
              <Pencil className="h-3.5 w-3.5" />
              編集
            </Button>
          </div>
        ) : (
          <div className="flex gap-2 ml-auto">
            <Button variant="outline" size="sm" onClick={() => setEditing(false)} disabled={saving}>
              <X className="h-3.5 w-3.5 mr-1" />キャンセル
            </Button>
            <Button size="sm" onClick={saveEdit} disabled={saving} className="gap-1.5">
              {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
              保存
            </Button>
          </div>
        )}
      </div>

      {!loading && (
        <div className="grid grid-cols-3 gap-4">
          {mlLoading && !mlInsights?.attrition ? (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-1.5">
                  <AlertTriangle className="h-3.5 w-3.5" />
                  離職リスク
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                <Skeleton className="h-6 w-20" />
                <Skeleton className="h-3 w-full" />
                <Skeleton className="h-3 w-3/4" />
              </CardContent>
            </Card>
          ) : (
          <Card
            className={`cursor-pointer transition-shadow hover:shadow-md ${mlInsights.attrition?.RISK_LABEL === "high" ? "border-red-200 bg-red-50/30" : mlInsights.attrition?.RISK_LABEL === "medium" ? "border-amber-200 bg-amber-50/30" : ""}`}
            onClick={() => setAttritionOpen(true)}
          >
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-1.5">
                <AlertTriangle className="h-3.5 w-3.5" />
                離職リスク
                <ChevronRight className="h-3 w-3 ml-auto text-muted-foreground" />
              </CardTitle>
            </CardHeader>
            <CardContent>
              {mlInsights.attrition ? (
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <Badge variant={mlInsights.attrition.RISK_LABEL === "high" ? "destructive" : mlInsights.attrition.RISK_LABEL === "medium" ? "default" : "secondary"} className="text-base px-3 py-1">
                      {mlInsights.attrition.RISK_LABEL === "high" ? "高リスク" : mlInsights.attrition.RISK_LABEL === "medium" ? "中リスク" : "低リスク"}
                    </Badge>
                  </div>
                  {mlInsights.shapFactors.length > 0 && (
                    <div className="space-y-1 mt-2">
                      <p className="text-[10px] text-muted-foreground flex items-center gap-1"><Brain className="h-2.5 w-2.5" />SHAP要因</p>
                      {mlInsights.shapFactors.slice(0, 3).map((sf, i) => (
                        <div key={i} className="flex items-center gap-1.5 text-[11px]">
                          <span className={`font-mono ${Number(sf.SHAP_VALUE) > 0 ? "text-red-600" : "text-green-600"}`}>
                            {Number(sf.SHAP_VALUE) > 0 ? "+" : ""}{Number(sf.SHAP_VALUE).toFixed(3)}
                          </span>
                          <span className="text-muted-foreground group relative cursor-help">
                            {FEATURE_LABELS[sf.FEATURE_NAME] || sf.FEATURE_NAME}
                            {FEATURE_DESCRIPTIONS[sf.FEATURE_NAME] && (
                              <span className="invisible group-hover:visible absolute left-0 bottom-full mb-1 w-56 p-2 rounded-md bg-popover text-popover-foreground text-[10px] leading-relaxed shadow-lg border z-50">
                                {FEATURE_DESCRIPTIONS[sf.FEATURE_NAME]}
                              </span>
                            )}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">データなし</p>
              )}
            </CardContent>
          </Card>
          )}

          {mlLoading && !mlInsights?.relationship ? (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-1.5">
                  <Users className="h-3.5 w-3.5" />
                  上司との関係性
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                <Skeleton className="h-8 w-16" />
                <Skeleton className="h-1.5 w-full" />
                <Skeleton className="h-3 w-24" />
              </CardContent>
            </Card>
          ) : (
          <Card
            className="cursor-pointer transition-shadow hover:shadow-md"
            onClick={() => setRelationshipOpen(true)}
          >
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-1.5">
                <Users className="h-3.5 w-3.5" />
                上司との関係性
                <ChevronRight className="h-3 w-3 ml-auto text-muted-foreground" />
              </CardTitle>
            </CardHeader>
            <CardContent>
              {mlInsights.relationship ? (
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="text-2xl font-bold font-mono">{(Number(mlInsights.relationship.RELATIONSHIP_SCORE) * 100).toFixed(0)}%</span>
                    <Badge variant={relLabel === "良好" ? "default" : relLabel === "要改善" ? "destructive" : "secondary"}>
                      {relLabel}
                    </Badge>
                  </div>
                  <Progress value={Number(mlInsights.relationship.RELATIONSHIP_SCORE) * 100} className="h-1.5" />
                  <p className="text-xs text-muted-foreground">
                    上司: {emp?.MANAGER_NAME || mlInsights.relationship.MANAGER_NAME}
                  </p>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">データなし</p>
              )}
            </CardContent>
          </Card>
          )}

          {mlLoading && !(mlInsights?.transferFit?.length > 0) ? (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-1.5">
                  <ArrowRightLeft className="h-3.5 w-3.5" />
                  配置適合（Top 3）
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-3/4" />
              </CardContent>
            </Card>
          ) : (
          <Card
            className="cursor-pointer transition-shadow hover:shadow-md"
            onClick={() => setTransferFitOpen(true)}
          >
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-1.5">
                <ArrowRightLeft className="h-3.5 w-3.5" />
                配置適合（Top 3）
                <ChevronRight className="h-3 w-3 ml-auto text-muted-foreground" />
              </CardTitle>
            </CardHeader>
            <CardContent>
              {mlInsights.transferFit?.length > 0 ? (
                <div className="space-y-2">
                  {mlInsights.transferFit.slice(0, 3).map((tf, i) => (
                    <div key={i} className="flex items-center gap-2">
                      <Badge variant="outline" className="text-[10px] w-12 justify-center shrink-0">
                        {(Number(tf.FIT_SCORE) * 100).toFixed(0)}%
                      </Badge>
                      <div className="text-xs truncate">
                        <span className="font-medium">{tf.TARGET_POSITION_TITLE}</span>
                        <span className="text-muted-foreground ml-1">/ {tf.TARGET_DEPT_NAME}</span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">データなし</p>
              )}
            </CardContent>
          </Card>
          )}
        </div>
      )}

      <Dialog open={attritionOpen} onOpenChange={setAttritionOpen}>
        <DialogContent className="sm:max-w-xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4" />
              離職リスク分析 — {emp.LAST_NAME}{emp.FIRST_NAME}
            </DialogTitle>
            <DialogDescription>予測の信頼度: {renderStars(aucToStars(ML_MODEL_METRICS.ATTRITION_AUC).stars)} ({aucToStars(ML_MODEL_METRICS.ATTRITION_AUC).label})</DialogDescription>
          </DialogHeader>
          {mlInsights?.attrition && (
            <div className="space-y-4">
              <Badge variant={mlInsights.attrition.RISK_LABEL === "high" ? "destructive" : mlInsights.attrition.RISK_LABEL === "medium" ? "default" : "secondary"} className="text-lg px-4 py-1">
                {mlInsights.attrition.RISK_LABEL === "high" ? "高リスク" : mlInsights.attrition.RISK_LABEL === "medium" ? "中リスク" : "低リスク"}
              </Badge>

              {mlInsights.attritionEvidence?.ai_summary && (
                <div className="p-3 rounded-lg bg-muted/50 border">
                  <p className="text-xs font-medium text-muted-foreground mb-1 flex items-center gap-1">
                    <Brain className="h-3 w-3" />AI分析サマリー
                  </p>
                  <div className="text-sm leading-relaxed prose prose-sm max-w-none prose-headings:text-base prose-headings:mt-2 prose-headings:mb-1">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{mlInsights.attritionEvidence.ai_summary}</ReactMarkdown>
                  </div>
                </div>
              )}

              {mlInsights.shapFactors.length > 0 && (
                <div>
                  <p className="text-sm font-medium mb-2">主な影響要因</p>
                  <div className="space-y-2">
                    {mlInsights.shapFactors.map((sf, i) => {
                      const h = shapToHumanText(Number(sf.SHAP_VALUE), sf.FEATURE_NAME, FEATURE_LABELS);
                      return (
                        <div key={i} className={`flex items-center gap-3 p-2.5 rounded-md ${h.direction === "up" ? "bg-red-50" : "bg-green-50"}`}>
                          <span className="text-lg w-6 text-center">{h.icon}</span>
                          <div className="flex-1">
                            <p className="text-sm font-medium">{h.label}</p>
                            <p className={`text-xs ${h.direction === "up" ? "text-red-600" : "text-green-600"}`}>{h.text}</p>
                          </div>
                          <Badge variant={h.impact === "large" ? "destructive" : h.impact === "medium" ? "default" : "secondary"} className="text-[10px]">
                            {h.impact === "large" ? "影響大" : h.impact === "medium" ? "影響中" : "影響小"}
                          </Badge>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {mlInsights.similarCases?.length > 0 && (
                <div>
                  <p className="text-sm font-medium mb-2">類似社員ケース</p>
                  <div className="space-y-1.5">
                    {mlInsights.similarCases.map((sc, i) => (
                      <div key={i} className="flex items-center gap-2 p-2 rounded border text-xs">
                        <Badge variant={sc.OUTCOME === "left" ? "destructive" : "default"} className="text-[10px] shrink-0">
                          {sc.OUTCOME === "left" ? "退職" : "在籍"}
                        </Badge>
                        <Link href={`/employees/${sc.SIMILAR_EMPLOYEE_ID}`} className="font-medium hover:underline">
                          {sc.SIM_NAME}
                        </Link>
                        <span className="text-muted-foreground">{sc.SIM_CODE}</span>
                        <span className="ml-auto font-mono">{(Number(sc.SIMILARITY_SCORE) * 100).toFixed(0)}%類似</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={relationshipOpen} onOpenChange={setRelationshipOpen}>
        <DialogContent className="sm:max-w-xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Users className="h-4 w-4" />
              上司との関係性分析 — {emp.LAST_NAME}{emp.FIRST_NAME}
            </DialogTitle>
            <DialogDescription>LightGBMモデル (RMSE={ML_MODEL_METRICS.RELATIONSHIP_RMSE}) による予測根拠</DialogDescription>
          </DialogHeader>
          {mlInsights?.relationship && (
            <div className="space-y-4">
              <div className="flex items-center gap-3">
                <span className="text-3xl font-bold font-mono">{(Number(mlInsights.relationship.RELATIONSHIP_SCORE) * 100).toFixed(0)}%</span>
                <Badge variant={relLabel === "良好" ? "default" : relLabel === "要改善" ? "destructive" : "secondary"} className="text-sm">
                  {relLabel}
                </Badge>
              </div>
              <p className="text-sm text-muted-foreground">
                上司: {mlInsights.relationship.MANAGER_NAME}
                {emp?.MANAGER_NAME && mlInsights.relationship.MANAGER_NAME !== emp.MANAGER_NAME && (
                  <span className="text-xs text-amber-600 ml-1">（分析時点 ※現上司: {emp.MANAGER_NAME}）</span>
                )}
              </p>

              {mlInsights.relationshipEvidence?.ai_summary && (
                <div className="p-3 rounded-lg bg-muted/50 border">
                  <p className="text-xs font-medium text-muted-foreground mb-1 flex items-center gap-1">
                    <Brain className="h-3 w-3" />AI分析サマリー
                  </p>
                  <div className="text-sm leading-relaxed prose prose-sm max-w-none prose-headings:text-base prose-headings:mt-2 prose-headings:mb-1">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{mlInsights.relationshipEvidence.ai_summary}</ReactMarkdown>
                  </div>
                </div>
              )}

              {mlInsights.relationshipShap?.length > 0 && (
                <div>
                  <p className="text-sm font-medium mb-2">SHAP特徴量重要度（関係性への寄与）</p>
                  <div className="space-y-2">
                    {mlInsights.relationshipShap.map((sf, i) => (
                      <div key={i} className="space-y-0.5">
                        <div className="flex items-center justify-between text-xs">
                          <span className="group relative cursor-help">
                            {FEATURE_LABELS[sf.FEATURE_NAME] || sf.FEATURE_NAME}
                            {FEATURE_DESCRIPTIONS[sf.FEATURE_NAME] && (
                              <span className="invisible group-hover:visible absolute left-0 bottom-full mb-1 w-64 p-2 rounded-md bg-popover text-popover-foreground text-[11px] leading-relaxed shadow-lg border z-50">
                                {FEATURE_DESCRIPTIONS[sf.FEATURE_NAME]}
                              </span>
                            )}
                          </span>
                          <div className="flex items-center gap-2">
                            <span className="text-muted-foreground">値: {typeof sf.FEATURE_VALUE === "number" ? sf.FEATURE_VALUE.toFixed(2) : isNaN(Number(sf.FEATURE_VALUE)) ? sf.FEATURE_VALUE : Number(sf.FEATURE_VALUE).toFixed(2)}</span>
                            <span className={`font-mono font-medium ${Number(sf.SHAP_VALUE) > 0 ? "text-green-600" : "text-red-600"}`}>
                              {Number(sf.SHAP_VALUE) > 0 ? "+" : ""}{Number(sf.SHAP_VALUE).toFixed(4)}
                            </span>
                          </div>
                        </div>
                        {renderShapBar(Number(sf.SHAP_VALUE), maxRelShapAbs, true)}
                      </div>
                    ))}
                  </div>
                  <p className="text-[10px] text-muted-foreground mt-2">緑=関係性向上方向 / 赤=関係性悪化方向</p>
                </div>
              )}

              {mlInsights.relationshipEvidence?.shap_factors && mlInsights.relationshipShap?.length === 0 && (
                <div>
                  <p className="text-sm font-medium mb-2">要因分析（Evidence Store）</p>
                  <div className="space-y-1.5">
                    {mlInsights.relationshipEvidence.shap_factors.map((sf, i) => (
                      <div key={i} className="flex items-center justify-between text-xs p-1.5 rounded border">
                        <span>{FEATURE_LABELS[sf.feature] || sf.feature}</span>
                        <div className="flex items-center gap-2">
                          <span className="text-muted-foreground">値: {sf.value}</span>
                          <span className={`font-mono font-medium ${Number(sf.shap) > 0 ? "text-green-600" : "text-red-600"}`}>
                            {Number(sf.shap) > 0 ? "+" : ""}{Number(sf.shap).toFixed(4)}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={transferFitOpen} onOpenChange={setTransferFitOpen}>
        <DialogContent className="sm:max-w-xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <ArrowRightLeft className="h-4 w-4" />
              配置適合分析 — {emp.LAST_NAME}{emp.FIRST_NAME}
            </DialogTitle>
            <DialogDescription>XGBoostモデル (RMSE={ML_MODEL_METRICS.TRANSFER_FIT_RMSE}) による適合度予測</DialogDescription>
          </DialogHeader>
          {mlInsights?.transferFit?.length > 0 && (
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">
                現在の配属: {emp.DEPT_NAME} / {emp.POSITION_TITLE}
              </p>
              <div className="space-y-3">
                {mlInsights.transferFit.map((tf, i) => (
                  <div key={i} className="p-3 rounded-lg border space-y-2">
                    <div className="flex items-center gap-2">
                      <Badge variant="outline" className="font-mono shrink-0">
                        #{i + 1}
                      </Badge>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium truncate">{tf.TARGET_POSITION_TITLE}</p>
                        <p className="text-xs text-muted-foreground">{tf.TARGET_DEPT_NAME}</p>
                      </div>
                      <span className="text-lg font-bold font-mono shrink-0">{(Number(tf.FIT_SCORE) * 100).toFixed(0)}%</span>
                    </div>
                    <Progress value={Number(tf.FIT_SCORE) * 100} className="h-1.5" />
                    <Link href={`/simulation?employee=${emp.EMPLOYEE_ID}`}>
                      <Button variant="ghost" size="sm" className="text-xs text-blue-600 gap-1 p-0 h-auto">
                        <ArrowRightLeft className="h-3 w-3" /> この社員で異動シミュレーション →
                      </Button>
                    </Link>
                  </div>
                ))}
              </div>
              <div className="p-3 rounded-lg bg-muted/50 border">
                <p className="text-xs text-muted-foreground">
                  配置適合スコアは、スキルマッチ度・評価履歴・勤続年数・部署カルチャーベクトルなどを総合的に分析し算出しています。
                  スコアが高いほど、その配属先でのパフォーマンス発揮が見込まれます。
                </p>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      <div className="grid grid-cols-3 gap-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">基本情報</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            {editing ? (
              <div className="space-y-3 text-sm">
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <span className="text-xs text-muted-foreground">姓</span>
                    <Input value={editForm.LAST_NAME as string} onChange={(e) => setEditForm({...editForm, LAST_NAME: e.target.value})} className="h-8" />
                  </div>
                  <div>
                    <span className="text-xs text-muted-foreground">名</span>
                    <Input value={editForm.FIRST_NAME as string} onChange={(e) => setEditForm({...editForm, FIRST_NAME: e.target.value})} className="h-8" />
                  </div>
                </div>
                <div>
                  <span className="text-xs text-muted-foreground">メール</span>
                  <Input value={editForm.EMAIL as string} onChange={(e) => setEditForm({...editForm, EMAIL: e.target.value})} className="h-8" />
                </div>
                <div>
                  <span className="text-xs text-muted-foreground">性別</span>
                  <Select value={editForm.GENDER as string} onValueChange={(v) => setEditForm({...editForm, GENDER: v})}>
                    <SelectTrigger className="h-8"><SelectValue>{({ M: "男性", F: "女性" } as Record<string, string>)[editForm.GENDER as string] ?? "選択"}</SelectValue></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="M">男性</SelectItem>
                      <SelectItem value="F">女性</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <span className="text-xs text-muted-foreground">給与</span>
                  <Input type="number" value={String(editForm.SALARY || "")} onChange={(e) => setEditForm({...editForm, SALARY: Number(e.target.value)})} className="h-8" />
                </div>
                <Separator />
                <div>
                  <span className="text-xs text-muted-foreground">ステータス</span>
                  <Select value={editForm.STATUS as string} onValueChange={(v) => setEditForm({...editForm, STATUS: v})}>
                    <SelectTrigger className="h-8"><SelectValue>{({ active: "在籍", inactive: "退職", leave: "休職" } as Record<string, string>)[editForm.STATUS as string] ?? "選択"}</SelectValue></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="active">在籍</SelectItem>
                      <SelectItem value="inactive">退職</SelectItem>
                      <SelectItem value="leave">休職</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <span className="text-xs text-muted-foreground">変更理由（異動履歴に記録）</span>
                  <Input value={editForm._transferReason as string} onChange={(e) => setEditForm({...editForm, _transferReason: e.target.value})} className="h-8" placeholder="例: 組織改編に伴う異動" />
                </div>
              </div>
            ) : (
              <>
            <div className="flex items-center gap-2">
              <Building className="h-4 w-4 text-muted-foreground" />
              <span className="text-muted-foreground">部署:</span>
              <span>{emp.DEPT_NAME}</span>
            </div>
            <div className="flex items-center gap-2">
              <Briefcase className="h-4 w-4 text-muted-foreground" />
              <span className="text-muted-foreground">役職:</span>
              <span>{emp.POSITION_TITLE}</span>
            </div>
            <div className="flex items-center gap-2">
              <Mail className="h-4 w-4 text-muted-foreground" />
              <span className="text-muted-foreground">Email:</span>
              <span className="truncate">{emp.EMAIL || "***"}</span>
            </div>
            <div className="flex items-center gap-2">
              <Calendar className="h-4 w-4 text-muted-foreground" />
              <span className="text-muted-foreground">入社:</span>
              <span>{emp.HIRE_DATE?.slice(0, 10)} ({tenure}年目)</span>
            </div>
            <Separator />
            <div className="flex justify-between">
              <span className="text-muted-foreground">年齢</span>
              <span>{age}歳 ({emp.GENDER === "M" ? "男性" : "女性"})</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">給与</span>
              <span className="font-mono">{formatSalary(emp.SALARY)}</span>
            </div>
            {emp.MANAGER_NAME && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">上司</span>
                <span>{emp.MANAGER_NAME}</span>
              </div>
            )}
              </>
            )}
          </CardContent>
        </Card>

        <Card className="col-span-2">
          <Tabs defaultValue="evaluations">
            <CardHeader className="pb-2">
              <TabsList>
                <TabsTrigger value="evaluations">評価履歴</TabsTrigger>
                <TabsTrigger value="career">異動履歴</TabsTrigger>
                <TabsTrigger value="skills">スキル</TabsTrigger>
                <TabsTrigger value="notes">1on1メモ</TabsTrigger>
              </TabsList>
            </CardHeader>
            <CardContent>
              <TabsContent value="evaluations" className="mt-0 space-y-4">
                {evalChartData.length > 0 && (
                  <ResponsiveContainer width="100%" height={180}>
                    <LineChart data={evalChartData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="period" tick={{ fontSize: 11 }} />
                      <YAxis domain={[1, 5]} tick={{ fontSize: 11 }} />
                      <Tooltip />
                      <Line type="monotone" dataKey="score" stroke="var(--color-chart-1)" strokeWidth={2} dot={{ r: 4, fill: "var(--color-chart-1)" }} />
                    </LineChart>
                  </ResponsiveContainer>
                )}
                <div className="space-y-2">
                  {evaluations.map((ev) => (
                    <div key={ev.EVALUATION_ID} className="p-3 rounded-lg border">
                      <div className="flex items-center gap-2 mb-1">
                        <Badge variant={ev.GRADE === "S" ? "destructive" : ev.GRADE === "A" ? "default" : "secondary"}>
                          {ev.GRADE}
                        </Badge>
                        <span className="text-sm font-medium">{ev.PERIOD}</span>
                        <span className="text-sm font-mono ml-auto">{ev.SCORE != null ? Number(ev.SCORE).toFixed(1) : '—'}</span>
                      </div>
                      <p className="text-sm text-muted-foreground">{ev.COMMENT || "—"}</p>
                    </div>
                  ))}
                  {evaluations.length === 0 && (
                    <p className="text-sm text-muted-foreground text-center py-8">評価データなし</p>
                  )}
                </div>
              </TabsContent>

              <TabsContent value="career" className="mt-0">
                {careerHistory && careerHistory.length > 0 ? (
                  <div className="relative ml-4 border-l-2 border-muted-foreground/20 space-y-0">
                    {careerHistory.map((ch, i) => {
                      const typeLabel: Record<string, string> = { hire: "入社", promotion: "昇進", lateral: "異動", demotion: "降格", transfer: "転籍" };
                      const typeColor: Record<string, string> = { hire: "bg-green-100 text-green-800", promotion: "bg-blue-100 text-blue-800", lateral: "bg-amber-100 text-amber-800", demotion: "bg-red-100 text-red-800", transfer: "bg-purple-100 text-purple-800" };
                      return (
                        <div key={ch.HISTORY_ID} className="relative pl-6 pb-4">
                          <div className={`absolute -left-[9px] top-1 h-4 w-4 rounded-full border-2 border-background ${i === 0 ? "bg-primary" : "bg-muted-foreground/30"}`} />
                          <div className="p-3 rounded-lg border">
                            <div className="flex items-center gap-2 mb-1">
                              <Badge className={`text-[10px] ${typeColor[ch.TRANSFER_TYPE] || "bg-gray-100 text-gray-700"}`}>
                                {typeLabel[ch.TRANSFER_TYPE] || ch.TRANSFER_TYPE}
                              </Badge>
                              <span className="text-xs text-muted-foreground">
                                {ch.START_DATE?.slice(0, 10)}{ch.END_DATE ? ` → ${ch.END_DATE.slice(0, 10)}` : " → 現在"}
                              </span>
                              {ch.PERFORMANCE_AFTER != null && (
                                <Badge variant="outline" className="text-[10px] ml-auto">
                                  異動後評価: {Number(ch.PERFORMANCE_AFTER).toFixed(1)}
                                </Badge>
                              )}
                            </div>
                            <p className="text-sm font-medium">{ch.DEPT_NAME}{ch.POSITION_TITLE ? ` / ${ch.POSITION_TITLE}` : ""}</p>
                            {ch.REASON && <p className="text-xs text-muted-foreground mt-1">{ch.REASON}</p>}
                            {ch.MANAGER_NAME && <p className="text-[11px] text-muted-foreground">上司: {ch.MANAGER_NAME}</p>}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground text-center py-8">異動履歴なし</p>
                )}
              </TabsContent>

              <TabsContent value="skills" className="mt-0">
                <div className="flex justify-end mb-2">
                  <Link href={`/employees/${emp.EMPLOYEE_ID}/skills`}>
                    <Button variant="outline" size="sm" className="gap-1.5 text-xs">
                      <Pencil className="h-3.5 w-3.5" />
                      スキル管理
                    </Button>
                  </Link>
                </div>
                {skills.length > 0 ? (
                  <div className="space-y-3">
                    {skills.map((s, i) => (
                      <div key={i}>
                        <div className="flex items-center justify-between mb-1">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-medium">{s.SKILL_NAME}</span>
                            <Badge variant="outline" className="text-[10px]">
                              {CATEGORY_LABELS[s.CATEGORY] || s.CATEGORY}
                            </Badge>
                          </div>
                          <span className="text-xs text-muted-foreground">Lv.{s.PROFICIENCY}</span>
                        </div>
                        <Progress value={s.PROFICIENCY * 20} className="h-2" />
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground text-center py-8">スキルデータなし</p>
                )}
              </TabsContent>

              <TabsContent value="notes" className="mt-0">
                <div className="flex justify-end mb-2">
                  <Link href={`/employees/${emp.EMPLOYEE_ID}/notes`}>
                    <Button variant="outline" size="sm" className="gap-1.5 text-xs">
                      <Pencil className="h-3.5 w-3.5" />
                      メモ管理
                    </Button>
                  </Link>
                </div>
                {notes.length > 0 ? (
                  <div className="space-y-2">
                    {notes.map((n) => (
                      <div key={n.NOTE_ID} className="p-3 rounded-lg border">
                        <div className="flex items-center gap-2 mb-1">
                          <Badge className={`text-[10px] ${CATEGORY_COLORS[n.CATEGORY] || ""}`}>
                            {CATEGORY_LABELS[n.CATEGORY] || n.CATEGORY}
                          </Badge>
                          <span className="text-xs text-muted-foreground">{n.NOTE_DATE?.slice(0, 10)}</span>
                        </div>
                        <p className="text-sm">{n.CONTENT}</p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground text-center py-8">1on1メモなし</p>
                )}
              </TabsContent>
            </CardContent>
          </Tabs>
        </Card>
      </div>

      {orgChart && (orgChart.deptColleagues?.length > 0 || Object.keys(subDeptGroups).length > 0) && (
        <Card>
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-base flex items-center gap-2">
                <Building className="h-4 w-4" />
                {emp.DEPT_NAME} 組織図
              </CardTitle>
              <div className="flex items-center gap-1 border rounded-md p-0.5">
                <button
                  onClick={() => setOrgViewMode("list")}
                  className={`inline-flex items-center gap-1 px-2 py-1 rounded text-xs transition-colors ${orgViewMode === "list" ? "bg-primary text-primary-foreground" : "hover:bg-accent"}`}
                >
                  <List className="h-3 w-3" />
                  リスト
                </button>
                <button
                  onClick={() => setOrgViewMode("tree")}
                  className={`inline-flex items-center gap-1 px-2 py-1 rounded text-xs transition-colors ${orgViewMode === "tree" ? "bg-primary text-primary-foreground" : "hover:bg-accent"}`}
                >
                  <GitBranch className="h-3 w-3" />
                  ツリー
                </button>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            {orgViewMode === "list" ? (
              <div className="space-y-4">
                {orgChart.deptColleagues?.length > 0 && (
                  <div>
                    <p className="text-xs font-medium text-muted-foreground mb-2">{emp.DEPT_NAME}（{orgChart.deptColleagues.length}名）</p>
                    <div className="flex flex-wrap gap-1.5">
                      {orgChart.deptColleagues.map((m) => (
                        <Link
                          key={m.EMPLOYEE_ID}
                          href={`/employees/${m.EMPLOYEE_ID}`}
                          className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-md border text-xs hover:bg-accent transition-colors ${m.EMPLOYEE_ID === emp.EMPLOYEE_ID ? "ring-2 ring-primary bg-primary/5" : ""}`}
                        >
                          <Badge className={`text-[9px] px-1 py-0 ${GRADE_COLORS[m.GRADE] || "bg-gray-100 text-gray-700"}`}>
                            {m.GRADE}
                          </Badge>
                          <span className="font-medium">{m.NAME}</span>
                          <span className="text-muted-foreground text-[10px]">{m.TITLE}</span>
                        </Link>
                      ))}
                    </div>
                  </div>
                )}

                {Object.entries(subDeptGroups).map(([deptName, members]) => (
                  <div key={deptName}>
                    <p className="text-xs font-medium text-muted-foreground mb-2">└ {deptName}（{members.length}名）</p>
                    <div className="flex flex-wrap gap-1.5 ml-4">
                      {members.map((m) => (
                        <Link
                          key={m.EMPLOYEE_ID}
                          href={`/employees/${m.EMPLOYEE_ID}`}
                          className="inline-flex items-center gap-1.5 px-2 py-1 rounded-md border text-xs hover:bg-accent transition-colors"
                        >
                          <Badge className={`text-[9px] px-1 py-0 ${GRADE_COLORS[m.GRADE] || "bg-gray-100 text-gray-700"}`}>
                            {m.GRADE}
                          </Badge>
                          <span className="font-medium">{m.NAME}</span>
                          <span className="text-muted-foreground text-[10px]">{m.TITLE}</span>
                        </Link>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="space-y-1 overflow-x-auto">
                {orgTree.length > 0 ? (
                  orgTree.map((root, i) => renderTreeNode(root, i === orgTree.length - 1, 0))
                ) : (
                  <p className="text-sm text-muted-foreground text-center py-4">ツリー構造を構築できません</p>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
