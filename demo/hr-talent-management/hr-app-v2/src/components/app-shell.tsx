"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { useDataPath } from "@/lib/data-path-context";
import {
  LayoutDashboard,
  Users,
  ClipboardCheck,
  Bot,
  TrendingDown,
  GitBranch,
  Shield,
  LogOut,
  ChevronDown,
  ChevronRight,
  Zap,
  Database,
  Snowflake,
  BarChart3,
  FileCheck,
  Archive,
  Shuffle,
  Brain,
  Scale,
  Settings,
  SlidersHorizontal,
  UserCheck,
  Award,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import type { UserRole } from "@/lib/types";

type NavItem = {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  roles?: string[];
  showBadge?: boolean;
};

const NAV_TOP: NavItem[] = [
  { href: "/my-team", label: "マイチーム評価", icon: UserCheck, roles: ["LINE_MANAGER"] },
  { href: "/", label: "ダッシュボード", icon: LayoutDashboard },
  { href: "/employees", label: "社員一覧", icon: Users },
  { href: "/agent", label: "AIエージェント", icon: Bot, roles: ["HR_ADMIN"] },
];

const NAV_EVAL: NavItem[] = [
  { href: "/evaluations", label: "評価管理", icon: ClipboardCheck },
  { href: "/evaluations/cross-review", label: "評価横断レビュー", icon: Brain, roles: ["HR_ADMIN", "HR_MANAGER"] },
  { href: "/evaluations/calibration", label: "評価調整会議", icon: Scale, roles: ["HR_ADMIN", "HR_MANAGER"] },
  { href: "/attrition", label: "離職予測", icon: TrendingDown },
];

const NAV_TRANSFER: NavItem[] = [
  { href: "/workforce-overview", label: "異動ダッシュボード", icon: BarChart3 },
  { href: "/simulation", label: "異動シナリオ作成", icon: GitBranch, roles: ["HR_ADMIN", "HR_MANAGER"] },
  { href: "/chain-simulation", label: "玉突き人事", icon: Zap, roles: ["HR_ADMIN", "HR_MANAGER"] },
  { href: "/review", label: "異動案レビュー", icon: FileCheck, showBadge: true, roles: ["HR_ADMIN"] },
  { href: "/snapshots", label: "確定済み異動", icon: Archive, roles: ["HR_ADMIN", "HR_MANAGER"] },
];

const NAV_BOTTOM: NavItem[] = [
  { href: "/governance", label: "ガバナンス監査", icon: Shield },
];

// Changing a standard re-ranks everyone, so keep settings admin-only.
const NAV_SETTINGS: NavItem[] = [
  { href: "/settings/score-standards", label: "評価基準マスタ", icon: SlidersHorizontal, roles: ["HR_ADMIN"] },
];

const ROLE_LABELS: Record<string, string> = {
  HR_ADMIN: "人事管理者",
  HR_MANAGER: "部門マネージャー",
  HR_VIEWER: "閲覧者",
  LINE_MANAGER: "評価者（上長）",
};

const ROLE_COLORS: Record<string, string> = {
  HR_ADMIN: "bg-red-100 text-red-700",
  HR_MANAGER: "bg-blue-100 text-blue-700",
  HR_VIEWER: "bg-green-100 text-green-700",
  LINE_MANAGER: "bg-amber-100 text-amber-800",
};

function NavLink({ href, label, icon: Icon, active, badge }: { href: string; label: string; icon: React.ComponentType<{ className?: string }>; active: boolean; badge?: number }) {
  return (
    <Link
      href={href}
      className={`flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors ${
        active ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
      }`}
    >
      <Icon className="h-4 w-4" />
      <span className="flex-1">{label}</span>
      {badge !== undefined && badge > 0 && (
        <span className="ml-auto min-w-5 h-5 rounded-full bg-yellow-500 text-white text-[10px] font-bold flex items-center justify-center">
          {badge}
        </span>
      )}
    </Link>
  );
}

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout, switchRole } = useAuth();
  const [evalOpen, setEvalOpen] = useState(true);
  const [transferOpen, setTransferOpen] = useState(true);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [reviewCount, setReviewCount] = useState(0);

  // Derive group activity from the group's own hrefs so adding an item
  // to a group cannot silently leave the header un-highlighted.
  const inGroup = (items: { href: string }[]) =>
    items.some((i) => pathname === i.href || pathname.startsWith(i.href + "/"));

  const evalActive = inGroup(NAV_EVAL);
  const transferActive = inGroup(NAV_TRANSFER);
  const settingsActive = inGroup(NAV_SETTINGS);

  const fetchReviewCount = useCallback(async () => {
    if (user?.role === "LINE_MANAGER") return; // 異動レビューは人事向け
    try {
      const res = await fetch("/api/simulation/scenarios");
      if (!res.ok) return;
      const data = await res.json();
      setReviewCount(data.filter((s: { status: string }) => s.status === "pending_review").length);
    } catch { /* ignore */ }
  }, [user?.role]);

  useEffect(() => {
    fetchReviewCount();
    const iv = setInterval(fetchReviewCount, 60000);
    return () => clearInterval(iv);
  }, [fetchReviewCount]);

  useEffect(() => {
    if (evalActive) setEvalOpen(true);
  }, [evalActive]);

  useEffect(() => {
    if (transferActive) setTransferOpen(true);
  }, [transferActive]);

  useEffect(() => {
    if (settingsActive) setSettingsOpen(true);
  }, [settingsActive]);

  // 上長は自分が評価する部下の画面だけを使う。全社データの画面には入らせない
  const lineManager = user?.role === "LINE_MANAGER";
  useEffect(() => {
    if (lineManager && !pathname.startsWith("/my-team")) router.replace("/my-team");
  }, [lineManager, pathname, router]);

  if (!user) return null;

  const handleLogout = async () => {
    await logout();
    router.push("/login");
  };

  // Highlight only the most specific match, so /evaluations/calibration does
  // not also light up its parent /evaluations.
  const matches = (href: string) =>
    pathname === href || (href !== "/" && pathname.startsWith(href + "/"));
  const activeHref = [...NAV_TOP, ...NAV_EVAL, ...NAV_TRANSFER, ...NAV_BOTTOM, ...NAV_SETTINGS]
    .map((i) => i.href)
    .filter(matches)
    .sort((a, b) => b.length - a.length)[0];
  const isActive = (href: string) => href === activeHref;

  // LINE_MANAGER sees only items that name it; everyone else sees unrestricted items too.
  const canSee = (item: { roles?: string[] }) =>
    item.roles ? item.roles.includes(user.role) : user.role !== "LINE_MANAGER";
  const visibleEval = NAV_EVAL.filter(canSee);
  const visibleTransfer = NAV_TRANSFER.filter(canSee);
  const visibleSettings = NAV_SETTINGS.filter(canSee);

  return (
    <div className="flex h-screen bg-background">
      <aside className="w-60 border-r bg-card flex flex-col">
        <div className="p-4">
          <h1 className="text-lg font-bold tracking-tight">HR Intelligence</h1>
          <p className="text-xs text-muted-foreground mt-0.5">Powered by Snowflake</p>
        </div>
        <Separator />
        <nav className="flex-1 p-2 space-y-0.5 overflow-y-auto">
          {NAV_TOP.filter(canSee).map((item) => (
            <NavLink key={item.href} {...item} active={isActive(item.href)} />
          ))}

          {visibleEval.length > 0 && (
            <>
              <button
                onClick={() => setEvalOpen(!evalOpen)}
                className={`flex items-center gap-3 px-3 py-2 rounded-md text-sm w-full transition-colors ${
                  evalActive && !evalOpen ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                }`}
              >
                <Award className="h-4 w-4" />
                <span className="flex-1 text-left">評価</span>
                {evalOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
              </button>
              {evalOpen && (
                <div className="ml-3 pl-3 border-l space-y-0.5">
                  {visibleEval.map((item) => (
                    <NavLink key={item.href} {...item} active={isActive(item.href)} />
                  ))}
                </div>
              )}
            </>
          )}

          {visibleTransfer.length > 0 && (
            <>
              <button
                onClick={() => setTransferOpen(!transferOpen)}
                className={`flex items-center gap-3 px-3 py-2 rounded-md text-sm w-full transition-colors ${
                  transferActive && !transferOpen ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                }`}
              >
                <Shuffle className="h-4 w-4" />
                <span className="flex-1 text-left">異動管理</span>
                {reviewCount > 0 && !transferOpen && (
                  <span className="min-w-5 h-5 rounded-full bg-yellow-500 text-white text-[10px] font-bold flex items-center justify-center">
                    {reviewCount}
                  </span>
                )}
                {transferOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
              </button>
              {transferOpen && (
                <div className="ml-3 pl-3 border-l space-y-0.5">
                  {visibleTransfer.map((item) => (
                    <NavLink
                      key={item.href}
                      {...item}
                      active={isActive(item.href)}
                      badge={item.showBadge ? reviewCount : undefined}
                    />
                  ))}
                </div>
              )}
            </>
          )}

          {NAV_BOTTOM.filter(canSee).map((item) => (
            <NavLink key={item.href} {...item} active={isActive(item.href)} />
          ))}

          {visibleSettings.length > 0 && (
            <>
              <button
                onClick={() => setSettingsOpen(!settingsOpen)}
                className={`flex items-center gap-3 px-3 py-2 rounded-md text-sm w-full transition-colors ${
                  settingsActive && !settingsOpen ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                }`}
              >
                <Settings className="h-4 w-4" />
                <span className="flex-1 text-left">設定</span>
                {settingsOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
              </button>
              {settingsOpen && (
                <div className="ml-3 pl-3 border-l space-y-0.5">
                  {visibleSettings.map((item) => (
                    <NavLink key={item.href} {...item} active={isActive(item.href)} />
                  ))}
                </div>
              )}
            </>
          )}
        </nav>
        <Separator />
        <div className="p-3">
          <div className="flex items-center gap-2 mb-2">
            <Avatar className="h-8 w-8">
              <AvatarFallback className="text-xs">
                {user.displayName.charAt(0)}
              </AvatarFallback>
            </Avatar>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium truncate">{user.displayName}</p>
              <Badge variant="secondary" className={`text-[10px] px-1.5 py-0 ${ROLE_COLORS[user.role] || ""}`}>
                {ROLE_LABELS[user.role]}
              </Badge>
            </div>
          </div>
          {!lineManager && <DropdownMenu>
            <DropdownMenuTrigger className="flex w-full items-center justify-between rounded-md border px-3 py-1.5 text-xs hover:bg-accent">
              ロール切替
              <ChevronDown className="h-3 w-3" />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-48">
              {(["HR_ADMIN", "HR_MANAGER", "HR_VIEWER"] as UserRole[]).map((role) => (
                <DropdownMenuItem
                  key={role}
                  onClick={() => switchRole(role)}
                  className={user.role === role ? "bg-accent" : ""}
                >
                  <Badge variant="secondary" className={`text-[10px] mr-2 ${ROLE_COLORS[role]}`}>
                    {role}
                  </Badge>
                  {ROLE_LABELS[role]}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>}
          <Button
            variant="ghost"
            size="sm"
            className="w-full justify-start text-xs text-muted-foreground mt-1"
            onClick={handleLogout}
          >
            <LogOut className="h-3 w-3 mr-2" />
            ログアウト
          </Button>
          <DataPathToggle />
        </div>
      </aside>
      <main className="flex-1 overflow-auto">{children}</main>
    </div>
  );
}

function DataPathToggle() {
  const { dataPath, toggle, isPgLake } = useDataPath();

  return (
    <div className="mt-2 pt-2 border-t">
      <button
        onClick={toggle}
        className="flex w-full items-center gap-2 rounded-md border px-3 py-1.5 text-xs hover:bg-accent transition-colors"
      >
        {isPgLake ? (
          <Database className="h-3.5 w-3.5 text-emerald-600" />
        ) : (
          <Snowflake className="h-3.5 w-3.5 text-sky-600" />
        )}
        <span className="flex-1 text-left">
          {isPgLake ? "pg_lake" : "snowflake-sdk"}
        </span>
        <Badge variant="secondary" className={`text-[10px] px-1.5 py-0 ${isPgLake ? "bg-emerald-100 text-emerald-700" : "bg-sky-100 text-sky-700"}`}>
          {isPgLake ? "Iceberg" : "SDK"}
        </Badge>
      </button>
    </div>
  );
}
