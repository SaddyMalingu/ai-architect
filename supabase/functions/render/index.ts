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
  line_art_url?: string;
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

function resolveModelFromDropdown(modelKey?: string): string {
  if (!modelKey) return defaultModel;
  const envVar = `REPLICATE_MODEL_${modelKey.toUpperCase()}`;
  return Deno.env.get(envVar) || defaultModel;
}

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
    const protocol = new URL(value).protocol;
    return protocol === "https:" || protocol === "data:";
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

function isReferenceCapableModel(model: string): boolean {
  const modelKey = Object.keys(MODEL_CAPABILITIES).find((k) => model.startsWith(k));
  const capabilities = modelKey ? MODEL_CAPABILITIES[modelKey] : { supportsReference: false };
  return capabilities.supportsReference;
}

function selectRenderModel(baseModel: string, payload: RenderRequest): { model: string; variant: "control" | "ab" } {
  let selectedModel = baseModel;

  if (payload.input_image_url && payload.strict_consistency) {
    selectedModel = "helios-infotech/sketch-to-image";
  } else if (payload.input_image_url && payload.reference_image_url) {
    selectedModel = "bytedance/seedream-4.5";
  } else if (payload.reference_image_url && !isReferenceCapableModel(selectedModel)) {
    selectedModel = "bytedance/seedream-4.5";
  }

  if (payload.strict_consistency || payload.input_image_url || !RENDER_AB_TEST_ENABLED || RENDER_AB_TEST_PERCENT <= 0) {
    return { model: selectedModel, variant: "control" };
  }

  const bucketKey = payload.consistency_key?.trim() || payload.user_id;
  const bucket = hashToBucket(bucketKey);
  if (bucket < RENDER_AB_TEST_PERCENT) {
    return { model: RENDER_AB_TEST_MODEL, variant: "ab" };
  }

  return { model: selectedModel, variant: "control" };
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
    return "input_image_url must be a valid https or data URL";
  }
  if (payload.line_art_url && !isHttpsUrl(payload.line_art_url)) {
    return "line_art_url must be a valid https or data URL";
  }
  if (payload.reference_image_url && !isHttpsUrl(payload.reference_image_url)) {
    return "reference_image_url must be a valid https or data URL";
  }
  if (payload.input_image_url && payload.strict_consistency) {
    const hasBlenderPass = Boolean(
      payload.blender_front_pass_url ||
        payload.blender_left_pass_url ||
        payload.blender_right_pass_url ||
        payload.blender_back_pass_url ||
        payload.line_art_url,
    );
    if (!hasBlenderPass) {
      return "strict sketch mode requires a Blender pass or line-art pass in the background before render";
    }
  }
  if (payload.mask_url && !isHttpsUrl(payload.mask_url)) {
    return "mask_url must be a valid https or data URL";
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
    // Use the mapping for dropdown values
    const mappedModel = resolveModelFromDropdown(payload.model);
    return { label: "balanced", model: mappedModel, guidance_scale: 7, num_inference_steps: 30 };
  }
  return MODEL_PROFILES["balanced"];
}

async function replicateCreatePrediction(payload: RenderRequest, model: string, profile: ModelProfile) {
  let promptText = payload.style
    ? `${payload.prompt}. Style: ${payload.style}`
    : payload.prompt;

  if (payload.strict_consistency || payload.input_image_url) {
    promptText = `${promptText} IMPORTANT: Preserve the exact geometry, massing, roofline, window spacing, doorway alignment, driveway layout, and facade proportions from the input sketch. Use the reference image only for material/color/lighting cues; do not let the reference redesign the building structure.`;
  }

  const promptFirst = isPromptFirstModel(model);



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

  // Special cases for models with different field names
  if (model.startsWith("qr2ai/outline")) {
    input.input_image = inputImageUrl;
    delete input.image;
  } else if (model.startsWith("xai/grok-imagine-image")) {
    input.instruction = promptText;
    // image field is already set
  } else if (model.startsWith("ideogram-ai/ideogram-v3-turbo") || model.startsWith("black-forest-labs/flux-2-max") || model.startsWith("black-forest-labs/flux-2-pro")) {
    // These models do not use image/reference_image
    input = {
      prompt: promptText,
      output_format: "png",
      aspect_ratio: PROMPT_FIRST_ASPECT_RATIO,
      num_outputs: payload.num_outputs ?? 1,
    };
  }

  // Add mask if available
  if (payload.mask_url) input.mask = payload.mask_url;

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

  if (payload.input_image_url) {
    payload.strict_consistency = true;
    payload.consistency_key = payload.consistency_key?.trim() || payload.user_id;
  }
  if (payload.input_image_url && payload.reference_image_url) {
    payload.strict_consistency = true;
    payload.consistency_key = payload.consistency_key?.trim() || payload.user_id;
  }

  const hasGeometryPass = Boolean(
    payload.line_art_url ||
      payload.blender_front_pass_url ||
      payload.blender_left_pass_url ||
      payload.blender_right_pass_url ||
      payload.blender_back_pass_url,
  );
  if (payload.strict_consistency && payload.input_image_url && !hasGeometryPass) {
    payload.line_art_url = payload.input_image_url;
  }

  async function _uploadDataUriToStorage(fieldName: string, value?: string) {
    if (!value || typeof value !== "string") return null;
    try {
      const m = value.match(/^data:(image\/[a-zA-Z0-9.+-]+);base64,(.+)$/i);
      const mime = m ? m[1] : "image/png";
      const b64 = m ? m[2] : value.replace(/^data:image\/[a-zA-Z0-9.+-]+;base64,/, "");
      const binary = atob(b64);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
      const uuid = crypto.randomUUID();
      const ext = mime.includes("jpeg") ? "jpg" : mime.includes("png") ? "png" : "png";
      const path = `${payload.user_id || "anon"}/${fieldName}-${uuid}.${ext}`;
      const { error: uploadError } = await supabase.storage.from("renders").upload(path, bytes, {
        contentType: mime,
        upsert: true,
      });
      if (uploadError) throw uploadError;
      const { data } = supabase.storage.from("renders").getPublicUrl(path);
      return data.publicUrl;
    } catch (err) {
      console && console.error && console.error(`data URL upload failed for ${fieldName}`, err);
      return null;
    }
  }

  // Support inline base64/data URLs for local workflows: upload to Supabase storage
  // and set the corresponding public URL on the payload so models receive an HTTPS URL.
  if ((payload as any).input_image_b64) {
    const url = await _uploadDataUriToStorage("input_image", (payload as any).input_image_b64 as string);
    if (url) payload.input_image_url = url;
  }
  if ((payload as any).reference_image_b64) {
    const url = await _uploadDataUriToStorage("reference_image", (payload as any).reference_image_b64 as string);
    if (url) payload.reference_image_url = url;
  }
  if (payload.input_image_url && payload.input_image_url.startsWith("data:")) {
    const url = await _uploadDataUriToStorage("input_image", payload.input_image_url);
    if (url) payload.input_image_url = url;
  }
  if (payload.reference_image_url && payload.reference_image_url.startsWith("data:")) {
    const url = await _uploadDataUriToStorage("reference_image", payload.reference_image_url);
    if (url) payload.reference_image_url = url;
  }
  if (payload.mask_url && payload.mask_url.startsWith("data:")) {
    const url = await _uploadDataUriToStorage("mask", payload.mask_url);
    if (url) payload.mask_url = url;
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
  let effectiveModel = selected.model;

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
    // If the request includes a reference image but the selected model does not support
    // reference conditioning, switch to a fallback model that does support references.
    // This avoids the model discarding the sketch/structure when a user provided a reference.
    const modelKey = Object.keys(MODEL_CAPABILITIES).find((k) => effectiveModel.startsWith(k));
    const capabilities = modelKey ? MODEL_CAPABILITIES[modelKey] : { supportsReference: false };
    if (payload.reference_image_url && !capabilities.supportsReference) {
      // choose a known reference-capable model as fallback
      const fallback = "bytedance/seedream-4.5";
      effectiveModel = fallback;
      // update profile to a reasonable default mapping
      // keep original profile label but override model used
      console.log(`Switching model to reference-capable fallback: ${fallback}`);
    }

    const prediction = await replicateCreatePrediction(payload, effectiveModel, profile);
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
        model: effectiveModel,
        resolved_model: effectiveModel,
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
