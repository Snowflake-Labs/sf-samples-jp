"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Shield,
  Users,
  Eye,
  Brain,
  Database,
  Lock,
  Search,
  Snowflake,
  ChevronRight,
  UserCheck,
} from "lucide-react";
import type { UserRole } from "@/lib/types";

const DEMO_USERS = [
  {
    username: "admin",
    label: "人事管理者",
    role: "HR_ADMIN" as UserRole,
    description: "全社員データ閲覧・給与/評価フルアクセス",
    features: [
      "全社ダッシュボード",
      "給与データ（マスキングなし）",
      "評価管理・承認",
      "離職予測モデル",
      "昇格・異動シミュレーション",
      "ガバナンス設定",
    ],
    icon: Shield,
    iconBg: "bg-red-100 dark:bg-red-950",
    iconColor: "text-red-600 dark:text-red-400",
    borderColor: "border-red-200 dark:border-red-800",
    hoverBg: "hover:bg-red-50/50 dark:hover:bg-red-950/30",
    badgeColor: "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300",
  },
  {
    username: "manager",
    label: "部門マネージャー",
    role: "HR_MANAGER" as UserRole,
    description: "営業本部管轄・給与マスキング適用",
    features: [
      "管轄部門ダッシュボード",
      "給与データ（動的マスキング）",
      "部門内評価管理",
      "部門離職リスク",
      "AIエージェント相談",
    ],
    icon: Users,
    iconBg: "bg-blue-100 dark:bg-blue-950",
    iconColor: "text-blue-600 dark:text-blue-400",
    borderColor: "border-blue-200 dark:border-blue-800",
    hoverBg: "hover:bg-blue-50/50 dark:hover:bg-blue-950/30",
    badgeColor: "bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300",
  },
  {
    username: "viewer",
    label: "一般閲覧者",
    role: "HR_VIEWER" as UserRole,
    description: "第一営業課のみ・給与/評価マスキング",
    features: [
      "限定ダッシュボード",
      "所属課の社員一覧",
      "給与・評価（マスキング）",
      "AIエージェント（制限付き）",
    ],
    icon: Eye,
    iconBg: "bg-emerald-100 dark:bg-emerald-950",
    iconColor: "text-emerald-600 dark:text-emerald-400",
    borderColor: "border-emerald-200 dark:border-emerald-800",
    hoverBg: "hover:bg-emerald-50/50 dark:hover:bg-emerald-950/30",
    badgeColor:
      "bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300",
  },
  {
    username: "linemgr",
    label: "評価者（課長）",
    role: "LINE_MANAGER" as UserRole,
    description: "内田洋平 課長・自分が評価する部下8名のみ",
    features: [
      "マイチームの評価進捗",
      "評価コメント入力とAI採点",
      "AIスコアの軸別修正（理由付き）",
      "人事への提出・差し戻し対応",
    ],
    icon: UserCheck,
    iconBg: "bg-amber-100 dark:bg-amber-950",
    iconColor: "text-amber-600 dark:text-amber-400",
    borderColor: "border-amber-200 dark:border-amber-800",
    hoverBg: "hover:bg-amber-50/50 dark:hover:bg-amber-950/30",
    badgeColor: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-300",
  },
];

const TECH_STACK = [
  { label: "Cortex Agent", icon: Brain },
  { label: "ML Registry", icon: Database },
  { label: "Dynamic Masking", icon: Lock },
  { label: "Cortex Search", icon: Search },
  { label: "Iceberg", icon: Snowflake },
];

export default function LoginPage() {
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [hoveredUser, setHoveredUser] = useState<string | null>(null);
  const { login } = useAuth();
  const router = useRouter();

  const handleLogin = async (username: string) => {
    setLoading(username);
    setError("");
    try {
      await login(username);
      router.push(username === "linemgr" ? "/my-team" : "/");
    } catch {
      setError("ログインに失敗しました");
    } finally {
      setLoading(null);
    }
  };

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-gradient-to-br from-slate-50 via-blue-50/30 to-slate-100 dark:from-slate-950 dark:via-blue-950/20 dark:to-slate-900 p-4">
      <div className="w-full max-w-2xl space-y-8">
        <div className="text-center space-y-3">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-blue-100/80 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 text-xs font-medium mb-2">
            <Snowflake className="h-3 w-3" />
            Snowflake Native App Demo
          </div>
          <h1 className="text-4xl font-bold tracking-tight bg-gradient-to-r from-slate-900 via-blue-900 to-slate-900 dark:from-white dark:via-blue-200 dark:to-white bg-clip-text text-transparent">
            HR Intelligence
          </h1>
          <p className="text-muted-foreground max-w-md mx-auto leading-relaxed">
            AIを活用した次世代人事データプラットフォーム。
            <br />
            社員管理・評価・離職予測・組織シミュレーションを統合し、
            <br />
            ロールベースの動的データマスキングで安全にデータを提供します。
          </p>
        </div>

        <Card className="border-0 shadow-lg shadow-slate-200/50 dark:shadow-slate-900/50">
          <CardHeader className="pb-4">
            <CardTitle className="text-lg">デモログイン</CardTitle>
            <CardDescription>
              ロールを選択してデモ環境にアクセスします。各ロールでデータの表示範囲とマスキングレベルが異なります。
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {DEMO_USERS.map((u) => (
              <button
                key={u.username}
                onClick={() => handleLogin(u.username)}
                onMouseEnter={() => setHoveredUser(u.username)}
                onMouseLeave={() => setHoveredUser(null)}
                disabled={loading !== null}
                className={`w-full text-left rounded-xl border-2 transition-all duration-200 disabled:opacity-50 ${u.borderColor} ${u.hoverBg} hover:shadow-md hover:scale-[1.01] active:scale-[0.99]`}
              >
                <div className="flex items-center gap-4 p-4">
                  <div
                    className={`flex items-center justify-center h-12 w-12 rounded-xl ${u.iconBg} shrink-0`}
                  >
                    <u.icon className={`h-6 w-6 ${u.iconColor}`} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-sm">{u.label}</span>
                      <Badge
                        variant="secondary"
                        className={`text-[10px] px-1.5 py-0 ${u.badgeColor}`}
                      >
                        {u.role}
                      </Badge>
                    </div>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {u.description}
                    </p>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {loading === u.username ? (
                      <div className="animate-spin h-5 w-5 border-2 border-current border-t-transparent rounded-full" />
                    ) : (
                      <ChevronRight
                        className={`h-4 w-4 text-muted-foreground transition-transform duration-200 ${hoveredUser === u.username ? "translate-x-0.5" : ""}`}
                      />
                    )}
                  </div>
                </div>
                <div
                  className={`overflow-hidden transition-all duration-300 ease-in-out ${hoveredUser === u.username ? "max-h-40 opacity-100" : "max-h-0 opacity-0"}`}
                >
                  <div className="px-4 pb-4 pt-0">
                    <div className="flex flex-wrap gap-1.5">
                      {u.features.map((f) => (
                        <Badge
                          key={f}
                          variant="outline"
                          className="text-[10px] font-normal"
                        >
                          {f}
                        </Badge>
                      ))}
                    </div>
                  </div>
                </div>
              </button>
            ))}
            {error && (
              <p className="text-sm text-destructive text-center pt-1">
                {error}
              </p>
            )}
          </CardContent>
        </Card>

        <div className="text-center space-y-3">
          <p className="text-[11px] text-muted-foreground font-medium uppercase tracking-widest">
            Powered by Snowflake
          </p>
          <div className="flex justify-center flex-wrap gap-3">
            {TECH_STACK.map((t) => (
              <div
                key={t.label}
                className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-white/60 dark:bg-slate-800/60 border border-slate-200/80 dark:border-slate-700/80 text-[11px] text-muted-foreground"
              >
                <t.icon className="h-3 w-3" />
                {t.label}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
