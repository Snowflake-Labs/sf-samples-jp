import Link from "next/link";
import { Info } from "lucide-react";

/**
 * One line under the page title telling which transfer screen to use.
 * 異動シナリオ作成 plans several moves together; 玉突き人事 fills one
 * vacancy caused by a resignation or transfer request, step by step.
 */
export function TransferModeHint({ current }: { current: "scenario" | "chain" }) {
  return (
    <p className="text-xs text-muted-foreground flex items-start gap-1.5 shrink-0">
      <Info className="h-3.5 w-3.5 shrink-0 mt-0.5" />
      {current === "scenario" ? (
        <span>
          定期異動など、複数の昇格・異動・退職をまとめて計画する画面です。
          退職や異動申請で空いた 1 つのポストを順に埋める場合は
          <Link href="/chain-simulation" className="text-blue-600 hover:underline mx-0.5">玉突き人事</Link>
          を使います。
        </span>
      ) : (
        <span>
          退職・異動申請など、突発的に空いた 1 つのポストの後任を、AI の比較を見ながら順に決める画面です。
          定期異動など複数の動きをまとめて計画する場合は
          <Link href="/simulation" className="text-blue-600 hover:underline mx-0.5">異動シナリオ作成</Link>
          を使います。
        </span>
      )}
    </p>
  );
}
