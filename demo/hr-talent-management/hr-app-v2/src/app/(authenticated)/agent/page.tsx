"use client";

import React, { useState, useRef, useEffect, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";

import { Send, Bot, User, Search, Loader2, Database, Brain, Sparkles, ChevronDown, Cog, Plus, MessageSquare, Trash2 } from "lucide-react";

interface ThinkingStep {
  tool: string;
  done: boolean;
}

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
  sql?: string;
  sqlResults?: unknown;
  searchResults?: SearchResult[];
  isAgent?: boolean;
  thinkingSteps?: ThinkingStep[];
  thinkingText?: string;
  statusText?: string;
}

interface SearchResult {
  EMPLOYEE_CODE: string;
  FULL_NAME: string;
  DEPT_NAME: string;
  POSITION_TITLE: string;
  GRADE: string;
  SKILLS: string;
}

interface SavedThread {
  id: number;
  threadId: string;
  title: string;
  parentMessageId: string;
  messages: Message[];
  createdAt: string;
  updatedAt: string;
}

const QUICK_ACTIONS = [
  "部署ごとの社員数を教えて",
  "離職リスクが高い社員は？",
  "営業経験のあるリーダー候補を探して",
  "平均評価スコアが高い部署のランキング",
  "Python が得意なエンジニアは？",
];

const TOOL_LABELS: Record<string, string> = {
  generate_and_run_sql: "SQL生成・実行",
  sql: "SQL生成・実行",
  cortex_search: "セマンティック検索",
  search: "セマンティック検索",
  cortex_analyst: "データ分析",
  analyst: "データ分析",
};

const WELCOME_MESSAGE: Message = {
  id: "welcome",
  role: "assistant",
  content: "HR AIエージェントです。人事に関する質問は何でもお聞きください。\n\nCortex Agent (HR_AGENT) が2つのツールを活用してお答えします:\n• 📊 構造化データ分析（SQL生成・実行）\n• 🔍 セマンティック人材検索",
  timestamp: new Date(),
  isAgent: true,
};

const STATUS_LABELS: Record<string, string> = {
  planning: "計画中...",
  executing_tool: "ツール実行中...",
  proceeding_to_answer: "回答を作成中...",
};

function ThinkingStepsView({ steps, sql, sqlResults, renderSqlResults, thinkingText, statusText }: {
  steps: ThinkingStep[];
  sql?: string;
  sqlResults?: unknown;
  renderSqlResults: (results: unknown) => React.ReactNode;
  thinkingText?: string;
  statusText?: string;
}) {
  const allDone = steps.every((s) => s.done);
  const [expanded, setExpanded] = useState(!allDone);

  useEffect(() => {
    if (!allDone) setExpanded(true);
  }, [allDone]);

  return (
    <div className="rounded-lg border border-muted bg-muted/30 px-3 py-2">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors w-full"
      >
        {allDone ? (
          <ChevronDown className={`h-3 w-3 transition-transform ${expanded ? "" : "-rotate-90"}`} />
        ) : (
          <Loader2 className="h-3 w-3 animate-spin" />
        )}
        <Cog className="h-3 w-3" />
        <span className="font-medium">{allDone ? `思考完了 — ${steps.length}件のツールを使用` : "思考中..."}</span>
      </button>
      {expanded && (
        <div className="mt-2 ml-3 pl-3 border-l-2 border-muted space-y-2">
          {statusText && (
            <div className="text-xs text-blue-500 font-medium">
              {STATUS_LABELS[statusText] || statusText}
            </div>
          )}
          {thinkingText && (
            <div className="text-xs text-muted-foreground whitespace-pre-wrap leading-relaxed bg-muted/40 rounded-md p-2">
              {thinkingText}
            </div>
          )}
          {steps.map((step, i) => (
            <div key={i} className="flex items-center gap-1.5 text-xs text-muted-foreground">
              {step.done ? (
                <span className="text-green-500">✓</span>
              ) : (
                <Loader2 className="h-3 w-3 animate-spin" />
              )}
              <span>{step.tool}</span>
            </div>
          ))}
          {sql && (
            <div className="mt-2 p-2 rounded-md bg-muted/70 border">
              <div className="flex items-center gap-1 text-[10px] text-muted-foreground mb-1">
                <Database className="h-2.5 w-2.5" />
                生成SQL
              </div>
              <pre className="text-[11px] font-mono overflow-x-auto whitespace-pre-wrap">{sql}</pre>
            </div>
          )}
          {sqlResults ? renderSqlResults(sqlResults) : null}
        </div>
      )}
    </div>
  );
}

export default function AgentPage() {
  const [messages, setMessages] = useState<Message[]>([WELCOME_MESSAGE]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [parentMessageId, setParentMessageId] = useState<string>("0");
  const scrollRef = useRef<HTMLDivElement>(null);

  const [savedThreads, setSavedThreads] = useState<SavedThread[]>([]);
  const [threadsLoading, setThreadsLoading] = useState(true);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const loadThreads = useCallback(async () => {
    try {
      const res = await fetch("/api/agent/threads");
      if (res.ok) {
        const data = await res.json();
        setSavedThreads(data);
      }
    } catch {}
    setThreadsLoading(false);
  }, []);

  useEffect(() => {
    loadThreads();
  }, [loadThreads]);

  const saveThread = useCallback((tid: string, msgs: Message[], pmid: string) => {
    if (!tid || msgs.length <= 1) return;
    const userMsgs = msgs.filter((m) => m.role === "user");
    const title = userMsgs[0]?.content?.slice(0, 40) || "新しい会話";
    const serializable = msgs.filter((m) => m.id !== "welcome").map((m) => ({
      ...m,
      timestamp: m.timestamp instanceof Date ? m.timestamp.toISOString() : m.timestamp,
    }));
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      fetch("/api/agent/threads", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ threadId: tid, title, parentMessageId: pmid, messages: serializable }),
      }).then(() => loadThreads()).catch((err) => console.error("[thread autosave] failed:", err));
    }, 1000);
  }, [loadThreads]);

  const loadThread = (thread: SavedThread) => {
    setThreadId(thread.threadId);
    setParentMessageId(thread.parentMessageId || "0");
    const restored: Message[] = [WELCOME_MESSAGE];
    if (Array.isArray(thread.messages)) {
      for (const m of thread.messages) {
        restored.push({
          ...m,
          timestamp: new Date(m.timestamp),
        });
      }
    }
    setMessages(restored);
  };

  const deleteThread = async (tid: string, e: React.MouseEvent) => {
    e.stopPropagation();
    await fetch(`/api/agent/threads?threadId=${encodeURIComponent(tid)}`, { method: "DELETE" });
    setSavedThreads((prev) => prev.filter((t) => t.threadId !== tid));
    if (threadId === tid) {
      resetThread();
    }
  };

  const sendMessage = async (text: string) => {
    if (!text.trim() || loading) return;
    setInput("");

    const userMsg: Message = {
      id: `user-${Date.now()}`,
      role: "user",
      content: text,
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setLoading(true);

    const botId = `bot-${Date.now()}`;

    try {
      const res = await fetch("/api/agent", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: text, threadId, parentMessageId }),
      });

      if (!res.ok) {
        const fallbackRes = await fetch("/api/talent-search", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query: text }),
        });
        const fallbackResults = await fallbackRes.json();
        const assistantMsg: Message = {
          id: botId,
          role: "assistant",
          content: Array.isArray(fallbackResults) && fallbackResults.length > 0
            ? `Agent APIが利用できないため、Cortex Searchで検索しました。「${text}」に関連する人材を${fallbackResults.length}名見つけました：`
            : "Agent APIが一時的に利用できません。別のキーワードでお試しください。",
          timestamp: new Date(),
          searchResults: Array.isArray(fallbackResults) ? fallbackResults : [],
        };
        setMessages((prev) => [...prev, assistantMsg]);
        return;
      }

      setMessages((prev) => [...prev, {
        id: botId,
        role: "assistant",
        content: "",
        timestamp: new Date(),
        isAgent: true,
      }]);

      const reader = res.body?.getReader();
      if (!reader) return;

      const decoder = new TextDecoder();
      let buffer = "";
      let accText = "";
      let accSql = "";
      let accSqlResults: unknown = null;
      let accThinkingSteps: ThinkingStep[] = [];
      let accThinkingText = "";
      let accStatusText = "";
      let latestThreadId = threadId;
      let latestParentMsgId = parentMessageId;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const evt = JSON.parse(line.slice(6));

            if (evt.type === "thread" && evt.threadId) {
              latestThreadId = String(evt.threadId);
              setThreadId(latestThreadId);
            } else if (evt.type === "thinking" && evt.tool) {
              const toolLabel = TOOL_LABELS[evt.tool] || evt.tool;
              accThinkingSteps = [...accThinkingSteps, { tool: toolLabel, done: false }];
              const snapshot = accThinkingSteps;
              setMessages((prev) => prev.map((m) =>
                m.id === botId ? { ...m, thinkingSteps: snapshot } : m
              ));
            } else if (evt.type === "thinking_text" && evt.text) {
              accThinkingText += evt.text;
              const snapshot = accThinkingText;
              setMessages((prev) => prev.map((m) =>
                m.id === botId ? { ...m, thinkingText: snapshot } : m
              ));
            } else if (evt.type === "status" && evt.message) {
              accStatusText = evt.message;
              const snapshot = accStatusText;
              setMessages((prev) => prev.map((m) =>
                m.id === botId ? { ...m, statusText: snapshot } : m
              ));
            } else if (evt.type === "thinking_done") {
              if (accThinkingSteps.length > 0) {
                accThinkingSteps = accThinkingSteps.map((s, i) =>
                  i === accThinkingSteps.length - 1 ? { ...s, done: true } : s
                );
                const snapshot = accThinkingSteps;
                setMessages((prev) => prev.map((m) =>
                  m.id === botId ? { ...m, thinkingSteps: snapshot } : m
                ));
              }
            } else if (evt.type === "text" && evt.text) {
              accText += evt.text;
              const snapshot = accText;
              setMessages((prev) => prev.map((m) =>
                m.id === botId ? { ...m, content: snapshot } : m
              ));
            } else if (evt.type === "sql" && evt.sql) {
              accSql = evt.sql;
              const snapshot = accSql;
              setMessages((prev) => prev.map((m) =>
                m.id === botId ? { ...m, sql: snapshot } : m
              ));
            } else if (evt.type === "sqlResults" && evt.results) {
              accSqlResults = evt.results;
              const snapshot = accSqlResults;
              setMessages((prev) => prev.map((m) =>
                m.id === botId ? { ...m, sqlResults: snapshot } : m
              ));
            } else if (evt.type === "done") {
              if (evt.messageId) {
                latestParentMsgId = String(evt.messageId);
                setParentMessageId(latestParentMsgId);
              }
              if (evt.threadId) {
                latestThreadId = String(evt.threadId);
                setThreadId(latestThreadId);
              }
            }
          } catch {}
        }
      }

      if (!accText) {
        setMessages((prev) => prev.map((m) =>
          m.id === botId ? { ...m, content: "応答を取得できませんでした。" } : m
        ));
      }

      setMessages((prev) => {
        if (latestThreadId) {
          saveThread(latestThreadId, prev, latestParentMsgId);
        }
        return prev;
      });
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          id: `err-${Date.now()}`,
          role: "assistant",
          content: "エラーが発生しました。もう一度お試しください。",
          timestamp: new Date(),
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const resetThread = () => {
    setThreadId(null);
    setParentMessageId("0");
    setMessages([WELCOME_MESSAGE]);
  };

  const renderSqlResults = (results: unknown): React.ReactNode => {
    if (!results || !Array.isArray(results) || results.length === 0) return null;
    const cols = Object.keys(results[0]);
    return (
      <div className="mt-2 overflow-x-auto rounded-md border">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-muted/50">
              {cols.map((c) => (
                <th key={c} className="px-2 py-1.5 text-left font-medium">{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {results.slice(0, 20).map((row: Record<string, unknown>, i: number) => (
              <tr key={i} className="border-t">
                {cols.map((c) => (
                  <td key={c} className="px-2 py-1 font-mono">{String(row[c] ?? "")}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {results.length > 20 && (
          <p className="text-[10px] text-muted-foreground px-2 py-1">他 {results.length - 20} 件...</p>
        )}
      </div>
    );
  };

  const formatTime = (ts: string) => {
    const d = new Date(ts);
    const now = new Date();
    const diff = now.getTime() - d.getTime();
    if (diff < 3600000) return `${Math.floor(diff / 60000)}分前`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}時間前`;
    return d.toLocaleDateString("ja-JP", { month: "short", day: "numeric" });
  };

  return (
    <div className="p-6 h-full flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <h2 className="text-2xl font-bold tracking-tight">AIエージェント</h2>
        <Badge variant="outline" className="gap-1 text-xs">
          <Sparkles className="h-3 w-3" />
          Cortex Agent (claude-haiku-4-5)
        </Badge>
      </div>

      <div className="flex-1 flex gap-4 min-h-0">
        <div className="w-64 shrink-0 flex flex-col border rounded-lg bg-card">
          <div className="p-3 border-b flex items-center justify-between">
            <span className="text-sm font-medium">会話履歴</span>
            <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={resetThread}>
              <Plus className="h-4 w-4" />
            </Button>
          </div>
          <ScrollArea className="flex-1">
            <div className="p-2 space-y-1">
              {threadsLoading ? (
                <div className="text-xs text-muted-foreground text-center py-4">読み込み中...</div>
              ) : savedThreads.length === 0 ? (
                <div className="text-xs text-muted-foreground text-center py-4">履歴なし</div>
              ) : (
                savedThreads.map((t) => (
                  <div
                    key={t.threadId}
                    className={`group flex items-center gap-2 p-2 rounded-md cursor-pointer text-sm transition-colors ${
                      threadId === t.threadId ? "bg-accent" : "hover:bg-muted/50"
                    }`}
                    onClick={() => loadThread(t)}
                  >
                    <MessageSquare className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                    <div className="flex-1 min-w-0">
                      <p className="truncate text-xs">{t.title}</p>
                      <p className="text-[10px] text-muted-foreground">{formatTime(t.updatedAt)}</p>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-6 w-6 p-0 opacity-0 group-hover:opacity-100 shrink-0"
                      onClick={(e) => deleteThread(t.threadId, e)}
                    >
                      <Trash2 className="h-3 w-3 text-muted-foreground" />
                    </Button>
                  </div>
                ))
              )}
            </div>
          </ScrollArea>
        </div>

        <Card className="flex-1 flex flex-col min-h-0">
          <CardHeader className="pb-2 shrink-0">
            <CardTitle className="text-base flex items-center gap-2">
              <Bot className="h-4 w-4" />
              よろず相談 — Cortex Agent
              {threadId && (
                <Badge variant="secondary" className="text-[10px] font-normal ml-2">
                  Thread: {threadId.slice(0, 8)}...
                </Badge>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="flex-1 flex flex-col min-h-0">
            <div className="flex-1 overflow-y-auto pr-4">
              <div className="space-y-4 pb-2">
                {messages.map((msg) => (
                  <div
                    key={msg.id}
                    className={`flex gap-3 ${msg.role === "user" ? "justify-end" : ""}`}
                  >
                    {msg.role === "assistant" && (
                      <div className="h-8 w-8 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
                        {msg.isAgent ? <Brain className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
                      </div>
                    )}
                    <div
                      className={`max-w-[80%] ${
                        msg.role === "user"
                          ? "bg-primary text-primary-foreground rounded-2xl rounded-tr-sm px-4 py-2"
                          : "space-y-2"
                      }`}
                    >
                      {msg.thinkingSteps && msg.thinkingSteps.length > 0 && (
                        <ThinkingStepsView steps={msg.thinkingSteps} sql={msg.sql} sqlResults={msg.sqlResults} renderSqlResults={renderSqlResults} thinkingText={msg.thinkingText} statusText={msg.statusText} />
                      )}

                      {msg.role === "assistant" ? (
                        <div className={`text-sm prose prose-sm dark:prose-invert max-w-none prose-p:my-1 prose-ul:my-1 prose-ol:my-1 prose-li:my-0.5 prose-headings:my-2 prose-table:text-xs ${
                          msg.thinkingSteps && msg.thinkingSteps.length > 0 && msg.content ? "mt-3 pt-3 border-t border-border" : ""
                        }`}>
                          {msg.thinkingSteps && msg.thinkingSteps.length > 0 && msg.content && (
                            <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground mb-2 not-prose">
                              <Sparkles className="h-3 w-3" />
                              回答
                            </div>
                          )}
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                        </div>
                      ) : (
                        <p className="text-sm whitespace-pre-wrap">{msg.content}</p>
                      )}

                      {!(msg.thinkingSteps && msg.thinkingSteps.length > 0) && msg.sql && (
                        <div className="mt-2 p-2 rounded-md bg-muted/70 border">
                          <div className="flex items-center gap-1 text-[10px] text-muted-foreground mb-1">
                            <Database className="h-2.5 w-2.5" />
                            生成SQL
                          </div>
                          <pre className="text-[11px] font-mono overflow-x-auto whitespace-pre-wrap">{msg.sql}</pre>
                        </div>
                      )}

                      {!(msg.thinkingSteps && msg.thinkingSteps.length > 0) && msg.sqlResults ? renderSqlResults(msg.sqlResults) : null}

                      {msg.searchResults && msg.searchResults.length > 0 && (
                        <div className="space-y-2 mt-2">
                          {msg.searchResults.map((r, i) => (
                            <div
                              key={i}
                              className="p-3 rounded-lg border bg-card hover:bg-accent transition-colors"
                            >
                              <div className="flex items-center gap-2 mb-1">
                                <span className="font-medium text-sm">{r.FULL_NAME}</span>
                                <Badge variant="outline" className="text-[10px]">{r.GRADE}</Badge>
                                <span className="text-xs text-muted-foreground ml-auto">{r.EMPLOYEE_CODE}</span>
                              </div>
                              <div className="text-xs text-muted-foreground">
                                {r.DEPT_NAME} / {r.POSITION_TITLE}
                              </div>
                              {r.SKILLS && (
                                <div className="flex flex-wrap gap-1 mt-1">
                                  {r.SKILLS.split(",").map((s, j) => (
                                    <Badge key={j} variant="secondary" className="text-[10px]">
                                      {s.trim()}
                                    </Badge>
                                  ))}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                    {msg.role === "user" && (
                      <div className="h-8 w-8 rounded-full bg-secondary flex items-center justify-center shrink-0">
                        <User className="h-4 w-4" />
                      </div>
                    )}
                  </div>
                ))}
                {loading && messages.length > 0 && !messages[messages.length - 1]?.thinkingSteps?.length && !messages[messages.length - 1]?.content && (
                  <div className="flex gap-3">
                    <div className="h-8 w-8 rounded-full bg-primary/10 flex items-center justify-center">
                      <Loader2 className="h-4 w-4 animate-spin" />
                    </div>
                    <div className="text-sm text-muted-foreground animate-pulse">
                      Cortex Agent に接続中...
                    </div>
                  </div>
                )}
                <div ref={scrollRef} />
              </div>
            </div>

            <div className="shrink-0 pt-3 border-t space-y-2">
              {!threadId && (
                <div className="flex flex-wrap gap-1.5">
                  {QUICK_ACTIONS.map((action) => (
                    <Button
                      key={action}
                      variant="outline"
                      size="sm"
                      className="text-xs"
                      onClick={() => sendMessage(action)}
                      disabled={loading}
                    >
                      <Search className="h-3 w-3 mr-1" />
                      {action}
                    </Button>
                  ))}
                </div>
              )}
              <form
                className="flex gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  sendMessage(input);
                }}
              >
                <Input
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder="人材検索やHRに関する質問を入力..."
                  disabled={loading}
                />
                <Button type="submit" disabled={loading || !input.trim()}>
                  <Send className="h-4 w-4" />
                </Button>
              </form>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
