// @ts-ignore Deno runtime resolves URL imports at deploy/runtime.
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

declare const Deno: {
  env: { get(name: string): string | undefined };
  serve(handler: (request: Request) => Response | Promise<Response>): void;
};

const supabaseUrl = Deno.env.get("SUPABASE_URL") || "";
const supabaseServiceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
const freeTierInitialCredits = Number(Deno.env.get("FREE_TIER_INITIAL_CREDITS") || "5");

const corsHeaders = {
  "Access-Control-Allow-Origin": Deno.env.get("ALLOWED_ORIGIN") || "*",
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

Deno.serve(async (request: Request) => {
  if (request.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  if (request.method !== "GET") {
    return jsonResponse(405, { detail: "Method not allowed" });
  }

  try {
    const url = new URL(request.url);
    const userId = (url.searchParams.get("user_id") || "").trim();

    if (!userId || !isValidUuid(userId)) {
      return jsonResponse(400, { detail: "user_id must be a valid UUID" });
    }

    let { data: credits, error } = await supabase
      .from("user_credits")
      .select("user_id,balance_credits,subscription_tier,trial_ends_at,updated_at")
      .eq("user_id", userId)
      .maybeSingle();

    if (error) {
      return jsonResponse(500, { detail: error.message });
    }

    if (!credits) {
      const trialEndsAt = new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString();
      const { data: inserted, error: insertError } = await supabase
        .from("user_credits")
        .insert({
          user_id: userId,
          balance_credits: freeTierInitialCredits,
          subscription_tier: "free",
          trial_started_at: new Date().toISOString(),
          trial_ends_at: trialEndsAt,
        })
        .select("user_id,balance_credits,subscription_tier,trial_ends_at,updated_at")
        .single();

      if (insertError) {
        return jsonResponse(500, { detail: insertError.message });
      }
      credits = inserted;
    }

    return jsonResponse(200, {
      user_id: credits.user_id,
      balance_credits: Number(credits.balance_credits || 0),
      subscription_tier: credits.subscription_tier || "free",
      trial_ends_at: credits.trial_ends_at || null,
      updated_at: credits.updated_at || null,
    });
  } catch (err) {
    return jsonResponse(500, { detail: err instanceof Error ? err.message : String(err) });
  }
});
