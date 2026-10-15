"use client";

import { useEffect, useState, useCallback, useRef, useMemo, Suspense } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Progress } from "@/components/ui/progress";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import {
  ArrowDown, Loader2, RotateCcw, Building2, Users,
  ChevronRight, CheckCircle2, Save, UserMinus, ArrowRightLeft,
  Briefcase, Search, Target, ArrowRight, CircleDot, Circle,
  Undo2, X, Sparkles, FolderOpen, Send, Archive,
} from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { GRADE_LABELS } from "@/lib/types";
import { Input } from "@/components/ui/input";

interface TriggerEvent {
  TRIGGER_TYPE: string;
  EVENT_ID: number;
  EMPLOYEE_ID: number;
  NAME: string;
  EMPLOYEE_CODE: string;
  GRADE: string;
  POSITION_TITLE: string;
  DEPT_ID: number;
  DEPT_NAME: string;
  TO_DEPT_ID: number | null;
  TO_DEPT_NAME: string | null;
  REASON: string;
  STATUS: string;
  EVENT_DATE: string | null;
}

interface OrgMember {
  EMPLOYEE_ID: number;
  NAME: string;
  EMPLOYEE_CODE: string;
  GRADE: string;
  POSITION_TITLE: string;
  MANAGER_ID: number | null;
  STATUS: string;
  AVG_EVAL: number;
  TENURE: number;
}

interface Candidate {
  EMPLOYEE_ID: number;
  NAME: string;
  DEPT_ID: number;
  DEPT_NAME: string;
  GRADE: string;
  POSITION_TITLE: string;
  AVG_EVAL: number;
  TENURE: number;
  SKILL_MATCH: number;
  COMPOSITE_SCORE: number;
}

interface MatchDetail {
  matchScore: number;
  skillScore: number;
  evalScore: number;
  tenureScore: number;
  matchedSkills: string[];
  missingSkills: string[];
  reason: string;
}

interface EmpDetail {
  employee: Record<string, unknown>;
  skills: { SKILL_NAME: string; CATEGORY: string; PROFICIENCY: number }[];
  evaluations: { PERIOD: string; SCORE: number; GRADE: string; COMMENT: string }[];
  mlInsights: {
    attrition: { RISK_SCORE: number; RISK_LABEL: string } | null;
    relationship: { RELATIONSHIP_SCORE: number; MANAGER_NAME: string } | null;
  };
}

interface ChainStep {
  id: string;
  vacantDeptId: number;
  vacantDeptName: string;
  vacantGrade: string;
  orgMembers: OrgMember[];
  candidates: Candidate[];
  selectedCandidate: Candidate | null;
  matchDetail: MatchDetail | null;
  confirmed: boolean;
  loading: boolean;
  candidatesLoading: boolean;
  matchLoading: boolean;
}

const GRADE_BG: Record<string, string> = {
  E1: "bg-purple-100 text-purple-800", D1: "bg-indigo-100 text-indigo-800",
  D2: "bg-blue-100 text-blue-800", M1: "bg-cyan-100 text-cyan-800",
  M2: "bg-teal-100 text-teal-800", S1: "bg-green-100 text-green-800",
  S2: "bg-lime-100 text-lime-800", J1: "bg-amber-100 text-amber-800",
  J2: "bg-orange-100 text-orange-800", J3: "bg-gray-100 text-gray-700",
};

function scoreColor(score: number): string {
  if (score >= 70) return "text-green-700 bg-green-100 border-green-300";
  if (score >= 40) return "text-amber-700 bg-amber-100 border-amber-300";
  return "text-red-700 bg-red-100 border-red-300";
}

function ChainSimulationPageInner() {
  const searchParams = useSearchParams();
  const [triggers, setTriggers] = useState<TriggerEvent[]>([]);
  const [triggersLoading, setTriggersLoading] = useState(true);
  const [filterType, setFilterType] = useState<string>("all");
  const [searchText, setSearchText] = useState("");
  const [selectedTrigger, setSelectedTrigger] = useState<TriggerEvent | null>(null);
  const [chain, setChain] = useState<ChainStep[]>([]);
  const [empModalOpen, setEmpModalOpen] = useState(false);
  const [empModalData, setEmpModalData] = useState<EmpDetail | null>(null);
  const [empModalLoading, setEmpModalLoading] = useState(false);
  const [empModalCandidateIdx, setEmpModalCandidateIdx] = useState<{ stepIdx: number; candidate: Candidate } | null>(null);
  const [targetModalData, setTargetModalData] = useState<EmpDetail | null>(null);
  const [targetModalLoading, setTargetModalLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [savedSimId, setSavedSimId] = useState<number | null>(null);
  const [submitLoading, setSubmitLoading] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [chainListOpen, setChainListOpen] = useState(false);
  const [chainList, setChainList] = useState<{simulation_id: number; simulation_name: string; trigger_type: string; status: string; step_count: number; rejected_count: number}[]>([]);
  const [chainListLoading, setChainListLoading] = useState(false);
  const [loadedSimId, setLoadedSimId] = useState<number | null>(null);
  const [loadedSimStatus, setLoadedSimStatus] = useState<string | null>(null);
  const [loadedSimName, setLoadedSimName] = useState<string | null>(null);
  const [confirmDialogOpen, setConfirmDialogOpen] = useState(false);
  const [confirmLabel, setConfirmLabel] = useState("");
  const [confirmDate, setConfirmDate] = useState("");
  const [confirmLoading, setConfirmLoading] = useState(false);
  const [aiComment, setAiComment] = useState<string | null>(null);
  const [aiCommentLoading, setAiCommentLoading] = useState(false);
  const [candidateSearch, setCandidateSearch] = useState<Record<string, string>>({});

  const chainRef = useRef(chain);
  chainRef.current = chain;

  useEffect(() => {
    fetch("/api/chain-simulation/triggers")
      .then((r) => r.ok ? r.json() : [])
      .then(setTriggers)
      .finally(() => setTriggersLoading(false));
  }, []);

  useEffect(() => {
    const loadId = searchParams.get("load");
    if (loadId) {
      setLoadedSimId(Number(loadId));
      fetch(`/api/chain-simulation/${loadId}`)
        .then((r) => r.ok ? r.json() : null)
        .then((data) => {
          if (data) {
            setLoadedSimStatus(data.simulation.status);
            setLoadedSimName(data.simulation.simulation_name);
          }
        })
        .catch((err) => console.error("[chain simulation status fetch] failed:", err));
    }
  }, [searchParams]);

  const filteredTriggers = useMemo(() => triggers.filter((t) => {
    if (filterType !== "all" && t.TRIGGER_TYPE !== filterType) return false;
    if (searchText && !t.NAME.includes(searchText) && !t.DEPT_NAME.includes(searchText) && !t.EMPLOYEE_CODE.includes(searchText)) return false;
    return true;
  }), [triggers, filterType, searchText]);

  const fetchOrg = useCallback(async (deptId: number): Promise<{ members: OrgMember[]; deptName: string }> => {
    try {
      const res = await fetch(`/api/chain-simulation/org?dept_id=${deptId}`);
      if (!res.ok) return { members: [], deptName: "" };
      const data = await res.json();
      return { members: data.members || [], deptName: data.department?.DEPT_NAME || "" };
    } catch { return { members: [], deptName: "" }; }
  }, []);

  // すでにチェーン内で動かした社員（起点の本人を含む）は候補から外す。
  // 外さないと同じ人が二度動いたり、A→Bの席・B→Aの席という循環が作れてしまう。
  const fetchCandidates = useCallback(async (deptId: number, grade: string, excludeIds: Set<number>): Promise<Candidate[]> => {
    try {
      // 除外で件数が減るため多めに取ってから10件に絞る
      const res = await fetch(`/api/simulation/candidates?dept_id=${deptId}&grade=${grade}&limit=${10 + excludeIds.size}`);
      if (!res.ok) return [];
      const list: Candidate[] = await res.json();
      return list.filter((c) => !excludeIds.has(c.EMPLOYEE_ID)).slice(0, 10);
    } catch { return []; }
  }, []);

  const fetchMatch = useCallback(async (empId: number, deptId: number): Promise<MatchDetail | null> => {
    try {
      const res = await fetch(`/api/simulation/match?employee_id=${empId}&to_dept_id=${deptId}`);
      if (!res.ok) return null;
      return await res.json();
    } catch { return null; }
  }, []);

  const fetchEmpDetail = useCallback(async (empId: number): Promise<EmpDetail | null> => {
    try {
      const res = await fetch(`/api/employees/${empId}`);
      if (!res.ok) return null;
      return await res.json();
    } catch { return null; }
  }, []);

  const selectTrigger = async (trigger: TriggerEvent) => {
    setSelectedTrigger(trigger);
    setSaved(false);

    const step: ChainStep = {
      id: "step-0",
      vacantDeptId: trigger.DEPT_ID,
      vacantDeptName: trigger.DEPT_NAME,
      vacantGrade: trigger.GRADE || "M2",
      orgMembers: [],
      candidates: [],
      selectedCandidate: null,
      matchDetail: null,
      confirmed: false,
      loading: true,
      candidatesLoading: false,
      matchLoading: false,
    };
    setChain([step]);

    const { members } = await fetchOrg(trigger.DEPT_ID);
    const candidates = await fetchCandidates(trigger.DEPT_ID, trigger.GRADE || "M2", new Set([trigger.EMPLOYEE_ID]));
    setChain([{
      ...step,
      orgMembers: members,
      candidates,
      loading: false,
    }]);
  };

  const getTargetEmployeeId = (stepIdx: number): number | null => {
    if (stepIdx === 0) return selectedTrigger?.EMPLOYEE_ID ?? null;
    const prevStep = chainRef.current[stepIdx - 1];
    return prevStep?.selectedCandidate?.EMPLOYEE_ID ?? null;
  };

  const handleAiComment = useCallback(async () => {
    if (!empModalCandidateIdx) return;
    const { stepIdx, candidate } = empModalCandidateIdx;
    const step = chainRef.current[stepIdx];
    if (!step) return;
    setAiCommentLoading(true);
    setAiComment(null);
    try {
      const targetId = getTargetEmployeeId(stepIdx);
      const res = await fetch("/api/chain-simulation/ai-comment", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          targetEmployeeId: targetId,
          candidateEmployeeId: candidate.EMPLOYEE_ID,
          vacantDeptId: step.vacantDeptId,
          vacantGrade: step.vacantGrade,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "API error");
      setAiComment(data.comment || "コメントを取得できませんでした。");
    } catch {
      setAiComment("AI評価の取得に失敗しました。");
    } finally {
      setAiCommentLoading(false);
    }
  }, [empModalCandidateIdx]);

  const openCandidateModal = async (stepIdx: number, candidate: Candidate) => {
    setEmpModalCandidateIdx({ stepIdx, candidate });
    setEmpModalOpen(true);
    setAiComment(null);
    setAiCommentLoading(false);
    setEmpModalLoading(true);
    setEmpModalData(null);
    setTargetModalData(null);
    setTargetModalLoading(true);

    const targetId = getTargetEmployeeId(stepIdx);
    const [candidateData, targetData] = await Promise.all([
      fetchEmpDetail(candidate.EMPLOYEE_ID),
      targetId ? fetchEmpDetail(targetId) : Promise.resolve(null),
    ]);
    setEmpModalData(candidateData);
    setEmpModalLoading(false);
    setTargetModalData(targetData);
    setTargetModalLoading(false);
  };

  const selectCandidateFromModal = () => {
    if (!empModalCandidateIdx) return;
    const { stepIdx, candidate } = empModalCandidateIdx;
    setEmpModalOpen(false);

    const current = chainRef.current;
    const step = current[stepIdx];
    if (!step) return;

    const updated = { ...step, selectedCandidate: candidate, matchDetail: null, matchLoading: false };
    setChain([...current.slice(0, stepIdx), updated]);
  };

  const analyzeMatch = async (stepIdx: number) => {
    const current = chainRef.current;
    const step = current[stepIdx];
    if (!step?.selectedCandidate) return;

    setChain((prev) => {
      const copy = [...prev];
      if (copy[stepIdx]) copy[stepIdx] = { ...copy[stepIdx], matchLoading: true };
      return copy;
    });

    const detail = await fetchMatch(step.selectedCandidate.EMPLOYEE_ID, step.vacantDeptId);
    setChain((prev) => {
      const copy = [...prev];
      if (copy[stepIdx]) {
        copy[stepIdx] = { ...copy[stepIdx], matchDetail: detail, matchLoading: false };
      }
      return copy;
    });
  };

  const confirmStep = async (stepIdx: number) => {
    const current = chainRef.current;
    const step = current[stepIdx];
    if (!step?.selectedCandidate) return;

    const candidate = step.selectedCandidate;
    const updated = [...current];
    updated[stepIdx] = { ...step, confirmed: true };

    const nextStep: ChainStep = {
      id: `step-${stepIdx + 1}`,
      vacantDeptId: candidate.DEPT_ID,
      vacantDeptName: candidate.DEPT_NAME,
      vacantGrade: candidate.GRADE,
      orgMembers: [],
      candidates: [],
      selectedCandidate: null,
      matchDetail: null,
      confirmed: false,
      loading: true,
      candidatesLoading: false,
      matchLoading: false,
    };
    updated.push(nextStep);
    setChain(updated);

    const { members } = await fetchOrg(candidate.DEPT_ID);
    const moved = new Set<number>([
      ...(selectedTrigger ? [selectedTrigger.EMPLOYEE_ID] : []),
      ...updated.flatMap((st) => (st.selectedCandidate ? [st.selectedCandidate.EMPLOYEE_ID] : [])),
    ]);
    const candidates = await fetchCandidates(candidate.DEPT_ID, candidate.GRADE, moved);
    setChain((prev) => {
      const copy = [...prev];
      if (copy[stepIdx + 1]) {
        copy[stepIdx + 1] = { ...copy[stepIdx + 1], orgMembers: members, candidates, loading: false };
      }
      return copy;
    });
  };

  const removeLastStep = () => {
    setChain((prev) => {
      if (prev.length <= 1) return prev;
      const copy = [...prev];
      copy.pop();
      const lastIdx = copy.length - 1;
      copy[lastIdx] = { ...copy[lastIdx], confirmed: false };
      return copy;
    });
  };

  const saveChain = async () => {
    if (!selectedTrigger) return;
    const confirmedSteps = chain.filter((s) => s.confirmed && s.selectedCandidate);
    if (confirmedSteps.length === 0) return;

    setSaving(true);
    try {
      const res = await fetch("/api/chain-simulation/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          triggerType: selectedTrigger.TRIGGER_TYPE,
          triggerEmployeeId: selectedTrigger.EMPLOYEE_ID,
          triggerDeptId: selectedTrigger.DEPT_ID,
          triggerGrade: selectedTrigger.GRADE || "M2",
          steps: confirmedSteps.map((s) => ({
            vacantDeptId: s.vacantDeptId,
            vacantGrade: s.vacantGrade,
            selectedEmployeeId: s.selectedCandidate!.EMPLOYEE_ID,
            fromDeptId: s.selectedCandidate!.DEPT_ID,
            fromGrade: s.selectedCandidate!.GRADE,
            matchScore: s.matchDetail?.matchScore || null,
            matchReason: s.matchDetail?.reason || null,
          })),
        }),
      });
      if (res.ok) {
        const data = await res.json();
        setSaved(true);
        setSavedSimId(data.simulationId);
        setSaveError(null);
      } else {
        setSaveError("保存に失敗しました");
      }
    } catch {
      setSaveError("ネットワークエラー: 保存に失敗しました");
    } finally {
      setSaving(false);
    }
  };

  const loadChainList = useCallback(async () => {
    setChainListLoading(true);
    try {
      const res = await fetch("/api/chain-simulation/list");
      if (res.ok) setChainList(await res.json());
    } finally {
      setChainListLoading(false);
    }
  }, []);

  const resetAll = () => {
    setSelectedTrigger(null);
    setChain([]);
    setSaved(false);
    setSavedSimId(null);
    setSubmitted(false);
    setLoadedSimId(null);
    setLoadedSimStatus(null);
    setLoadedSimName(null);
  };

  const confirmedCount = chain.filter((s) => s.confirmed).length;
  const allConfirmed = chain.length > 1 && chain.slice(0, -1).every((s) => s.confirmed);
  const activeStepIdx = chain.findIndex((s) => !s.confirmed);

  if (triggersLoading) {
    return (
      <div className="p-6 space-y-4">
        <h2 className="text-2xl font-bold">玉突き人事シミュレーション</h2>
        <Skeleton className="h-[600px]" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-4 h-full flex flex-col">
      <div className="flex items-center gap-3 shrink-0">
        <h2 className="text-2xl font-bold tracking-tight">玉突き人事シミュレーション</h2>
        {selectedTrigger && (
          <Button variant="outline" size="sm" onClick={resetAll}>
            <RotateCcw className="h-3.5 w-3.5 mr-1" />
            リセット
          </Button>
        )}
        <div className="ml-auto">
          <Button variant="outline" size="sm" className="gap-1.5" onClick={() => { setChainListOpen(true); loadChainList(); }}>
            <FolderOpen className="h-3.5 w-3.5" />
            保存済みチェーン
          </Button>
        </div>
      </div>

      {loadedSimId && loadedSimStatus && (
        <div className={`flex items-center gap-3 px-4 py-2 rounded-lg border text-sm ${
          loadedSimStatus === "revision_requested" ? "bg-red-50 border-red-200" :
          loadedSimStatus === "approved" ? "bg-green-50 border-green-200" :
          loadedSimStatus === "pending_review" ? "bg-yellow-50 border-yellow-200" : "bg-muted/50"
        }`}>
          <span className="font-medium truncate">{loadedSimName}</span>
          <Badge variant="secondary" className={`text-[10px] shrink-0 ${
            loadedSimStatus === "pending_review" ? "bg-yellow-100 text-yellow-700" :
            loadedSimStatus === "revision_requested" ? "bg-red-100 text-red-700" :
            loadedSimStatus === "approved" ? "bg-green-100 text-green-700" : ""
          }`}>
            {loadedSimStatus === "draft" ? "下書き" : loadedSimStatus === "pending_review" ? "レビュー待ち" :
             loadedSimStatus === "revision_requested" ? "差し戻しあり" : loadedSimStatus === "approved" ? "承認済み" : loadedSimStatus}
          </Badge>
          {loadedSimStatus === "pending_review" && (
            <Link href="/review" className="text-xs text-blue-600 hover:underline ml-auto">レビュー状況を見る →</Link>
          )}
          {loadedSimStatus === "approved" && (
            <Button size="sm" variant="default" className="ml-auto bg-green-600 hover:bg-green-700" onClick={() => {
              setConfirmLabel(loadedSimName || "");
              setConfirmDate(new Date().toISOString().slice(0, 10));
              setConfirmDialogOpen(true);
            }}>
              <Archive className="h-3.5 w-3.5 mr-1" />
              確定（スナップショット保存）
            </Button>
          )}
        </div>
      )}

      {!selectedTrigger ? (
        <Card className="flex-1 flex flex-col max-w-3xl">
          <CardHeader className="pb-2 shrink-0">
            <CardTitle className="text-sm flex items-center gap-2">
              <UserMinus className="h-4 w-4" />
              空席イベントを選択してシミュレーション開始
            </CardTitle>
            <div className="flex items-center gap-2 mt-2">
              <div className="flex gap-1">
                {["all", "transfer", "retirement"].map((t) => (
                  <Button
                    key={t}
                    variant={filterType === t ? "default" : "outline"}
                    size="sm"
                    className="text-xs h-7"
                    onClick={() => setFilterType(t)}
                  >
                    {t === "all" ? "全て" : t === "transfer" ? "異動" : "退職"}
                  </Button>
                ))}
              </div>
              <div className="relative flex-1 max-w-xs">
                <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                <input
                  type="text"
                  placeholder="社員名・部署名で検索..."
                  className="w-full pl-7 pr-2 py-1.5 text-xs border rounded-md"
                  value={searchText}
                  onChange={(e) => setSearchText(e.target.value)}
                />
              </div>
              <span className="text-xs text-muted-foreground">{filteredTriggers.length}件</span>
            </div>
          </CardHeader>
          <CardContent className="flex-1 p-0">
            <ScrollArea className="h-[calc(100vh-280px)]">
              <div className="p-3 space-y-1">
                {filteredTriggers.map((t) => (
                  <button
                    key={`${t.TRIGGER_TYPE}-${t.EVENT_ID}`}
                    className="w-full text-left p-2.5 rounded-lg border hover:bg-accent hover:shadow-sm transition-all group"
                    onClick={() => selectTrigger(t)}
                  >
                    <div className="flex items-center gap-2">
                      <Badge variant={t.TRIGGER_TYPE === "transfer" ? "default" : "destructive"} className="text-[10px] shrink-0">
                        {t.TRIGGER_TYPE === "transfer" ? "異動" : "退職"}
                      </Badge>
                      <Badge variant="outline" className={`text-[9px] shrink-0 ${GRADE_BG[t.GRADE] || ""}`}>
                        {t.GRADE}
                      </Badge>
                      <span className="font-medium text-sm">{t.NAME}</span>
                      <span className="text-xs text-muted-foreground">{t.EMPLOYEE_CODE}</span>
                      <span className="text-xs text-muted-foreground ml-auto">{t.DEPT_NAME}</span>
                      <ChevronRight className="h-3.5 w-3.5 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
                    </div>
                    {(t.TO_DEPT_NAME || t.POSITION_TITLE) && (
                      <div className="flex items-center gap-2 mt-0.5 text-[11px] text-muted-foreground ml-[4.5rem]">
                        {t.POSITION_TITLE && <span>{t.POSITION_TITLE}</span>}
                        {t.TO_DEPT_NAME && (
                          <>
                            <ArrowRightLeft className="h-3 w-3" />
                            <span>{t.TO_DEPT_NAME}へ</span>
                          </>
                        )}
                      </div>
                    )}
                  </button>
                ))}
                {filteredTriggers.length === 0 && (
                  <p className="text-sm text-muted-foreground text-center py-12">該当するイベントがありません</p>
                )}
              </div>
            </ScrollArea>
          </CardContent>
        </Card>
      ) : (
        <div className="flex-1 flex gap-4 min-h-0">
          <div className="flex-1 min-w-0 flex flex-col">
            <Card className="shrink-0 mb-3">
              <CardContent className="p-3">
                <div className="flex items-center gap-2 text-sm">
                  <Badge variant={selectedTrigger.TRIGGER_TYPE === "transfer" ? "default" : "destructive"} className="text-[10px]">
                    {selectedTrigger.TRIGGER_TYPE === "transfer" ? "異動" : "退職"}
                  </Badge>
                  <span className="font-medium">{selectedTrigger.NAME}</span>
                  <Badge variant="outline" className={`text-[9px] ${GRADE_BG[selectedTrigger.GRADE] || ""}`}>
                    {selectedTrigger.GRADE} {GRADE_LABELS[selectedTrigger.GRADE]}
                  </Badge>
                  <span className="text-muted-foreground text-xs">が {selectedTrigger.DEPT_NAME} から離脱</span>
                </div>
              </CardContent>
            </Card>

            <ScrollArea className="flex-1">
              <div className="space-y-3 pb-4 pr-1">
                {chain.map((step, idx) => {
                  const isActive = idx === activeStepIdx;
                  return (
                    <div key={step.id}>
                      {idx > 0 && (
                        <div className="flex justify-center py-1">
                          <div className="flex items-center gap-1.5 text-muted-foreground">
                            <ArrowDown className="h-3.5 w-3.5" />
                            <span className="text-[11px]">空席が連鎖</span>
                          </div>
                        </div>
                      )}

                      <Card className={`transition-all ${
                        step.confirmed
                          ? "border-green-300/60 bg-green-50/30"
                          : isActive
                          ? "border-blue-300 bg-blue-50/30 shadow-sm"
                          : "border-muted"
                      }`}>
                        <CardHeader className="pb-1.5 pt-3 px-3">
                          <CardTitle className="text-xs flex items-center gap-1.5">
                            {step.confirmed ? (
                              <CheckCircle2 className="h-3.5 w-3.5 text-green-600 shrink-0" />
                            ) : (
                              <CircleDot className="h-3.5 w-3.5 text-blue-600 shrink-0" />
                            )}
                            <span className="text-muted-foreground font-normal">Step {idx + 1}</span>
                            <Building2 className="h-3 w-3 text-muted-foreground" />
                            <span className="font-semibold">{step.vacantDeptName}</span>
                            <Badge variant="outline" className={`text-[9px] ${GRADE_BG[step.vacantGrade] || ""}`}>
                              {step.vacantGrade}
                            </Badge>
                            <span className="text-muted-foreground font-normal">の空席</span>
                          </CardTitle>
                        </CardHeader>
                        <CardContent className="px-3 pb-3 space-y-2">
                          {step.loading ? (
                            <div className="flex items-center gap-2 text-xs text-muted-foreground py-4 justify-center">
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              読み込み中...
                            </div>
                          ) : (
                            <>
                              {step.confirmed && step.selectedCandidate ? (
                                <div className="flex items-center gap-2 text-xs p-2 rounded-md bg-green-100/60 border border-green-200">
                                  <CheckCircle2 className="h-3.5 w-3.5 text-green-600 shrink-0" />
                                  <Badge className={`text-[9px] px-1 py-0 ${GRADE_BG[step.selectedCandidate.GRADE] || ""}`}>
                                    {step.selectedCandidate.GRADE}
                                  </Badge>
                                  <span className="font-medium">{step.selectedCandidate.NAME}</span>
                                  <span className="text-muted-foreground">{step.selectedCandidate.DEPT_NAME}から</span>
                                  {step.matchDetail && (
                                    <Badge variant="outline" className={`text-[9px] ml-auto font-mono ${scoreColor(step.matchDetail.matchScore)}`}>
                                      {step.matchDetail.matchScore}%
                                    </Badge>
                                  )}
                                </div>
                              ) : (
                                <>
                                  <details className="group">
                                    <summary className="text-[11px] font-medium text-muted-foreground cursor-pointer flex items-center gap-1 hover:text-foreground">
                                      <Users className="h-3 w-3" />
                                      現組織メンバー（{step.orgMembers.length}名）
                                      <ChevronRight className="h-3 w-3 transition-transform group-open:rotate-90" />
                                    </summary>
                                    <ScrollArea className="h-28 border rounded-md mt-1">
                                      <div className="p-1.5 space-y-0.5">
                                        {step.orgMembers.map((m) => (
                                          <div
                                            key={m.EMPLOYEE_ID}
                                            className="flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] hover:bg-muted/50"
                                          >
                                            <Badge className={`text-[8px] px-1 py-0 shrink-0 ${GRADE_BG[m.GRADE] || "bg-gray-100 text-gray-700"}`}>
                                              {m.GRADE}
                                            </Badge>
                                            <span className="font-medium truncate">{m.NAME}</span>
                                            <span className="text-muted-foreground truncate">{m.POSITION_TITLE}</span>
                                            <span className="text-muted-foreground ml-auto whitespace-nowrap">{Number(m.AVG_EVAL).toFixed(1)} / {m.TENURE}年</span>
                                          </div>
                                        ))}
                                      </div>
                                    </ScrollArea>
                                  </details>

                                  <div>
                                    <div className="flex items-center gap-2 mb-1">
                                      <p className="text-[11px] font-medium text-muted-foreground flex items-center gap-1">
                                        <Target className="h-3 w-3" />
                                        異動候補者
                                      </p>
                                      <div className="relative flex-1 max-w-[200px]">
                                        <Search className="absolute left-1.5 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground" />
                                        <input
                                          type="text"
                                          placeholder="候補者を検索..."
                                          className="w-full pl-6 pr-2 py-0.5 text-[11px] border rounded"
                                          value={candidateSearch[step.id] || ""}
                                          onChange={(e) => setCandidateSearch((prev) => ({ ...prev, [step.id]: e.target.value }))}
                                        />
                                      </div>
                                    </div>
                                    {(() => {
                                      const q = (candidateSearch[step.id] || "").toLowerCase();
                                      const filtered = q
                                        ? step.candidates.filter((c) =>
                                            c.NAME.toLowerCase().includes(q) ||
                                            c.DEPT_NAME.toLowerCase().includes(q) ||
                                            c.POSITION_TITLE.toLowerCase().includes(q) ||
                                            c.GRADE.toLowerCase().includes(q)
                                          )
                                        : step.candidates;
                                      return filtered.length > 0 ? (
                                      <div className="space-y-0.5">
                                        {filtered.map((c, ci) => {
                                          const isSelected = step.selectedCandidate?.EMPLOYEE_ID === c.EMPLOYEE_ID;
                                          const alreadyUsed = chain.some(
                                            (s, i) => i !== idx && s.selectedCandidate?.EMPLOYEE_ID === c.EMPLOYEE_ID
                                          );
                                          return (
                                            <button
                                              key={c.EMPLOYEE_ID}
                                              onClick={() => {
                                                if (!step.confirmed && !isSelected && !alreadyUsed) {
                                                  openCandidateModal(idx, c);
                                                }
                                              }}
                                              disabled={step.confirmed || alreadyUsed}
                                              className={`w-full text-left px-2 py-1.5 rounded border text-[11px] transition-all flex items-center gap-1.5 ${
                                                isSelected
                                                  ? "ring-2 ring-blue-400 border-blue-400 bg-blue-50"
                                                  : alreadyUsed
                                                  ? "opacity-30 cursor-not-allowed"
                                                  : "hover:shadow-sm hover:border-blue-300 cursor-pointer"
                                              }`}
                                            >
                                              <span className="text-muted-foreground w-4 text-right shrink-0">{ci + 1}</span>
                                              <Badge className={`text-[8px] px-1 py-0 shrink-0 ${GRADE_BG[c.GRADE] || ""}`}>
                                                {c.GRADE}
                                              </Badge>
                                              <span className="font-medium truncate">{c.NAME}</span>
                                              <span className="text-muted-foreground truncate hidden sm:inline">{c.DEPT_NAME}</span>
                                              <div className="ml-auto flex items-center gap-1.5 shrink-0">
                                                <span className="text-muted-foreground hidden md:inline">{Number(c.AVG_EVAL).toFixed(1)}</span>
                                                <Badge variant="outline" className={`font-mono text-[10px] ${scoreColor(c.COMPOSITE_SCORE)}`}>
                                                  {c.COMPOSITE_SCORE}
                                                </Badge>
                                              </div>
                                              {isSelected && <CheckCircle2 className="h-3.5 w-3.5 text-blue-600 shrink-0" />}
                                            </button>
                                          );
                                        })}
                                      </div>
                                    ) : (
                                      <p className="text-[11px] text-muted-foreground text-center py-4">{q ? "検索条件に一致する候補者がいません" : "候補者なし"}</p>
                                    );
                                    })()}
                                  </div>

                                  {step.matchLoading && (
                                    <div className="flex items-center gap-2 text-[11px] text-blue-700 bg-blue-50 p-2 rounded border border-blue-200">
                                      <Loader2 className="h-3 w-3 animate-spin" />
                                      マッチ度を分析中...
                                    </div>
                                  )}

                                  {step.matchDetail && !step.matchLoading && (
                                    <div className="p-2 rounded-md border bg-muted/30 space-y-1">
                                      <div className="flex items-center gap-2 text-[11px]">
                                        <span className="font-medium">マッチ度</span>
                                        <Badge variant="outline" className={`font-mono text-[10px] ${scoreColor(step.matchDetail.matchScore)}`}>
                                          {step.matchDetail.matchScore}%
                                        </Badge>
                                        <span className="text-muted-foreground">スキル{step.matchDetail.skillScore}%</span>
                                        <span className="text-muted-foreground">評価{step.matchDetail.evalScore}%</span>
                                        <span className="text-muted-foreground">経験{step.matchDetail.tenureScore}%</span>
                                      </div>
                                      <div className="text-[10px] text-muted-foreground leading-relaxed prose prose-xs max-w-none [&_p]:text-[10px] [&_p]:mb-1 [&_strong]:text-foreground">
                                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{step.matchDetail.reason}</ReactMarkdown>
                                      </div>
                                    </div>
                                  )}

                                  {step.selectedCandidate && !step.confirmed && !step.matchLoading && (
                                    <div className="flex items-center gap-2 pt-1">
                                      {!step.matchDetail && (
                                        <Button size="sm" variant="outline" className="h-7 text-xs border-blue-300 text-blue-700 hover:bg-blue-50" onClick={() => analyzeMatch(idx)}>
                                          <Target className="h-3 w-3 mr-1" />
                                          マッチ度を分析
                                        </Button>
                                      )}
                                      <Button size="sm" className="h-7 text-xs" onClick={() => confirmStep(idx)}>
                                        <CheckCircle2 className="h-3 w-3 mr-1" />
                                        確定
                                      </Button>
                                      <Button
                                        size="sm"
                                        variant="ghost"
                                        className="h-7 text-xs"
                                        onClick={() => {
                                          setChain((prev) => {
                                            const copy = [...prev];
                                            copy[idx] = { ...copy[idx], selectedCandidate: null, matchDetail: null };
                                            return copy;
                                          });
                                        }}
                                      >
                                        <X className="h-3 w-3 mr-1" />
                                        取消
                                      </Button>
                                    </div>
                                  )}
                                </>
                              )}
                            </>
                          )}
                        </CardContent>
                      </Card>
                    </div>
                  );
                })}
              </div>
            </ScrollArea>
          </div>

          <div className="w-72 shrink-0 flex flex-col gap-3">
            <Card className="shrink-0">
              <CardHeader className="pb-1.5 pt-3 px-3">
                <CardTitle className="text-xs flex items-center gap-1.5">
                  <ArrowRightLeft className="h-3.5 w-3.5" />
                  異動チェーン
                  {confirmedCount > 0 && (
                    <Badge variant="secondary" className="text-[9px] ml-auto">{confirmedCount}件確定</Badge>
                  )}
                </CardTitle>
              </CardHeader>
              <CardContent className="px-3 pb-3">
                {confirmedCount === 0 && chain.length <= 1 ? (
                  <p className="text-[11px] text-muted-foreground text-center py-4">候補者を選択して確定すると<br />ここにチェーンが表示されます</p>
                ) : (
                  <div className="space-y-0">
                    <div className="flex items-start gap-2 pb-2">
                      <div className="flex flex-col items-center">
                        <div className="w-5 h-5 rounded-full bg-red-100 border-2 border-red-400 flex items-center justify-center">
                          <UserMinus className="h-2.5 w-2.5 text-red-600" />
                        </div>
                        {chain.length > 0 && <div className="w-0.5 h-4 bg-muted-foreground/20" />}
                      </div>
                      <div className="pt-0.5">
                        <p className="text-[11px] font-medium">{selectedTrigger.NAME}</p>
                        <p className="text-[10px] text-muted-foreground">{selectedTrigger.DEPT_NAME}を離脱</p>
                      </div>
                    </div>

                    {chain.map((step, idx) => {
                      const isLast = idx === chain.length - 1;
                      const hasCandidate = step.selectedCandidate;
                      return (
                        <div key={step.id} className="flex items-start gap-2 pb-2">
                          <div className="flex flex-col items-center">
                            <div className={`w-5 h-5 rounded-full flex items-center justify-center border-2 ${
                              step.confirmed
                                ? "bg-green-100 border-green-400"
                                : hasCandidate
                                ? "bg-blue-100 border-blue-400"
                                : "bg-muted border-muted-foreground/30"
                            }`}>
                              {step.confirmed ? (
                                <CheckCircle2 className="h-2.5 w-2.5 text-green-600" />
                              ) : hasCandidate ? (
                                <CircleDot className="h-2.5 w-2.5 text-blue-600" />
                              ) : (
                                <Circle className="h-2.5 w-2.5 text-muted-foreground" />
                              )}
                            </div>
                            {!isLast && <div className="w-0.5 h-4 bg-muted-foreground/20" />}
                          </div>
                          <div className="pt-0.5 min-w-0 flex-1">
                            <div className="flex items-center gap-1">
                              <Badge variant="outline" className={`text-[8px] px-1 py-0 ${GRADE_BG[step.vacantGrade] || ""}`}>
                                {step.vacantGrade}
                              </Badge>
                              <span className="text-[11px] font-medium truncate">{step.vacantDeptName}</span>
                            </div>
                            {hasCandidate ? (
                              <div className="flex items-center gap-1 mt-0.5">
                                <ArrowRight className="h-2.5 w-2.5 text-muted-foreground shrink-0" />
                                <span className="text-[10px] text-foreground">{step.selectedCandidate!.NAME}</span>
                                {step.matchDetail && (
                                  <Badge variant="outline" className={`text-[8px] font-mono ml-auto ${scoreColor(step.matchDetail.matchScore)}`}>
                                    {step.matchDetail.matchScore}%
                                  </Badge>
                                )}
                              </div>
                            ) : (
                              <p className="text-[10px] text-muted-foreground mt-0.5">候補者を選択中...</p>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </CardContent>
            </Card>

            {confirmedCount > 0 && (
              <Card className="shrink-0">
                <CardContent className="p-3 space-y-2">
                  <div className="grid grid-cols-2 gap-2 text-center">
                    <div className="p-2 rounded-md bg-muted/50">
                      <p className="text-lg font-bold">{confirmedCount}</p>
                      <p className="text-[10px] text-muted-foreground">異動数</p>
                    </div>
                    <div className="p-2 rounded-md bg-muted/50">
                      <p className="text-lg font-bold">
                        {chain.filter((s) => s.confirmed && s.matchDetail).length > 0
                          ? Math.round(
                              chain
                                .filter((s) => s.confirmed && s.matchDetail)
                                .reduce((sum, s) => sum + (s.matchDetail?.matchScore || 0), 0) /
                              chain.filter((s) => s.confirmed && s.matchDetail).length
                            )
                          : "—"}
                      </p>
                      <p className="text-[10px] text-muted-foreground">平均マッチ度</p>
                    </div>
                  </div>

                  <Separator />

                  <div className="flex flex-col gap-1.5">
                    {!saved ? (
                      <>
                        <Button size="sm" className="w-full h-8 text-xs" onClick={saveChain} disabled={saving || !allConfirmed}>
                          {saving ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <Save className="h-3.5 w-3.5 mr-1" />}
                          シミュレーション保存
                        </Button>
                        {saveError && <p className="text-[10px] text-red-600 text-center">{saveError}</p>}
                        {chain.length > 1 && !chain[chain.length - 1].confirmed && (
                          <Button variant="outline" size="sm" className="w-full h-7 text-[11px]" onClick={removeLastStep}>
                            <Undo2 className="h-3 w-3 mr-1" />
                            最後のステップを取消
                          </Button>
                        )}
                      </>
                    ) : (
                      <div className="space-y-2">
                        <div className="flex items-center justify-center gap-1.5 py-1 text-green-700">
                          <CheckCircle2 className="h-4 w-4" />
                          <span className="text-xs font-medium">保存完了</span>
                        </div>
                        {!submitted && savedSimId && (
                          <Button size="sm" className="w-full h-8 text-xs" disabled={submitLoading} onClick={async () => {
                            setSubmitLoading(true);
                            try {
                              const res = await fetch("/api/chain-simulation/submit", {
                                method: "POST",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({ simulationId: savedSimId }),
                              });
                              if (res.ok) setSubmitted(true);
                            } finally { setSubmitLoading(false); }
                          }}>
                            <Send className="h-3.5 w-3.5 mr-1" />
                            レビュー依頼
                          </Button>
                        )}
                        {submitted && (
                          <div className="flex items-center justify-center gap-1.5 py-1 text-yellow-700">
                            <Send className="h-4 w-4" />
                            <span className="text-xs font-medium">レビュー依頼済み</span>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </CardContent>
              </Card>
            )}
          </div>
        </div>
      )}

      <Dialog open={empModalOpen} onOpenChange={setEmpModalOpen}>
        <DialogContent className="sm:max-w-4xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-sm">
              <Briefcase className="h-4 w-4" />
              候補者比較
            </DialogTitle>
            <DialogDescription>
              空席ポジションの前任者と候補者を比較
            </DialogDescription>
          </DialogHeader>
          {empModalLoading && targetModalLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-3 p-3 rounded-lg border bg-red-50/30 border-red-200">
                  <div className="flex items-center gap-2">
                    <Badge variant="destructive" className="text-[10px]">対象者（前任）</Badge>
                    {targetModalLoading && <Loader2 className="h-3 w-3 animate-spin" />}
                  </div>
                  {targetModalData ? (() => {
                    const emp = targetModalData.employee as Record<string, unknown>;
                    return (
                      <div className="space-y-2.5">
                        <div>
                          <p className="font-semibold text-sm">{emp.NAME as string}</p>
                          <p className="text-[11px] text-muted-foreground">{emp.DEPT_NAME as string} / {emp.POSITION_TITLE as string}</p>
                        </div>
                        <div className="grid grid-cols-2 gap-2 text-xs">
                          <div><p className="text-muted-foreground">等級</p><p className="font-medium">{emp.GRADE as string} {GRADE_LABELS[emp.GRADE as string]}</p></div>
                          <div><p className="text-muted-foreground">勤続</p><p className="font-medium">{emp.TENURE_YEARS != null ? `${emp.TENURE_YEARS}年` : "—"}</p></div>
                          <div><p className="text-muted-foreground">平均評価</p><p className="font-medium">{emp.AVG_EVAL != null ? `${Number(emp.AVG_EVAL).toFixed(1)}/5.0` : "—"}</p></div>
                        </div>
                        {targetModalData.mlInsights?.attrition && (
                          <div className="flex items-center gap-2 text-xs p-1.5 rounded border bg-white">
                            <span className="text-muted-foreground">離職リスク</span>
                            <Badge variant={targetModalData.mlInsights.attrition.RISK_LABEL === "high" ? "destructive" : "secondary"} className="text-[9px]">
                              {targetModalData.mlInsights.attrition.RISK_LABEL === "high" ? "高" : targetModalData.mlInsights.attrition.RISK_LABEL === "medium" ? "中" : "低"}
                            </Badge>
                            <span className="font-mono">{(Number(targetModalData.mlInsights.attrition.RISK_SCORE) * 100).toFixed(0)}%</span>
                          </div>
                        )}
                        {targetModalData.mlInsights?.relationship && (
                          <div className="flex items-center gap-2 text-xs p-1.5 rounded border bg-white">
                            <span className="text-muted-foreground">上司関係性</span>
                            <span className="font-mono">{(Number(targetModalData.mlInsights.relationship.RELATIONSHIP_SCORE) * 100).toFixed(0)}%</span>
                            <span className="text-muted-foreground">上司: {targetModalData.mlInsights.relationship.MANAGER_NAME}</span>
                          </div>
                        )}
                        {targetModalData.skills?.length > 0 && (
                          <div>
                            <p className="text-[11px] font-medium text-muted-foreground mb-1">スキル</p>
                            <div className="space-y-0.5">
                              {targetModalData.skills.slice(0, 5).map((s, i) => (
                                <div key={i} className="flex items-center gap-1.5 text-[11px]">
                                  <span className="flex-1 truncate">{s.SKILL_NAME}</span>
                                  <Progress value={Number(s.PROFICIENCY) * 20} className="h-1 w-14" />
                                  <span className="text-muted-foreground w-5 text-right">L{s.PROFICIENCY}</span>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                        {targetModalData.evaluations?.length > 0 && (
                          <div>
                            <p className="text-[11px] font-medium text-muted-foreground mb-1">直近評価</p>
                            <div className="space-y-0.5">
                              {targetModalData.evaluations.slice(0, 2).map((ev, i) => (
                                <div key={i} className="flex items-center gap-1.5 text-[11px] p-1 rounded border bg-white">
                                  <Badge variant={ev.GRADE === "S" ? "destructive" : ev.GRADE === "A" ? "default" : "secondary"} className="text-[8px] px-1 py-0">{ev.GRADE}</Badge>
                                  <span>{ev.PERIOD}</span>
                                  <span className="font-mono">{Number(ev.SCORE).toFixed(1)}</span>
                                  <span className="text-muted-foreground truncate flex-1">{ev.COMMENT}</span>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })() : (
                    <p className="text-[11px] text-muted-foreground py-4 text-center">データなし</p>
                  )}
                </div>

                <div className="space-y-3 p-3 rounded-lg border bg-blue-50/30 border-blue-200">
                  <div className="flex items-center gap-2">
                    <Badge className="text-[10px] bg-blue-600">候補者</Badge>
                    {empModalLoading && <Loader2 className="h-3 w-3 animate-spin" />}
                  </div>
                  {empModalData ? (() => {
                    const emp = empModalData.employee as Record<string, unknown>;
                    const c = empModalCandidateIdx?.candidate;
                    return (
                      <div className="space-y-2.5">
                        <div>
                          <p className="font-semibold text-sm">{c?.NAME || emp.NAME as string}</p>
                          <p className="text-[11px] text-muted-foreground">{c?.DEPT_NAME || emp.DEPT_NAME as string} / {c?.POSITION_TITLE || emp.POSITION_TITLE as string}</p>
                        </div>
                        <div className="grid grid-cols-2 gap-2 text-xs">
                          <div><p className="text-muted-foreground">等級</p><p className="font-medium">{emp.GRADE as string} {GRADE_LABELS[emp.GRADE as string]}</p></div>
                          <div><p className="text-muted-foreground">勤続</p><p className="font-medium">{c?.TENURE || 0}年</p></div>
                          <div><p className="text-muted-foreground">平均評価</p><p className="font-medium">{Number(c?.AVG_EVAL).toFixed(1)}/5.0</p></div>
                          <div><p className="text-muted-foreground">スキルマッチ</p><p className="font-medium">{c?.SKILL_MATCH}/5</p></div>
                        </div>
                        {empModalData.mlInsights?.attrition && (
                          <div className="flex items-center gap-2 text-xs p-1.5 rounded border bg-white">
                            <span className="text-muted-foreground">離職リスク</span>
                            <Badge variant={empModalData.mlInsights.attrition.RISK_LABEL === "high" ? "destructive" : "secondary"} className="text-[9px]">
                              {empModalData.mlInsights.attrition.RISK_LABEL === "high" ? "高" : empModalData.mlInsights.attrition.RISK_LABEL === "medium" ? "中" : "低"}
                            </Badge>
                            <span className="font-mono">{(Number(empModalData.mlInsights.attrition.RISK_SCORE) * 100).toFixed(0)}%</span>
                          </div>
                        )}
                        {empModalData.mlInsights?.relationship && (
                          <div className="flex items-center gap-2 text-xs p-1.5 rounded border bg-white">
                            <span className="text-muted-foreground">上司関係性</span>
                            <span className="font-mono">{(Number(empModalData.mlInsights.relationship.RELATIONSHIP_SCORE) * 100).toFixed(0)}%</span>
                            <span className="text-muted-foreground">上司: {empModalData.mlInsights.relationship.MANAGER_NAME}</span>
                          </div>
                        )}
                        {empModalData.skills?.length > 0 && (
                          <div>
                            <p className="text-[11px] font-medium text-muted-foreground mb-1">スキル</p>
                            <div className="space-y-0.5">
                              {empModalData.skills.slice(0, 5).map((s, i) => (
                                <div key={i} className="flex items-center gap-1.5 text-[11px]">
                                  <span className="flex-1 truncate">{s.SKILL_NAME}</span>
                                  <Progress value={Number(s.PROFICIENCY) * 20} className="h-1 w-14" />
                                  <span className="text-muted-foreground w-5 text-right">L{s.PROFICIENCY}</span>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                        {empModalData.evaluations?.length > 0 && (
                          <div>
                            <p className="text-[11px] font-medium text-muted-foreground mb-1">直近評価</p>
                            <div className="space-y-0.5">
                              {empModalData.evaluations.slice(0, 2).map((ev, i) => (
                                <div key={i} className="flex items-center gap-1.5 text-[11px] p-1 rounded border bg-white">
                                  <Badge variant={ev.GRADE === "S" ? "destructive" : ev.GRADE === "A" ? "default" : "secondary"} className="text-[8px] px-1 py-0">{ev.GRADE}</Badge>
                                  <span>{ev.PERIOD}</span>
                                  <span className="font-mono">{Number(ev.SCORE).toFixed(1)}</span>
                                  <span className="text-muted-foreground truncate flex-1">{ev.COMMENT}</span>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })() : (
                    <p className="text-[11px] text-muted-foreground py-4 text-center">データなし</p>
                  )}
                </div>
              </div>

              {aiComment && (
                <div className="p-3 rounded-lg border bg-purple-50/50 border-purple-200">
                  <div className="flex items-center gap-1.5 mb-1.5">
                    <Sparkles className="h-3.5 w-3.5 text-purple-600" />
                    <span className="text-xs font-semibold text-purple-700">AI評価コメント</span>
                  </div>
                  <div className="text-xs leading-relaxed text-gray-700 prose prose-xs max-w-none [&_h1]:text-sm [&_h1]:font-bold [&_h1]:mb-1 [&_h1]:mt-2 [&_h2]:text-xs [&_h2]:font-bold [&_h2]:mb-1 [&_h2]:mt-2 [&_h3]:text-xs [&_h3]:font-semibold [&_h3]:mb-1 [&_h3]:mt-1.5 [&_p]:mb-1.5 [&_p]:text-xs [&_p]:leading-relaxed [&_strong]:text-purple-800 [&_ul]:my-1 [&_ul]:pl-4 [&_li]:text-xs [&_li]:mb-0.5"><ReactMarkdown remarkPlugins={[remarkGfm]}>{aiComment}</ReactMarkdown></div>
                </div>
              )}

              <div className="flex justify-between gap-2 pt-1">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleAiComment}
                  disabled={aiCommentLoading || empModalLoading}
                  className="text-purple-700 border-purple-300 hover:bg-purple-50"
                >
                  {aiCommentLoading ? (
                    <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />
                  ) : (
                    <Sparkles className="h-3.5 w-3.5 mr-1" />
                  )}
                  AI評価
                </Button>
                <div className="flex gap-2">
                  <Button variant="outline" size="sm" onClick={() => setEmpModalOpen(false)}>
                    閉じる
                  </Button>
                  <Button size="sm" onClick={selectCandidateFromModal}>
                    <CheckCircle2 className="h-3.5 w-3.5 mr-1" />
                    この候補者を選択
                  </Button>
                </div>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={chainListOpen} onOpenChange={setChainListOpen}>
        <DialogContent className="sm:max-w-lg max-h-[70vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <FolderOpen className="h-5 w-5" />
              保存済みチェーン
            </DialogTitle>
            <DialogDescription>チェーンを選択してロード</DialogDescription>
          </DialogHeader>
          {chainListLoading ? (
            <div className="flex justify-center py-8"><Loader2 className="h-5 w-5 animate-spin" /></div>
          ) : chainList.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-8">保存済みチェーンがありません</p>
          ) : (
            <div className="space-y-2">
              {chainList.map((c) => (
                <div key={c.simulation_id} className="flex items-center gap-3 p-3 rounded-lg border hover:bg-accent cursor-pointer" onClick={() => {
                  setLoadedSimId(c.simulation_id);
                  setLoadedSimStatus(c.status);
                  setLoadedSimName(c.simulation_name);
                  setChainListOpen(false);
                }}>
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-medium">{c.simulation_name}</p>
                      {c.status && c.status !== "draft" && (
                        <Badge variant="secondary" className={`text-[10px] ${
                          c.status === "pending_review" ? "bg-yellow-100 text-yellow-700" :
                          c.status === "revision_requested" ? "bg-red-100 text-red-700" :
                          c.status === "approved" ? "bg-green-100 text-green-700" : ""
                        }`}>
                          {c.status === "pending_review" ? "レビュー待ち" : c.status === "revision_requested" ? "差し戻しあり" :
                           c.status === "approved" ? "承認済み" : c.status}
                        </Badge>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground">{c.trigger_type} / {c.step_count}ステップ</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={confirmDialogOpen} onOpenChange={setConfirmDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>スナップショット確定</DialogTitle>
            <DialogDescription>確定データとして保管します</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <label className="text-sm font-medium">ラベル</label>
              <Input value={confirmLabel} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setConfirmLabel(e.target.value)} placeholder="例: 2026年4月 玉突き人事" />
            </div>
            <div>
              <label className="text-sm font-medium">発令日</label>
              <Input type="date" value={confirmDate} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setConfirmDate(e.target.value)} />
            </div>
          </div>
          <div className="flex justify-end gap-2 mt-4">
            <Button variant="outline" onClick={() => setConfirmDialogOpen(false)}>キャンセル</Button>
            <Button disabled={!confirmLabel.trim() || !confirmDate || confirmLoading} onClick={async () => {
              setConfirmLoading(true);
              try {
                const res = await fetch("/api/chain-simulation/confirm", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ simulationId: loadedSimId, label: confirmLabel, effectiveDate: confirmDate }),
                });
                if (res.ok) { setConfirmDialogOpen(false); setLoadedSimStatus("confirmed"); }
              } finally { setConfirmLoading(false); }
            }}>
              {confirmLoading ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : <Archive className="h-4 w-4 mr-1" />}
              確定
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default function ChainSimulationPage() {
  return <Suspense><ChainSimulationPageInner /></Suspense>;
}
