"use client";

import Link from "next/link";
import { ChevronRight, Home } from "lucide-react";

export interface Crumb {
  label: string;
  href?: string;
}

/**
 * Breadcrumb trail for nested pages. Pass the ancestors in order;
 * the last item is rendered as the current page (not a link).
 *
 *   <Breadcrumb items={[
 *     { label: "社員一覧", href: "/employees" },
 *     { label: emp.NAME, href: `/employees/${id}` },
 *     { label: "スキル管理" },
 *   ]} />
 */
export function Breadcrumb({ items }: { items: Crumb[] }) {
  return (
    <nav aria-label="パンくずリスト" className="flex items-center gap-1 text-xs text-muted-foreground mb-3 flex-wrap">
      <Link href="/" className="flex items-center gap-1 hover:text-foreground transition-colors">
        <Home className="h-3 w-3" />
        <span>ダッシュボード</span>
      </Link>
      {items.map((item, i) => {
        const isLast = i === items.length - 1;
        return (
          <span key={i} className="flex items-center gap-1">
            <ChevronRight className="h-3 w-3 shrink-0" />
            {isLast || !item.href ? (
              <span className={isLast ? "text-foreground font-medium" : ""} aria-current={isLast ? "page" : undefined}>
                {item.label}
              </span>
            ) : (
              <Link href={item.href} className="hover:text-foreground transition-colors">
                {item.label}
              </Link>
            )}
          </span>
        );
      })}
    </nav>
  );
}
