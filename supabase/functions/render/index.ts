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
  blender_front_pass_url?: string;
  blender_left_pass_url?: string;
  blender_right_pass_url?: string;
  blender_back_pass_url?: string;
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

const MODEL_KEY_FALLBACKS: Record<string, string> = {
  flux_1_kontext_pro: "black-forest-labs/flux-2-pro",
  nano_banana_2: "google/nano-banana-2",
  nano_banana_2_lite: "google/nano-banana-2",
  nano_banana_pro: "google/nano-banana-2",
  seedream_5_0_pro: "bytedance/seedream-4.5",
  seedream_5_0: "bytedance/seedream-5-lite",
  gpt_image_2: "black-forest-labs/flux-2-pro",
  kling_3_0: "black-forest-labs/flux-2-pro",
  kling_03: "black-forest-labs/flux-2-pro",
  artlist_original_1_0: "black-forest-labs/flux-2-pro",
  krea_2: "black-forest-labs/flux-2-pro",
  flux_2_0_pro_ai: "black-forest-labs/flux-2-pro",
};

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


// Model capability registry
const MODEL_CAPABILITIES: Record<string, { supportsReference: boolean }> = {
  "flux_1_kontext_pro": { supportsReference: true },
  "nano_banana_2": { supportsReference: true },
  "nano_banana_2_lite": { supportsReference: true },
  "nano_banana_pro": { supportsReference: true },
  "seedream_5_0_pro": { supportsReference: true },
  "seedream_5_0": { supportsReference: true },
  "gpt_image_2": { supportsReference: true },
  "kling_3_0": { supportsReference: true },
  "kling_03": { supportsReference: true },
  "artlist_original_1_0": { supportsReference: true },
  "krea_2": { supportsReference: true },
  "flux_2_0_pro_ai": { supportsReference: true },
  "bytedance/seedream-5-lite": { supportsReference: true },
  "bytedance/seedream-4.5": { supportsReference: true },
  "prunaai/flux-fast": { supportsReference: false },
  "helios-infotech/sketch-to-image": { supportsReference: false },
  "jagilley/controlnet-scribble": { supportsReference: false },
  "qr2ai/outline": { supportsReference: false },
  "xai/grok-imagine-image": { supportsReference: false },
  "ideogram-ai/ideogram-v3-turbo": { supportsReference: false },
  "wan-video/wan-2.7-image-pro": { supportsReference: false },
  "black-forest-labs/flux-2-max": { supportsReference: false },
  "black-forest-labs/flux-2-pro": { supportsReference: false },
  "sourceful/riverflow-2.0-pro": { supportsReference: false },
  "google/nano-banana": { supportsReference: false },
  "google/nano-banana-2": { supportsReference: false },
  "lightweight-ai/test_sk2ig_f": { supportsReference: false },
};

function toEnvModelKey(input: string): string {
  return input
    .trim()
    .replace(/[^a-zA-Z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .toUpperCase();
}

function resolveModelFromDropdown(modelKey?: string): string {
  if (!modelKey) return defaultModel;
  const trimmed = modelKey.trim();
  // UI may send full Replicate slug/version directly.
  if (trimmed.includes("/")) return trimmed;

  const normalized = trimmed.toLowerCase();
  const envVar = `REPLICATE_MODEL_${toEnvModelKey(normalized)}`;
  const fromEnv = Deno.env.get(envVar);
  if (isUsableModelRef(fromEnv)) return fromEnv;

  const fallback = MODEL_KEY_FALLBACKS[normalized];
  if (isUsableModelRef(fallback)) return fallback;

  return defaultModel;
}

function isUsableModelRef(value?: string): value is string {
  if (!value) return false;
  const trimmed = value.trim();
  if (!trimmed) return false;
  const lowered = trimmed.toLowerCase();
  if (lowered === "false" || lowered === "true" || lowered === "null" || lowered === "undefined") {
    return false;
  }
  return true;
}

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
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

function isImageSourceUrl(value?: string): boolean {
  if (!value) return false;
  return isHttpsUrl(value) || value.startsWith("data:image/");
}

function describeImageSource(value?: string): string {
  if (!value) return "missing";
  if (value.startsWith("data:image/")) return `data-url:${value.slice(0, 30)}... len=${value.length}`;
  if (isHttpsUrl(value)) return `https-url:${value}`;
  return `other:${value.slice(0, 30)}... len=${value.length}`;
}

function summarizeRenderRequest(payload: RenderRequest) {
  return {
    user_id: payload.user_id,
    prompt_chars: payload.prompt ? payload.prompt.length : 0,
    style_chars: payload.style ? payload.style.length : 0,
    input_image: describeImageSource(payload.input_image_url),
    reference_image: describeImageSource(payload.reference_image_url),
    mask_url: payload.mask_url ? describeImageSource(payload.mask_url) : "missing",
    model: payload.model ?? null,
    model_profile: payload.model_profile ?? null,
    num_outputs: payload.num_outputs ?? null,
    consistency_key_present: Boolean(payload.consistency_key),
    strict_consistency: Boolean(payload.strict_consistency),
    blender_conditioned: Boolean(payload.blender_conditioned),
    blender_pass_type: payload.blender_pass_type ?? null,
  };
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

function prefersImageConditioning(payload: RenderRequest): boolean {
  return Boolean(
    payload.input_image_url ||
      payload.reference_image_url ||
      payload.strict_consistency ||
      payload.blender_conditioned,
  );
}

function resolveImageConditionedModel(baseModel: string, payload: RenderRequest): string {
  const explicitModel = resolveModelFromDropdown(payload.model);
  if (isUsableModelRef(explicitModel)) {
    return explicitModel;
  }

  if (!prefersImageConditioning(payload)) return baseModel;
  if (!isPromptFirstModel(baseModel)) return baseModel;

  const candidates = [
    Deno.env.get("REPLICATE_MODEL_SKETCH") || "",
    Deno.env.get("REPLICATE_MODEL_CONTROLNET") || "",
    Deno.env.get("REPLICATE_MODEL_IPADAPTER") || "",
    Deno.env.get("REPLICATE_MODEL_INPAINT") || "",
    Deno.env.get("REPLICATE_MODEL_SDXL") || "",
    Deno.env.get("REPLICATE_MODEL") || "",
  ].filter((value, index, array) => isUsableModelRef(value) && array.indexOf(value) === index);

  return candidates.find((candidate) => !isPromptFirstModel(candidate)) || baseModel;
}

function isReplicate404(error: unknown): boolean {
  if (!(error instanceof Error)) return false;
  return error.message.includes("Replicate create failed: 404");
}

function candidateModelsForRender(
  payload: RenderRequest,
  profileModel: string,
  selectedModel: string,
): string[] {
  const explicitModel = resolveModelFromDropdown(payload.model);
  if (isUsableModelRef(explicitModel)) {
    return [explicitModel];
  }

  const candidates = [
    selectedModel,
    resolveImageConditionedModel(profileModel, payload),
    resolveImageConditionedModel(Deno.env.get("REPLICATE_MODEL") || "", payload),
    Deno.env.get("REPLICATE_MODEL_SKETCH") || "",
    Deno.env.get("REPLICATE_MODEL_CONTROLNET") || "",
    Deno.env.get("REPLICATE_MODEL_IPADAPTER") || "",
    Deno.env.get("REPLICATE_MODEL_INPAINT") || "",
    Deno.env.get("REPLICATE_MODEL_BALANCED") || "",
    Deno.env.get("REPLICATE_MODEL_FAST") || "",
    Deno.env.get("REPLICATE_MODEL_QUALITY") || "",
  ];

  return candidates.filter((model, index) => isUsableModelRef(model) && candidates.indexOf(model) === index);
}

function resolveReplicateTarget(modelRef: string): {
  endpoint: string;
  bodyBase: Record<string, unknown>;
} {
  const trimmed = modelRef.trim();

  // owner/model:versionId (versioned slug)
  if (trimmed.includes("/") && trimmed.includes(":")) {
    const [slug, version] = trimmed.split(":", 2);
    return {
      endpoint: `https://api.replicate.com/v1/models/${slug}/versions/${version}/predictions`,
      bodyBase: {}, // Do NOT send version in body
    };
  }

  // owner/model
  if (trimmed.includes("/")) {
    return {
      endpoint: `https://api.replicate.com/v1/models/${trimmed}/predictions`,
      bodyBase: {},
    };
  }

  // version id only
  return {
    endpoint: "https://api.replicate.com/v1/predictions",
    bodyBase: { version: trimmed },
  };
}

function selectRenderModel(baseModel: string, payload: RenderRequest): { model: string; variant: "control" | "ab" } {
  const explicitModel = resolveModelFromDropdown(payload.model);
  if (isUsableModelRef(explicitModel)) {
    return { model: explicitModel, variant: "control" };
  }

  if (payload.strict_consistency || !RENDER_AB_TEST_ENABLED || RENDER_AB_TEST_PERCENT <= 0) {
    return { model: resolveImageConditionedModel(baseModel, payload), variant: "control" };
  }

  const bucketKey = payload.consistency_key?.trim() || payload.user_id;
  const bucket = hashToBucket(bucketKey);
  if (bucket < RENDER_AB_TEST_PERCENT) {
    return { model: RENDER_AB_TEST_MODEL, variant: "ab" };
  }

  return { model: resolveImageConditionedModel(baseModel, payload), variant: "control" };
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
  if (payload.input_image_url && !isImageSourceUrl(payload.input_image_url)) {
    return "input_image_url must be a valid https URL or data URL";
  }
  if (payload.reference_image_url && !isImageSourceUrl(payload.reference_image_url)) {
    return "reference_image_url must be a valid https URL or data URL";
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
  // Explicit model key always wins — use profile only for guidance/steps defaults.
  if (payload.model) {
    const mappedModel = resolveModelFromDropdown(payload.model);
    if (isUsableModelRef(mappedModel)) {
      const base = (payload.model_profile && MODEL_PROFILES[payload.model_profile])
        ? MODEL_PROFILES[payload.model_profile]
        : MODEL_PROFILES["balanced"];
      return { label: base.label, model: mappedModel, guidance_scale: base.guidance_scale, num_inference_steps: base.num_inference_steps };
    }
  }
  if (payload.model_profile && MODEL_PROFILES[payload.model_profile]) {
    return MODEL_PROFILES[payload.model_profile];
  }
  return MODEL_PROFILES["balanced"];
}

async function replicateCreatePrediction(payload: RenderRequest, model: string, profile: ModelProfile) {
  const promptText = payload.style
    ? `${payload.prompt}. Style: ${payload.style}`
    : payload.prompt;

  // Find the canonical model key for capability lookup
  const modelKey = Object.keys(MODEL_CAPABILITIES).find((k) => model.startsWith(k));
  const capabilities = modelKey ? MODEL_CAPABILITIES[modelKey] : { supportsReference: false };

  // --- Blender-conditioned mode: override input_image_url with Blender pass if enabled ---
  let inputImageUrl = payload.input_image_url;
  if (payload.blender_conditioned && payload.blender_pass_type) {
    switch (payload.blender_pass_type) {
      case "front":
        if (payload.blender_front_pass_url) inputImageUrl = payload.blender_front_pass_url;
        break;
      case "left":
        if (payload.blender_left_pass_url) inputImageUrl = payload.blender_left_pass_url;
        break;
      case "right":
        if (payload.blender_right_pass_url) inputImageUrl = payload.blender_right_pass_url;
        break;
      case "back":
        if (payload.blender_back_pass_url) inputImageUrl = payload.blender_back_pass_url;
        break;
      default:
        break;
    }
  }

  // Default input mapping
  let input: Record<string, unknown> = {
    prompt: promptText,
    output_format: "png",
    num_outputs: payload.num_outputs ?? 1,
  };

  // Add image if available
  if (inputImageUrl) input.image = inputImageUrl;

  // Add reference_image if supported and available
  if (capabilities.supportsReference && payload.reference_image_url) {
    input.reference_image = payload.reference_image_url;
  }

  if (payload.reference_image_url && !capabilities.supportsReference) {
    input.reference_image_url = payload.reference_image_url;
  }

  // Add mask if available
  if (payload.mask_url) input.mask = payload.mask_url;

  console.info(
    `[render] create_prediction model=${model} input_image=${describeImageSource(inputImageUrl)} reference_image=${describeImageSource(payload.reference_image_url)} mask=${payload.mask_url ? describeImageSource(payload.mask_url) : "missing"}`,
  );

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
  const traceId = crypto.randomUUID();
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

  console.info(`[render:${traceId}] request received`, summarizeRenderRequest(payload));

  const validationError = validatePayload(payload);
  if (validationError) {
    console.warn(`[render:${traceId}] validation failed: ${validationError}`, summarizeRenderRequest(payload));
    return jsonResponse(400, {
      error: validationError,
      diagnostics: summarizeRenderRequest(payload),
    });
  }

  const withinQuota = await checkDailyQuota(payload.user_id);
  if (!withinQuota) {
    return jsonResponse(429, {
      error: `Daily render quota of ${DAILY_QUOTA_LIMIT} reached. Try again tomorrow.`,
    });
  }

  const profile = resolveModelProfile(payload);
  const selected = selectRenderModel(profile.model, payload);

  console.info(`[render:${traceId}] model resolved`, {
    profile: profile.label,
    selected_model: selected.model,
    variant: selected.variant,
    candidate_models: candidateModelsForRender(payload, profile.model, selected.model),
  });

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
    console.error(`[render:${traceId}] failed to insert request row`, insertError?.message || "missing id");
    return jsonResponse(500, {
      error: "Failed to insert render request",
      details: insertError?.message,
    });
  }

  const requestId = requestRow.id as string;
  const replicateStartMs = Date.now();
  let modelUsed = selected.model;

  try {
    let prediction: Record<string, unknown> | null = null;
    let lastError: unknown = null;

    const candidateModels = payload.strict_consistency
      ? [selected.model]
      : candidateModelsForRender(payload, profile.model, selected.model);

    for (const candidateModel of candidateModels) {
      modelUsed = candidateModel;
      console.info(`[render:${traceId}] trying candidate model`, candidateModel);
      try {
        prediction = await replicateCreatePrediction(payload, candidateModel, profile);
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

    console.info(`[render:${traceId}] prediction created`, { request_id: requestId, prediction_id: predictionId, model_used: modelUsed });

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

    console.info(`[render:${traceId}] output stored`, { request_id: requestId, output_url: publicUrl, latency_ms: latencyMs });

    const { error: resultError } = await supabase.from("render_results").insert({
      request_id: requestId,
      user_id: payload.user_id,
      output_image_url: publicUrl,
      metadata: {
        replicate_prediction_id: predictionId,
        replicate_model: modelUsed,
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
        resolved_model: modelUsed,
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
    const targetInfo = resolveReplicateTarget(modelUsed);
    const candidateModels = candidateModelsForRender(payload, profile.model, selected.model);

    console.error(`[render:${traceId}] render failed`, {
      request_id: requestId,
      message,
      provider_status: providerMeta?.status ?? null,
      selected_model: modelUsed,
      candidate_models: candidateModels,
      payload: summarizeRenderRequest(payload),
      provider_body: providerMeta?.body ?? null,
    });

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
    if (providerMeta?.status === 422) statusCode = 422;

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
      diagnostics: {
        model_profile: profile.label,
        profile_model: profile.model,
        selected_model: modelUsed,
        candidate_models: candidateModels,
        ab_variant: selected.variant,
        target_endpoint: targetInfo.endpoint,
        target_body_base: targetInfo.bodyBase,
        model_traits: {
          prompt_first: isPromptFirstModel(selected.model),
          flux_like: isFluxLikeModel(selected.model),
        },
        input_flags: {
          has_input_image_url: Boolean(payload.input_image_url),
          has_reference_image_url: Boolean(payload.reference_image_url),
          has_mask_url: Boolean(payload.mask_url),
          strict_consistency: Boolean(payload.strict_consistency),
          blender_conditioned: Boolean(payload.blender_conditioned),
          blender_pass_type: payload.blender_pass_type ?? null,
        },
        provider_body: providerMeta?.body ?? null,
      },
    });
  }
});
