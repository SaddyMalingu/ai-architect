// @ts-ignore Deno runtime resolves URL imports at deploy/runtime.
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

declare const Deno: {
  env: { get(name: string): string | undefined };
  serve(handler: (request: Request) => Response | Promise<Response>): void;
};

type HistoryItem = {
  request_id: string;
  created_at: string;
  updated_at: string | null;
  status: string;
  prompt: string;
  style: string | null;
  model_profile: string | null;
  image_url: string | null;
  latency_ms: number | null;
  error: string | null;
};

type RequestRow = {
  id: string;
  created_at: string;
  updated_at: string | null;
  status: string | null;
  prompt: string | null;
  style: string | null;
  model_profile: string | null;
  error_message: string | null;
};

type ResultRow = {
  request_id: string;
  output_image_url: string | null;
  metadata: unknown;
  created_at: string;
};

const supabaseUrl = Deno.env.get("SUPABASE_URL") || "";
const supabaseServiceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
};

const supabase = createClient(supabaseUrl, supabaseServiceRoleKey);

function jsonResponse(status: number, body: Record<string, unknown>) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...corsHeaders },
  });
}

function isValidUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}

function toInt(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return Math.max(0, Math.floor(value));
  if (typeof value === "string" && /^\d+$/.test(value.trim())) return parseInt(value.trim(), 10);
  return null;
}

function getLatency(metadata: unknown): number | null {
  if (!metadata || typeof metadata !== "object") return null;
  const value = (metadata as Record<string, unknown>).latency_ms;
  return toInt(value);
}

function getError(metadata: unknown, fallback: string | null): string | null {
  if (fallback) return fallback;
  if (!metadata || typeof metadata !== "object") return null;
  const value = (metadata as Record<string, unknown>).error;
  return typeof value === "string" ? value : null;
}

Deno.serve(async (request: Request) => {
  if (request.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  if (request.method !== "GET") {
    return jsonResponse(405, { error: "Method not allowed" });
  }

  if (!supabaseUrl || !supabaseServiceRoleKey) {
    return jsonResponse(500, { error: "Missing required secrets: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY" });
  }

  const url = new URL(request.url);
  const userId = url.searchParams.get("user_id") || "";
  const limit = Math.min(Math.max(parseInt(url.searchParams.get("limit") || "20", 10) || 20, 1), 50);
  const offset = Math.max(parseInt(url.searchParams.get("offset") || "0", 10) || 0, 0);

  if (!userId || !isValidUuid(userId)) {
    return jsonResponse(400, { error: "user_id is required and must be a valid UUID" });
  }

  const { data: requestRows, error: requestError, count } = await supabase
    .from("render_requests")
    .select("id,created_at,updated_at,status,prompt,style,model_profile,error_message,user_id", { count: "exact" })
    .eq("user_id", userId)
    .order("created_at", { ascending: false })
    .range(offset, offset + limit - 1);

  if (requestError) {
    return jsonResponse(500, { error: "Failed to load render history", details: requestError.message });
  }

  const typedRequestRows = (requestRows || []) as RequestRow[];
  const requestIds = typedRequestRows.map((row) => row.id).filter(Boolean);
  const resultMap = new Map<string, { output_image_url: string | null; metadata: unknown }>();

  if (requestIds.length) {
    const { data: resultRows, error: resultError } = await supabase
      .from("render_results")
      .select("request_id,output_image_url,metadata,created_at")
      .in("request_id", requestIds)
      .order("created_at", { ascending: false });

    if (resultError) {
      return jsonResponse(500, { error: "Failed to load render results", details: resultError.message });
    }

    ((resultRows || []) as ResultRow[]).forEach((row) => {
      if (!resultMap.has(row.request_id)) {
        resultMap.set(row.request_id, {
          output_image_url: typeof row.output_image_url === "string" ? row.output_image_url : null,
          metadata: row.metadata,
        });
      }
    });
  }

  const items: HistoryItem[] = typedRequestRows.map((row) => {
    const result = resultMap.get(row.id);
    return {
      request_id: row.id,
      created_at: row.created_at,
      updated_at: row.updated_at ?? null,
      status: row.status || (result ? "completed" : "processing"),
      prompt: row.prompt || "",
      style: row.style ?? null,
      model_profile: row.model_profile ?? null,
      image_url: result?.output_image_url ?? null,
      latency_ms: getLatency(result?.metadata),
      error: getError(result?.metadata, row.error_message ?? null),
    };
  });

  return jsonResponse(200, {
    items,
    limit,
    offset,
    total_estimate: count ?? items.length,
  });
});
