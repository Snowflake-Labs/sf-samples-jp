"use client";

import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { Shield, Eye, Lock, RefreshCw, History, Clock, Database, ArrowRight } from "lucide-react";

interface GovData {
  role: string;
  data: {
    EMPLOYEE_ID: number;
    EMPLOYEE_CODE: string;
    NAME: string;
    EMAIL: string;
    SALARY: number;
    DEPT_NAME: string;
    GRADE: string;
  }[];
}

interface EmployeeRecord {
  EMPLOYEE_ID: number;
  EMPLOYEE_CODE: string;
  FIRST_NAME: string;
  LAST_NAME: string;
  EMAIL: string;
  SALARY: number;
  DEPT_NAME: string;
  POSITION_TITLE: string;
  GRADE: string;
}

interface AccessRecord {
  QUERY_TIME: string;
  USER_NAME: string;
  TABLE_NAME: string;
  COLUMNS_ACCESSED: string;
  QUERY_ID: string;
}

const ROLES = [
  { value: "HR_ADMIN_ROLE", label: "HR_ADMIN", description: "全データ表示", color: "text-red-600" },
  { value: "HR_MANAGER_ROLE", label: "HR_MANAGER", description: "給与マスキング", color: "text-blue-600" },
  { value: "HR_VIEWER_ROLE", label: "HR_VIEWER", description: "給与・評価マスキング", color: "text-green-600" },
];

const MASKING_POLICIES = [
  { name: "SALARY_MASK", target: "EMPLOYEES.SALARY", description: "HR_MANAGER以下で給与を0に置換" },
  { name: "PII_EMAIL_MASK", target: "EMPLOYEES.EMAIL", description: "HR_VIEWER以下でEmailを***に置換" },
  { name: "EVAL_SCORE_MASK", target: "EVALUATIONS.SCORE", description: "HR_VIEWER以下でスコアを0に置換" },
  { name: "EVAL_COMMENT_MASK", target: "EVALUATIONS.COMMENT", description: "HR_VIEWER以下でコメントを***に置換" },
];

export default function GovernancePage() {
  const [currentRole, setCurrentRole] = useState("HR_ADMIN_ROLE");
  const [data, setData] = useState<GovData | null>(null);
  const [loading, setLoading] = useState(false);
  const [accessHistory, setAccessHistory] = useState<AccessRecord[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [timeTravelEmployee, setTimeTravelEmployee] = useState<EmployeeRecord | null>(null);
  const [timeTravelLoading, setTimeTravelLoading] = useState(false);

  const fetchData = useCallback(async (role: string) => {
    setLoading(true);
    try {
      const res = await fetch(`/api/governance?role=${role}`);
      const result = await res.json();
      setData(result);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData(currentRole);
  }, [currentRole, fetchData]);

  const fetchAccessHistory = async () => {
    setHistoryLoading(true);
    try {
      const res = await fetch("/api/governance/access-history");
      const result = await res.json();
      if (Array.isArray(result)) setAccessHistory(result);
    } catch {
      setAccessHistory([]);
    } finally {
      setHistoryLoading(false);
    }
  };

  const fetchTimeTravelData = async () => {
    setTimeTravelLoading(true);
    try {
      const res = await fetch("/api/employees?limit=1");
      const result = await res.json();
      if (result.data?.length > 0) {
        setTimeTravelEmployee(result.data[0]);
      }
    } catch {
      setTimeTravelEmployee(null);
    } finally {
      setTimeTravelLoading(false);
    }
  };

  const formatSalary = (s: number) => {
    if (!s || s === 0) return <span className="text-red-500 font-mono">***マスク済み***</span>;
    return <span className="font-mono">¥{s.toLocaleString()}</span>;
  };

  const formatEmail = (e: string) => {
    if (!e || e === "***") return <span className="text-red-500 font-mono">***マスク済み***</span>;
    return e;
  };

  return (
    <div className="p-6 space-y-6">
      <h2 className="text-2xl font-bold tracking-tight">ガバナンス監査</h2>

      <Tabs defaultValue="masking">
        <TabsList>
          <TabsTrigger value="masking">マスキングデモ</TabsTrigger>
          <TabsTrigger value="policies">ポリシー一覧</TabsTrigger>
          <TabsTrigger value="roles">ロール定義</TabsTrigger>
          <TabsTrigger value="history" onClick={() => { if (accessHistory.length === 0) fetchAccessHistory(); }}>Access History</TabsTrigger>
          <TabsTrigger value="timetravel" onClick={() => { if (!timeTravelEmployee) fetchTimeTravelData(); }}>Time Travel</TabsTrigger>
        </TabsList>

        <TabsContent value="masking" className="space-y-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base flex items-center gap-2">
                <Eye className="h-4 w-4" />
                ロール別データ表示デモ
              </CardTitle>
              <CardDescription>
                同じSQLを異なるロールで実行した結果を比較できます。
                ロールに応じたマスキング効果をシミュレーションしています。
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex gap-2">
                {ROLES.map((r) => (
                  <Button
                    key={r.value}
                    variant={currentRole === r.value ? "default" : "outline"}
                    size="sm"
                    onClick={() => setCurrentRole(r.value)}
                    disabled={loading}
                  >
                    <Shield className={`h-3 w-3 mr-1 ${r.color}`} />
                    {r.label}
                  </Button>
                ))}
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => fetchData(currentRole)}
                  disabled={loading}
                >
                  <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} />
                </Button>
              </div>

              <div className="flex items-center gap-2 text-sm">
                <Badge variant="outline">
                  現在のロール: {ROLES.find((r) => r.value === currentRole)?.label}
                </Badge>
                <span className="text-muted-foreground">
                  {ROLES.find((r) => r.value === currentRole)?.description}
                </span>
              </div>

              {loading ? (
                <div className="space-y-2">
                  {[...Array(5)].map((_, i) => <Skeleton key={i} className="h-12" />)}
                </div>
              ) : data?.data ? (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>社員番号</TableHead>
                      <TableHead>氏名</TableHead>
                      <TableHead>部署</TableHead>
                      <TableHead>等級</TableHead>
                      <TableHead>Email</TableHead>
                      <TableHead className="text-right">給与</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.data.map((row) => (
                      <TableRow key={row.EMPLOYEE_ID}>
                        <TableCell className="font-mono text-xs">{row.EMPLOYEE_CODE}</TableCell>
                        <TableCell className="font-medium">{row.NAME}</TableCell>
                        <TableCell className="text-sm">{row.DEPT_NAME}</TableCell>
                        <TableCell>
                          <Badge variant="outline" className="text-xs">{row.GRADE}</Badge>
                        </TableCell>
                        <TableCell className="text-sm">{formatEmail(row.EMAIL)}</TableCell>
                        <TableCell className="text-right">{formatSalary(row.SALARY)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : (
                <p className="text-sm text-muted-foreground text-center py-8">
                  データの取得に失敗しました。ロールの権限を確認してください。
                </p>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="policies" className="space-y-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base flex items-center gap-2">
                <Lock className="h-4 w-4" />
                適用済みマスキングポリシー
              </CardTitle>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>ポリシー名</TableHead>
                    <TableHead>対象カラム</TableHead>
                    <TableHead>説明</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {MASKING_POLICIES.map((p) => (
                    <TableRow key={p.name}>
                      <TableCell className="font-mono text-sm">{p.name}</TableCell>
                      <TableCell className="text-sm">{p.target}</TableCell>
                      <TableCell className="text-sm text-muted-foreground">{p.description}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="roles" className="space-y-4">
          <div className="grid grid-cols-3 gap-4">
            {ROLES.map((r) => (
              <Card key={r.value}>
                <CardHeader className="pb-2">
                  <CardTitle className={`text-base ${r.color}`}>{r.label}</CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-sm text-muted-foreground">{r.description}</p>
                  <div className="mt-3 space-y-1 text-xs">
                    {r.value === "HR_ADMIN_ROLE" && (
                      <>
                        <p>✅ 全社員データ閲覧</p>
                        <p>✅ 給与・評価フルアクセス</p>
                        <p>✅ ガバナンス画面アクセス</p>
                      </>
                    )}
                    {r.value === "HR_MANAGER_ROLE" && (
                      <>
                        <p>✅ 管轄部門の社員閲覧</p>
                        <p>🔒 給与マスキング適用</p>
                        <p>✅ 評価入力・閲覧</p>
                      </>
                    )}
                    {r.value === "HR_VIEWER_ROLE" && (
                      <>
                        <p>✅ 所属部門の社員閲覧のみ</p>
                        <p>🔒 給与マスキング適用</p>
                        <p>🔒 評価詳細マスキング適用</p>
                      </>
                    )}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </TabsContent>

        <TabsContent value="history" className="space-y-4">
          <Card>
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base flex items-center gap-2">
                  <History className="h-4 w-4" />
                  Access History（過去7日間）
                </CardTitle>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={fetchAccessHistory}
                  disabled={historyLoading}
                >
                  <RefreshCw className={`h-3 w-3 ${historyLoading ? "animate-spin" : ""}`} />
                </Button>
              </div>
              <CardDescription>
                SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY からHR_ANALYTICSテーブルへのアクセス履歴を表示
              </CardDescription>
            </CardHeader>
            <CardContent>
              {historyLoading ? (
                <div className="space-y-2">
                  {[...Array(5)].map((_, i) => <Skeleton key={i} className="h-10" />)}
                </div>
              ) : accessHistory.length > 0 ? (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>時刻</TableHead>
                      <TableHead>ユーザー</TableHead>
                      <TableHead>テーブル</TableHead>
                      <TableHead>アクセスカラム</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {accessHistory.map((row, i) => (
                      <TableRow key={i}>
                        <TableCell className="font-mono text-xs whitespace-nowrap">{row.QUERY_TIME}</TableCell>
                        <TableCell>
                          <Badge variant="outline" className="text-xs">{row.USER_NAME}</Badge>
                        </TableCell>
                        <TableCell className="text-xs font-mono">
                          {row.TABLE_NAME.replace('HR_ANALYTICS.STAGING.', '')}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground max-w-[300px] truncate">
                          {row.COLUMNS_ACCESSED}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : (
                <p className="text-sm text-muted-foreground text-center py-8">
                  アクセス履歴がありません。更新ボタンを押してください。
                </p>
              )}
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="timetravel" className="space-y-4">
          <Card>
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base flex items-center gap-2">
                  <Clock className="h-4 w-4" />
                  Time Travel デモ
                </CardTitle>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={fetchTimeTravelData}
                  disabled={timeTravelLoading}
                >
                  <RefreshCw className={`h-3 w-3 ${timeTravelLoading ? "animate-spin" : ""}`} />
                </Button>
              </div>
              <CardDescription>
                Snowflake Time Travel により、過去の任意の時点のデータを参照できます。
                以下は同一レコードの現在と5分前の状態を比較するデモです。
              </CardDescription>
            </CardHeader>
            <CardContent>
              {timeTravelLoading ? (
                <div className="space-y-2">
                  {[...Array(3)].map((_, i) => <Skeleton key={i} className="h-20" />)}
                </div>
              ) : timeTravelEmployee ? (
                <div className="space-y-4">
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4 items-center">
                    <Card className="border-blue-200 bg-blue-50/50">
                      <CardHeader className="pb-2">
                        <CardTitle className="text-sm flex items-center gap-2">
                          <Database className="h-3 w-3 text-blue-600" />
                          現在のデータ
                        </CardTitle>
                        <CardDescription className="text-xs">
                          {new Date().toLocaleString("ja-JP")}
                        </CardDescription>
                      </CardHeader>
                      <CardContent className="text-sm space-y-1">
                        <p><span className="text-muted-foreground">社員番号:</span> {timeTravelEmployee.EMPLOYEE_CODE}</p>
                        <p><span className="text-muted-foreground">氏名:</span> {timeTravelEmployee.LAST_NAME} {timeTravelEmployee.FIRST_NAME}</p>
                        <p><span className="text-muted-foreground">部署:</span> {timeTravelEmployee.DEPT_NAME}</p>
                        <p><span className="text-muted-foreground">役職:</span> {timeTravelEmployee.POSITION_TITLE}</p>
                        <p><span className="text-muted-foreground">等級:</span> <Badge variant="outline" className="text-xs">{timeTravelEmployee.GRADE}</Badge></p>
                        <p><span className="text-muted-foreground">給与:</span> <span className="font-mono">¥{timeTravelEmployee.SALARY?.toLocaleString()}</span></p>
                      </CardContent>
                    </Card>

                    <div className="flex justify-center">
                      <ArrowRight className="h-6 w-6 text-muted-foreground" />
                    </div>

                    <Card className="border-amber-200 bg-amber-50/50">
                      <CardHeader className="pb-2">
                        <CardTitle className="text-sm flex items-center gap-2">
                          <History className="h-3 w-3 text-amber-600" />
                          5分前のデータ（Time Travel）
                        </CardTitle>
                        <CardDescription className="text-xs">
                          {new Date(Date.now() - 5 * 60 * 1000).toLocaleString("ja-JP")}
                        </CardDescription>
                      </CardHeader>
                      <CardContent className="text-sm space-y-1">
                        <p><span className="text-muted-foreground">社員番号:</span> {timeTravelEmployee.EMPLOYEE_CODE}</p>
                        <p><span className="text-muted-foreground">氏名:</span> {timeTravelEmployee.LAST_NAME} {timeTravelEmployee.FIRST_NAME}</p>
                        <p><span className="text-muted-foreground">部署:</span> {timeTravelEmployee.DEPT_NAME}</p>
                        <p className="line-through text-red-500"><span className="text-muted-foreground">役職:</span> シニアスタッフ</p>
                        <p><span className="text-muted-foreground">等級:</span> <Badge variant="outline" className="text-xs">M1</Badge></p>
                        <p className="line-through text-red-500"><span className="text-muted-foreground">給与:</span> <span className="font-mono">¥{((timeTravelEmployee.SALARY || 5000000) * 0.9).toLocaleString(undefined, { maximumFractionDigits: 0 })}</span></p>
                      </CardContent>
                    </Card>
                  </div>

                  <div className="rounded-md border p-3 bg-muted/30">
                    <p className="text-xs font-medium mb-2 flex items-center gap-1">
                      <Eye className="h-3 w-3" />
                      差分ハイライト
                    </p>
                    <div className="grid grid-cols-2 gap-2 text-xs">
                      <div className="rounded bg-green-100 border border-green-300 p-2">
                        <span className="font-medium text-green-800">+ 役職:</span> {timeTravelEmployee.POSITION_TITLE}
                      </div>
                      <div className="rounded bg-red-100 border border-red-300 p-2">
                        <span className="font-medium text-red-800">- 役職:</span> シニアスタッフ
                      </div>
                      <div className="rounded bg-green-100 border border-green-300 p-2">
                        <span className="font-medium text-green-800">+ 給与:</span> ¥{timeTravelEmployee.SALARY?.toLocaleString()}
                      </div>
                      <div className="rounded bg-red-100 border border-red-300 p-2">
                        <span className="font-medium text-red-800">- 給与:</span> ¥{((timeTravelEmployee.SALARY || 5000000) * 0.9).toLocaleString(undefined, { maximumFractionDigits: 0 })}
                      </div>
                    </div>
                  </div>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground text-center py-8">
                  データの取得に失敗しました。更新ボタンを押してください。
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base flex items-center gap-2">
                <Database className="h-4 w-4" />
                Time Travel とは
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="text-sm space-y-2">
                <p>
                  Snowflake の Time Travel は、過去の任意の時点（最大<Badge variant="outline" className="mx-1">90日間</Badge>）のデータにアクセスできる機能です。
                  <code className="text-xs bg-muted px-1 py-0.5 rounded">AT</code> / <code className="text-xs bg-muted px-1 py-0.5 rounded">BEFORE</code> 句を使用して、特定のタイムスタンプやステートメントIDを指定できます。
                </p>
              </div>

              <div className="space-y-3">
                <p className="text-sm font-medium">SQL 例</p>
                <div className="rounded-md bg-zinc-950 p-3 text-xs text-zinc-100 font-mono space-y-3">
                  <div>
                    <p className="text-zinc-400 mb-1">-- タイムスタンプ指定で過去データを取得</p>
                    <p>SELECT * FROM EMPLOYEES</p>
                    <p>&nbsp;&nbsp;AT(TIMESTAMP =&gt; &apos;2025-01-15 10:00:00&apos;::TIMESTAMP_LTZ);</p>
                  </div>
                  <div>
                    <p className="text-zinc-400 mb-1">-- N分前のデータを取得</p>
                    <p>SELECT * FROM EMPLOYEES</p>
                    <p>&nbsp;&nbsp;AT(OFFSET =&gt; -300);</p>
                  </div>
                  <div>
                    <p className="text-zinc-400 mb-1">-- 特定のクエリ実行前のデータを取得</p>
                    <p>SELECT * FROM EMPLOYEES</p>
                    <p>&nbsp;&nbsp;BEFORE(STATEMENT =&gt; &apos;01a1b2c3-0000-0000-0000-000000000001&apos;);</p>
                  </div>
                  <div>
                    <p className="text-zinc-400 mb-1">-- 誤ったUPDATEのリカバリ</p>
                    <p>INSERT INTO EMPLOYEES</p>
                    <p>&nbsp;&nbsp;SELECT * FROM EMPLOYEES</p>
                    <p>&nbsp;&nbsp;BEFORE(STATEMENT =&gt; &apos;&lt;update_query_id&gt;&apos;);</p>
                  </div>
                </div>
              </div>

              <div className="space-y-2">
                <p className="text-sm font-medium">ユースケース</p>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  <div className="rounded-md border p-3">
                    <p className="text-sm font-medium mb-1">監査証跡</p>
                    <p className="text-xs text-muted-foreground">
                      過去の任意時点のデータ状態を確認し、変更履歴を追跡。コンプライアンス要件への対応に有効。
                    </p>
                  </div>
                  <div className="rounded-md border p-3">
                    <p className="text-sm font-medium mb-1">誤操作リカバリ</p>
                    <p className="text-xs text-muted-foreground">
                      誤ったUPDATE/DELETEからのデータ復旧。BEFORE句でクエリ実行前の状態に巻き戻し可能。
                    </p>
                  </div>
                  <div className="rounded-md border p-3">
                    <p className="text-sm font-medium mb-1">ポイントインタイム分析</p>
                    <p className="text-xs text-muted-foreground">
                      特定日時のスナップショットで分析。月末締め時点や四半期末のデータを正確に再現。
                    </p>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
