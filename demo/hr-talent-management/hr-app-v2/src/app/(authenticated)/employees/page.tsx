"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import Link from "next/link";
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Search, ChevronDown, Download, UserPlus } from "lucide-react";
import type { Employee, Department } from "@/lib/types";
import { GRADE_LABELS } from "@/lib/types";
import { useHonbu } from "@/lib/honbu-context";

const PAGE_SIZE = 50;
const DEBOUNCE_MS = 300;

export default function EmployeeListPage() {
  const [employees, setEmployees] = useState<Employee[]>([]);
  const { honbu, setHonbu, honbuList } = useHonbu();
  const [childDepts, setChildDepts] = useState<Department[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [deptFilter, setDeptFilter] = useState("");
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [offset, setOffset] = useState(0);
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fetchCounter = useRef(0);

  useEffect(() => {
    if (debounceTimer.current) clearTimeout(debounceTimer.current);
    debounceTimer.current = setTimeout(() => {
      setDebouncedSearch(search);
    }, DEBOUNCE_MS);
    return () => {
      if (debounceTimer.current) clearTimeout(debounceTimer.current);
    };
  }, [search]);

  useEffect(() => {
    if (!honbu) return;
    setDeptFilter("");
    fetch(`/api/departments?parent_id=${honbu}`)
      .then((r) => {
        if (!r.ok) throw new Error("Failed to fetch child departments");
        return r.json();
      })
      .then((depts: Department[]) => setChildDepts(depts))
      .catch((err) => console.error("Child departments error:", err));
  }, [honbu]);

  const fetchEmployees = useCallback((h: string, d: string, q: string, off: number, append: boolean) => {
    if (!h) return;
    const thisRequest = ++fetchCounter.current;
    if (append) setLoadingMore(true);
    else setLoading(true);
    const params = new URLSearchParams();
    params.set("honbu", h);
    if (d) params.set("dept", d);
    if (q) params.set("q", q);
    params.set("limit", String(PAGE_SIZE));
    params.set("offset", String(off));
    fetch(`/api/employees?${params}`)
      .then((r) => {
        if (!r.ok) throw new Error("Failed to fetch employees");
        return r.json();
      })
      .then((res) => {
        if (thisRequest !== fetchCounter.current) return;
        if (append) {
          setEmployees((prev) => [...prev, ...res.data]);
        } else {
          setEmployees(res.data);
        }
        setTotal(res.total);
        setHasMore(res.hasMore);
        setOffset(off + res.data.length);
      })
      .catch((err) => console.error("Employees error:", err))
      .finally(() => {
        if (thisRequest !== fetchCounter.current) return;
        setLoading(false);
        setLoadingMore(false);
      });
  }, []);

  useEffect(() => {
    if (honbu) {
      fetchEmployees(honbu, deptFilter, debouncedSearch, 0, false);
    }
  }, [honbu, deptFilter, debouncedSearch, fetchEmployees]);

  const loadMore = () => {
    fetchEmployees(honbu, deptFilter, debouncedSearch, offset, true);
  };

  const formatSalary = (salary: number) => {
    if (!salary || salary === 0) return "***";
    return `¥${(salary / 10000).toLocaleString()}万`;
  };

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center gap-4 flex-wrap">
        <h2 className="text-2xl font-bold tracking-tight">社員一覧</h2>
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
        <Link href="/employees/new">
          <Button variant="default" size="sm" className="gap-1.5">
            <UserPlus className="h-3.5 w-3.5" />
            新規登録
          </Button>
        </Link>
      </div>

      <div className="flex gap-3 flex-wrap">
        <Select value={deptFilter} onValueChange={(v) => setDeptFilter(!v || v === "__all__" ? "" : v)}>
          <SelectTrigger className="w-52">
            <SelectValue placeholder="部署で絞り込み">
              {deptFilter ? childDepts.find((d) => String(d.DEPT_ID) === deptFilter)?.DEPT_NAME || "本部全体" : "本部全体"}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__">本部全体</SelectItem>
            {childDepts.map((d) => (
              <SelectItem key={d.DEPT_ID} value={String(d.DEPT_ID)}>
                {d.DEPT_NAME}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="氏名・社員番号で検索"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
          />
        </div>
      </div>

      <Card>
        <CardHeader className="pb-2 flex flex-row items-center justify-between">
          <CardTitle className="text-base">
            {loading ? "読み込み中..." : `${employees.length} / ${total.toLocaleString()}名`}
          </CardTitle>
          {!loading && employees.length > 0 && (
            <Button
              variant="outline"
              size="sm"
              className="gap-1.5"
              onClick={() => {
                const headers = ["社員番号","氏名","部署","役職","等級","入社日","給与"];
                const rows = employees.map((e) => [
                  e.EMPLOYEE_CODE,
                  `${e.LAST_NAME}${e.FIRST_NAME}`,
                  e.DEPT_NAME || "",
                  e.POSITION_TITLE || "",
                  e.GRADE || "",
                  e.HIRE_DATE?.slice(0, 10) || "",
                  String(e.SALARY || ""),
                ]);
                const bom = "\uFEFF";
                const csv = bom + [headers, ...rows].map((r) => r.map((c) => `"${c}"`).join(",")).join("\n");
                const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = `employees_${new Date().toISOString().slice(0,10)}.csv`;
                a.click();
                URL.revokeObjectURL(url);
              }}
            >
              <Download className="h-3.5 w-3.5" />
              CSV
            </Button>
          )}
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-2">
              {[...Array(10)].map((_, i) => (
                <Skeleton key={i} className="h-12" />
              ))}
            </div>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-24">社員番号</TableHead>
                    <TableHead>氏名</TableHead>
                    <TableHead>部署</TableHead>
                    <TableHead>役職</TableHead>
                    <TableHead>等級</TableHead>
                    <TableHead>入社日</TableHead>
                    <TableHead className="text-right">給与</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {employees.map((emp) => (
                    <TableRow key={emp.EMPLOYEE_ID} className="cursor-pointer hover:bg-accent">
                      <TableCell>
                        <Link
                          href={`/employees/${emp.EMPLOYEE_ID}`}
                          className="text-blue-600 hover:underline font-mono text-xs"
                        >
                          {emp.EMPLOYEE_CODE}
                        </Link>
                      </TableCell>
                      <TableCell className="font-medium">
                        <Link href={`/employees/${emp.EMPLOYEE_ID}`}>
                          {emp.LAST_NAME}{emp.FIRST_NAME}
                        </Link>
                      </TableCell>
                      <TableCell className="text-sm">{emp.DEPT_NAME}</TableCell>
                      <TableCell className="text-sm">{emp.POSITION_TITLE}</TableCell>
                      <TableCell>
                        <Badge variant="outline" className="text-xs">
                          {emp.GRADE} {GRADE_LABELS[emp.GRADE] || ""}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {emp.HIRE_DATE?.slice(0, 10)}
                      </TableCell>
                      <TableCell className="text-right font-mono text-sm">
                        {formatSalary(emp.SALARY)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {hasMore && (
                <div className="flex justify-center pt-4">
                  <Button
                    variant="outline"
                    onClick={loadMore}
                    disabled={loadingMore}
                    className="gap-2"
                  >
                    <ChevronDown className="h-4 w-4" />
                    {loadingMore ? "読み込み中..." : `もっと見る（次の${Math.min(PAGE_SIZE, total - offset).toLocaleString()}件）`}
                  </Button>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
