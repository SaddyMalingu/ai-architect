"""
Payment and Billing API Endpoints
Stripe integration, credit purchases, and subscription management
"""

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel
import os
import stripe
from typing import Optional
from decimal import Decimal
import json
import hashlib

from billing import get_billing_client, BillingClient, SubscriptionTier, PaymentProvider, TransactionType

router = APIRouter(prefix="/billing", tags=["billing"])

# Initialize Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
PAYMENT_PROVIDER = os.getenv("PAYMENT_PROVIDER", "stripe").lower()
FLW_WEBHOOK_HASH = os.getenv("FLW_WEBHOOK_HASH", "")
APP_URL = os.getenv("APP_URL", "http://localhost:8080")
LSQ_WEBHOOK_SECRET = os.getenv("LSQ_WEBHOOK_SECRET", "")
LSQ_VARIANT_STARTER = os.getenv("LSQ_VARIANT_STARTER", "")
LSQ_VARIANT_PRO = os.getenv("LSQ_VARIANT_PRO", "")
BILLING_ADMIN_KEY = os.getenv("BILLING_ADMIN_KEY", "")
CONTROL_ROOM_TEST_USER_ID = os.getenv("CONTROL_ROOM_TEST_USER_ID", "")
CONTROL_ROOM_DEFAULT_GRANT_CREDITS = os.getenv("CONTROL_ROOM_DEFAULT_GRANT_CREDITS", "10")

# =====================================================================
# REQUEST/RESPONSE MODELS
# =====================================================================

class CreatePaymentIntentRequest(BaseModel):
    user_id: str
    email: str
    amount_credits: int  # Number of credits to purchase

class PaymentConfirmRequest(BaseModel):
    user_id: str
    payment_intent_id: str

class SubscribeRequest(BaseModel):
    user_id: str
    tier: str  # "starter", "pro", "enterprise"

class UserCreditsResponse(BaseModel):
    user_id: str
    balance_credits: float
    subscription_tier: str
    lifetime_purchased: float

class AdminGrantCreditsRequest(BaseModel):
    admin_key: str
    user_id: str
    amount_credits: float
    reason: Optional[str] = None

class PricingResponse(BaseModel):
    per_render: float
    payment_provider: str
    tiers: dict

# =====================================================================
# GET ENDPOINTS
# =====================================================================

@router.get("/pricing", response_model=PricingResponse)
async def get_pricing():
    """Get all pricing information"""
    try:
        pricing = BillingClient.get_pricing_summary()
        return PricingResponse(**pricing)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/credits/{user_id}", response_model=UserCreditsResponse)
async def get_user_credits(user_id: str):
    """Get user's current credit balance and subscription status"""
    try:
        billing = get_billing_client()
        credits_data = billing.get_user_credits(user_id)
        return UserCreditsResponse(**credits_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/subscription-status/{user_id}")
async def get_subscription_status(user_id: str):
    """Get user's subscription status"""
    try:
        billing = get_billing_client()
        credits_data = billing.get_user_credits(user_id)
        return {
            "subscription_tier": credits_data.get("subscription_tier"),
            "subscription_expires_at": credits_data.get("subscription_expires_at"),
            "trial_ends_at": credits_data.get("trial_ends_at")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# =====================================================================
# POST ENDPOINTS - PAYMENTS
# =====================================================================

@router.post("/create-payment-intent")
async def create_payment_intent(request: CreatePaymentIntentRequest):
    """Create hosted checkout/payment session using configured provider"""
    try:
        billing = get_billing_client()
        provider = billing.payment_provider

        # Convert credits to dollar amount for hosted checkout.
        amount_usd = float(request.amount_credits)

        if provider == PaymentProvider.FLUTTERWAVE:
            checkout = billing.create_flutterwave_checkout(
                user_id=request.user_id,
                email=request.email,
                amount=amount_usd,
                tx_ref=f"credits_{request.user_id}_{request.amount_credits}",
                description=f"Purchase {request.amount_credits} credits",
                redirect_url=f"{APP_URL}/dashboard.html",
            )
            return {
                "success": True,
                "provider": "flutterwave",
                "checkout_url": checkout["checkout_url"],
                "tx_ref": checkout["tx_ref"],
                "amount_usd": amount_usd,
            }

        if provider == PaymentProvider.LEMONSQUEEZY:
            # For credit top-ups, use Starter variant as the credit pack product
            variant_id = LSQ_VARIANT_STARTER
            if not variant_id:
                raise HTTPException(status_code=500, detail="LSQ_VARIANT_STARTER not configured")
            tx_ref = f"credits_{request.user_id}_{request.amount_credits}"
            checkout = billing.create_lemonsqueezy_checkout(
                user_id=request.user_id,
                email=request.email,
                variant_id=variant_id,
                tx_ref=tx_ref,
                redirect_url=f"{APP_URL}/dashboard.html",
            )
            return {
                "success": True,
                "provider": "lemonsqueezy",
                "checkout_url": checkout["checkout_url"],
                "tx_ref": tx_ref,
            }
        
        # Ensure Stripe customer exists
        stripe_customer_id = billing.get_stripe_customer_id(request.user_id)
        if not stripe_customer_id:
            stripe_customer_id = billing.create_stripe_customer(
                request.user_id,
                request.email
            )
        
        # Convert credits to cents (1 credit = $1)
        amount_cents = request.amount_credits * 100
        
        # Create payment intent
        intent_data = billing.create_payment_intent(
            request.user_id,
            int(amount_cents),
            f"Purchase {request.amount_credits} credits"
        )
        
        return {
            "success": True,
            "provider": "stripe",
            "client_secret": intent_data["client_secret"],
            "payment_intent_id": intent_data["payment_intent_id"],
            "amount_usd": intent_data["amount_usd"]
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/admin/grant-credits")
async def admin_grant_credits(request: AdminGrantCreditsRequest):
    """Grant bonus/test credits to a specific user using a server-side admin key."""
    if not BILLING_ADMIN_KEY:
        raise HTTPException(status_code=503, detail="BILLING_ADMIN_KEY is not configured")
    if request.admin_key != BILLING_ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    if request.amount_credits <= 0:
        raise HTTPException(status_code=400, detail="amount_credits must be positive")
    if CONTROL_ROOM_TEST_USER_ID and request.user_id != CONTROL_ROOM_TEST_USER_ID:
        raise HTTPException(status_code=403, detail="Credit grants are restricted to the configured control-room test user")

    billing = get_billing_client()
    success = billing.add_credits(
        request.user_id,
        Decimal(str(request.amount_credits)),
        reason=request.reason or "admin_test_grant",
        transaction_type=TransactionType.BONUS,
    )
    if not success:
        raise HTTPException(status_code=500, detail="Failed to grant credits")

    credits = billing.get_user_credits(request.user_id)
    return {
        "success": True,
        "user_id": request.user_id,
        "balance_credits": credits.get("balance_credits"),
        "subscription_tier": credits.get("subscription_tier"),
    }

@router.get("/admin/control-room-config")
async def control_room_config(user_id: str):
    """Return whether the current user is allowed to run test credit grants from the control room."""
    allowed = bool(CONTROL_ROOM_TEST_USER_ID) and user_id == CONTROL_ROOM_TEST_USER_ID
    return {
        "allowed": allowed,
        "default_grant_credits": float(Decimal(CONTROL_ROOM_DEFAULT_GRANT_CREDITS)),
    }

@router.post("/confirm-payment")
async def confirm_payment(request: PaymentConfirmRequest):
    """Confirm payment and add credits to user account"""
    try:
        billing = get_billing_client()
        
        # We'll confirm and add the full amount as credits
        # (In real system, map amount to credits dynamically)
        credits_to_add = Decimal("10.00")  # Assuming $10 purchase = 10 credits
        
        success = billing.confirm_payment(
            request.user_id,
            request.payment_intent_id,
            credits_to_add
        )
        
        if not success:
            raise HTTPException(status_code=400, detail="Payment could not be confirmed")
        
        credits = billing.get_user_credits(request.user_id)
        return {
            "success": True,
            "message": "Payment confirmed and credits added",
            "new_balance": credits.get("balance_credits")
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# =====================================================================
# POST ENDPOINTS - SUBSCRIPTIONS
# =====================================================================

@router.post("/subscribe")
async def create_subscription(request: SubscribeRequest):
    """Create or upgrade subscription"""
    try:
        billing = get_billing_client()
        provider = billing.payment_provider
        
        # Validate tier
        try:
            tier = SubscriptionTier[request.tier.upper()]
        except KeyError:
            raise HTTPException(status_code=400, detail=f"Invalid tier: {request.tier}")

        if provider == PaymentProvider.FLUTTERWAVE:
            tier_amounts = {
                SubscriptionTier.STARTER: 9.0,
                SubscriptionTier.PRO: 29.0,
            }
            if tier not in tier_amounts:
                raise HTTPException(status_code=400, detail="Tier not enabled for Flutterwave checkout")

            checkout = billing.create_flutterwave_checkout(
                user_id=request.user_id,
                email=f"{request.user_id}@placeholder.local",
                amount=tier_amounts[tier],
                tx_ref=f"sub_{tier.value}_{request.user_id}",
                description=f"{tier.value.title()} monthly plan",
                redirect_url=f"{APP_URL}/dashboard.html",
            )
            return {
                "success": True,
                "provider": "flutterwave",
                "status": "pending_checkout",
                "tier": tier.value,
                "checkout_url": checkout["checkout_url"],
                "tx_ref": checkout["tx_ref"],
            }

        if provider == PaymentProvider.LEMONSQUEEZY:
            tier_variants = {
                SubscriptionTier.STARTER: LSQ_VARIANT_STARTER,
                SubscriptionTier.PRO: LSQ_VARIANT_PRO,
            }
            variant_id = tier_variants.get(tier, "")
            if not variant_id:
                raise HTTPException(status_code=400, detail=f"LSQ variant not configured for tier: {tier.value}")

            tx_ref = f"sub_{tier.value}_{request.user_id}"
            checkout = billing.create_lemonsqueezy_checkout(
                user_id=request.user_id,
                email=f"{request.user_id}@placeholder.local",
                variant_id=variant_id,
                tx_ref=tx_ref,
                redirect_url=f"{APP_URL}/dashboard.html",
            )
            return {
                "success": True,
                "provider": "lemonsqueezy",
                "status": "pending_checkout",
                "tier": tier.value,
                "checkout_url": checkout["checkout_url"],
                "tx_ref": tx_ref,
            }
        
        # Ensure Stripe customer exists
        stripe_customer_id = billing.get_stripe_customer_id(request.user_id)
        if not stripe_customer_id:
            raise HTTPException(status_code=400, detail="User must create payment method first")
        
        # Create subscription
        subscription_data = billing.create_subscription(request.user_id, tier)
        
        return {
            "success": True,
            "provider": "stripe",
            "subscription_id": subscription_data["subscription_id"],
            "status": subscription_data["status"],
            "tier": subscription_data["tier"]
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/cancel-subscription/{user_id}")
async def cancel_subscription(user_id: str):
    """Cancel user's active subscription"""
    try:
        billing = get_billing_client()
        success = billing.cancel_subscription(user_id)
        
        if not success:
            raise HTTPException(status_code=400, detail="Could not cancel subscription")
        
        return {
            "success": True,
            "message": "Subscription cancelled. Account reverted to free tier."
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# =====================================================================
# WEBHOOK - STRIPE EVENTS
# =====================================================================

@router.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events"""
    try:
        payload = await request.body()
        sig_header = request.headers.get("stripe-signature")
        
        # Verify webhook signature
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError as e:
        raise HTTPException(status_code=400, detail="Invalid signature")
    
    # Handle specific events
    billing = get_billing_client()
    
    if event["type"] == "payment_intent.succeeded":
        payment_intent = event["data"]["object"]
        user_id = payment_intent.get("metadata", {}).get("user_id")
        
        if user_id:
            # Credits already added in confirm_payment endpoint
            print(f"[Billing] Payment succeeded for user {user_id}")
    
    elif event["type"] == "customer.subscription.updated":
        subscription = event["data"]["object"]
        print(f"[Billing] Subscription updated: {subscription.id}")
    
    elif event["type"] == "customer.subscription.deleted":
        subscription = event["data"]["object"]
        print(f"[Billing] Subscription cancelled: {subscription.id}")
    
    return {"success": True}


@router.post("/webhook/flutterwave")
async def flutterwave_webhook(request: Request):
    """Handle Flutterwave webhook events for successful payments."""
    payload = await request.body()
    provided_hash = request.headers.get("verif-hash", "")

    if not FLW_WEBHOOK_HASH or provided_hash != FLW_WEBHOOK_HASH:
        raise HTTPException(status_code=401, detail="Invalid Flutterwave webhook signature")

    event = json.loads(payload.decode("utf-8"))
    if event.get("event") != "charge.completed":
        return {"success": True, "ignored": True}

    data = event.get("data", {})
    if data.get("status") != "successful":
        return {"success": True, "ignored": True}

    meta = data.get("meta", {}) or {}
    user_id = meta.get("user_id")
    amount = data.get("amount")

    if not user_id or amount is None:
        raise HTTPException(status_code=400, detail="Missing user_id or amount in webhook payload")

    billing = get_billing_client()
    credits = Decimal(str(amount))
    billing.add_credits(user_id, credits, reason="flutterwave_purchase", payment_intent_id=data.get("id"))

    return {"success": True, "user_id": user_id, "credits_added": float(credits)}


@router.post("/webhook/lemonsqueezy")
async def lemonsqueezy_webhook(request: Request):
    """Handle Lemon Squeezy webhook events (order_created / subscription_payment_success)."""
    payload = await request.body()

    # Verify HMAC-SHA256 signature
    provided_sig = request.headers.get("x-signature", "")
    if LSQ_WEBHOOK_SECRET:
        import hmac
        expected_sig = hmac.new(
            LSQ_WEBHOOK_SECRET.encode(), payload, "sha256"
        ).hexdigest()
        if not hmac.compare_digest(provided_sig, expected_sig):
            raise HTTPException(status_code=401, detail="Invalid Lemon Squeezy signature")

    event_name = request.headers.get("x-event-name", "")
    if event_name not in ("order_created", "subscription_payment_success"):
        return {"success": True, "ignored": True}

    data = json.loads(payload.decode("utf-8"))
    meta_custom = data.get("meta", {}).get("custom_data", {})
    user_id = meta_custom.get("user_id")

    order_data = data.get("data", {}).get("attributes", {})
    # Amount is in cents (USD)
    total_cents = order_data.get("total", 0)
    amount_usd = Decimal(str(total_cents)) / Decimal("100")

    if not user_id or amount_usd <= 0:
        raise HTTPException(status_code=400, detail="Missing user_id or amount in webhook")

    billing = get_billing_client()
    # 1 USD = 1 credit
    billing.add_credits(user_id, amount_usd, reason="lemonsqueezy_purchase",
                        payment_intent_id=str(order_data.get("order_number", "")))

    return {"success": True, "user_id": user_id, "credits_added": float(amount_usd)}

# =====================================================================
# REFERRAL ENDPOINTS
# =====================================================================

@router.get("/referral-link/{user_id}")
async def get_referral_link(user_id: str):
    """Get referral link for user"""
    try:
        billing = get_billing_client()
        referral_link = billing.get_referral_link(user_id)
        return {"referral_link": referral_link}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/referral-signup")
async def record_referral_signup(referred_user_email: str, referrer_user_id: str):
    """Record when a referred user signs up"""
    try:
        billing = get_billing_client()
        success = billing.record_referral(referrer_user_id, referred_user_email)
        
        if not success:
            raise HTTPException(status_code=400, detail="Could not record referral")
        
        return {"success": True, "message": "Referral recorded"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# =====================================================================
# UTILITY ENDPOINTS
# =====================================================================

@router.post("/verify-customer/{user_id}")
async def verify_customer(user_id: str):
    """Verify and create Stripe customer if needed"""
    try:
        billing = get_billing_client()
        stripe_customer_id = billing.get_stripe_customer_id(user_id)
        
        return {
            "user_id": user_id,
            "has_stripe_customer": stripe_customer_id is not None,
            "stripe_customer_id": stripe_customer_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
