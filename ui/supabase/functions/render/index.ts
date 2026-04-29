// @ts-ignore Deno runtime resolves URL imports at deploy/runtime.
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

declare const Deno: {
  env: { get(name: string): string | undefined };
  serve(handler: (request: Request) => Response | Promise<Response>): void;
};

type ProfileName = "fast" | "balanced" | "quality";

type RenderRequest = {
  user_id: string;
  prompt: string;
  style?: string;
  input_image_url?: string;
  reference_image_url?: string;
  mask_url?: string;
  model?: string;
  model_profile?: ProfileName;
  num_outputs?: number;
  consistency_key?: string;
  strict_consistency?: boolean;
  blender_conditioned?: boolean;
  blender_pass_type?: "front" | "left" | "right" | "back" | string;
};

type ModelProfile = {
  label: ProfileName;
  model: string;
  guidance_scale: number;
  num_inference_steps: number;
};

type ProviderErrorMeta = {
  status: number;
  detail: string;
  retry_after?: number;
  low_credit?: boolean;
  billing_url?: string;
  body?: unknown;
};

type ErrorWithProviderMeta = Error & {
  provider_meta?: ProviderErrorMeta;
};

const PROMPT_MAX_CHARS = 1200;
const NUM_OUTPUTS_MIN = 1;
const NUM_OUTPUTS_MAX = 4;
const POLL_MAX_ATTEMPTS = 60;
const POLL_INTERVAL_MS = 2000;

const supabaseUrl = Deno.env.get("SUPABASE_URL") || "";
const supabaseServiceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
const replicateApiToken = Deno.env.get("REPLICATE_API_TOKEN") || "";
const defaultModel = Deno.env.get("REPLICATE_MODEL") || "stability-ai/sdxl";
const DAILY_QUOTA_LIMIT = parseInt(Deno.env.get("DAILY_QUOTA_LIMIT") || "100", 10);
const CREATE_RETRY_MAX_ATTEMPTS = parseInt(Deno.env.get("REPLICATE_CREATE_RETRY_MAX_ATTEMPTS") || "3", 10);
const CREATE_RETRY_FALLBACK_SECONDS = parseInt(
  Deno.env.get("REPLICATE_CREATE_RETRY_FALLBACK_SECONDS") || "10",
  10,
);
const RENDER_AB_TEST_ENABLED =
  (Deno.env.get("REPLICATE_RENDER_AB_TEST_ENABLED") || "false").toLowerCase() === "true";
const RENDER_AB_TEST_MODEL =
  Deno.env.get("REPLICATE_RENDER_AB_TEST_MODEL") || "black-forest-labs/flux-2-pro";
const RENDER_AB_TEST_PERCENT = Math.max(
  0,
  Math.min(100, parseInt(Deno.env.get("REPLICATE_RENDER_AB_TEST_PERCENT") || "0", 10)),
);
const PROMPT_FIRST_ASPECT_RATIO = Deno.env.get("REPLICATE_PROMPT_FIRST_ASPECT_RATIO") || "1:1";

const MODEL_PROFILES: Record<ProfileName, ModelProfile> = {
  fast: {
    label: "fast",
    model: Deno.env.get("REPLICATE_MODEL_FAST") || defaultModel,
    guidance_scale: 5,
    num_inference_steps: 20,
  },
  balanced: {
    label: "balanced",
    model: Deno.env.get("REPLICATE_MODEL_BALANCED") || defaultModel,
    guidance_scale: 7,
    num_inference_steps: 30,
  },
  quality: {
    label: "quality",
    model: Deno.env.get("REPLICATE_MODEL_QUALITY") || defaultModel,
    guidance_scale: 9,
    num_inference_steps: 50,
  },
};

const corsHeaders = {
  "Access-Control-Allow-Origin": Deno.env.get("ALLOWED_ORIGIN") || "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

const supabase = createClient(supabaseUrl, supabaseServiceRoleKey);

function jsonResponse(status: number, body: Record<string, unknown>) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...corsHeaders },
  });
}

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function extractBillingUrl(detail: string): string | undefined {
  const m = detail.match(/https:\/\/[^\s"}]+/i);
  return m ? m[0] : undefined;
}

function toInt(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) {
    return Math.max(0, Math.floor(value));
  }
  if (typeof value === "string" && /^\d+$/.test(value.trim())) {
    return parseInt(value.trim(), 10);
  }
  return undefined;
}

function parseRetryAfterSeconds(detail: string): number | undefined {
  const m = detail.match(/~\s*(\d+)\s*s/i);
  if (!m) return undefined;
  return parseInt(m[1], 10);
}

function parseProviderError(status: number, text: string): ProviderErrorMeta {
  let parsed: unknown = undefined;
  try {
    parsed = JSON.parse(text);
  } catch {
    parsed = undefined;
  }

  const parsedObj = typeof parsed === "object" && parsed ? (parsed as Record<string, unknown>) : null;
  const detail =
    (parsedObj && typeof parsedObj.detail === "string" ? parsedObj.detail : "") ||
    (parsedObj && typeof parsedObj.title === "string" ? parsedObj.title : "") ||
    text;

  const retry_after =
    (parsedObj ? toInt(parsedObj.retry_after) : undefined) ??
    parseRetryAfterSeconds(detail);

  const low_credit = /less than\s*\$?5/i.test(detail) || /insufficient credit/i.test(detail);
  const billing_url = extractBillingUrl(detail);

  return {
    status,
    detail,
    retry_after,
    low_credit,
    billing_url,
    body: parsedObj ?? text,
  };
}

function providerErrorFromResponse(status: number, text: string): ErrorWithProviderMeta {
  const meta = parseProviderError(status, text);
  const err = new Error(`Replicate create failed: ${status} ${text}`) as ErrorWithProviderMeta;
  err.provider_meta = meta;
  return err;
}

function extractProviderMeta(error: unknown): ProviderErrorMeta | undefined {
  if (!error || typeof error !== "object") return undefined;
  return (error as ErrorWithProviderMeta).provider_meta;
}

function isValidUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}

function isHttpsUrl(value?: string): boolean {
  if (!value) return false;
  try {
    return new URL(value).protocol === "https:";
  } catch {
    return false;
  }
}

function hashToBucket(input: string): number {
  let h = 2166136261;
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return Math.abs(h >>> 0) % 100;
}

function isFluxLikeModel(model: string): boolean {
  const m = model.toLowerCase();
  return m.includes("flux-2-pro") || m.includes("flux");
}

function isPromptFirstModel(model: string): boolean {
  const m = model.toLowerCase();
  return (
    isFluxLikeModel(model) ||
    m.includes("seedance") ||
    m.includes("seedream") ||
    m.includes("text-to-image")
  );
}

function resolveReplicateTarget(modelRef: string): {
  endpoint: string;
  bodyBase: Record<string, unknown>;
} {
  const trimmed = modelRef.trim();

  // owner/model:versionId
  if (trimmed.includes("/") && trimmed.includes(":")) {
    const [slug, version] = trimmed.split(":", 2);
    return {
      endpoint: `https://api.replicate.com/v1/models/${slug}/predictions`,
      bodyBase: { version },
    };
  }

  // owner/model
  if (trimmed.includes("/")) {
    return {
      endpoint: `https://api.replicate.com/v1/models/${trimmed}/predictions`,
      bodyBase: {},
    };
  }

  // version id
  return {
    endpoint: "https://api.replicate.com/v1/predictions",
    bodyBase: { version: trimmed },
  };
}

function selectRenderModel(baseModel: string, payload: RenderRequest): { model: string; variant: "control" | "ab" } {
  if (payload.strict_consistency || !RENDER_AB_TEST_ENABLED || RENDER_AB_TEST_PERCENT <= 0) {
    return { model: baseModel, variant: "control" };
  }

  const bucketKey = payload.consistency_key?.trim() || payload.user_id;
  const bucket = hashToBucket(bucketKey);
  if (bucket < RENDER_AB_TEST_PERCENT) {
    return { model: RENDER_AB_TEST_MODEL, variant: "ab" };
  }

  return { model: baseModel, variant: "control" };
}

function validatePayload(payload: RenderRequest): string | null {
  if (!payload.user_id) return "user_id is required";
  if (!isValidUuid(payload.user_id)) return "user_id must be a valid UUID";
  if (!payload.prompt || payload.prompt.trim().length === 0) return "prompt is required";
  if (payload.prompt.length > PROMPT_MAX_CHARS) {
    return `prompt exceeds maximum length of ${PROMPT_MAX_CHARS} characters`;
  }
  if (payload.num_outputs !== undefined) {
    if (
      !Number.isInteger(payload.num_outputs) ||
      payload.num_outputs < NUM_OUTPUTS_MIN ||
      payload.num_outputs > NUM_OUTPUTS_MAX
    ) {
      return `num_outputs must be an integer between ${NUM_OUTPUTS_MIN} and ${NUM_OUTPUTS_MAX}`;
    }
  }
  if (payload.input_image_url && !isHttpsUrl(payload.input_image_url)) {
    return "input_image_url must be a valid https URL";
  }
  if (payload.reference_image_url && !isHttpsUrl(payload.reference_image_url)) {
    return "reference_image_url must be a valid https URL";
  }
  if (payload.mask_url && !isHttpsUrl(payload.mask_url)) {
    return "mask_url must be a valid https URL";
  }
  if (payload.blender_conditioned) {
    if (!payload.input_image_url) {
      return "input_image_url is required when blender_conditioned is true";
    }
    if (!payload.consistency_key || !payload.consistency_key.trim()) {
      return "consistency_key is required when blender_conditioned is true";
    }
    if (!payload.strict_consistency) {
      return "strict_consistency must be true when blender_conditioned is true";
    }
  }
  if (payload.model_profile && !Object.keys(MODEL_PROFILES).includes(payload.model_profile)) {
    return "model_profile must be one of: fast, balanced, quality";
  }
  return null;
}

async function checkDailyQuota(userId: string): Promise<boolean> {
  const todayStart = new Date();
  todayStart.setUTCHours(0, 0, 0, 0);
  const { count, error } = await supabase
    .from("render_requests")
    .select("id", { count: "exact", head: true })
    .eq("user_id", userId)
    .gte("created_at", todayStart.toISOString());

  if (error) return true;
  return (count ?? 0) < DAILY_QUOTA_LIMIT;
}

function resolveModelProfile(payload: RenderRequest): ModelProfile {
  if (payload.model_profile && MODEL_PROFILES[payload.model_profile]) {
    return MODEL_PROFILES[payload.model_profile];
  }
  if (payload.model) {
    return { label: "balanced", model: payload.model, guidance_scale: 7, num_inference_steps: 30 };
  }
  return MODEL_PROFILES["balanced"];
}

async function replicateCreatePrediction(payload: RenderRequest, model: string, profile: ModelProfile) {
  const promptText = payload.style
    ? `${payload.prompt}. Style: ${payload.style}`
    : payload.prompt;

  const promptFirst = isPromptFirstModel(model);

  const input: Record<string, unknown> = promptFirst
    ? {
        // Keep prompt-first path stable across Flux / Seedance-like schemas.
        prompt: promptText,
        output_format: "png",
        aspect_ratio: PROMPT_FIRST_ASPECT_RATIO,
      }
    : {
        prompt: promptText,
        num_outputs: payload.num_outputs ?? 1,
        output_format: "png",
        guidance_scale: profile.guidance_scale,
        num_inference_steps: profile.num_inference_steps,
      };

  if (!promptFirst) {
    if (payload.input_image_url) input.image = payload.input_image_url;
    if (payload.mask_url) input.mask = payload.mask_url;
  }

  const target = resolveReplicateTarget(model);
  const requestBody = { ...target.bodyBase, input };

  for (let attempt = 1; attempt <= CREATE_RETRY_MAX_ATTEMPTS; attempt++) {
    const response = await fetch(target.endpoint, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${replicateApiToken}`,
        "Content-Type": "application/json",
        Prefer: "wait",
      },
      body: JSON.stringify(requestBody),
    });

    if (response.ok) {
      return await response.json();
    }

    const text = await response.text();
    const providerError = providerErrorFromResponse(response.status, text);
    const meta = providerError.provider_meta;
    const shouldRetry = response.status === 429 && attempt < CREATE_RETRY_MAX_ATTEMPTS;

    if (!shouldRetry) {
      throw providerError;
    }

    const retryAfterSeconds = meta?.retry_after ?? CREATE_RETRY_FALLBACK_SECONDS;
    await sleep((retryAfterSeconds + 1) * 1000);
  }

  throw new Error("Replicate create failed after retries");
}

async function replicatePollPrediction(predictionId: string) {
  for (let attempt = 0; attempt < POLL_MAX_ATTEMPTS; attempt++) {
    const response = await fetch(`https://api.replicate.com/v1/predictions/${predictionId}`, {
      method: "GET",
      headers: {
        Authorization: `Bearer ${replicateApiToken}`,
        "Content-Type": "application/json",
      },
    });

    if (!response.ok) {
      const text = await response.text();
      throw new Error(`Replicate poll failed: ${response.status} ${text}`);
    }

    const prediction = await response.json();
    const status = prediction?.status;

    if (status === "succeeded") return prediction;
    if (status === "failed" || status === "canceled") {
      throw new Error(`Replicate prediction ended with status: ${status}`);
    }

    await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
  }

  throw new Error(
    `Replicate prediction timed out after ${(POLL_MAX_ATTEMPTS * POLL_INTERVAL_MS) / 1000}s`,
  );
}

function pickOutputUrl(prediction: Record<string, unknown>): string {
  const output = prediction.output;
  if (Array.isArray(output) && output.length > 0 && typeof output[0] === "string") {
    return output[0];
  }
  if (typeof output === "string") return output;
  throw new Error("No output URL returned by Replicate");
}

async function uploadImageToSupabase(userId: string, requestId: string, outputUrl: string) {
  if (!isHttpsUrl(outputUrl)) {
    throw new Error(`Replicate returned a non-https output URL: ${outputUrl}`);
  }

  const imageResponse = await fetch(outputUrl);
  if (!imageResponse.ok) {
    throw new Error(`Failed to download Replicate output: ${imageResponse.status}`);
  }

  const imageBuffer = await imageResponse.arrayBuffer();
  const path = `${userId}/${requestId}.png`;

  const { error: uploadError } = await supabase.storage
    .from("renders")
    .upload(path, imageBuffer, { contentType: "image/png", upsert: true });

  if (uploadError) {
    throw new Error(`Supabase upload failed: ${uploadError.message}`);
  }

  const { data } = supabase.storage.from("renders").getPublicUrl(path);
  return data.publicUrl;
}

Deno.serve(async (request: Request) => {
  if (request.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  if (request.method !== "POST") {
    return jsonResponse(405, { error: "Method not allowed" });
  }

  if (!supabaseUrl || !supabaseServiceRoleKey || !replicateApiToken) {
    return jsonResponse(500, {
      error: "Missing required secrets: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, REPLICATE_API_TOKEN",
    });
  }

  let payload: RenderRequest;
  try {
    payload = await request.json();
  } catch {
    return jsonResponse(400, { error: "Invalid JSON payload" });
  }

  const validationError = validatePayload(payload);
  if (validationError) {
    return jsonResponse(400, { error: validationError });
  }

  const withinQuota = await checkDailyQuota(payload.user_id);
  if (!withinQuota) {
    return jsonResponse(429, {
      error: `Daily render quota of ${DAILY_QUOTA_LIMIT} reached. Try again tomorrow.`,
    });
  }

  const profile = resolveModelProfile(payload);
  const selected = selectRenderModel(profile.model, payload);

  const { data: requestRow, error: insertError } = await supabase
    .from("render_requests")
    .insert({
      user_id: payload.user_id,
      prompt: payload.prompt,
      style: payload.style ?? null,
      input_image_url: payload.input_image_url ?? null,
      reference_image_url: payload.reference_image_url ?? null,
      mask_url: payload.mask_url ?? null,
      provider: "replicate",
      model_profile: profile.label,
      status: "processing",
    })
    .select("id")
    .single();

  if (insertError || !requestRow?.id) {
    return jsonResponse(500, {
      error: "Failed to insert render request",
      details: insertError?.message,
    });
  }

  const requestId = requestRow.id as string;
  const replicateStartMs = Date.now();

  try {
    const prediction = await replicateCreatePrediction(payload, selected.model, profile);
    const predictionId = prediction.id as string;

    await supabase
      .from("render_requests")
      .update({ replicate_prediction_id: predictionId })
      .eq("id", requestId);

    const finalPrediction =
      prediction.status === "succeeded"
        ? prediction
        : await replicatePollPrediction(predictionId);

    const latencyMs = Date.now() - replicateStartMs;
    const replicateOutputUrl = pickOutputUrl(finalPrediction);
    const publicUrl = await uploadImageToSupabase(payload.user_id, requestId, replicateOutputUrl);

    const { error: resultError } = await supabase.from("render_results").insert({
      request_id: requestId,
      user_id: payload.user_id,
      output_image_url: publicUrl,
      metadata: {
        replicate_prediction_id: predictionId,
        replicate_model: selected.model,
        model_profile: profile.label,
        blender_conditioned: Boolean(payload.blender_conditioned),
        blender_pass_type: payload.blender_pass_type ?? null,
        ab_variant: selected.variant,
        ab_percent: RENDER_AB_TEST_PERCENT,
        used_flux_path: isFluxLikeModel(selected.model),
        guidance_scale: profile.guidance_scale,
        num_inference_steps: profile.num_inference_steps,
        latency_ms: latencyMs,
        num_outputs: payload.num_outputs ?? 1,
      },
    });

    if (resultError) {
      throw new Error(`Failed to insert result row: ${resultError.message}`);
    }

    await supabase
      .from("render_requests")
      .update({ status: "completed" })
      .eq("id", requestId);

    return jsonResponse(200, {
      request_id: requestId,
      status: "completed",
      image_url: publicUrl,
      meta: {
        model: selected.model,
        model_profile: profile.label,
        blender_conditioned: Boolean(payload.blender_conditioned),
        blender_pass_type: payload.blender_pass_type ?? null,
        ab_variant: selected.variant,
        latency_ms: latencyMs,
      },
    });
  } catch (error) {
    const providerMeta = extractProviderMeta(error);
    let message = error instanceof Error ? error.message : "Unknown render error";

    if (providerMeta?.status === 404) {
      message =
        "Replicate model endpoint could not be found (provider 404). " +
        "Check REPLICATE_MODEL / profile model env variables.";
    }

    await supabase
      .from("render_requests")
      .update({ status: "failed", error_message: message })
      .eq("id", requestId);

    let statusCode = 500;
    if (providerMeta?.status === 429) statusCode = 429;
    if (providerMeta?.status === 402) statusCode = 402;
    if (providerMeta?.status === 404) statusCode = 502;

    return jsonResponse(statusCode, {
      request_id: requestId,
      status: "failed",
      error: message,
      provider_status: providerMeta?.status ?? null,
      retry_after: providerMeta?.retry_after ?? null,
      guardrail: {
        type:
          providerMeta?.status === 429
            ? "rate_limit"
            : providerMeta?.status === 402
            ? "insufficient_credit"
            : providerMeta?.status === 404
            ? "provider_model_missing"
            : "unknown",
        low_credit: providerMeta?.low_credit ?? false,
        billing_url: providerMeta?.billing_url ?? "https://replicate.com/account/billing#billing",
        recommended_batch_interval_seconds:
          providerMeta?.status === 429 && providerMeta?.low_credit
            ? 10
            : providerMeta?.retry_after ?? null,
      },
    });
  }
});
