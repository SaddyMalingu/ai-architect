// @ts-ignore Deno runtime resolves URL imports at deploy/runtime.
declare const Deno: {
  env: { get(name: string): string | undefined };
  serve(handler: (request: Request) => Response | Promise<Response>): void;
};

type ViewKey = "front" | "left" | "right" | "back";

type PreflightRequest = {
  mode?: "render" | "regional" | "all";
  user_id?: string;
  blender_conditioned?: boolean;
  strict_consistency?: boolean;
  consistency_key?: string;
  active_view?: ViewKey | string;
  passes?: Partial<Record<ViewKey, string>>;
  target_image_url?: string;
  prompt?: string;
  selection_mode?: "automatic" | "manual" | string;
  target_mask_url?: string;
  target_mask_data_url?: string;
};

const corsHeaders = {
  "Access-Control-Allow-Origin": Deno.env.get("ALLOWED_ORIGIN") || "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

function jsonResponse(status: number, body: Record<string, unknown>) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...corsHeaders },
  });
}

function isHttpsUrl(value?: string): boolean {
  if (!value) return false;
  try {
    return new URL(value).protocol === "https:";
  } catch {
    return false;
  }
}

function isValidUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}

function normalizeView(value: string | undefined): ViewKey {
  const v = String(value || "front").toLowerCase();
  if (v === "left" || v === "right" || v === "back") return v;
  return "front";
}

function validatePreflight(payload: PreflightRequest) {
  const mode = payload.mode || "all";
  const view = normalizeView(payload.active_view);
  const issues: string[] = [];
  const warnings: string[] = [];

  if (payload.user_id && !isValidUuid(payload.user_id)) {
    issues.push("user_id must be a valid UUID");
  }

  if (payload.prompt && payload.prompt.length > 1200) {
    issues.push("prompt exceeds maximum length of 1200 characters");
  }

  const passes = payload.passes || {};

  if (payload.blender_conditioned) {
    if (!payload.consistency_key || !payload.consistency_key.trim()) {
      issues.push("Blender consistency key is missing");
    }
    if (!payload.strict_consistency) {
      issues.push("strict_consistency must be true when blender_conditioned is enabled");
    }

    const requiredViews: ViewKey[] = mode === "render" ? [view] : ["front", "left", "right", "back"];
    requiredViews.forEach((v) => {
      const pass = passes[v];
      if (!pass) {
        issues.push(`Missing Blender pass URL for ${v} view`);
      } else if (!isHttpsUrl(pass)) {
        issues.push(`Blender pass URL for ${v} view must be https`);
      }
    });
  }

  if (mode === "regional" || mode === "all") {
    if (payload.target_image_url) {
      if (!isHttpsUrl(payload.target_image_url)) {
        issues.push("target_image_url must be a valid https URL");
      }
    } else {
      warnings.push("target_image_url is not set for regional edit");
    }

    if (String(payload.selection_mode || "automatic") === "manual") {
      const hasMaskUrl = Boolean(payload.target_mask_url);
      const hasMaskData = Boolean(payload.target_mask_data_url);
      if (!hasMaskUrl && !hasMaskData) {
        warnings.push("manual regional mode selected without mask data/url");
      }
      if (hasMaskUrl && !isHttpsUrl(payload.target_mask_url)) {
        issues.push("target_mask_url must be a valid https URL");
      }
      if (hasMaskData && !String(payload.target_mask_data_url).startsWith("data:image/png;base64,")) {
        issues.push("target_mask_data_url must be a PNG data URL");
      }
    }
  }

  if (!payload.reference_image_url && mode !== "regional") {
    warnings.push("reference image URL is empty; style drift may increase");
  }

  return {
    ok: issues.length === 0,
    mode,
    active_view: view,
    issues,
    warnings,
    guidance: [
      "Fix all issues before paid inference calls",
      "For blender-conditioned mode, keep one consistency_key for the whole package",
      "Prefer sequential runs during low-credit periods"
    ]
  };
}

Deno.serve(async (request: Request) => {
  if (request.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  if (request.method !== "POST") {
    return jsonResponse(405, { error: "Method not allowed" });
  }

  let payload: PreflightRequest;
  try {
    payload = await request.json();
  } catch {
    return jsonResponse(400, { error: "Invalid JSON payload" });
  }

  const result = validatePreflight(payload);
  return jsonResponse(200, result);
});