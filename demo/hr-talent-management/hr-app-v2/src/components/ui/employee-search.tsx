"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { Input } from "@/components/ui/input";
import { Search, X } from "lucide-react";

interface SearchResult {
  employee_id: number;
  name: string;
  dept_name: string | null;
  grade: string | null;
  position_name: string | null;
}

interface EmployeeSearchProps {
  value: string;
  onSelect: (employeeId: number, name: string) => void;
  onClear?: () => void;
  placeholder?: string;
  selectedLabel?: string;
}

export function EmployeeSearch({
  value,
  onSelect,
  onClear,
  placeholder = "名前または社員番号で検索",
  selectedLabel,
}: EmployeeSearchProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  const search = useCallback(async (q: string) => {
    if (q.length < 2) {
      setResults([]);
      return;
    }
    setLoading(true);
    try {
      const res = await fetch(`/api/employees/search?q=${encodeURIComponent(q)}&limit=10`);
      if (res.ok) setResults(await res.json());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => search(query), 300);
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, [query, search]);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  if (value && selectedLabel) {
    return (
      <div className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm">
        <span className="flex-1 truncate">{selectedLabel}</span>
        <button
          type="button"
          onClick={() => { onClear?.(); setQuery(""); }}
          className="text-muted-foreground hover:text-foreground"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    );
  }

  return (
    <div ref={ref} className="relative">
      <div className="relative">
        <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
        <Input
          value={query}
          onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
          onFocus={() => { if (results.length > 0) setOpen(true); }}
          placeholder={placeholder}
          className="pl-8"
        />
      </div>
      {open && (query.length >= 2) && (
        <div className="absolute z-50 mt-1 w-full rounded-md border bg-popover shadow-lg max-h-60 overflow-auto">
          {loading && <div className="p-3 text-sm text-muted-foreground">検索中...</div>}
          {!loading && results.length === 0 && (
            <div className="p-3 text-sm text-muted-foreground">該当なし</div>
          )}
          {results.map((r) => (
            <button
              key={r.employee_id}
              type="button"
              className="w-full text-left px-3 py-2 text-sm hover:bg-accent flex items-center justify-between"
              onClick={() => {
                onSelect(r.employee_id, `${r.name}（${r.dept_name || "-"}・${r.grade || "-"}）`);
                setOpen(false);
                setQuery("");
              }}
            >
              <span className="font-medium">{r.name}</span>
              <span className="text-xs text-muted-foreground">
                {r.dept_name || "-"} / {r.grade || "-"} / ID:{r.employee_id}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
