"use client";

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  type ReactNode,
} from "react";
import type { Department } from "@/lib/types";

interface HonbuContextType {
  honbu: string;
  setHonbu: (id: string) => void;
  honbuList: Department[];
  honbuLoading: boolean;
}

const HonbuContext = createContext<HonbuContextType>({
  honbu: "",
  setHonbu: () => {},
  honbuList: [],
  honbuLoading: true,
});

const STORAGE_KEY = "hr_honbu_id";

export function HonbuProvider({ children }: { children: ReactNode }) {
  const [honbuList, setHonbuList] = useState<Department[]>([]);
  const [honbu, setHonbuRaw] = useState("");
  const [honbuLoading, setHonbuLoading] = useState(true);

  const setHonbu = useCallback((id: string) => {
    setHonbuRaw(id);
    try {
      sessionStorage.setItem(STORAGE_KEY, id);
    } catch {}
  }, []);

  useEffect(() => {
    fetch("/api/departments?level=1")
      .then((r) => r.json())
      .then((raw) => Array.isArray(raw) ? raw as Department[] : [])
      .then((depts) => {
        setHonbuList(depts);
        let saved = "";
        try {
          saved = sessionStorage.getItem(STORAGE_KEY) || "";
        } catch {}
        if (saved && depts.some((d) => String(d.DEPT_ID) === saved)) {
          setHonbuRaw(saved);
        } else if (depts.length > 0) {
          const first = String(depts[0].DEPT_ID);
          setHonbuRaw(first);
          try {
            sessionStorage.setItem(STORAGE_KEY, first);
          } catch {}
        }
      })
      .finally(() => setHonbuLoading(false));
  }, []);

  return (
    <HonbuContext.Provider value={{ honbu, setHonbu, honbuList, honbuLoading }}>
      {children}
    </HonbuContext.Provider>
  );
}

export const useHonbu = () => useContext(HonbuContext);
