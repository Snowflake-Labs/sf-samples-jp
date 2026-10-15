import fs from "fs";
import { getSession, requireRole } from "@/lib/session";

const SNOWFLAKE_HOST = process.env.SNOWFLAKE_HOST || "";
const ACCOUNT = process.env.SNOWFLAKE_ACCOUNT || "";
const EFFECTIVE_HOST = SNOWFLAKE_HOST || (ACCOUNT ? ACCOUNT.replace(/_/g, "-") + ".snowflakecomputing.com" : "");
const AGENT_DB = "HR_ANALYTICS";
const AGENT_SCHEMA = "PUBLIC";
const AGENT_NAME = "HR_AGENT";
const SPCS_TOKEN_PATH = "/snowflake/session/token";

let cachedToken: { value: string; readAt: number } | null = null;
const TOKEN_CACHE_TTL = 30000;

function getAuthInfo(): { token: string; isPat: boolean } {
  const pat = process.env.SNOWFLAKE_PAT || "";
  if (pat) return { token: pat, isPat: true };
  try {
    if (fs.existsSync(SPCS_TOKEN_PATH)) {
      if (cachedToken && Date.now() - cachedToken.readAt < TOKEN_CACHE_TTL) {
        return { token: cachedToken.value, isPat: false };
      }
      const value = fs.readFileSync(SPCS_TOKEN_PATH, "utf-8").trim();
      cachedToken = { value, readAt: Date.now() };
      return { token: value, isPat: false };
    }
  } catch {}
  return { token: "", isPat: false };
}

function buildHeaders(token: string, isPat: boolean): Record<string, string> {
  const h: Record<string, string> = {
    "Authorization": `Bearer ${token}`,
    "Content-Type": "application/json",
  };
  if (isPat) {
    h["X-Snowflake-Authorization-Token-Type"] = "PROGRAMMATIC_ACCESS_TOKEN";
  }
  return h;
}

async function createThread(headers: Record<string, string>): Promise<string> {
  const threadRes = await fetch(`https://${EFFECTIVE_HOST}/api/v2/cortex/threads`, {
    method: "POST",
    headers,
    body: JSON.stringify({}),
  });
  if (!threadRes.ok) {
    const body = await threadRes.text().catch(() => "");
    throw new Error(`Thread creation failed: ${threadRes.status} ${body}`);
  }
  const threadData = await threadRes.json();
  return String(threadData.thread_id);
}

async function runAgent(
  headers: Record<string, string>,
  threadId: string,
  parentMsgId: string,
  query: string,
): Promise<Response> {
  const agentUrl = `https://${EFFECTIVE_HOST}/api/v2/databases/${AGENT_DB}/schemas/${AGENT_SCHEMA}/agents/${AGENT_NAME}:run`;
  return fetch(agentUrl, {
    method: "POST",
    headers,
    body: JSON.stringify({
      thread_id: threadId,
      parent_message_id: parentMsgId,
      messages: [
        {
          role: "user",
          content: [{ type: "text", text: query }],
        },
      ],
    }),
  });
}

export async function POST(request: Request) {
  const session = await getSession();
  const auth = requireRole(session, ["HR_ADMIN"]);
  if (!auth.ok) return Response.json(auth.body, { status: auth.status });
  try {
    const { query, threadId, parentMessageId } = await request.json();

    if (!query || typeof query !== "string" || query.length > 2000) {
      return Response.json({ error: "不正なクエリ" }, { status: 400 });
    }

    const { token, isPat } = getAuthInfo();
    if (!token) {
      return Response.json({ error: "認証トークンなし" }, { status: 500 });
    }

    const headers = buildHeaders(token, isPat);

    let currentThreadId = threadId ? String(threadId) : "";
    if (!currentThreadId) {
      currentThreadId = await createThread(headers);
    }

    const parentMsgId = parentMessageId && parentMessageId !== "" ? String(parentMessageId) : "0";

    let agentRes = await runAgent(headers, currentThreadId, parentMsgId, query);

    if (!agentRes.ok && parentMsgId !== "0") {
      console.warn("Agent retry: creating new thread after error", agentRes.status);
      currentThreadId = await createThread(headers);
      agentRes = await runAgent(headers, currentThreadId, "0", query);
    }

    if (!agentRes.ok) {
      const err = await agentRes.text();
      console.error("Agent API error:", agentRes.status, err);
      return Response.json({ error: "Agent API エラー", detail: err }, { status: 500 });
    }

    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      async start(controller) {
        const sendEvent = (eventData: Record<string, unknown>) => {
          controller.enqueue(encoder.encode(`data: ${JSON.stringify(eventData)}\n\n`));
        };

        sendEvent({ type: "thread", threadId: currentThreadId });

        const reader = agentRes.body?.getReader();
        if (!reader) {
          sendEvent({ type: "error", text: "No response body" });
          controller.close();
          return;
        }

        const decoder = new TextDecoder();
        let buffer = "";
        let lastMessageId = "";
        const emittedToolNames = new Set<string>();

        try {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() || "";

            let currentEventType = "";

            for (const line of lines) {
              if (line.startsWith("event: ")) {
                currentEventType = line.slice(7).trim();
                continue;
              }

              if (!line.startsWith("data: ")) continue;

              try {
                const data = JSON.parse(line.slice(6)) as Record<string, unknown>;
                const evt = currentEventType;
                currentEventType = "";

                if (evt === "metadata") {
                  if (data.message_id) {
                    lastMessageId = String(data.message_id);
                  }
                  continue;
                }

                if (evt === "response.text.delta") {
                  if (data.text) {
                    sendEvent({ type: "text", text: data.text as string });
                  }
                  continue;
                }

                if (evt === "response.status") {
                  const msg = data.message as string | undefined;
                  if (msg) {
                    sendEvent({ type: "status", message: msg });
                  }
                  continue;
                }

                if (evt === "response.thinking.delta") {
                  if (data.text) {
                    sendEvent({ type: "thinking_text", text: data.text as string });
                  }
                  continue;
                }

                if (evt === "response.tool_use") {
                  const toolName = (data.name || "tool") as string;
                  if (!emittedToolNames.has(toolName)) {
                    emittedToolNames.add(toolName);
                    sendEvent({ type: "thinking", tool: toolName });
                  }
                  continue;
                }

                if (evt === "response.tool_result.status") {
                  continue;
                }

                if (evt === "response.tool_result") {
                  sendEvent({ type: "thinking_done" });
                  const content = data.content as Array<Record<string, unknown>> | undefined;
                  if (content && Array.isArray(content)) {
                    for (const tc of content) {
                      if (tc.type === "json" && tc.json) {
                        const j = tc.json as Record<string, unknown>;
                        if (j.sql) sendEvent({ type: "sql", sql: j.sql });
                        if (j.results) sendEvent({ type: "sqlResults", results: j.results });
                      }
                      if (tc.type === "text" && tc.text) {
                        sendEvent({ type: "sql", sql: tc.text as string });
                      }
                    }
                  }
                  continue;
                }

                if (evt === "response.tool_result.analyst.delta") {
                  continue;
                }

                if (evt === "response.table") {
                  const rs = data.result_set as Record<string, unknown> | undefined;
                  if (rs) {
                    const rowType = (rs.resultSetMetaData as Record<string, unknown>)?.rowType as Array<Record<string, unknown>> | undefined;
                    const rows = rs.data as unknown[][] | undefined;
                    if (rowType && rows) {
                      const cols = rowType.map((r) => String(r.name));
                      const results = rows.map((row) => {
                        const obj: Record<string, unknown> = {};
                        cols.forEach((c, i) => { obj[c] = row[i]; });
                        return obj;
                      });
                      sendEvent({ type: "sqlResults", results });
                    }
                  }
                  continue;
                }

                if (evt === "response.text" || evt === "response.thinking" || evt === "response.chart" || evt === "response") {
                  if (evt === "response" && data.metadata) {
                    const meta = data.metadata as Record<string, unknown>;
                    if (meta.message_id) {
                      lastMessageId = String(meta.message_id);
                    }
                  }
                  continue;
                }

                if (!evt) {
                  if (data.message_id) {
                    lastMessageId = String(data.message_id);
                  }
                  if (data.metadata) {
                    const meta = data.metadata as Record<string, unknown>;
                    if (meta.message_id) {
                      lastMessageId = String(meta.message_id);
                    }
                  }
                }
              } catch {}
            }
          }
        } catch (err) {
          console.error("Stream read error:", err);
        }

        sendEvent({ type: "done", messageId: lastMessageId, threadId: currentThreadId });
        controller.close();
      },
    });

    return new Response(stream, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
      },
    });
  } catch (error) {
    console.error("Agent proxy error:", error);
    return Response.json({ error: "Agent呼び出しに失敗しました" }, { status: 500 });
  }
}
