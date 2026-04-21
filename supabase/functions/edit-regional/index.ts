// @ts-ignore Deno runtime resolves URL imports at deploy/runtime.
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

declare const Deno: {
  env: { get(name: string): string | undefined };
  serve(handler: (request: Request) => Response | Promise<Response>): void;
};

type EditCategory = "element_texture" | "whole_building" | "prompt_only";
type SelectionMode = "automatic" | "manual";
type ProfileName = "fast" | "balanced" | "quality";

type RegionalEditRequest = {
  user_id: string;
  target_image_url: string;
  reference_image_url?: string;
  prompt?: string;
  edit_category: EditCategory;
  region_hint?: string;
  selection_mode: SelectionMode;
  target_mask_url?: string;
  target_mask_data_url?: string;
  reference_mask_url?: string;
  strict_consistency?: boolean;
  model_profile?: ProfileName;
  strength?: number;
  num_outputs?: number;
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

const POLL_MAX_ATTEMPTS = 60;
const POLL_INTERVAL_MS = 2000;

const supabaseUrl = Deno.env.get("SUPABASE_URL") || "";
const supabaseServiceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
const replicateApiToken = Deno.env.get("REPLICATE_API_TOKEN") || "";
const DAILY_QUOTA_LIMIT = parseInt(Deno.env.get("DAILY_QUOTA_LIMIT") || "100", 10);
const CREATE_RETRY_MAX_ATTEMPTS = parseInt(Deno.env.get("REPLICATE_CREATE_RETRY_MAX_ATTEMPTS") || "3", 10);
const CREATE_RETRY_FALLBACK_SECONDS = parseInt(
  Deno.env.get("REPLICATE_CREATE_RETRY_FALLBACK_SECONDS") || "10",
  10,
);

const supportsReference =
  (Deno.env.get("REPLICATE_SUPPORTS_REFERENCE") || "false").toLowerCase() === "true";

const fallbackModel =
  Deno.env.get("REPLICATE_REGIONAL_MODEL") ||
  Deno.env.get("REPLICATE_MODEL") ||
  "stability-ai/sdxl";

const REGIONAL_MODELS: Record<ProfileName, string> = {
  fast: Deno.env.get("REPLICATE_REGIONAL_MODEL_FAST") || fallbackModel,
  balanced: Deno.env.get("REPLICATE_REGIONAL_MODEL_BALANCED") || fallbackModel,
  quality: Deno.env.get("REPLICATE_REGIONAL_MODEL_QUALITY") || fallbackModel,
};
const RENDER_MODELS: Record<ProfileName, string> = {
  fast: Deno.env.get("REPLICATE_MODEL_FAST") || Deno.env.get("REPLICATE_MODEL") || "",
  balanced: Deno.env.get("REPLICATE_MODEL_BALANCED") || Deno.env.get("REPLICATE_MODEL") || "",
  quality: Deno.env.get("REPLICATE_MODEL_QUALITY") || Deno.env.get("REPLICATE_MODEL") || "",
};
const renderAbModel = Deno.env.get("REPLICATE_RENDER_AB_TEST_MODEL") || "";

const GUIDANCE_BY_PROFILE: Record<ProfileName, number> = { fast: 5, balanced: 7, quality: 9 };
const STEPS_BY_PROFILE: Record<ProfileName, number> = { fast: 20, balanced: 30, quality: 50 };

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

function validatePayload(payload: RegionalEditRequest): string | null {
  if (!payload.user_id) return "user_id is required";
  if (!isValidUuid(payload.user_id)) return "user_id must be a valid UUID";
  if (!payload.target_image_url) return "target_image_url is required";
  if (!isHttpsUrl(payload.target_image_url)) return "target_image_url must be a valid https URL";
  if (payload.reference_image_url && !isHttpsUrl(payload.reference_image_url)) {
    return "reference_image_url must be a valid https URL";
  }
  if (payload.target_mask_url && !isHttpsUrl(payload.target_mask_url)) {
    return "target_mask_url must be a valid https URL";
  }
  if (payload.target_mask_data_url && !payload.target_mask_data_url.startsWith("data:image/png;base64,")) {
    return "target_mask_data_url must be a PNG data URL";
  }
  if (payload.reference_mask_url && !isHttpsUrl(payload.reference_mask_url)) {
    return "reference_mask_url must be a valid https URL";
  }

  const validCategories: EditCategory[] = ["element_texture", "whole_building", "prompt_only"];
  if (!validCategories.includes(payload.edit_category)) {
    return "edit_category must be one of: element_texture, whole_building, prompt_only";
  }

  const validSelectionModes: SelectionMode[] = ["automatic", "manual"];
  if (!validSelectionModes.includes(payload.selection_mode)) {
    return "selection_mode must be one of: automatic, manual";
  }

  if (payload.edit_category === "prompt_only") {
    if (!payload.prompt || payload.prompt.trim().length === 0) {
      return "prompt is required when edit_category is prompt_only";
    }
    if (payload.prompt.length > 1200) {
      return "prompt exceeds maximum length of 1200 characters";
    }
  }

  if (payload.selection_mode === "manual" && !payload.target_mask_url && !payload.target_mask_data_url) {
    return "target_mask_url or target_mask_data_url is required when selection_mode is manual";
  }

  if (payload.strength !== undefined && (payload.strength < 0 || payload.strength > 1)) {
    return "strength must be between 0.0 and 1.0";
  }

  if (payload.num_outputs !== undefined && (payload.num_outputs < 1 || payload.num_outputs > 4)) {
    return "num_outputs must be between 1 and 4";
  }

  if (payload.model_profile && !["fast", "balanced", "quality"].includes(payload.model_profile)) {
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

function buildPrompt(payload: RegionalEditRequest): string {
  const basePrompt = payload.prompt?.trim() || "Apply reference-guided architectural edit";
  const profile = payload.model_profile || "balanced";
  const promptParts = [
    basePrompt,
    `Edit category: ${payload.edit_category}`,
    `Selection mode: ${payload.selection_mode}`,
    `Model profile: ${profile}`,
  ];

  if (payload.region_hint) {
    promptParts.push(`Target region: ${payload.region_hint}`);
  }
  if (payload.strict_consistency) {
    promptParts.push(
      "Strict consistency: preserve the same building geometry, camera framing, window layout, openings, structure, and all unselected regions"
    );
  }

  return promptParts.join(". ");
}

function buildReplicateInput(payload: RegionalEditRequest): Record<string, unknown> {
  const profile = (payload.model_profile || "balanced") as ProfileName;
  const guidanceBoost = payload.strict_consistency ? 1 : 0;
  const input: Record<string, unknown> = {
    prompt: buildPrompt(payload),
    image: payload.target_image_url,
    num_outputs: payload.num_outputs ?? 1,
    output_format: "png",
    guidance_scale: GUIDANCE_BY_PROFILE[profile] + guidanceBoost,
    num_inference_steps: STEPS_BY_PROFILE[profile],
  };

  if (payload.target_mask_url) input.mask = payload.target_mask_url;
  if (payload.strength !== undefined) input.prompt_strength = payload.strength;

  if (supportsReference) {
    if (payload.reference_image_url) input.reference_image = payload.reference_image_url;
    if (payload.reference_mask_url) input.reference_mask = payload.reference_mask_url;
  }

  return input;
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

function isReplicate404(error: unknown): boolean {
  if (!(error instanceof Error)) return false;
  return error.message.includes("Replicate create failed: 404");
}

function candidateModelsForRegional(profile: ProfileName): string[] {
  const candidates = [
    REGIONAL_MODELS[profile],
    RENDER_MODELS[profile],
    renderAbModel,
    Deno.env.get("REPLICATE_MODEL") || "",
  ];

  return candidates.filter((m, idx) => !!m && candidates.indexOf(m) === idx);
}

async function uploadMaskDataUrlToSupabase(userId: string, requestId: string, dataUrl: string) {
  const prefix = "data:image/png;base64,";
  const base64 = dataUrl.slice(prefix.length);
  const binary = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
  const path = `${userId}/${requestId}-mask.png`;

  const { error: uploadError } = await supabase.storage
    .from("renders")
    .upload(path, binary, { contentType: "image/png", upsert: true });

  if (uploadError) {
    throw new Error(`Supabase mask upload failed: ${uploadError.message}`);
  }

  const { data } = supabase.storage.from("renders").getPublicUrl(path);
  return data.publicUrl;
}

async function replicateCreatePrediction(payload: RegionalEditRequest, overrideModel?: string) {
  const profile = (payload.model_profile || "balanced") as ProfileName;
  const model = overrideModel || REGIONAL_MODELS[profile];

  const target = resolveReplicateTarget(model);
  const requestBody = { ...target.bodyBase, input: buildReplicateInput(payload) };

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

  let payload: RegionalEditRequest;
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

  const profile = (payload.model_profile || "balanced") as ProfileName;
  const requestPrompt = buildPrompt(payload);

  const { data: requestRow, error: insertError } = await supabase
    .from("render_requests")
    .insert({
      user_id: payload.user_id,
      prompt: requestPrompt,
      style: payload.model_profile ?? null,
      input_image_url: payload.target_image_url,
      reference_image_url: payload.reference_image_url ?? null,
      mask_url: payload.target_mask_url ?? null,
      provider: "replicate",
      model_profile: profile,
      status: "processing",
    })
    .select("id")
    .single();

  if (insertError || !requestRow?.id) {
    return jsonResponse(500, {
      error: "Failed to insert edit request",
      details: insertError?.message,
    });
  }

  const requestId = requestRow.id as string;
  const replicateStartMs = Date.now();

  try {
    if (payload.target_mask_data_url && !payload.target_mask_url) {
      payload.target_mask_url = await uploadMaskDataUrlToSupabase(
        payload.user_id,
        requestId,
        payload.target_mask_data_url,
      );
    }

    let prediction: Record<string, unknown> | null = null;
    let modelUsed = REGIONAL_MODELS[profile];
    let lastError: unknown = null;

    const candidateModels = payload.strict_consistency
      ? [REGIONAL_MODELS[profile]]
      : candidateModelsForRegional(profile);

    for (const candidateModel of candidateModels) {
      modelUsed = candidateModel;
      try {
        prediction = await replicateCreatePrediction(payload, candidateModel);
        lastError = null;
        break;
      } catch (error) {
        lastError = error;
        if (!isReplicate404(error)) {
          throw error;
        }
      }
    }

    if (!prediction) {
      throw (lastError instanceof Error ? lastError : new Error("No valid Replicate model available"));
    }

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

    const coverageRatio = payload.selection_mode === "manual" ? 0.25 : 0.35;
    const editTarget =
      payload.edit_category === "whole_building"
        ? "multi_feature"
        : payload.edit_category === "element_texture"
        ? "regional_element"
        : "semantic_region";

    const { error: resultError } = await supabase.from("render_results").insert({
      request_id: requestId,
      user_id: payload.user_id,
      output_image_url: publicUrl,
      metadata: {
        replicate_prediction_id: predictionId,
        replicate_model: modelUsed,
        model_profile: profile,
        guidance_scale: GUIDANCE_BY_PROFILE[profile],
        num_inference_steps: STEPS_BY_PROFILE[profile],
        latency_ms: latencyMs,
        edit_category: payload.edit_category,
        selection_mode: payload.selection_mode,
        region_hint: payload.region_hint ?? null,
        strict_consistency: Boolean(payload.strict_consistency),
        strength: payload.strength ?? null,
        target_mask_url: payload.target_mask_url ?? null,
        reference_mask_url: supportsReference ? (payload.reference_mask_url ?? null) : null,
        applied_region: { mode: payload.selection_mode, coverage_ratio: coverageRatio },
        edit_summary: {
          category: payload.edit_category,
          target: editTarget,
          changes:
            payload.edit_category === "prompt_only"
              ? ["semantic_transform"]
              : ["material", "color", "finish"],
        },
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
        model: modelUsed,
        model_profile: profile,
        latency_ms: latencyMs,
      },
      applied_region: { mode: payload.selection_mode, coverage_ratio: coverageRatio },
      edit_summary: {
        category: payload.edit_category,
        target: editTarget,
        changes:
          payload.edit_category === "prompt_only"
            ? ["semantic_transform"]
            : ["material", "color", "finish"],
      },
    });
  } catch (error) {
    const providerMeta = extractProviderMeta(error);
    let message = error instanceof Error ? error.message : "Unknown regional edit error";

    if (providerMeta?.status === 404) {
      message =
        "Replicate model endpoint could not be found (provider 404). " +
        "Check REPLICATE_REGIONAL_MODEL / REPLICATE_MODEL env variables.";
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