"use client";

import { createContext, useContext, useState, useCallback, type ReactNode } from "react";

type DataPath = "warehouse" | "pg_lake";

interface DataPathContextType {
  dataPath: DataPath;
  toggle: () => void;
  isPgLake: boolean;
}

const DataPathContext = createContext<DataPathContextType>({
  dataPath: "pg_lake",
  toggle: () => {},
  isPgLake: true,
});

export function DataPathProvider({ children }: { children: ReactNode }) {
  const [dataPath, setDataPath] = useState<DataPath>(() => {
    if (typeof document !== "undefined") {
      const match = document.cookie.match(/(?:^|;\s*)data_path=(\w+)/);
      return (match?.[1] as DataPath) || "pg_lake";
    }
    return "pg_lake";
  });

  const toggle = useCallback(() => {
    setDataPath((prev) => {
      const next = prev === "pg_lake" ? "warehouse" : "pg_lake";
      document.cookie = `data_path=${next};path=/;max-age=31536000`;
      return next;
    });
  }, []);

  return (
    <DataPathContext.Provider value={{ dataPath, toggle, isPgLake: dataPath === "pg_lake" }}>
      {children}
    </DataPathContext.Provider>
  );
}

export function useDataPath() {
  return useContext(DataPathContext);
}
