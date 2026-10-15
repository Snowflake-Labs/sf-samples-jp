"use client";

import { useEffect, useState, useCallback, useRef, useMemo, Suspense } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  GitBranch,
  Building2,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  Users,
  X,
  ArrowUp,
  ArrowDown,
  UserMinus,
  Undo2,
  AlertTriangle,
  Shuffle,
  Loader2,
  CheckCircle2,
  XCircle,
  Target,
  Brain,
  Eye,
  ExternalLink,
  Briefcase,
  Sparkles,
  TrendingUp,
  TrendingDown,
  DollarSign,
  BarChart3,
  ShieldAlert,
  Minus,
  Save,
  Search,
  FolderOpen,
  ArrowLeftRight,
  Send,
  Upload,
  SlidersHorizontal,
  Archive,
  ExternalLink as ExternalLinkIcon,
  CornerDownRight,
  CircleDashed,
} from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Progress } from "@/components/ui/progress";
import { Input } from "@/components/ui/input";
import { GRADE_LABELS, GRADE_ORDER, FEATURE_LABELS } from "@/lib/types";
import { useHonbu } from "@/lib/honbu-context";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { buildVacancyLedger, buildChains } from "@/lib/vacancy-ledger";

interface OrgEmployee {
  EMPLOYEE_ID: number;
  NAME: string;
  DEPT_ID: number;
  POSITION_ID: number;
  MANAGER_ID: number | null;
  SALARY: number;
  DEPT_NAME: string;
  POSITION_TITLE: string;
  GRADE: string;
  AGE: number | null;
  TENURE_YEARS: number | null;
  ENTRY_TYPE: string | null;
}

interface OrgDept {
  DEPT_ID: number;
  DEPT_NAME: string;
  DEPT_CODE: string;
  PARENT_DEPT_ID: number | null;
  LEVEL: number;
  EMP_COUNT: number;
}

interface VacantPosition {
  POSITION_ID: number;
  TITLE: string;
  DEPT_ID: number;
  GRADE: string;
  IS_VACANT: boolean;
  HEADCOUNT: number;
  DEPT_NAME: string;
}

type ActionType = "promote" | "transfer" | "retire";

interface SimAction {
  id: string;
  type: ActionType;
  employee: OrgEmployee;
  fromGrade: string;
  toGrade?: string;
  fromDeptId: number;
  toDeptId?: number;
  fromDeptName: string;
  toDeptName?: string;
  matchScore?: number;
  matchReason?: string;
}

interface MatchResult {
  matchScore: number;
  skillScore: number;
  evalScore: number;
  tenureScore: number;
  matchedSkills: string[];
  missingSkills: string[];
  empSkills: { name: string; proficiency: number }[];
  requiredSkills: string[];
  avgEvalScore: number;
  tenureYears: number;
  reason: string;
}

interface DeptEmployee {
  EMPLOYEE_ID: number;
  NAME: string;
  GRADE: string;
  POSITION_TITLE: string;
  TENURE_YEARS: number;
  AVG_EVAL: number;
  SKILL_COUNT: number;
  RISK_SCORE: number | null;
  RISK_LABEL: string | null;
}

interface PeekEmpDetail {
  employee: Record<string, unknown>;
  skills: { SKILL_NAME: string; CATEGORY: string; PROFICIENCY: number }[];
  evaluations: { PERIOD: string; SCORE: number; GRADE: string; COMMENT: string }[];
  mlInsights: {
    attrition: { RISK_SCORE: number; RISK_LABEL: string } | null;
    relationship: { RELATIONSHIP_SCORE: number; MANAGER_NAME: string } | null;
  };
}

interface CompareResult {
  employee: {
    name: string;
    grade: string;
    deptName: string;
    tenure: number;
    avgEval: number;
    skills: { name: string; proficiency: number }[];
  };
  toDeptName: string;
  peers: {
    employeeId: number;
    name: string;
    grade: string;
    positionTitle: string;
    tenure: number;
    avgEval: number;
    skills: string;
  }[];
  peerCount: number;
  aiComparison: string;
}

const GRADE_COLORS: Record<string, string> = {
  E1: "border-red-400 bg-red-50 text-red-900",
  D1: "border-orange-400 bg-orange-50 text-orange-900",
  D2: "border-amber-400 bg-amber-50 text-amber-900",
  M1: "border-yellow-400 bg-yellow-50 text-yellow-900",
  M2: "border-lime-400 bg-lime-50 text-lime-900",
  S1: "border-green-400 bg-green-50 text-green-900",
  S2: "border-emerald-400 bg-emerald-50 text-emerald-900",
  J1: "border-cyan-400 bg-cyan-50 text-cyan-900",
  J2: "border-blue-400 bg-blue-50 text-blue-900",
  J3: "border-violet-400 bg-violet-50 text-violet-900",
};

const GRADE_BG: Record<string, string> = {
  E1: "bg-red-100",
  D1: "bg-orange-100",
  D2: "bg-amber-100",
  M1: "bg-yellow-100",
  M2: "bg-lime-100",
  S1: "bg-green-100",
  S2: "bg-emerald-100",
  J1: "bg-cyan-100",
  J2: "bg-blue-100",
  J3: "bg-violet-100",
};

const ACTION_LABELS: Record<ActionType, { label: string; icon: typeof ArrowUp; color: string }> = {
  promote: { label: "昇格", icon: ArrowUp, color: "text-green-600 bg-green-50 border-green-200" },
  transfer: { label: "異動", icon: Shuffle, color: "text-blue-600 bg-blue-50 border-blue-200" },
  retire: { label: "退職", icon: UserMinus, color: "text-red-600 bg-red-50 border-red-200" },
};

function scoreColor(score: number): string {
  if (score >= 70) return "text-green-700 bg-green-100 border-green-300";
  if (score >= 40) return "text-amber-700 bg-amber-100 border-amber-300";
  return "text-red-700 bg-red-100 border-red-300";
}

const GRADE_AVG_SALARY: Record<string, number> = {
  E1: 15450000, D1: 14827000, D2: 12148000, M1: 9474000, M2: 8237000,
  S1: 7011000, S2: 5986000, J1: 5243000, J2: 4251000, J3: 3501000,
};

function formatYen(n: number): string {
  const abs = Math.abs(n);
  if (abs >= 100000000) return `${(n / 100000000).toFixed(1)}億円`;
  if (abs >= 10000) return `${Math.round(n / 10000).toLocaleString()}万円`;
  return `${n.toLocaleString()}円`;
}

function DeptTreeNode({
  dept,
  childDepts,
  selectedDeptId,
  onSelect,
  affectedDeptIds,
}: {
  dept: OrgDept;
  childDepts: OrgDept[];
  selectedDeptId: number | null;
  onSelect: (d: OrgDept) => void;
  affectedDeptIds: Set<number>;
}) {
  const [expanded, setExpanded] = useState(true);
  const children = childDepts.filter((d) => d.PARENT_DEPT_ID === dept.DEPT_ID);
  const isSelected = selectedDeptId === dept.DEPT_ID;
  const isAffected = affectedDeptIds.has(dept.DEPT_ID);

  return (
    <div className="ml-2">
      <div
        className={`flex items-center gap-1 py-1 px-2 rounded-md cursor-pointer transition-colors ${
          isSelected
            ? "bg-primary text-primary-foreground"
            : isAffected
            ? "bg-amber-50 border border-amber-200 hover:bg-amber-100"
            : "hover:bg-accent"
        }`}
        onClick={() => onSelect(dept)}
      >
        {children.length > 0 ? (
          <button
            onClick={(e) => {
              e.stopPropagation();
              setExpanded(!expanded);
            }}
            className="p-0.5"
          >
            {expanded ? (
              <ChevronDown className="h-3 w-3" />
            ) : (
              <ChevronRight className="h-3 w-3" />
            )}
          </button>
        ) : (
          <span className="w-4" />
        )}
        <Building2 className="h-3.5 w-3.5 shrink-0" />
        <span className="text-sm truncate flex-1">{dept.DEPT_NAME}</span>
        {isAffected && (
          <AlertTriangle className="h-3 w-3 text-amber-500 shrink-0" />
        )}
        <Badge
          variant="secondary"
          className={`text-[10px] px-1 py-0 shrink-0 ${
            isSelected ? "bg-primary-foreground/20" : ""
          }`}
        >
          {dept.EMP_COUNT}名
        </Badge>
      </div>
      {expanded &&
        children.map((child) => (
          <DeptTreeNode
            key={child.DEPT_ID}
            dept={child}
            childDepts={childDepts}
            selectedDeptId={selectedDeptId}
            onSelect={onSelect}
            affectedDeptIds={affectedDeptIds}
          />
        ))}
    </div>
  );
}

function EmployeeCard({
  emp,
  isActioned,
  actionBadge,
  onClick,
}: {
  emp: OrgEmployee;
  isActioned: boolean;
  actionBadge?: string;
  onClick?: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`w-full text-left p-2 rounded-md border transition-all ${
        isActioned
          ? "ring-2 ring-amber-400 border-amber-400 bg-amber-50 opacity-70"
          : GRADE_COLORS[emp.GRADE] || "border-gray-200 bg-white"
      } hover:shadow-sm`}
    >
      <div className="flex items-center justify-between">
        <span className="font-medium text-sm">{emp.NAME}</span>
        <div className="flex gap-1">
          {actionBadge && (
            <Badge variant="outline" className="text-[9px] bg-amber-100 border-amber-300">
              {actionBadge}
            </Badge>
          )}
          <Badge
            variant="outline"
            className={`text-[10px] ${GRADE_BG[emp.GRADE] || ""}`}
          >
            {emp.GRADE}
          </Badge>
        </div>
      </div>
      <p className="text-[11px] text-muted-foreground truncate">
        {emp.POSITION_TITLE}
        {emp.AGE != null && <> / {emp.AGE}歳</>}
        {emp.TENURE_YEARS != null && <> / 勤続{emp.TENURE_YEARS}年</>}
        {emp.ENTRY_TYPE && <> / {emp.ENTRY_TYPE === "mid_career" ? "中途" : emp.ENTRY_TYPE === "new_grad" ? "新卒" : emp.ENTRY_TYPE}</>}
      </p>
    </button>
  );
}

function SimulationPageInner() {
  const { honbu, setHonbu, honbuList } = useHonbu();
  const searchParams = useSearchParams();
  const [incomingContext, setIncomingContext] = useState<{
    employeeId: number;
    name: string;
    riskScore: number | null;
    riskLabel: string | null;
    topFactors: { name: string; value: number }[];
    evidenceSummary: string | null;
  } | null>(null);
  const [departments, setDepartments] = useState<OrgDept[]>([]);
  const [allEmployees, setAllEmployees] = useState<OrgEmployee[]>([]);
  const [vacancies, setVacancies] = useState<VacantPosition[]>([]);
  const [selectedDept, setSelectedDept] = useState<OrgDept | null>(null);
  const [loading, setLoading] = useState(true);

  const [actions, setActions] = useState<SimAction[]>([]);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogType, setDialogType] = useState<ActionType>("promote");
  const [dialogEmployee, setDialogEmployee] = useState<OrgEmployee | null>(null);
  const [dialogToGrade, setDialogToGrade] = useState("");
  const [dialogToDept, setDialogToDept] = useState("");

  const [matchResult, setMatchResult] = useState<MatchResult | null>(null);
  const [matchLoading, setMatchLoading] = useState(false);
  const [matchError, setMatchError] = useState(false);
  const matchAbortRef = useRef<AbortController | null>(null);

  const [deptEmployees, setDeptEmployees] = useState<DeptEmployee[]>([]);
  const [deptEmpLoading, setDeptEmpLoading] = useState(false);
  const [peekOpen, setPeekOpen] = useState(false);
  const [peekDetail, setPeekDetail] = useState<PeekEmpDetail | null>(null);
  const [peekDetailLoading, setPeekDetailLoading] = useState(false);
  const [peekCandidate, setPeekCandidate] = useState<{EMPLOYEE_ID: number; NAME: string; DEPT_NAME: string; GRADE: string; POSITION_TITLE: string; AVG_EVAL: number; TENURE: number; SKILL_MATCH: number; COMPOSITE_SCORE: number} | null>(null);
  const [compareResult, setCompareResult] = useState<CompareResult | null>(null);
  const [compareLoading, setCompareLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedScenarioId, setSavedScenarioId] = useState<number | null>(null);
  const [submitLoading, setSubmitLoading] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [loadedScenarioId, setLoadedScenarioId] = useState<number | null>(null);
  const [loadedScenarioStatus, setLoadedScenarioStatus] = useState<string | null>(null);
  const [loadedScenarioName, setLoadedScenarioName] = useState<string | null>(null);
  const [loadedRejectedComments, setLoadedRejectedComments] = useState<{employee_name: string; comment: string}[]>([]);
  const [confirmDialogOpen, setConfirmDialogOpen] = useState(false);
  const [confirmLabel, setConfirmLabel] = useState("");
  const [confirmDate, setConfirmDate] = useState("");
  const [confirmLoading, setConfirmLoading] = useState(false);
  const [vacancyExpanded, setVacancyExpanded] = useState(false);

  const [scenariosOpen, setScenariosOpen] = useState(false);
  const [scenariosList, setScenariosList] = useState<{scenario_id: number; scenario_name: string; created_by: string; created_at: string; action_count: number; status?: string; rejected_count?: number; approved_count?: number}[]>([]);
  const [scenariosLoading, setScenariosLoading] = useState(false);
  const [compareMode, setCompareMode] = useState(false);
  const [compareScenario, setCompareScenario] = useState<{scenario: Record<string, unknown>; actions: {employee_id: number; employee_name: string; action_type: string; from_dept_name: string; to_dept_name: string; grade: string}[]} | null>(null);
  const [allDeptsList, setAllDeptsList] = useState<{DEPT_ID: number; DEPT_NAME: string; LEVEL: number; PARENT_DEPT_ID: number | null}[]>([]);

  const [vacancyCandidatesOpen, setVacancyCandidatesOpen] = useState(false);
  const [vacancyCandidates, setVacancyCandidates] = useState<{EMPLOYEE_ID: number; NAME: string; DEPT_ID: number; DEPT_NAME: string; GRADE: string; POSITION_TITLE: string; AVG_EVAL: number; TENURE: number; SKILL_MATCH: number; COMPOSITE_SCORE: number; SKILL_PCT: number; EVAL_PCT: number; TENURE_PCT: number; REASON: string; ENTRY_TYPE: string | null; MANAGER_ID: number | null; MANAGER_NAME: string | null; SALARY?: number | null; POSITION_ID?: number | null}[]>([]);
  const [vacancyCandidatesLoading, setVacancyCandidatesLoading] = useState(false);
  const [vacancyTarget, setVacancyTarget] = useState<{grade: string; deptId: number; deptName: string; label: string} | null>(null);
  const [vacancySearch, setVacancySearch] = useState("");
  const [vcFilterMinScore, setVcFilterMinScore] = useState(0);
  const [vcFilterMinTenure, setVcFilterMinTenure] = useState(0);
  const [vcFilterEntryType, setVcFilterEntryType] = useState("");
  const [vcFilterDept, setVcFilterDept] = useState("");
  const [vcFilterManager, setVcFilterManager] = useState("");
  const [vcShowFilters, setVcShowFilters] = useState(false);

  const fetchCounterRef = useRef(0);

  const loadScenariosList = useCallback(async () => {
    setScenariosLoading(true);
    try {
      const res = await fetch("/api/simulation/scenarios");
      if (res.ok) setScenariosList(await res.json());
    } finally {
      setScenariosLoading(false);
    }
  }, []);

  const loadScenarioForCompare = useCallback(async (id: number) => {
    try {
      const res = await fetch(`/api/simulation/scenarios/${id}`);
      if (res.ok) {
        setCompareScenario(await res.json());
        setCompareMode(true);
        setScenariosOpen(false);
      }
    } catch { /* ignore */ }
  }, []);

  const loadScenarioForEdit = useCallback(async (id: number) => {
    try {
      const res = await fetch(`/api/simulation/scenarios/${id}`);
      if (!res.ok) return;
      const data = await res.json();
      const scenario = data.scenario;
      setLoadedScenarioId(scenario.scenario_id);
      setLoadedScenarioStatus(scenario.status);
      setLoadedScenarioName(scenario.scenario_name);

      const rejected = data.actions
        .filter((a: { action_status: string }) => a.action_status === "rejected")
        .map((a: { employee_name: string; reviewer_comment: string }) => ({
          employee_name: a.employee_name,
          comment: a.reviewer_comment,
        }));
      setLoadedRejectedComments(rejected);

      const restoredActions: SimAction[] = data.actions.map((a: Record<string, unknown>, i: number) => ({
        id: `loaded-${i}`,
        type: (a.action_type as ActionType) || "transfer",
        employee: {
          EMPLOYEE_ID: a.employee_id as number,
          NAME: a.employee_name as string,
          DEPT_ID: a.from_dept_id as number,
          DEPT_NAME: a.from_dept_name as string,
          GRADE: a.grade as string,
          POSITION_TITLE: "",
          // 給与を復元しないと等級平均で代替され、保存前とコスト影響がずれる
          POSITION_ID: (a.position_id as number) ?? 0, MANAGER_ID: null, SALARY: Number(a.salary) || 0, AGE: null, TENURE_YEARS: null, ENTRY_TYPE: null,
        } as OrgEmployee,
        fromGrade: a.grade as string,
        toGrade: (a.to_grade as string | null) ?? (a.action_type === "transfer" ? (a.grade as string) : undefined),
        matchScore: a.match_score == null ? undefined : Number(a.match_score),
        matchReason: (a.match_reason as string | null) ?? undefined,
        fromDeptId: a.from_dept_id as number,
        toDeptId: a.to_dept_id as number | undefined,
        fromDeptName: a.from_dept_name as string,
        toDeptName: a.to_dept_name as string | undefined,
      }));
      setActions(restoredActions);
      setSaved(true);
      setSavedScenarioId(scenario.scenario_id);
      setSubmitted(scenario.status !== "draft");
      setScenariosOpen(false);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    const loadId = searchParams.get("load");
    if (loadId) loadScenarioForEdit(Number(loadId));
  }, [searchParams, loadScenarioForEdit]);

  useEffect(() => {
    const empId = searchParams.get("employee");
    if (empId && allEmployees.length > 0) {
      const emp = allEmployees.find((e) => e.EMPLOYEE_ID === Number(empId));
      if (emp) {
        setDialogEmployee(emp);
        setDialogType("transfer");
        setDialogOpen(true);
        // Carry the ML context over from the referring screen (M1)
        fetch(`/api/attrition/${empId}`)
          .then((r) => (r.ok ? r.json() : null))
          .then((d) => {
            if (!d) return;
            setIncomingContext({
              employeeId: Number(empId),
              name: emp.NAME || "",
              riskScore: d.prediction?.RISK_SCORE ?? null,
              riskLabel: d.prediction?.RISK_LABEL ?? null,
              topFactors: (d.shapFactors || [])
                .slice(0, 3)
                .map((s: { FEATURE_NAME: string; SHAP_VALUE: number }) => ({
                  name: s.FEATURE_NAME,
                  value: Number(s.SHAP_VALUE),
                })),
              evidenceSummary: d.evidence?.ai_summary ?? null,
            });
          })
          .catch((err) => console.error("[simulation incoming context] failed:", err));
      }
    }
  }, [searchParams, allEmployees]);

  const fetchPeekDetail = useCallback(async (empId: number) => {
    setPeekDetailLoading(true);
    setPeekDetail(null);
    try {
      const [basicRes, mlRes] = await Promise.all([
        fetch(`/api/employees/${empId}?section=basic`),
        fetch(`/api/employees/${empId}?section=ml`),
      ]);
      const basic = basicRes.ok ? await basicRes.json() : null;
      const ml = mlRes.ok ? await mlRes.json() : null;
      if (basic) {
        setPeekDetail({
          employee: basic.employee,
          skills: basic.skills || [],
          evaluations: (basic.evaluations || []).slice(0, 3),
          mlInsights: {
            attrition: ml?.attrition || null,
            relationship: ml?.relationship || null,
          },
        });
      }
    } catch {
      setPeekDetail(null);
    } finally {
      setPeekDetailLoading(false);
    }
  }, []);

  const fetchOrgData = useCallback((h: string) => {
    if (!h) return;
    setLoading(true);
    const counter = ++fetchCounterRef.current;
    fetch(`/api/org-tree?honbu=${h}`)
      .then((r) => {
        if (!r.ok) throw new Error("Failed");
        return r.json();
      })
      .then(({ employees, departments: depts }) => {
        if (counter !== fetchCounterRef.current) return;
        setAllEmployees(employees);
        setDepartments(depts);
        setSelectedDept(null);
        setActions([]);
      })
      .catch((err) => console.error("Org tree error:", err))
      .finally(() => setLoading(false));

    fetch(`/api/positions?honbu=${h}&vacant=true`)
      .then((r) => {
        if (!r.ok) throw new Error("Failed");
        return r.json();
      })
      .then((data: VacantPosition[]) => {
        if (counter !== fetchCounterRef.current) return;
        setVacancies(data);
      })
      .catch((err) => console.error("Vacancies error:", err));
  }, []);

  useEffect(() => {
    if (honbu) fetchOrgData(honbu);
  }, [honbu, fetchOrgData]);

  useEffect(() => {
    fetch("/api/departments")
      .then((r) => r.ok ? r.json() : [])
      .then((data) => setAllDeptsList(data))
      .catch((err) => console.error("[departments fetch] failed:", err));
  }, []);

  const fetchMatch = useCallback((empId: number, deptId: number) => {
    if (matchAbortRef.current) matchAbortRef.current.abort();
    const ctrl = new AbortController();
    matchAbortRef.current = ctrl;
    setMatchLoading(true);
    setMatchResult(null);
    setMatchError(false);
    fetch(`/api/simulation/match?employee_id=${empId}&to_dept_id=${deptId}`, {
      signal: ctrl.signal,
    })
      .then((r) => {
        if (!r.ok) throw new Error(`Match API error: ${r.status}`);
        return r.json();
      })
      .then((data: MatchResult) => {
        if (!ctrl.signal.aborted) setMatchResult(data);
      })
      .catch((err) => {
        if (err.name !== "AbortError") {
          console.error("Match error:", err);
          if (!ctrl.signal.aborted) setMatchError(true);
        }
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setMatchLoading(false);
      });
  }, []);

  const actionedEmpIds = useMemo(() => new Set(actions.map((a) => a.employee.EMPLOYEE_ID)), [actions]);
  const affectedDeptIds = new Set(
    actions.flatMap((a) => [a.fromDeptId, ...(a.toDeptId ? [a.toDeptId] : [])])
  );

  // Replay the moves against the vacancy ledger so a slot, once filled,
  // is no longer offered. Derived (not stored) so reloaded scenarios
  // reconcile the same way.
  const ledger = useMemo(() => buildVacancyLedger(
    actions.map((a) => ({
      id: a.id,
      type: a.type,
      employeeId: a.employee.EMPLOYEE_ID,
      employeeName: a.employee.NAME,
      fromDeptId: a.fromDeptId,
      fromDeptName: a.fromDeptName,
      fromGrade: a.fromGrade,
      toDeptId: a.toDeptId,
      toDeptName: a.toDeptName,
      toGrade: a.toGrade,
    })),
    vacancies.map((v) => ({
      positionId: v.POSITION_ID,
      title: v.TITLE,
      deptId: v.DEPT_ID,
      deptName: v.DEPT_NAME,
      grade: v.GRADE,
    }))
  ), [actions, vacancies]);

  const openGenerated = ledger.open.filter((s) => s.source === "generated");
  const openExisting = ledger.open.filter((s) => s.source === "existing");
  const overfillByAction = new Map(ledger.overfills.map((o) => [o.actionId, o]));
  const chains = useMemo(
    () => buildChains(actions.map((a) => ({
      id: a.id, type: a.type, employeeId: a.employee.EMPLOYEE_ID, employeeName: a.employee.NAME,
      fromDeptId: a.fromDeptId, fromDeptName: a.fromDeptName, fromGrade: a.fromGrade,
      toDeptId: a.toDeptId, toDeptName: a.toDeptName, toGrade: a.toGrade,
    })), ledger),
    [actions, ledger]
  );

  // Auto-expand vacancy card when the scenario leaves seats open
  useEffect(() => {
    if (openGenerated.length > 0) setVacancyExpanded(true);
  }, [openGenerated.length]);

  // Grade summary for still-open existing vacancies
  const vacancyGradeSummary = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const s of ledger.open) counts[s.grade] = (counts[s.grade] || 0) + 1;
    return GRADE_ORDER.filter((g) => counts[g]).map((g) => `${g}×${counts[g]}`);
  }, [ledger]);

  const honbuDept = departments.find((d) => String(d.DEPT_ID) === honbu);
  const childDepts = departments.filter(
    (d) => String(d.PARENT_DEPT_ID) === honbu
  );
  const allDepts = honbuDept ? [honbuDept, ...childDepts] : childDepts;

  const selectedDeptEmps = selectedDept
    ? allEmployees
        .filter((e) => e.DEPT_ID === selectedDept.DEPT_ID)
        .sort(
          (a, b) =>
            GRADE_ORDER.indexOf(a.GRADE) - GRADE_ORDER.indexOf(b.GRADE)
        )
    : [];

  const getActionBadge = (empId: number): string | undefined => {
    const a = actions.find((act) => act.employee.EMPLOYEE_ID === empId);
    if (!a) return undefined;
    return ACTION_LABELS[a.type].label;
  };

  const openActionDialog = (type: ActionType, emp: OrgEmployee) => {
    setDialogType(type);
    setDialogEmployee(emp);
    setMatchResult(null);
    setMatchLoading(false);
    setMatchError(false);
    setDeptEmployees([]);
    setDeptEmpLoading(false);
    setCompareResult(null);
    setCompareLoading(false);
    if (type === "promote") {
      const idx = GRADE_ORDER.indexOf(emp.GRADE);
      setDialogToGrade(idx > 0 ? GRADE_ORDER[idx - 1] : emp.GRADE);
    } else {
      setDialogToGrade("");
    }
    setDialogToDept("");
    setDialogOpen(true);
  };

  const fetchVacancyCandidates = useCallback((deptId: number, grade: string, opts?: {minScore?: number; minTenure?: number; entryType?: string; deptFilter?: string; managerId?: string}) => {
    setVacancyCandidatesLoading(true);
    setVacancyCandidates([]);
    const qs = new URLSearchParams({
      dept_id: String(deptId), grade, limit: "20",
      ...(opts?.minScore ? { min_score: String(opts.minScore) } : {}),
      ...(opts?.minTenure ? { min_tenure: String(opts.minTenure) } : {}),
      ...(opts?.entryType ? { entry_type: opts.entryType } : {}),
      ...(opts?.deptFilter ? { dept_filter: opts.deptFilter } : {}),
      ...(opts?.managerId ? { manager_id: opts.managerId } : {}),
    });
    fetch(`/api/simulation/candidates?${qs}`)
      .then((r) => { if (!r.ok) throw new Error("Failed"); return r.json(); })
      .then(setVacancyCandidates)
      .catch((err) => console.error("[vacancy candidates fetch] failed:", err))
      .finally(() => setVacancyCandidatesLoading(false));
  }, []);

  const openVacancyCandidates = useCallback((grade: string, deptId: number, deptName: string, label: string) => {
    setVacancyTarget({ grade, deptId, deptName, label });
    setVacancySearch("");
    setVcFilterMinScore(0);
    setVcFilterMinTenure(0);
    setVcFilterEntryType("");
    setVcFilterDept("");
    setVcFilterManager("");
    setVcShowFilters(false);
    setVacancyCandidatesOpen(true);
    fetchVacancyCandidates(deptId, grade);
  }, [fetchVacancyCandidates]);

  const filteredVacancyCandidates = useMemo(() => {
    // Someone already moved in this scenario cannot be moved again
    const available = vacancyCandidates.filter((c) => !actionedEmpIds.has(c.EMPLOYEE_ID));
    if (!vacancySearch) return available;
    const q = vacancySearch.toLowerCase();
    return available.filter((c) =>
      c.NAME.toLowerCase().includes(q) ||
      c.DEPT_NAME.toLowerCase().includes(q) ||
      c.POSITION_TITLE.toLowerCase().includes(q) ||
      c.GRADE.toLowerCase().includes(q)
    );
  }, [vacancyCandidates, vacancySearch, actionedEmpIds]);

  const fetchDeptEmployees = useCallback((dId: number, gradeFilter?: string) => {
    setDeptEmpLoading(true);
    setDeptEmployees([]);
    const params = new URLSearchParams({ dept_id: String(dId) });
    if (gradeFilter) params.set("grade", gradeFilter);
    fetch(`/api/simulation/dept-employees?${params}`)
      .then((r) => { if (!r.ok) throw new Error("Failed"); return r.json(); })
      .then(setDeptEmployees)
      .catch((err) => console.error("Dept employees error:", err))
      .finally(() => setDeptEmpLoading(false));
  }, []);

  const runCompare = useCallback((empId: number, dId: number) => {
    setCompareLoading(true);
    setCompareResult(null);
    fetch(`/api/simulation/compare?employee_id=${empId}&to_dept_id=${dId}`)
      .then((r) => {
        if (!r.ok) throw new Error(`Compare API error: ${r.status}`);
        return r.json();
      })
      .then(setCompareResult)
      .catch((err) => console.error("Compare error:", err))
      .finally(() => setCompareLoading(false));
  }, []);

  const handleDeptChange = (v: string | null) => {
    if (!v) return;
    setDialogToDept(v);
    setMatchResult(null);
    setMatchLoading(false);
    setCompareResult(null);
    setCompareLoading(false);
    fetchDeptEmployees(Number(v), dialogEmployee?.GRADE);
  };

  const addAction = () => {
    if (!dialogEmployee) return;
    const emp = dialogEmployee;
    const newAction: SimAction = {
      id: `${Date.now()}-${emp.EMPLOYEE_ID}`,
      type: dialogType,
      employee: emp,
      fromGrade: emp.GRADE,
      fromDeptId: emp.DEPT_ID,
      fromDeptName: emp.DEPT_NAME,
    };
    if (dialogType === "promote") {
      newAction.toGrade = dialogToGrade;
      newAction.toDeptId = emp.DEPT_ID;
      newAction.toDeptName = emp.DEPT_NAME;
    } else if (dialogType === "transfer") {
      const toDeptId = Number(dialogToDept);
      if (!toDeptId) return;
      newAction.toGrade = emp.GRADE;
      newAction.toDeptId = toDeptId;
      const td = allDeptsList.find((d) => d.DEPT_ID === toDeptId) || departments.find((d) => d.DEPT_ID === toDeptId);
      newAction.toDeptName = td?.DEPT_NAME || `部署${toDeptId}`;
      if (matchResult) {
        newAction.matchScore = matchResult.matchScore;
        newAction.matchReason = compareResult?.aiComparison || matchResult.reason;
      } else if (compareResult) {
        newAction.matchReason = compareResult.aiComparison;
      }
    }
    setActions((prev) => [...prev, newAction]);
    setDialogOpen(false);
  };

  // チェーンの途中の手を消すと、その人が空けた席がなくなり後続の手が
  // 「枠なし」になる。黙って赤くせず、後続があれば削除前に確認する。
  const [pendingRemove, setPendingRemove] = useState<{ id: string; dependents: string[] } | null>(null);

  const dependentsOf = (id: string): string[] => {
    const chain = chains.find((c) => c.some((st) => st.actionId === id));
    if (!chain) return [];
    const idx = chain.findIndex((st) => st.actionId === id);
    return chain.slice(idx + 1).map((st) => st.actionId);
  };

  const removeAction = (id: string) => {
    const dependents = dependentsOf(id);
    if (dependents.length > 0) {
      setPendingRemove({ id, dependents });
      return;
    }
    setActions((prev) => prev.filter((a) => a.id !== id));
  };

  const confirmRemove = (withDependents: boolean) => {
    if (!pendingRemove) return;
    const drop = new Set([pendingRemove.id, ...(withDependents ? pendingRemove.dependents : [])]);
    setActions((prev) => prev.filter((a) => !drop.has(a.id)));
    setPendingRemove(null);
  };

  const resetAll = () => {
    setActions([]);
    setSaved(false);
    setSaveError(null);
    setSavedScenarioId(null);
    setSubmitted(false);
  };

  const saveScenario = async () => {
    if (actions.length === 0) return;
    setSaving(true);
    setSaveError(null);
    try {
      const res = await fetch("/api/simulation/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scenarioName: `What-if ${new Date().toLocaleDateString("ja-JP")} ${honbuList.find((d) => String(d.DEPT_ID) === honbu)?.DEPT_NAME || ""}`,
          honbuDeptId: Number(honbu),
          actions: actions.map((a) => ({
            type: a.type,
            employeeId: a.employee.EMPLOYEE_ID,
            employeeName: a.employee.NAME,
            fromGrade: a.fromGrade,
            toGrade: a.toGrade || null,
            fromDeptId: a.fromDeptId,
            toDeptId: a.toDeptId || null,
            fromDeptName: a.fromDeptName,
            toDeptName: a.toDeptName || null,
            matchScore: a.matchScore || null,
            matchReason: a.matchReason || null,
          })),
        }),
      });
      if (res.ok) {
        const data = await res.json();
        setSaved(true);
        setSavedScenarioId(data.scenarioId);
        console.log("Scenario saved:", data.scenarioId, data.actionCount, "actions");
      } else {
        const errBody = await res.json().catch(() => null);
        setSaveError(errBody?.error || `保存に失敗しました (${res.status})`);
      }
    } catch (e) {
      setSaveError("ネットワークエラー: 保存に失敗しました");
      console.error("Save scenario error:", e);
    } finally {
      setSaving(false);
    }
  };

  if (loading && departments.length === 0) {
    return (
      <div className="p-6 space-y-4">
        <h2 className="text-2xl font-bold">異動シナリオ作成</h2>
        <Skeleton className="h-[600px]" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-4 h-full flex flex-col">
      <div className="flex items-center gap-4 flex-wrap shrink-0">
        <h2 className="text-2xl font-bold tracking-tight">
          異動シナリオ作成
        </h2>
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
        <Badge variant="outline" className="text-xs">
          <Users className="h-3 w-3 mr-1" />
          {allEmployees.length.toLocaleString()}名
        </Badge>
        {ledger.open.length > 0 && (
          <Badge variant="outline" className="text-xs text-amber-600 border-amber-300">
            <AlertTriangle className="h-3 w-3 mr-1" />
            未充足の空席 {ledger.open.length}件
          </Badge>
        )}
        <div className="ml-auto flex gap-2">
          <Button variant="outline" size="sm" className="gap-1.5" onClick={() => { setScenariosOpen(true); loadScenariosList(); }}>
            <FolderOpen className="h-3.5 w-3.5" />
            保存済みシナリオ
          </Button>
          {compareMode && (
            <Button variant="outline" size="sm" className="gap-1.5" onClick={() => { setCompareMode(false); setCompareScenario(null); }}>
              <X className="h-3.5 w-3.5" />
              比較終了
            </Button>
          )}
        </div>
      </div>

      {incomingContext && (
        <div className="flex items-start gap-3 px-4 py-3 rounded-lg border border-red-200 bg-red-50/60 text-sm shrink-0">
          <AlertTriangle className="h-4 w-4 text-red-600 mt-0.5 shrink-0" />
          <div className="flex-1 min-w-0 space-y-1">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-medium">{incomingContext.name}</span>
              <span className="text-muted-foreground text-xs">の離職リスク対応として遷移</span>
              {incomingContext.riskScore != null && (
                <Badge variant={incomingContext.riskLabel === "high" ? "destructive" : "default"} className="text-[10px]">
                  リスク {(Number(incomingContext.riskScore) * 100).toFixed(0)}%
                  {incomingContext.riskLabel === "high" ? " (高)" : incomingContext.riskLabel === "medium" ? " (中)" : ""}
                </Badge>
              )}
            </div>
            {incomingContext.topFactors.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                <span className="text-[11px] text-muted-foreground">主要因:</span>
                {incomingContext.topFactors.map((f, i) => (
                  <span key={i} className="inline-flex items-center px-1.5 py-0.5 rounded bg-red-100 text-red-700 text-[10px]">
                    {FEATURE_LABELS[f.name] || f.name} ({f.value > 0 ? "+" : ""}{f.value.toFixed(2)})
                  </span>
                ))}
              </div>
            )}
            {incomingContext.evidenceSummary && (
              <p className="text-xs text-muted-foreground line-clamp-2">{incomingContext.evidenceSummary}</p>
            )}
          </div>
          <Link href={`/employees/${incomingContext.employeeId}`} className="shrink-0">
            <Button variant="outline" size="sm" className="text-xs h-7">社員詳細</Button>
          </Link>
          <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0" onClick={() => setIncomingContext(null)}>
            <X className="h-3.5 w-3.5" />
          </Button>
        </div>
      )}

      {loadedScenarioId && loadedScenarioStatus && (
        <div className={`flex items-center gap-3 px-4 py-2 rounded-lg border text-sm ${
          loadedScenarioStatus === "revision_requested" ? "bg-red-50 border-red-200" :
          loadedScenarioStatus === "approved" ? "bg-green-50 border-green-200" :
          loadedScenarioStatus === "pending_review" ? "bg-yellow-50 border-yellow-200" :
          "bg-muted/50 border-border"
        }`}>
          <span className="font-medium truncate">{loadedScenarioName}</span>
          <Badge variant="secondary" className={`text-[10px] shrink-0 ${
            loadedScenarioStatus === "pending_review" ? "bg-yellow-100 text-yellow-700" :
            loadedScenarioStatus === "revision_requested" ? "bg-red-100 text-red-700" :
            loadedScenarioStatus === "approved" ? "bg-green-100 text-green-700" :
            "bg-gray-100 text-gray-700"
          }`}>
            {loadedScenarioStatus === "draft" ? "下書き" :
             loadedScenarioStatus === "pending_review" ? "レビュー待ち" :
             loadedScenarioStatus === "revision_requested" ? "差し戻しあり" :
             loadedScenarioStatus === "approved" ? "承認済み" :
             loadedScenarioStatus === "confirmed" ? "確定済み" : loadedScenarioStatus}
          </Badge>
          {loadedScenarioStatus === "pending_review" && (
            <Link href="/review" className="text-xs text-blue-600 hover:underline ml-auto shrink-0">レビュー状況を見る →</Link>
          )}
          {loadedScenarioStatus === "revision_requested" && loadedRejectedComments.length > 0 && (
            <span className="text-xs text-red-600 truncate ml-2">
              {loadedRejectedComments[0].employee_name}: {loadedRejectedComments[0].comment}
            </span>
          )}
          {loadedScenarioStatus === "approved" && (
            <Button size="sm" variant="default" className="ml-auto shrink-0 bg-green-600 hover:bg-green-700" onClick={() => {
              setConfirmLabel(loadedScenarioName || "");
              setConfirmDate(new Date().toISOString().slice(0, 10));
              setConfirmDialogOpen(true);
            }}>
              <Archive className="h-3.5 w-3.5 mr-1" />
              確定（スナップショット保存）
            </Button>
          )}
        </div>
      )}
      <div className="flex-1 flex gap-4 min-h-0">
        <div className="w-[300px] shrink-0 flex flex-col gap-3">
          <Card className="flex-1 flex flex-col min-h-0">
            <CardHeader className="pb-2 shrink-0">
              <CardTitle className="text-sm flex items-center gap-2">
                <GitBranch className="h-4 w-4" />
                部署階層
              </CardTitle>
            </CardHeader>
            <CardContent className="flex-1 min-h-0 p-2">
              <ScrollArea className="h-full">
                {honbuDept && (
                  <DeptTreeNode
                    dept={honbuDept}
                    childDepts={childDepts}
                    selectedDeptId={selectedDept?.DEPT_ID ?? null}
                    onSelect={setSelectedDept}
                    affectedDeptIds={affectedDeptIds}
                  />
                )}
                {!honbuDept && childDepts.length > 0 &&
                  childDepts
                    .filter((d) => d.PARENT_DEPT_ID === Number(honbu))
                    .map((d) => (
                      <DeptTreeNode
                        key={d.DEPT_ID}
                        dept={d}
                        childDepts={childDepts}
                        selectedDeptId={selectedDept?.DEPT_ID ?? null}
                        onSelect={setSelectedDept}
                        affectedDeptIds={affectedDeptIds}
                      />
                    ))}
              </ScrollArea>
            </CardContent>
          </Card>

          {selectedDept && (
            <Card className="max-h-[45%] flex flex-col min-h-0">
              <CardHeader className="pb-2 shrink-0">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm flex items-center gap-1.5">
                    <Users className="h-4 w-4" />
                    {selectedDept.DEPT_NAME}
                  </CardTitle>
                  <Badge variant="secondary" className="text-[10px]">
                    {selectedDeptEmps.length}名
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="flex-1 min-h-0 p-2">
                <ScrollArea className="h-full">
                  <div className="space-y-1 pr-2">
                    {selectedDeptEmps.map((emp) => (
                      <EmployeeCard
                        key={emp.EMPLOYEE_ID}
                        emp={emp}
                        isActioned={actionedEmpIds.has(emp.EMPLOYEE_ID)}
                        actionBadge={getActionBadge(emp.EMPLOYEE_ID)}
                        onClick={() => {
                          if (!actionedEmpIds.has(emp.EMPLOYEE_ID)) {
                            openActionDialog("promote", emp);
                          }
                        }}
                      />
                    ))}
                  </div>
                </ScrollArea>
              </CardContent>
            </Card>
          )}
        </div>

        <Separator orientation="vertical" />

        <div className="flex-1 min-w-0 flex flex-col gap-3">
          <div className="flex items-center justify-between shrink-0">
            <div className="flex items-center gap-2">
              <h3 className="text-base font-semibold">What-if シナリオ</h3>
              <StepGuide
                step={actions.length === 0 ? 1 : ledger.open.some((sl) => sl.source === "generated") ? 2 : 3}
              />
            </div>
            {actions.length > 0 && (
              <div className="flex items-center gap-2">
                {!saved ? (
                  <Button
                    size="sm"
                    onClick={saveScenario}
                    disabled={saving || ledger.overfills.length > 0}
                    title={ledger.overfills.length > 0 ? "枠のない異動があるため保存できません" : undefined}
                  >
                    {saving ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <Save className="h-3.5 w-3.5 mr-1" />}
                    確定・保存
                  </Button>
                ) : (
                  <div className="flex items-center gap-2">
                    <Badge className="bg-green-600 text-sm py-1 px-3">
                      <CheckCircle2 className="h-3.5 w-3.5 mr-1" />
                      保存完了
                    </Badge>
                    {!submitted && savedScenarioId && (
                      <Button
                        size="sm"
                        variant="default"
                        disabled={submitLoading}
                        onClick={async () => {
                          setSubmitLoading(true);
                          try {
                            const res = await fetch("/api/simulation/submit", {
                              method: "POST",
                              headers: { "Content-Type": "application/json" },
                              body: JSON.stringify({ scenarioId: savedScenarioId }),
                            });
                            if (res.ok) setSubmitted(true);
                          } finally {
                            setSubmitLoading(false);
                          }
                        }}
                      >
                        {submitLoading ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <Send className="h-3.5 w-3.5 mr-1" />}
                        レビュー依頼
                      </Button>
                    )}
                    {submitted && (
                      <Badge className="bg-yellow-500 text-sm py-1 px-3">
                        <Send className="h-3.5 w-3.5 mr-1" />
                        レビュー依頼済み
                      </Badge>
                    )}
                  </div>
                )}
                <Button variant="outline" size="sm" onClick={resetAll}>
                  <Undo2 className="h-3 w-3 mr-1" />
                  リセット
                </Button>
                {saveError && (
                  <span className="text-xs text-red-600 flex items-center gap-1">
                    <XCircle className="h-3 w-3" />{saveError}
                  </span>
                )}
              </div>
            )}
          </div>

          {actions.length === 0 ? (
            <Card className="flex-1 flex items-center justify-center">
              <div className="space-y-4 text-muted-foreground max-w-md px-6">
                <div className="text-center">
                  <Shuffle className="h-10 w-10 mx-auto opacity-30 mb-2" />
                  <p className="text-sm font-semibold text-foreground">What-if シナリオ分析</p>
                  <p className="text-xs mt-1">昇格・異動・退職のシミュレーションを作成し、コスト・等級構成への影響を分析できます</p>
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div className="flex items-start gap-2 p-2 rounded-lg bg-muted/50">
                    <GitBranch className="h-4 w-4 shrink-0 mt-0.5 text-blue-500" />
                    <div><p className="font-medium text-foreground">1. 部署を選択</p><p>左のツリーで対象部署を選択</p></div>
                  </div>
                  <div className="flex items-start gap-2 p-2 rounded-lg bg-muted/50">
                    <Users className="h-4 w-4 shrink-0 mt-0.5 text-green-500" />
                    <div><p className="font-medium text-foreground">2. 社員を選択</p><p>社員カードをクリック</p></div>
                  </div>
                  <div className="flex items-start gap-2 p-2 rounded-lg bg-muted/50">
                    <ArrowUp className="h-4 w-4 shrink-0 mt-0.5 text-purple-500" />
                    <div><p className="font-medium text-foreground">3. アクション追加</p><p>昇格・異動・退職を選択</p></div>
                  </div>
                  <div className="flex items-start gap-2 p-2 rounded-lg bg-muted/50">
                    <BarChart3 className="h-4 w-4 shrink-0 mt-0.5 text-amber-500" />
                    <div><p className="font-medium text-foreground">4. 影響分析</p><p>コスト・等級・部署変動を確認</p></div>
                  </div>
                </div>
              </div>
            </Card>
          ) : (
            <ScrollArea className="flex-1">
              <div className="space-y-3 pr-2">
                {ledger.overfills.length > 0 && (
                  <div className="flex items-start gap-2 rounded-lg border border-red-300 bg-red-50 p-3 text-xs text-red-800">
                    <XCircle className="h-4 w-4 shrink-0 mt-0.5" />
                    <div>
                      <p className="font-semibold">空いていない枠への異動があります（保存できません）</p>
                      <ul className="mt-1 space-y-0.5">
                        {ledger.overfills.map((o) => (
                          <li key={o.actionId}>
                            {o.employeeName} → {o.deptName} {o.grade}：この枠は既に埋まっているか、もともと空いていません
                          </li>
                        ))}
                      </ul>
                      <p className="mt-1 text-red-700/80">該当のアクションを削除してください。</p>
                    </div>
                  </div>
                )}
                {chains.map((chain, ci) => {
                  const last = actions.find((x) => x.id === chain[chain.length - 1].actionId);
                  const tailOpen = last ? ledger.open.find((sl) => sl.openedBy === last.id) : undefined;
                  return (
                    <div key={chain[0].actionId} className="rounded-xl border bg-card">
                      <div className="flex items-center gap-2 px-3 py-2 border-b bg-muted/30 rounded-t-xl">
                        <span className="text-xs font-semibold">チェーン {ci + 1}</span>
                        <span className="text-[11px] text-muted-foreground">{chain.length}手</span>
                        {tailOpen ? (
                          <Badge variant="outline" className="ml-auto text-[10px] border-amber-300 text-amber-700">
                            <CircleDashed className="h-3 w-3 mr-0.5" />未完了：空席が残っています
                          </Badge>
                        ) : (
                          <Badge variant="outline" className="ml-auto text-[10px] border-green-300 text-green-700">
                            <CheckCircle2 className="h-3 w-3 mr-0.5" />完結
                          </Badge>
                        )}
                      </div>
                      <div className="p-2 space-y-1">
                        {chain.map((step, si) => {
                          const a = actions.find((x) => x.id === step.actionId);
                          if (!a) return null;
                          const meta = ACTION_LABELS[a.type];
                          const Icon = meta.icon;
                          const over = overfillByAction.get(a.id);
                          return (
                            <div key={a.id} className={si > 0 ? "ml-5 border-l-2 border-dashed border-muted pl-3" : ""}>
                              {step.filled && (
                                <p className="text-[10px] text-muted-foreground flex items-center gap-1 py-0.5">
                                  <CornerDownRight className="h-3 w-3" />
                                  {step.filled.deptName} {step.filled.grade} の空席を埋める
                                </p>
                              )}
                              <div className={`flex items-start gap-2 rounded-lg border p-2 ${over ? "border-red-300 bg-red-50" : meta.color}`}>
                                <Badge variant="outline" className={`text-[10px] shrink-0 mt-0.5 ${meta.color}`}>
                                  <Icon className="h-3 w-3 mr-0.5" />{meta.label}
                                </Badge>
                                <div className="min-w-0 flex-1">
                                  <div className="flex items-center gap-2">
                                    <p className="text-sm font-medium truncate">{a.employee.NAME}</p>
                                    {a.type === "transfer" && a.matchScore !== undefined && (
                                      <Badge variant="outline" className={`text-[10px] shrink-0 ${scoreColor(a.matchScore)}`}>
                                        <Target className="h-3 w-3 mr-0.5" />適合 {a.matchScore}%
                                      </Badge>
                                    )}
                                  </div>
                                  <p className="text-xs text-muted-foreground">
                                    {a.type === "promote" && (<>{a.fromDeptName}：{a.fromGrade} → <span className="font-medium text-green-700">{a.toGrade}（{GRADE_LABELS[a.toGrade || ""]}）</span></>)}
                                    {a.type === "transfer" && (<>{a.fromDeptName} → <span className="font-medium text-blue-700">{a.toDeptName}</span>（{a.toGrade && a.toGrade !== a.fromGrade ? <>{a.fromGrade} → <span className="font-medium text-green-700">{a.toGrade}</span> 昇格を伴う</> : a.fromGrade}）</>)}
                                    {a.type === "retire" && (<>{a.fromDeptName}：{a.fromGrade}（{GRADE_LABELS[a.fromGrade]}）</>)}
                                  </p>
                                  {over && <p className="text-[11px] text-red-700 mt-0.5">この枠は空いていません</p>}
                                  {a.type === "transfer" && a.matchReason && (
                                    <div className="prose prose-xs max-w-none dark:prose-invert text-[11px] text-muted-foreground mt-1 line-clamp-2">
                                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{a.matchReason}</ReactMarkdown>
                                    </div>
                                  )}
                                </div>
                                <Button variant="ghost" size="icon" className="h-6 w-6 shrink-0" title="このアクションを削除" onClick={() => removeAction(a.id)}>
                                  <X className="h-3 w-3" />
                                </Button>
                              </div>
                            </div>
                          );
                        })}
                        {tailOpen && (
                          <button
                            className="ml-5 flex w-[calc(100%-1.25rem)] items-center gap-2 rounded-lg border-2 border-dashed border-amber-300 bg-amber-50/60 px-3 py-2 text-xs text-amber-800 hover:bg-amber-100 transition-colors"
                            onClick={() => openVacancyCandidates(tailOpen.grade, tailOpen.deptId, tailOpen.deptName, `${tailOpen.deptName} ${tailOpen.grade}（${tailOpen.origin}）`)}
                          >
                            <CircleDashed className="h-4 w-4" />
                            <span><strong>{tailOpen.deptName} {tailOpen.grade}</strong> が空席のまま — クリックして後任を選ぶ</span>
                            <Search className="h-3.5 w-3.5 ml-auto" />
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </ScrollArea>
          )}

          {(ledger.open.length > 0 || ledger.filled.length > 0) && (
            <Card className="shrink-0 border-amber-200 bg-amber-50/50">
              <button
                className="w-full flex items-center gap-2 px-4 py-2.5 text-left"
                onClick={() => setVacancyExpanded((p) => !p)}
              >
                <AlertTriangle className="h-4 w-4 text-amber-700 shrink-0" />
                <span className="text-sm font-semibold text-amber-700">空席ポジション</span>
                <Badge variant="outline" className="text-[10px] border-amber-300">未充足 {ledger.open.length}</Badge>
                {ledger.filled.length > 0 && (
                  <Badge variant="outline" className="text-[10px] border-green-300 text-green-700">充足済み {ledger.filled.length}</Badge>
                )}
                {!vacancyExpanded && vacancyGradeSummary.length > 0 && (
                  <span className="text-[10px] text-muted-foreground ml-1 truncate">({vacancyGradeSummary.join(", ")})</span>
                )}
                {vacancyExpanded ? (
                  <ChevronUp className="h-4 w-4 ml-auto text-amber-600 shrink-0" />
                ) : (
                  <ChevronDown className="h-4 w-4 ml-auto text-amber-600 shrink-0" />
                )}
              </button>
              {vacancyExpanded && (
                <CardContent className="p-2 pt-0">
                  <ScrollArea className="max-h-[180px]">
                    <div className="space-y-1 pr-2">
                      {[...openGenerated, ...openExisting].map((v) => (
                        <button
                          key={v.id}
                          className={`w-full flex items-center gap-2 p-1.5 rounded border bg-white text-xs hover:bg-amber-50 hover:shadow-sm transition-all cursor-pointer text-left ${
                            v.source === "generated" ? "border-amber-300" : "border-dashed border-gray-300"
                          }`}
                          onClick={() => openVacancyCandidates(v.grade, v.deptId, v.deptName, `${v.deptName} ${v.grade}（${v.origin}）`)}
                        >
                          <Badge variant="outline" className={`text-[9px] shrink-0 ${GRADE_BG[v.grade] || ""}`}>{v.grade}</Badge>
                          <span className="truncate font-medium">{v.deptName}</span>
                          <span className="text-muted-foreground truncate">{v.origin}</span>
                          <span className="ml-auto shrink-0 text-amber-700 flex items-center gap-1">後任を選ぶ<Search className="h-3 w-3" /></span>
                        </button>
                      ))}
                      {ledger.filled.map((v) => (
                        <div
                          key={v.id}
                          className="w-full flex items-center gap-2 p-1.5 rounded border border-green-200 bg-green-50/60 text-xs text-muted-foreground"
                          title="このシナリオ内で既に埋まっています"
                        >
                          <Badge variant="outline" className={`text-[9px] shrink-0 opacity-60 ${GRADE_BG[v.grade] || ""}`}>{v.grade}</Badge>
                          <span className="truncate line-through">{v.deptName}</span>
                          <span className="truncate">{v.origin}</span>
                          <span className="ml-auto shrink-0 text-green-700 flex items-center gap-1">
                            <CheckCircle2 className="h-3 w-3" />{v.filledByName} が充足
                          </span>
                        </div>
                      ))}
                    </div>
                  </ScrollArea>
                </CardContent>
              )}
            </Card>
          )}

          {actions.length > 0 && (() => {
            // A transfer into a higher-grade seat is also a promotion
            const isGradeUp = (a: SimAction) => a.type !== "retire" && !!a.toGrade && a.toGrade !== a.fromGrade;
            const promotions = actions.filter(isGradeUp);
            const transfers = actions.filter((a) => a.type === "transfer");
            const retires = actions.filter((a) => a.type === "retire");

            const costImpact = actions.reduce((sum, a) => {
              const salary = a.employee.SALARY || GRADE_AVG_SALARY[a.fromGrade] || 0;
              if (isGradeUp(a) && a.toGrade) {
                return sum + (GRADE_AVG_SALARY[a.toGrade] || 0) - salary;
              }
              if (a.type === "retire") {
                return sum - salary;
              }
              return sum;
            }, 0);

            const gradeBefore: Record<string, number> = {};
            const gradeAfter: Record<string, number> = {};
            allEmployees.forEach((e) => {
              gradeBefore[e.GRADE] = (gradeBefore[e.GRADE] || 0) + 1;
              gradeAfter[e.GRADE] = (gradeAfter[e.GRADE] || 0) + 1;
            });
            actions.forEach((a) => {
              if (isGradeUp(a) && a.toGrade) {
                gradeAfter[a.fromGrade] = (gradeAfter[a.fromGrade] || 0) - 1;
                gradeAfter[a.toGrade] = (gradeAfter[a.toGrade] || 0) + 1;
              } else if (a.type === "retire") {
                gradeAfter[a.fromGrade] = (gradeAfter[a.fromGrade] || 0) - 1;
              }
            });

            const deptChanges: Record<string, { name: string; delta: number }> = {};
            actions.forEach((a) => {
              if (a.type === "transfer") {
                const fk = String(a.fromDeptId);
                if (!deptChanges[fk]) deptChanges[fk] = { name: a.fromDeptName, delta: 0 };
                deptChanges[fk].delta -= 1;
                if (a.toDeptId) {
                  const tk = String(a.toDeptId);
                  if (!deptChanges[tk]) deptChanges[tk] = { name: a.toDeptName || "", delta: 0 };
                  deptChanges[tk].delta += 1;
                }
              } else if (a.type === "retire") {
                const fk = String(a.fromDeptId);
                if (!deptChanges[fk]) deptChanges[fk] = { name: a.fromDeptName, delta: 0 };
                deptChanges[fk].delta -= 1;
              }
            });
            const deptChangeList = Object.entries(deptChanges).filter(([, v]) => v.delta !== 0).sort((a, b) => a[1].delta - b[1].delta);

            return (
              <div className="shrink-0 space-y-2">
                <Card>
                  <CardContent className="p-3">
                    <div className="flex items-center gap-3 text-sm flex-wrap">
                      <span className="text-muted-foreground font-medium">影響分析</span>
                      <Badge variant="secondary" className="gap-1">
                        <ArrowUp className="h-3 w-3 text-green-600" />
                        昇格 {promotions.length}
                      </Badge>
                      <Badge variant="secondary" className="gap-1">
                        <Shuffle className="h-3 w-3 text-blue-600" />
                        異動 {transfers.length}
                      </Badge>
                      <Badge variant="secondary" className="gap-1">
                        <UserMinus className="h-3 w-3 text-red-600" />
                        退職 {retires.length}
                      </Badge>
                      <Badge variant="secondary" className="text-amber-700 bg-amber-100 gap-1">
                        <AlertTriangle className="h-3 w-3" />
                        未充足 {ledger.open.length}
                      </Badge>
                    </div>
                  </CardContent>
                </Card>

                <div className="grid grid-cols-2 gap-2">
                  <Card>
                    <CardContent className="p-3">
                      <p className="text-[11px] text-muted-foreground flex items-center gap-1 mb-1">
                        <DollarSign className="h-3 w-3" />
                        年間コストインパクト
                      </p>
                      <p className={`text-lg font-bold ${costImpact > 0 ? "text-red-600" : costImpact < 0 ? "text-green-600" : "text-muted-foreground"}`}>
                        {costImpact > 0 ? "+" : ""}{formatYen(costImpact)}
                      </p>
                      <div className="text-[10px] text-muted-foreground mt-1 space-y-0.5">
                        {promotions.length > 0 && (
                          <p className="text-red-500">昇格コスト: +{formatYen(promotions.reduce((s, a) => s + ((GRADE_AVG_SALARY[a.toGrade || ""] || 0) - (a.employee.SALARY || GRADE_AVG_SALARY[a.fromGrade] || 0)), 0))}</p>
                        )}
                        {retires.length > 0 && (
                          <p className="text-green-600">退職削減: -{formatYen(retires.reduce((s, a) => s + (a.employee.SALARY || GRADE_AVG_SALARY[a.fromGrade] || 0), 0))}</p>
                        )}
                      </div>
                    </CardContent>
                  </Card>

                  <Card>
                    <CardContent className="p-3">
                      <p className="text-[11px] text-muted-foreground flex items-center gap-1 mb-1">
                        <BarChart3 className="h-3 w-3" />
                        部署ヘッドカウント変動
                      </p>
                      {deptChangeList.length === 0 ? (
                        <p className="text-xs text-muted-foreground">変動なし</p>
                      ) : (
                        <div className="space-y-1 max-h-[80px] overflow-y-auto">
                          {deptChangeList.map(([k, v]) => (
                            <div key={k} className="flex items-center justify-between text-xs">
                              <span className="truncate mr-2">{v.name}</span>
                              <Badge variant="outline" className={`text-[10px] shrink-0 ${v.delta > 0 ? "text-green-700 bg-green-50 border-green-300" : "text-red-700 bg-red-50 border-red-300"}`}>
                                {v.delta > 0 ? <TrendingUp className="h-2.5 w-2.5 mr-0.5" /> : <TrendingDown className="h-2.5 w-2.5 mr-0.5" />}
                                {v.delta > 0 ? "+" : ""}{v.delta}名
                              </Badge>
                            </div>
                          ))}
                        </div>
                      )}
                    </CardContent>
                  </Card>
                </div>

                {GRADE_ORDER.some((g) => (gradeBefore[g] || 0) !== (gradeAfter[g] || 0)) && (
                  <Card>
                    <CardContent className="p-3">
                      <p className="text-[11px] text-muted-foreground flex items-center gap-1 mb-2">
                        <BarChart3 className="h-3 w-3" />
                        等級構成の変化
                      </p>
                      <div className="space-y-1">
                        {GRADE_ORDER.filter((g) => (gradeBefore[g] || 0) > 0 || (gradeAfter[g] || 0) > 0).map((g) => {
                          const before = gradeBefore[g] || 0;
                          const after = gradeAfter[g] || 0;
                          const diff = after - before;
                          const maxVal = Math.max(...GRADE_ORDER.map((gr) => Math.max(gradeBefore[gr] || 0, gradeAfter[gr] || 0)), 1);
                          return (
                            <div key={g} className="flex items-center gap-2 text-xs">
                              <Badge variant="outline" className={`text-[9px] w-8 justify-center shrink-0 ${GRADE_BG[g] || ""}`}>{g}</Badge>
                              <div className="flex-1 flex items-center gap-1">
                                <div className="flex-1 h-3 bg-gray-100 rounded-full overflow-hidden relative">
                                  <div className="absolute inset-y-0 left-0 bg-gray-300 rounded-full" style={{ width: `${(before / maxVal) * 100}%` }} />
                                  <div className={`absolute inset-y-0 left-0 rounded-full ${diff > 0 ? "bg-green-400" : diff < 0 ? "bg-red-400" : "bg-gray-400"}`} style={{ width: `${(after / maxVal) * 100}%` }} />
                                </div>
                              </div>
                              <span className="w-8 text-right text-muted-foreground">{before}</span>
                              {diff !== 0 && (
                                <span className={`w-10 text-right font-medium ${diff > 0 ? "text-green-600" : "text-red-600"}`}>
                                  →{after}
                                </span>
                              )}
                              {diff === 0 && <span className="w-10" />}
                            </div>
                          );
                        })}
                      </div>
                    </CardContent>
                  </Card>
                )}
              </div>
            );
          })()}

          <Card className="shrink-0">
            <CardContent className="p-3">
              <div className="flex flex-wrap gap-2">
                {GRADE_ORDER.map((grade) => (
                  <Badge
                    key={grade}
                    variant="outline"
                    className={`text-[10px] ${GRADE_BG[grade] || ""}`}
                  >
                    {grade}: {GRADE_LABELS[grade]}
                  </Badge>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>

      <Dialog open={!!pendingRemove} onOpenChange={(o) => !o && setPendingRemove(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-sm">後続の手があります</DialogTitle>
            <DialogDescription>
              {(() => {
                const target = actions.find((a) => a.id === pendingRemove?.id);
                return target ? `${target.employee.NAME}のアクションを削除すると、その人が空けた席がなくなります。` : "";
              })()}
              以下の手は埋める席がなくなるため、残すと保存できません。
            </DialogDescription>
          </DialogHeader>
          <ul className="text-xs space-y-1 rounded-md border bg-muted/40 p-2">
            {pendingRemove?.dependents.map((id) => {
              const a = actions.find((x) => x.id === id);
              if (!a) return null;
              return (
                <li key={id} className="flex items-center gap-2">
                  <Badge variant="outline" className={`text-[10px] ${ACTION_LABELS[a.type].color}`}>{ACTION_LABELS[a.type].label}</Badge>
                  <span>{a.employee.NAME}</span>
                  <span className="text-muted-foreground">{a.fromDeptName} → {a.toDeptName ?? a.fromDeptName}</span>
                </li>
              );
            })}
          </ul>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" size="sm" onClick={() => setPendingRemove(null)}>キャンセル</Button>
            <Button variant="outline" size="sm" onClick={() => confirmRemove(false)}>この手だけ削除</Button>
            <Button variant="destructive" size="sm" onClick={() => confirmRemove(true)}>
              以降の{pendingRemove?.dependents.length}手も削除
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={vacancyCandidatesOpen} onOpenChange={setVacancyCandidatesOpen}>
        <DialogContent className="sm:max-w-2xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-sm">
              <Target className="h-4 w-4" />
              後任を選ぶ：{vacancyTarget?.deptName} {vacancyTarget?.grade}
            </DialogTitle>
            <DialogDescription>
              {vacancyTarget?.label}。AI推薦スコア順（スキル適合50% + 評価30% + 勤続20%）。
              このシナリオで既に動かしている社員は候補から除外しています。選んだ人の元の席は新たな空席になります。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="flex gap-2">
              <div className="relative flex-1">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                <input
                  type="text"
                  placeholder="社員名・部署名・役職で検索..."
                  className="w-full pl-8 pr-3 py-2 text-sm border rounded-md"
                  value={vacancySearch}
                  onChange={(e) => setVacancySearch(e.target.value)}
                />
              </div>
              <Button variant={vcShowFilters ? "default" : "outline"} size="sm" className="gap-1 shrink-0" onClick={() => setVcShowFilters((p) => !p)}>
                <SlidersHorizontal className="h-3.5 w-3.5" />
                フィルター
              </Button>
            </div>
            {vcShowFilters && (
              <div className="grid grid-cols-3 gap-2 p-3 rounded-lg bg-muted/50 border text-xs">
                <div>
                  <label className="text-muted-foreground mb-1 block">部署で絞り込み</label>
                  <Select value={vcFilterDept} onValueChange={(v) => setVcFilterDept(v || "")}>
                    <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="全部署" /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">全部署</SelectItem>
                      {departments.map((d) => (
                        <SelectItem key={d.DEPT_ID} value={String(d.DEPT_ID)}>{d.DEPT_NAME}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <label className="text-muted-foreground mb-1 block">上司で絞り込み</label>
                  <Select value={vcFilterManager} onValueChange={(v) => setVcFilterManager(v || "")}>
                    <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="全マネージャー" /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">全マネージャー</SelectItem>
                      {(() => {
                        const seen = new Set<number>();
                        return allEmployees
                          .filter((e) => {
                            if (!e.MANAGER_ID || seen.has(e.MANAGER_ID)) return false;
                            seen.add(e.MANAGER_ID);
                            return true;
                          })
                          .map((e) => {
                            const mgr = allEmployees.find((m) => m.EMPLOYEE_ID === e.MANAGER_ID);
                            return mgr ? { id: mgr.EMPLOYEE_ID, name: mgr.NAME, dept: mgr.DEPT_NAME, grade: mgr.GRADE } : null;
                          })
                          .filter(Boolean)
                          .sort((a, b) => GRADE_ORDER.indexOf(a!.grade) - GRADE_ORDER.indexOf(b!.grade))
                          .map((m) => (
                            <SelectItem key={m!.id} value={String(m!.id)}>{m!.name}（{m!.dept}）</SelectItem>
                          ));
                      })()}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <label className="text-muted-foreground mb-1 block">入社区分</label>
                  <Select value={vcFilterEntryType} onValueChange={(v) => setVcFilterEntryType(v || "")}>
                    <SelectTrigger className="h-8 text-xs"><SelectValue>{({ all: "すべて", new_grad: "新卒", mid_career: "中途" } as Record<string, string>)[vcFilterEntryType || "all"] ?? "すべて"}</SelectValue></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">すべて</SelectItem>
                      <SelectItem value="new_grad">新卒</SelectItem>
                      <SelectItem value="mid_career">中途</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <label className="text-muted-foreground mb-1 block">最低スコア</label>
                  <Select value={String(vcFilterMinScore)} onValueChange={(v) => setVcFilterMinScore(Number(v))}>
                    <SelectTrigger className="h-8 text-xs"><SelectValue>{vcFilterMinScore ? `${vcFilterMinScore}以上` : "指定なし"}</SelectValue></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="0">指定なし</SelectItem>
                      <SelectItem value="30">30以上</SelectItem>
                      <SelectItem value="50">50以上</SelectItem>
                      <SelectItem value="70">70以上</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <label className="text-muted-foreground mb-1 block">最低勤続年数</label>
                  <Select value={String(vcFilterMinTenure)} onValueChange={(v) => setVcFilterMinTenure(Number(v))}>
                    <SelectTrigger className="h-8 text-xs"><SelectValue>{vcFilterMinTenure ? `${vcFilterMinTenure}年以上` : "指定なし"}</SelectValue></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="0">指定なし</SelectItem>
                      <SelectItem value="3">3年以上</SelectItem>
                      <SelectItem value="5">5年以上</SelectItem>
                      <SelectItem value="10">10年以上</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex items-end">
                  <Button size="sm" variant="outline" className="text-xs h-8 w-full" onClick={() => {
                    if (!vacancyTarget) return;
                    fetchVacancyCandidates(vacancyTarget.deptId, vacancyTarget.grade, {
                      minScore: vcFilterMinScore,
                      minTenure: vcFilterMinTenure,
                      entryType: vcFilterEntryType === "all" ? "" : vcFilterEntryType,
                      deptFilter: vcFilterDept === "all" ? "" : vcFilterDept,
                      managerId: vcFilterManager === "all" ? "" : vcFilterManager,
                    });
                  }}>
                    <Search className="h-3 w-3 mr-1" />
                    再検索
                  </Button>
                </div>
              </div>
            )}
            {vacancyCandidatesLoading ? (
              <div className="flex items-center gap-2 py-8 justify-center text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                候補者を検索中...
              </div>
            ) : filteredVacancyCandidates.length > 0 ? (
              <ScrollArea className="max-h-[50vh]">
                <div className="space-y-1.5 pr-2">
                  {filteredVacancyCandidates.map((c, ci) => (
                    <div
                      key={c.EMPLOYEE_ID}
                      className="p-2.5 rounded-lg border hover:shadow-sm hover:border-primary/50 hover:bg-accent/50 transition-all text-xs cursor-pointer"
                      onClick={() => {
                        if (!vacancyTarget) return;
                        const emp: OrgEmployee = {
                          EMPLOYEE_ID: c.EMPLOYEE_ID,
                          NAME: c.NAME,
                          DEPT_ID: c.DEPT_ID,
                          DEPT_NAME: c.DEPT_NAME,
                          GRADE: c.GRADE,
                          POSITION_TITLE: c.POSITION_TITLE,
                          POSITION_ID: c.POSITION_ID ?? 0,
                          MANAGER_ID: c.MANAGER_ID,
                          SALARY: Number(c.SALARY) || 0,
                          AGE: null,
                          TENURE_YEARS: null,
                          ENTRY_TYPE: null,
                        };
                        // The successor takes the vacant seat at *its* grade.
                        // Candidates can come from one grade below, so this may be
                        // a promotion (same dept) or a promotion-with-transfer.
                        const sameDept = emp.DEPT_ID === vacancyTarget.deptId;
                        const newAction: SimAction = {
                          id: `${Date.now()}-${emp.EMPLOYEE_ID}`,
                          type: sameDept && emp.GRADE !== vacancyTarget.grade ? "promote" : "transfer",
                          employee: emp,
                          fromGrade: emp.GRADE,
                          toGrade: vacancyTarget.grade,
                          fromDeptId: emp.DEPT_ID,
                          fromDeptName: emp.DEPT_NAME,
                          toDeptId: vacancyTarget.deptId,
                          toDeptName: vacancyTarget.deptName,
                          matchScore: c.COMPOSITE_SCORE,
                          matchReason: c.REASON,
                        };
                        setActions((prev) => [...prev, newAction]);
                        setVacancyCandidatesOpen(false);
                      }}
                    >
                      <div className="flex items-center gap-1.5">
                        <span className="text-muted-foreground w-4 text-right shrink-0">{ci + 1}</span>
                        <Badge variant="outline" className={`text-[9px] shrink-0 ${GRADE_BG[c.GRADE] || ""}`}>
                          {c.GRADE}
                        </Badge>
                        <span className="font-medium truncate">{c.NAME}</span>
                        <span className="text-muted-foreground truncate">{c.DEPT_NAME}</span>
                        <span className="text-muted-foreground truncate hidden sm:inline">{c.POSITION_TITLE}</span>
                        <Badge variant="outline" className={`font-mono text-[10px] ml-auto shrink-0 ${scoreColor(c.COMPOSITE_SCORE)}`}>
                          {c.COMPOSITE_SCORE}
                        </Badge>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-6 w-6 shrink-0"
                          onClick={(e) => {
                            e.stopPropagation();
                            setPeekCandidate(c);
                            setPeekOpen(true);
                            fetchPeekDetail(c.EMPLOYEE_ID);
                          }}
                        >
                          <Eye className="h-3 w-3" />
                        </Button>
                      </div>
                      <div className="mt-1.5 ml-5 flex items-center gap-3 flex-wrap">
                        <div className="flex items-center gap-1">
                          <span className="text-muted-foreground">スキル</span>
                          <Progress value={c.SKILL_PCT} className="w-12 h-1.5" />
                          <span className="font-mono w-7 text-right">{c.SKILL_PCT}%</span>
                        </div>
                        <div className="flex items-center gap-1">
                          <span className="text-muted-foreground">評価</span>
                          <span className="font-mono">{Number(c.AVG_EVAL).toFixed(1)}</span>
                        </div>
                        <div className="flex items-center gap-1">
                          <span className="text-muted-foreground">勤続</span>
                          <span className="font-mono">{c.TENURE}年</span>
                        </div>
                        {c.MANAGER_NAME && (
                          <div className="flex items-center gap-1">
                            <span className="text-muted-foreground">上司</span>
                            <span className="font-medium">{c.MANAGER_NAME}</span>
                          </div>
                        )}
                      </div>
                      {c.REASON && (
                        <div className="mt-1 ml-5 text-[11px] text-blue-600 bg-blue-50 px-2 py-0.5 rounded inline-block">
                          <Sparkles className="h-3 w-3 inline mr-0.5 -mt-0.5" />
                          {c.REASON}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </ScrollArea>
            ) : (
              <p className="text-sm text-muted-foreground text-center py-8">
                {vacancySearch ? "検索条件に一致する候補者がいません" : "該当する候補者が見つかりませんでした"}
              </p>
            )}
            <div className="text-[10px] text-muted-foreground text-right">
              {filteredVacancyCandidates.length}件表示 / 最大20件
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={peekOpen} onOpenChange={setPeekOpen}>
        <DialogContent className="sm:max-w-2xl max-h-[85vh] overflow-y-auto">
          {peekCandidate && (
            <>
              <DialogHeader>
                <DialogTitle className="flex items-center gap-2 text-sm">
                  <Briefcase className="h-4 w-4" />
                  候補者詳細
                </DialogTitle>
                <DialogDescription>
                  {peekCandidate.DEPT_NAME} / {peekCandidate.POSITION_TITLE}
                </DialogDescription>
              </DialogHeader>
              {peekDetailLoading ? (
                <div className="flex items-center justify-center py-12">
                  <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                </div>
              ) : (
                <div className="space-y-4">
                  <div className="space-y-3 p-3 rounded-lg border bg-blue-50/30 border-blue-200">
                    <div className="flex items-center gap-2">
                      <Badge className="text-[10px] bg-blue-600">{peekCandidate.GRADE} {GRADE_LABELS[peekCandidate.GRADE]}</Badge>
                    </div>
                    <div>
                      <p className="font-semibold text-sm">{peekCandidate.NAME}</p>
                      <p className="text-[11px] text-muted-foreground">{peekCandidate.DEPT_NAME} / {peekCandidate.POSITION_TITLE}</p>
                    </div>
                    <div className="grid grid-cols-4 gap-2 text-xs">
                      <div><p className="text-muted-foreground">勤続</p><p className="font-medium">{peekCandidate.TENURE}年</p></div>
                      <div><p className="text-muted-foreground">平均評価</p><p className="font-medium">{Number(peekCandidate.AVG_EVAL).toFixed(1)}/5.0</p></div>
                      <div><p className="text-muted-foreground">スキルマッチ</p><p className="font-medium">{peekCandidate.SKILL_MATCH}/5</p></div>
                      <div><p className="text-muted-foreground">総合スコア</p><Badge variant="outline" className={`font-mono text-[10px] ${scoreColor(peekCandidate.COMPOSITE_SCORE)}`}>{peekCandidate.COMPOSITE_SCORE}</Badge></div>
                    </div>
                    {peekDetail?.mlInsights?.attrition && (
                      <div className="flex items-center gap-2 text-xs p-1.5 rounded border bg-white">
                        <AlertTriangle className={`h-3.5 w-3.5 ${peekDetail.mlInsights.attrition.RISK_LABEL === "high" ? "text-red-500" : peekDetail.mlInsights.attrition.RISK_LABEL === "medium" ? "text-amber-500" : "text-green-500"}`} />
                        <span className="text-muted-foreground">離職リスク</span>
                        <Badge variant={peekDetail.mlInsights.attrition.RISK_LABEL === "high" ? "destructive" : "secondary"} className="text-[9px]">
                          {peekDetail.mlInsights.attrition.RISK_LABEL === "high" ? "高" : peekDetail.mlInsights.attrition.RISK_LABEL === "medium" ? "中" : "低"}
                        </Badge>
                        <span className="font-mono">{(Number(peekDetail.mlInsights.attrition.RISK_SCORE) * 100).toFixed(0)}%</span>
                      </div>
                    )}
                    {peekDetail?.mlInsights?.relationship && (
                      <div className="flex items-center gap-2 text-xs p-1.5 rounded border bg-white">
                        <Users className="h-3.5 w-3.5 text-blue-500" />
                        <span className="text-muted-foreground">上司関係性</span>
                        <span className="font-mono">{(Number(peekDetail.mlInsights.relationship.RELATIONSHIP_SCORE) * 100).toFixed(0)}%</span>
                        <span className="text-muted-foreground">上司: {peekDetail.mlInsights.relationship.MANAGER_NAME}</span>
                      </div>
                    )}
                    {peekDetail?.skills && peekDetail.skills.length > 0 && (
                      <div>
                        <p className="text-[11px] font-medium text-muted-foreground mb-1">スキル</p>
                        <div className="space-y-0.5">
                          {peekDetail.skills.slice(0, 6).map((s, i) => (
                            <div key={i} className="flex items-center gap-1.5 text-[11px]">
                              <span className="flex-1 truncate">{s.SKILL_NAME}</span>
                              <Badge variant="outline" className="text-[9px] px-1">{s.CATEGORY}</Badge>
                              <Progress value={Number(s.PROFICIENCY) * 20} className="h-1 w-14" />
                              <span className="text-muted-foreground w-5 text-right">L{s.PROFICIENCY}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                    {peekDetail?.evaluations && peekDetail.evaluations.length > 0 && (
                      <div>
                        <p className="text-[11px] font-medium text-muted-foreground mb-1">直近評価</p>
                        <div className="space-y-0.5">
                          {peekDetail.evaluations.slice(0, 3).map((ev, i) => (
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
                  <DialogFooter className="flex gap-2 sm:justify-between">
                    <Link href={`/employees/${peekCandidate.EMPLOYEE_ID}`} target="_blank">
                      <Button variant="ghost" size="sm" className="gap-1.5 text-muted-foreground">
                        <ExternalLink className="h-3.5 w-3.5" />
                        別タブで開く
                      </Button>
                    </Link>
                    <Button variant="outline" size="sm" onClick={() => setPeekOpen(false)}>
                      閉じる
                    </Button>
                  </DialogFooter>
                </div>
              )}
            </>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-2xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>アクション追加</DialogTitle>
            <DialogDescription>
              {dialogEmployee?.NAME} ({dialogEmployee?.GRADE}: {GRADE_LABELS[dialogEmployee?.GRADE || ""]})
              — {dialogEmployee?.DEPT_NAME}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-2">
            <div className="flex gap-2">
              {(["promote", "transfer", "retire"] as ActionType[]).map((t) => {
                const meta = ACTION_LABELS[t];
                const Icon = meta.icon;
                return (
                  <Button
                    key={t}
                    variant={dialogType === t ? "default" : "outline"}
                    size="sm"
                    onClick={() => {
                      setDialogType(t);
                      setMatchResult(null);
                      setMatchLoading(false);
                    }}
                    className="flex-1"
                  >
                    <Icon className="h-3.5 w-3.5 mr-1" />
                    {meta.label}
                  </Button>
                );
              })}
            </div>

            {dialogType === "promote" && dialogEmployee && (
              <div className="space-y-2">
                <label className="text-sm font-medium">昇格先等級</label>
                <Select value={dialogToGrade} onValueChange={(v) => v && setDialogToGrade(v)}>
                  <SelectTrigger>
                    <SelectValue>
                      {dialogToGrade
                        ? `${dialogToGrade}: ${GRADE_LABELS[dialogToGrade]}`
                        : "等級を選択"}
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {GRADE_ORDER.slice(
                      0,
                      GRADE_ORDER.indexOf(dialogEmployee.GRADE)
                    ).map((g) => (
                      <SelectItem key={g} value={g}>
                        {g}: {GRADE_LABELS[g]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  現在: {dialogEmployee.GRADE} ({GRADE_LABELS[dialogEmployee.GRADE]})
                  → {dialogToGrade} ({GRADE_LABELS[dialogToGrade]})
                </p>
              </div>
            )}

            {dialogType === "transfer" && (
              <div className="space-y-3">
                <div className="space-y-2">
                  <label className="text-sm font-medium">異動先部署</label>
                  <Select value={dialogToDept} onValueChange={handleDeptChange}>
                    <SelectTrigger>
                      <SelectValue>
                        {dialogToDept
                          ? allDeptsList.find((d) => String(d.DEPT_ID) === dialogToDept)?.DEPT_NAME || "部署を選択"
                          : "部署を選択"}
                      </SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                      {allDeptsList
                        .filter((d) => d.DEPT_ID !== dialogEmployee?.DEPT_ID && d.LEVEL >= 2)
                        .map((d) => (
                          <SelectItem key={d.DEPT_ID} value={String(d.DEPT_ID)}>
                            {d.DEPT_NAME}
                          </SelectItem>
                        ))}
                    </SelectContent>
                  </Select>
                </div>

                {dialogToDept && (
                  <Card className="border-gray-200">
                    <CardHeader className="pb-2">
                      <div className="flex items-center justify-between">
                        <CardTitle className="text-sm flex items-center gap-1.5">
                          <Users className="h-4 w-4" />
                          異動先の社員一覧
                        </CardTitle>
                        <Badge variant="secondary" className="text-[10px]">
                          {deptEmpLoading ? "..." : `${deptEmployees.length}名`}
                        </Badge>
                      </div>
                    </CardHeader>
                    <CardContent className="p-2">
                      {deptEmpLoading ? (
                        <div className="flex items-center gap-2 py-4 justify-center text-sm text-muted-foreground">
                          <Loader2 className="h-4 w-4 animate-spin" />
                          取得中...
                        </div>
                      ) : (
                        <ScrollArea className="max-h-[200px]">
                          <div className="space-y-1 pr-2">
                            {deptEmployees.map((de) => {
                              const isSameGrade = de.GRADE === dialogEmployee?.GRADE;
                              return (
                                <button
                                  key={de.EMPLOYEE_ID}
                                  type="button"
                                  className={`w-full text-left p-2 rounded-md border transition-all hover:shadow-sm ${
                                    isSameGrade
                                      ? "border-blue-300 bg-blue-50 ring-1 ring-blue-200"
                                      : GRADE_COLORS[de.GRADE] || "border-gray-200 bg-white"
                                  }`}
                                  onClick={() => {
                                    setPeekCandidate({
                                      EMPLOYEE_ID: de.EMPLOYEE_ID,
                                      NAME: de.NAME,
                                      DEPT_NAME: selectedDept?.DEPT_NAME || "",
                                      GRADE: de.GRADE,
                                      POSITION_TITLE: de.POSITION_TITLE,
                                      AVG_EVAL: de.AVG_EVAL,
                                      TENURE: de.TENURE_YEARS,
                                      SKILL_MATCH: de.SKILL_COUNT,
                                      COMPOSITE_SCORE: 0,
                                    });
                                    setPeekOpen(true);
                                    fetchPeekDetail(de.EMPLOYEE_ID);
                                  }}
                                >
                                  <div className="flex items-center justify-between">
                                    <div className="flex items-center gap-2 min-w-0">
                                      <Eye className="h-3 w-3 text-muted-foreground shrink-0" />
                                      <span className="text-sm font-medium truncate">{de.NAME}</span>
                                      {isSameGrade && (
                                        <Badge variant="outline" className="text-[9px] bg-blue-100 border-blue-300 shrink-0">
                                          同ランク
                                        </Badge>
                                      )}
                                    </div>
                                    <div className="flex items-center gap-1 shrink-0">
                                      <Badge variant="outline" className={`text-[10px] ${GRADE_BG[de.GRADE] || ""}`}>
                                        {de.GRADE}
                                      </Badge>
                                      {de.RISK_LABEL === "high" && (
                                        <Badge variant="destructive" className="text-[9px] px-1">
                                          離職リスク
                                        </Badge>
                                      )}
                                    </div>
                                  </div>
                                  <p className="text-[11px] text-muted-foreground truncate ml-5">
                                    {de.POSITION_TITLE} / 勤続{de.TENURE_YEARS}年 / 評価{de.AVG_EVAL}/5
                                  </p>
                                </button>
                              );
                            })}
                          </div>
                        </ScrollArea>
                      )}
                    </CardContent>
                  </Card>
                )}

                {dialogToDept && !deptEmpLoading && (
                  <div className="space-y-3">
                    <Button
                      variant="outline"
                      className="w-full gap-2 border-blue-300 text-blue-700 hover:bg-blue-50"
                      onClick={() => {
                        if (dialogEmployee && dialogToDept) {
                          runCompare(dialogEmployee.EMPLOYEE_ID, Number(dialogToDept));
                          fetchMatch(dialogEmployee.EMPLOYEE_ID, Number(dialogToDept));
                        }
                      }}
                      disabled={compareLoading || matchLoading}
                    >
                      {compareLoading || matchLoading ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Brain className="h-4 w-4" />
                      )}
                      {compareLoading || matchLoading ? "AI分析実行中..." : "AI比較分析を実行"}
                    </Button>

                    {matchError && !matchLoading && (
                      <Card className="border-red-200 bg-red-50/30">
                        <CardContent className="p-3 flex items-center gap-2">
                          <AlertTriangle className="h-4 w-4 text-red-500 shrink-0" />
                          <span className="text-xs text-red-700">配置マッチ度の取得に失敗しました</span>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="text-xs h-6 ml-auto"
                            onClick={() => {
                              if (dialogEmployee && dialogToDept) {
                                fetchMatch(dialogEmployee.EMPLOYEE_ID, Number(dialogToDept));
                              }
                            }}
                          >
                            再試行
                          </Button>
                        </CardContent>
                      </Card>
                    )}

                    {matchResult && !matchLoading && (
                      <Card className="border-gray-200">
                        <CardHeader className="pb-2">
                          <CardTitle className="text-sm flex items-center gap-2">
                            <Target className="h-4 w-4" />
                            配置マッチ度
                            <Badge variant="outline" className={`text-sm font-bold ${scoreColor(matchResult.matchScore)}`}>
                              {matchResult.matchScore}%
                            </Badge>
                          </CardTitle>
                        </CardHeader>
                        <CardContent className="p-3 space-y-3">
                          <div className="grid grid-cols-3 gap-2 text-xs">
                            <div className="text-center p-2 rounded bg-gray-50 border">
                              <p className="text-muted-foreground">スキル適合</p>
                              <p className="text-lg font-bold">{matchResult.skillScore}%</p>
                            </div>
                            <div className="text-center p-2 rounded bg-gray-50 border">
                              <p className="text-muted-foreground">評価実績</p>
                              <p className="text-lg font-bold">{matchResult.evalScore}%</p>
                            </div>
                            <div className="text-center p-2 rounded bg-gray-50 border">
                              <p className="text-muted-foreground">経験年数</p>
                              <p className="text-lg font-bold">{matchResult.tenureScore}%</p>
                            </div>
                          </div>
                          <div className="space-y-1">
                            {matchResult.matchedSkills.length > 0 && (
                              <div className="flex items-start gap-1.5 text-xs">
                                <CheckCircle2 className="h-3.5 w-3.5 text-green-600 mt-0.5 shrink-0" />
                                <span>
                                  <span className="font-medium text-green-700">合致:</span>{" "}
                                  {matchResult.matchedSkills.join(", ")}
                                </span>
                              </div>
                            )}
                            {matchResult.missingSkills.length > 0 && (
                              <div className="flex items-start gap-1.5 text-xs">
                                <XCircle className="h-3.5 w-3.5 text-red-500 mt-0.5 shrink-0" />
                                <span>
                                  <span className="font-medium text-red-600">不足:</span>{" "}
                                  {matchResult.missingSkills.join(", ")}
                                </span>
                              </div>
                            )}
                          </div>
                        </CardContent>
                      </Card>
                    )}

                    {compareResult && !compareLoading && (
                      <Card className="border-blue-200 bg-blue-50/30">
                        <CardHeader className="pb-2">
                          <CardTitle className="text-sm flex items-center gap-2">
                            <Brain className="h-4 w-4 text-blue-600" />
                            同ランク比較分析
                            <Badge variant="outline" className="text-[10px] border-blue-300">
                              {compareResult.employee.grade} × {compareResult.peerCount}名
                              {compareResult.peerCount > 1 && " (AI_AGG使用)"}
                            </Badge>
                          </CardTitle>
                        </CardHeader>
                        <CardContent className="p-3 space-y-3">
                          {compareResult.peerCount > 0 && (
                            <div className="space-y-1">
                              <p className="text-[11px] font-medium text-muted-foreground">異動先の同ランク社員:</p>
                              {compareResult.peers.map((p) => (
                                <div key={p.employeeId} className="flex items-center gap-2 text-xs p-1.5 rounded border bg-white">
                                  <Badge variant="outline" className={`text-[9px] shrink-0 ${GRADE_BG[p.grade] || ""}`}>
                                    {p.grade}
                                  </Badge>
                                  <span className="font-medium">{p.name}</span>
                                  <span className="text-muted-foreground">{p.positionTitle}</span>
                                  <span className="text-muted-foreground ml-auto shrink-0">評価{p.avgEval}/5 勤続{p.tenure}年</span>
                                </div>
                              ))}
                            </div>
                          )}
                          {compareResult.peerCount === 0 && (
                            <p className="text-xs text-muted-foreground">異動先に同ランク（{compareResult.employee.grade}）の社員はいません</p>
                          )}
                          <div className="text-xs bg-white rounded p-3 border border-blue-200">
                            <p className="font-medium text-blue-800 mb-1.5 flex items-center gap-1">
                              <Brain className="h-3 w-3" />
                              AI比較分析（Cortex {compareResult.peerCount > 1 ? "AI_AGG" : "AI_COMPLETE"}）
                            </p>
                            <div className="prose prose-sm max-w-none dark:prose-invert">
                              <ReactMarkdown remarkPlugins={[remarkGfm]}>{compareResult.aiComparison}</ReactMarkdown>
                            </div>
                          </div>
                        </CardContent>
                      </Card>
                    )}
                  </div>
                )}
              </div>
            )}

            {dialogType === "retire" && (
              <p className="text-sm text-muted-foreground">
                {dialogEmployee?.NAME} の退職をシナリオに追加します。
                {dialogEmployee?.GRADE} ポジションの空席が発生します。
              </p>
            )}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>
              キャンセル
            </Button>
            <Button
              onClick={addAction}
              disabled={
                (dialogType === "transfer" && !dialogToDept) ||
                (dialogType === "promote" && !dialogToGrade) ||
                (dialogType === "transfer" && (matchLoading || compareLoading))
              }
            >
              追加
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={scenariosOpen} onOpenChange={setScenariosOpen}>
        <DialogContent className="sm:max-w-lg max-h-[70vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <FolderOpen className="h-5 w-5" />
              保存済みシナリオ
            </DialogTitle>
            <DialogDescription>シナリオを選択して比較表示</DialogDescription>
          </DialogHeader>
          {scenariosLoading ? (
            <div className="flex justify-center py-8"><Loader2 className="h-5 w-5 animate-spin" /></div>
          ) : scenariosList.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-8">保存済みシナリオがありません</p>
          ) : (
            <div className="space-y-2">
              {scenariosList.map((s) => (
                <div key={s.scenario_id} className={`flex items-center gap-3 p-3 rounded-lg border hover:bg-accent cursor-pointer ${s.status === "revision_requested" ? "border-red-300 bg-red-50/50" : ""}`} onClick={() => loadScenarioForCompare(s.scenario_id)}>
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-medium">{s.scenario_name}</p>
                      {s.status && s.status !== "draft" && (
                        <Badge variant="secondary" className={`text-[10px] ${
                          s.status === "pending_review" ? "bg-yellow-100 text-yellow-700" :
                          s.status === "revision_requested" ? "bg-red-100 text-red-700" :
                          s.status === "approved" ? "bg-green-100 text-green-700" : ""
                        }`}>
                          {s.status === "pending_review" ? "レビュー待ち" :
                           s.status === "revision_requested" ? "差し戻しあり" :
                           s.status === "approved" ? "承認済み" : s.status}
                        </Badge>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground">{new Date(s.created_at).toLocaleDateString("ja-JP")} / {s.action_count}件のアクション
                      {Number(s.rejected_count) > 0 && <span className="text-red-600 ml-1">({s.rejected_count}件差し戻し)</span>}
                    </p>
                  </div>
                  <div className="flex gap-1">
                    <Button variant="ghost" size="sm" className="gap-1" onClick={(e) => { e.stopPropagation(); loadScenarioForEdit(s.scenario_id); }}>
                      <Upload className="h-3.5 w-3.5" />ロード
                    </Button>
                    <Button variant="ghost" size="sm" className="gap-1"><ArrowLeftRight className="h-3.5 w-3.5" />比較</Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </DialogContent>
      </Dialog>

      {compareMode && compareScenario && (
        <div className="fixed bottom-0 left-[240px] right-0 bg-background border-t shadow-lg z-40 p-4 max-h-[35vh] overflow-y-auto">
          <div className="flex items-center gap-3 mb-3">
            <ArrowLeftRight className="h-4 w-4" />
            <h4 className="font-semibold text-sm">シナリオ比較: {(compareScenario.scenario as { scenario_name?: string }).scenario_name}</h4>
            <Badge variant="outline" className="text-[10px]">{compareScenario.actions.length}件</Badge>
            <Button variant="ghost" size="sm" className="ml-auto" onClick={() => { setCompareMode(false); setCompareScenario(null); }}>
              <X className="h-3.5 w-3.5" />
            </Button>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-xs font-medium text-muted-foreground mb-2">保存済みシナリオ</p>
              <div className="space-y-1">
                {compareScenario.actions.map((a, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs p-1.5 rounded bg-muted/50">
                    <Badge variant="outline" className="text-[9px]">
                      {a.action_type === "transfer" ? "異動" : a.action_type === "promote" ? "昇格" : "退職"}
                    </Badge>
                    <span className="font-medium">{a.employee_name}</span>
                    {a.from_dept_name && a.to_dept_name && (
                      <span className="text-muted-foreground">{a.from_dept_name} → {a.to_dept_name}</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
            <div>
              <p className="text-xs font-medium text-muted-foreground mb-2">現在のシナリオ（{actions.length}件）</p>
              <div className="space-y-1">
                {actions.length === 0 ? (
                  <p className="text-xs text-muted-foreground py-2">アクションなし</p>
                ) : actions.map((a) => (
                  <div key={a.id} className="flex items-center gap-2 text-xs p-1.5 rounded bg-muted/50">
                    <Badge variant="outline" className="text-[9px]">
                      {a.type === "transfer" ? "異動" : a.type === "promote" ? "昇格" : "退職"}
                    </Badge>
                    <span className="font-medium">{a.employee.NAME}</span>
                    {a.fromDeptName && a.toDeptName && (
                      <span className="text-muted-foreground">{a.fromDeptName} → {a.toDeptName}</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      <Dialog open={confirmDialogOpen} onOpenChange={setConfirmDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>スナップショット確定</DialogTitle>
            <DialogDescription>確定データとして保管します。確定後はCSV出力や過去比較が可能になります。</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <label className="text-sm font-medium">ラベル</label>
              <Input value={confirmLabel} onChange={(e) => setConfirmLabel(e.target.value)} placeholder="例: 2026年4月 定期異動" />
            </div>
            <div>
              <label className="text-sm font-medium">発令日</label>
              <Input type="date" value={confirmDate} onChange={(e) => setConfirmDate(e.target.value)} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmDialogOpen(false)}>キャンセル</Button>
            <Button
              disabled={!confirmLabel.trim() || !confirmDate || confirmLoading}
              onClick={async () => {
                setConfirmLoading(true);
                try {
                  const res = await fetch("/api/simulation/confirm", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ scenarioId: loadedScenarioId, label: confirmLabel, effectiveDate: confirmDate }),
                  });
                  if (res.ok) {
                    setConfirmDialogOpen(false);
                    setLoadedScenarioStatus("confirmed");
                  }
                } finally {
                  setConfirmLoading(false);
                }
              }}
            >
              {confirmLoading ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : <Archive className="h-4 w-4 mr-1" />}
              確定
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default function SimulationPage() {
  return <Suspense><SimulationPageInner /></Suspense>;
}

function StepGuide({ step }: { step: 1 | 2 | 3 }) {
  const steps = ["起点を作る（昇格・異動・退職）", "空いた席の後任を選ぶ", "保存してレビュー依頼"];
  return (
    <ol className="hidden md:flex items-center gap-1 text-[11px]">
      {steps.map((label, i) => {
        const n = i + 1;
        const state = n < step ? "done" : n === step ? "current" : "todo";
        return (
          <li key={label} className="flex items-center gap-1">
            <span
              className={`flex h-4 w-4 items-center justify-center rounded-full text-[10px] font-bold ${
                state === "done" ? "bg-green-600 text-white" : state === "current" ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"
              }`}
            >
              {state === "done" ? "✓" : n}
            </span>
            <span className={state === "current" ? "font-semibold text-foreground" : "text-muted-foreground"}>{label}</span>
            {n < steps.length && <span className="text-muted-foreground mx-1">›</span>}
          </li>
        );
      })}
    </ol>
  );
}
