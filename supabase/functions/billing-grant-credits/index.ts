// @ts-ignore Deno runtime resolves URL imports at deploy/runtime.
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

declare const Deno: {
  env: { get(name: string): string | undefined };
  serve(handler: (request: Request) => Response | Promise<Response>): void;
};

type GrantRequest = {
  admin_key?: string;
  user_id?: string;
  amount_credits?: number;
  reason?: string;
};

const supabaseUrl = Deno.env.get("SUPABASE_URL") || "";
const supabaseServiceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
const billingAdminKey = Deno.env.get("BILLING_ADMIN_KEY") || "";
const controlRoomTestUserId = Deno.env.get("CONTROL_ROOM_TEST_USER_ID") || "";
const freeTierInitialCredits = Number(Deno.env.get("FREE_TIER_INITIAL_CREDITS") || "5");

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

function isValidUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}

Deno.serve(async (request: Request) => {
  if (request.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  if (request.method !== "POST") {
    return jsonResponse(405, { detail: "Method not allowed" });
  }

  try {
    if (!billingAdminKey) {
      return jsonResponse(500, { detail: "BILLING_ADMIN_KEY is not configured on this function" });
    }

    const payload = (await request.json()) as GrantRequest;
    const adminKey = String(payload.admin_key || "").trim();
    const userId = String(payload.user_id || "").trim();
    const amount = Number(payload.amount_credits || 0);
    const reason = String(payload.reason || "control_room_test_grant").trim();

    if (adminKey !== billingAdminKey) {
      return jsonResponse(403, { detail: "Invalid admin key" });
    }

    if (!userId || !isValidUuid(userId)) {
      return jsonResponse(400, { detail: "user_id must be a valid UUID" });
    }

    if (controlRoomTestUserId && userId !== controlRoomTestUserId) {
      return jsonResponse(403, { detail: "Grant only allowed for configured control-room test user" });
    }

    if (!Number.isFinite(amount) || amount <= 0) {
      return jsonResponse(400, { detail: "amount_credits must be a positive number" });
    }

    let { data: credits, error } = await supabase
      .from("user_credits")
      .select("user_id,balance_credits,subscription_tier")
      .eq("user_id", userId)
      .maybeSingle();

    if (error) {
      return jsonResponse(500, { detail: error.message });
    }

    if (!credits) {
      const { data: inserted, error: insertError } = await supabase
        .from("user_credits")
        .insert({
          user_id: userId,
          balance_credits: freeTierInitialCredits,
          subscription_tier: "free",
          trial_started_at: new Date().toISOString(),
          trial_ends_at: new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString(),
        })
        .select("user_id,balance_credits,subscription_tier")
        .single();

      if (insertError) {
        return jsonResponse(500, { detail: insertError.message });
      }
      credits = inserted;
    }

    const before = Number(credits.balance_credits || 0);
    const after = before + amount;

    const { error: updateError } = await supabase
      .from("user_credits")
      .update({ balance_credits: after })
      .eq("user_id", userId);

    if (updateError) {
      return jsonResponse(500, { detail: updateError.message });
    }

    const { error: txError } = await supabase.from("credit_transactions").insert({
      user_id: userId,
      amount: amount,
      transaction_type: "bonus",
      reason,
      balance_before: before,
      balance_after: after,
    });

    if (txError) {
      return jsonResponse(500, { detail: txError.message });
    }

    return jsonResponse(200, {
      success: true,
      user_id: userId,
      granted_credits: amount,
      balance_credits: after,
      reason,
    });
  } catch (err) {
    return jsonResponse(500, { detail: err instanceof Error ? err.message : String(err) });
  }
});
