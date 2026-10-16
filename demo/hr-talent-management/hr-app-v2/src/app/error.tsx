"use client";

import { useEffect } from "react";
import { Button } from "@/components/ui/button";
import { isChunkError, shouldAutoReload, RELOAD_KEY } from "@/lib/chunk-error";

export default function AppError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error("[app error]", error);
    const last = Number(sessionStorage.getItem(RELOAD_KEY) ?? 0);
    if (shouldAutoReload(error, last, Date.now())) {
      sessionStorage.setItem(RELOAD_KEY, String(Date.now()));
      window.location.reload();
    }
  }, [error]);

  const chunk = isChunkError(error);
  return (
    <div className="mx-auto max-w-lg space-y-4 p-8">
      <h2 className="text-lg font-semibold">
        {chunk ? "アプリが更新されました" : "画面の表示中にエラーが発生しました"}
      </h2>
      <p className="text-sm text-muted-foreground">
        {chunk
          ? "新しいバージョンが公開されたため、ページを再読み込みしてください。入力途中の内容は保存されていない可能性があります。"
          : "保存済みのデータには影響ありません。再試行しても解消しない場合は、下記の内容を管理者に伝えてください。"}
      </p>
      {!chunk && (
        <pre className="max-h-40 overflow-auto rounded-md bg-muted p-2 text-xs">
          {error.message}{error.digest ? `\n(digest: ${error.digest})` : ""}
        </pre>
      )}
      <div className="flex gap-2">
        {!chunk && <Button variant="outline" onClick={reset}>再試行</Button>}
        <Button onClick={() => window.location.reload()}>再読み込み</Button>
      </div>
    </div>
  );
}
