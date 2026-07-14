// @ts-ignore Deno runtime resolves URL imports at deploy/runtime.
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

declare const Deno: {
  env: { get(name: string): string | undefined };
  serve(handler: (request: Request) => Response | Promise<Response>): void;
};

type RenderStatusResponse = {
  request_id: string;
  status: "queued" | "processing" | "completed" | "failed";
  image_url: string | null;
  error: string | null;
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

function parseMetadata(metadata: unknown): Record<string, unknown> | null {
  return metadata && typeof metadata === "object" ? (metadata as Record<string, unknown>) : null;
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
  const requestId = url.searchParams.get("request_id") || "";
  const userId = url.searchParams.get("user_id") || "";

  if (!requestId || !isValidUuid(requestId)) {
    return jsonResponse(400, { error: "request_id is required and must be a valid UUID" });
  }
  if (userId && !isValidUuid(userId)) {
    return jsonResponse(400, { error: "user_id must be a valid UUID" });
  }

  let requestQuery = supabase
    .from("render_requests")
    .select("id,user_id,status,error_message,created_at,updated_at,prompt,style,model_profile", { count: "exact" })
    .eq("id", requestId)
    .maybeSingle();

  if (userId) {
    requestQuery = requestQuery.eq("user_id", userId);
  }

  const { data: renderRequest, error: requestError } = await requestQuery;
  if (requestError) {
    return jsonResponse(500, { error: "Failed to load render status", details: requestError.message });
  }
  if (!renderRequest) {
    return jsonResponse(404, { error: "Render request not found" });
  }

  const { data: renderResult, error: resultError } = await supabase
    .from("render_results")
    .select("output_image_url, metadata, created_at")
    .eq("request_id", requestId)
    .order("created_at", { ascending: false })
    .limit(1)
    .maybeSingle();

  if (resultError) {
    return jsonResponse(500, { error: "Failed to load render result", details: resultError.message });
  }

  const metadata = parseMetadata(renderResult?.metadata);
  const status = (renderRequest.status || (renderResult ? "completed" : "processing")) as RenderStatusResponse["status"];
  const imageUrl =
    typeof renderResult?.output_image_url === "string" ? renderResult.output_image_url : null;
  const errorMessage =
    typeof renderRequest.error_message === "string"
      ? renderRequest.error_message
      : typeof metadata?.error === "string"
        ? metadata.error
        : null;

  return jsonResponse(200, {
    request_id: renderRequest.id,
    status,
    image_url: imageUrl,
    error: errorMessage,
  });
});
