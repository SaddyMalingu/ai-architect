"""
Billing and Credits Management System
Handles Stripe integration, credit tracking, and render costs
"""

import os
import json
import stripe
import requests
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Dict, Any
from decimal import Decimal
import uuid

# Configure Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PUBLIC_KEY = os.getenv("STRIPE_PUBLIC_KEY", "")
PAYMENT_PROVIDER = os.getenv("PAYMENT_PROVIDER", "stripe").lower()

FLW_SECRET_KEY = os.getenv("FLW_SECRET_KEY", "")
FLW_PUBLIC_KEY = os.getenv("FLW_PUBLIC_KEY", "")
FLW_WEBHOOK_HASH = os.getenv("FLW_WEBHOOK_HASH", "")
FLW_REDIRECT_URL = os.getenv("FLW_REDIRECT_URL", "http://localhost:8080/dashboard.html")
FLW_CURRENCY = os.getenv("FLW_CURRENCY", "USD")

# Lemon Squeezy config
LSQ_API_KEY = os.getenv("LSQ_API_KEY", "")
LSQ_STORE_ID = os.getenv("LSQ_STORE_ID", "")
LSQ_WEBHOOK_SECRET = os.getenv("LSQ_WEBHOOK_SECRET", "")
LSQ_VARIANT_STARTER = os.getenv("LSQ_VARIANT_STARTER", "")
LSQ_VARIANT_PRO = os.getenv("LSQ_VARIANT_PRO", "")

# Pricing Constants
RENDER_COST_CREDITS = Decimal("0.50")  # $0.50 per render
FREE_TIER_INITIAL_CREDITS = Decimal(os.getenv("FREE_TIER_INITIAL_CREDITS", "5"))
FREE_TIER_MONTHLY_CREDITS = int(os.getenv("FREE_TIER_MONTHLY_CREDITS", "5"))
STARTER_TIER_MONTHLY_CREDITS = 50
PRO_TIER_MONTHLY_CREDITS = 500
REFERRAL_COMMISSION = Decimal("5.00")  # $5 per referral

class TransactionType(Enum):
    CHARGE = "charge"  # Deduction from render API call
    PURCHASE = "purchase"  # Credit purchase/payment
    REFUND = "refund"  # Credit refund
    BONUS = "bonus"  # Promotional credits
    SUBSCRIPTION = "subscription"  # Subscription payment

class SubscriptionTier(Enum):
    FREE = "free"
    STARTER = "starter"  # $9/month
    PRO = "pro"  # $29/month
    ENTERPRISE = "enterprise"  # Custom


class PaymentProvider(Enum):
    STRIPE = "stripe"
    FLUTTERWAVE = "flutterwave"
    LEMONSQUEEZY = "lemonsqueezy"

class BillingClient:
    """Handles all billing operations"""
    
    def __init__(self, supabase_client=None):
        """Initialize billing client with optional Supabase connection"""
        self.supabase = supabase_client
        self.stripe_key = stripe.api_key
        provider_name = os.getenv("PAYMENT_PROVIDER", PAYMENT_PROVIDER).lower()
        if provider_name == "flutterwave":
            self.payment_provider = PaymentProvider.FLUTTERWAVE
        elif provider_name == "lemonsqueezy":
            self.payment_provider = PaymentProvider.LEMONSQUEEZY
        else:
            self.payment_provider = PaymentProvider.STRIPE
    
    # =====================================================================
    # STRIPE CUSTOMER MANAGEMENT
    # =====================================================================
    
    def create_stripe_customer(self, user_id: str, email: str, name: str = "") -> str:
        """Create Stripe customer and link to user"""
        try:
            customer = stripe.Customer.create(
                email=email,
                name=name or email,
                metadata={"user_id": user_id}
            )
            
            # Save to database
            if self.supabase:
                self.supabase.table("stripe_customers").insert({
                    "user_id": user_id,
                    "stripe_customer_id": customer.id,
                    "created_at": datetime.utcnow().isoformat()
                }).execute()
            
            return customer.id
        except stripe.error.StripeError as e:
            raise Exception(f"Failed to create Stripe customer: {str(e)}")
    
    def get_stripe_customer_id(self, user_id: str) -> Optional[str]:
        """Get Stripe customer ID for user"""
        if self.supabase:
            response = self.supabase.table("stripe_customers").select(
                "stripe_customer_id"
            ).eq("user_id", user_id).single().execute()
            
            if response.data:
                return response.data["stripe_customer_id"]
        return None
    
    # =====================================================================
    # CREDIT OPERATIONS
    # =====================================================================
    
    def get_user_credits(self, user_id: str) -> Dict[str, Any]:
        """Get user's current credit balance and subscription info"""
        if not self.supabase:
            return {"balance_credits": 0, "subscription_tier": "free"}
        
        response = self.supabase.table("user_credits").select(
            "*"
        ).eq("user_id", user_id).single().execute()
        
        if response.data:
            return response.data
        
        # Create new user credits entry if doesn't exist
        return self._create_user_credits(user_id)
    
    def _create_user_credits(self, user_id: str) -> Dict[str, Any]:
        """Initialize credits for new user (free tier)"""
        if not self.supabase:
            return {"balance_credits": float(FREE_TIER_INITIAL_CREDITS), "subscription_tier": "free"}
        
        data = {
            "user_id": user_id,
            "balance_credits": float(FREE_TIER_INITIAL_CREDITS),
            "subscription_tier": "free",
            "trial_started_at": datetime.utcnow().isoformat(),
            "trial_ends_at": (datetime.utcnow() + timedelta(days=7)).isoformat()
        }
        
        response = self.supabase.table("user_credits").insert(data).execute()
        return response.data[0] if response.data else data
    
    def deduct_credits(self, user_id: str, amount: Decimal, reason: str, 
                      render_request_id: Optional[str] = None) -> bool:
        """Deduct credits from user account (for API usage)"""
        if not self.supabase:
            return True
        
        try:
            # Get current balance
            credits = self.get_user_credits(user_id)
            current_balance = Decimal(str(credits.get("balance_credits", 0)))
            
            if current_balance < amount:
                raise ValueError(f"Insufficient credits. Have {current_balance}, need {amount}")
            
            new_balance = current_balance - amount
            
            # Record transaction
            self.supabase.table("credit_transactions").insert({
                "user_id": user_id,
                "amount": float(-amount),  # Negative for deduction
                "transaction_type": TransactionType.CHARGE.value,
                "reason": reason,
                "render_request_id": render_request_id,
                "balance_before": float(current_balance),
                "balance_after": float(new_balance),
                "created_at": datetime.utcnow().isoformat()
            }).execute()
            
            # Update balance
            self.supabase.table("user_credits").update({
                "balance_credits": float(new_balance),
                "updated_at": datetime.utcnow().isoformat()
            }).eq("user_id", user_id).execute()
            
            return True
        except Exception as e:
            print(f"Error deducting credits: {str(e)}")
            return False
    
    def add_credits(self, user_id: str, amount: Decimal, reason: str = "manual_add",
                   payment_intent_id: Optional[str] = None,
                   transaction_type: TransactionType = TransactionType.PURCHASE) -> bool:
        """Add credits to user account (from payment)"""
        if not self.supabase:
            return True
        
        try:
            credits = self.get_user_credits(user_id)
            current_balance = Decimal(str(credits.get("balance_credits", 0)))
            new_balance = current_balance + amount
            
            # Record transaction
            self.supabase.table("credit_transactions").insert({
                "user_id": user_id,
                "amount": float(amount),  # Positive for addition
                "transaction_type": transaction_type.value,
                "reason": reason,
                "stripe_payment_intent_id": payment_intent_id,
                "balance_before": float(current_balance),
                "balance_after": float(new_balance),
                "created_at": datetime.utcnow().isoformat()
            }).execute()
            
            # Update balance
            self.supabase.table("user_credits").update({
                "balance_credits": float(new_balance),
                "lifetime_purchased": float(Decimal(str(credits.get("lifetime_purchased", 0))) + amount),
                "updated_at": datetime.utcnow().isoformat()
            }).eq("user_id", user_id).execute()
            
            return True
        except Exception as e:
            print(f"Error adding credits: {str(e)}")
            return False
    
    # =====================================================================
    # PAYMENT PROCESSING
    # =====================================================================

    def create_flutterwave_checkout(
        self,
        user_id: str,
        email: str,
        amount: float,
        tx_ref: str,
        description: str,
        redirect_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create Flutterwave hosted checkout for countries unsupported by Stripe."""
        if not FLW_SECRET_KEY:
            raise ValueError("FLW_SECRET_KEY is missing. Set Flutterwave credentials in .env")

        payload = {
            "tx_ref": tx_ref,
            "amount": str(amount),
            "currency": FLW_CURRENCY,
            "redirect_url": redirect_url or FLW_REDIRECT_URL,
            "payment_options": "card,mobilemoney,ussd",
            "customer": {
                "email": email,
                "name": email,
            },
            "customizations": {
                "title": "AI Architect",
                "description": description,
                "logo": "",
            },
            "meta": {
                "user_id": user_id,
            },
        }

        headers = {
            "Authorization": f"Bearer {FLW_SECRET_KEY}",
            "Content-Type": "application/json",
        }
        response = requests.post(
            "https://api.flutterwave.com/v3/payments",
            headers=headers,
            json=payload,
            timeout=20,
        )
        data = response.json()
        if response.status_code >= 400 or data.get("status") != "success":
            raise Exception(f"Flutterwave checkout init failed: {data}")

        return {
            "checkout_url": data["data"]["link"],
            "tx_ref": tx_ref,
            "amount": amount,
            "provider": PaymentProvider.FLUTTERWAVE.value,
        }

    def create_lemonsqueezy_checkout(
        self,
        user_id: str,
        email: str,
        variant_id: str,
        tx_ref: str,
        redirect_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create Lemon Squeezy hosted checkout (global, handles taxes/VAT automatically)."""
        if not LSQ_API_KEY:
            raise ValueError("LSQ_API_KEY is missing. Set Lemon Squeezy credentials in .env")
        if not LSQ_STORE_ID:
            raise ValueError("LSQ_STORE_ID is missing. Set it in .env")

        payload = {
            "data": {
                "type": "checkouts",
                "attributes": {
                    "checkout_data": {
                        "email": email,
                        "custom": {"user_id": user_id, "tx_ref": tx_ref},
                    },
                    "product_options": {
                        "redirect_url": redirect_url or f"http://localhost:8080/dashboard.html",
                    },
                },
                "relationships": {
                    "store": {"data": {"type": "stores", "id": str(LSQ_STORE_ID)}},
                    "variant": {"data": {"type": "variants", "id": str(variant_id)}},
                },
            }
        }

        headers = {
            "Authorization": f"Bearer {LSQ_API_KEY}",
            "Content-Type": "application/vnd.api+json",
            "Accept": "application/vnd.api+json",
        }
        response = requests.post(
            "https://api.lemonsqueezy.com/v1/checkouts",
            headers=headers,
            json=payload,
            timeout=20,
        )
        data = response.json()
        if response.status_code >= 400:
            raise Exception(f"Lemon Squeezy checkout failed: {data}")

        checkout_url = data["data"]["attributes"]["url"]
        return {
            "checkout_url": checkout_url,
            "tx_ref": tx_ref,
            "variant_id": variant_id,
            "provider": PaymentProvider.LEMONSQUEEZY.value,
        }

    def create_payment_intent(self, user_id: str, amount_cents: int, 
                            description: str = "") -> Dict[str, Any]:
        """Create Stripe Payment Intent for one-time purchase"""
        try:
            stripe_customer_id = self.get_stripe_customer_id(user_id)
            if not stripe_customer_id:
                raise ValueError("No Stripe customer found for user")
            
            intent = stripe.PaymentIntent.create(
                amount=amount_cents,
                currency="usd",
                customer=stripe_customer_id,
                description=description or f"AI Architect Credits - User {user_id}",
                metadata={
                    "user_id": user_id,
                    "type": "credit_purchase"
                }
            )
            
            return {
                "client_secret": intent.client_secret,
                "payment_intent_id": intent.id,
                "amount_usd": amount_cents / 100
            }
        except stripe.error.StripeError as e:
            raise Exception(f"Failed to create payment intent: {str(e)}")
    
    def confirm_payment(self, user_id: str, payment_intent_id: str, 
                       credits_to_add: Decimal) -> bool:
        """Confirm payment and add credits to user"""
        try:
            # Verify payment succeeded
            intent = stripe.PaymentIntent.retrieve(payment_intent_id)
            
            if intent.status != "succeeded":
                return False
            
            # Add credits
            return self.add_credits(
                user_id, 
                credits_to_add, 
                reason="payment_purchase",
                payment_intent_id=payment_intent_id
            )
        except stripe.error.StripeError as e:
            print(f"Error confirming payment: {str(e)}")
            return False
    
    # =====================================================================
    # SUBSCRIPTION MANAGEMENT
    # =====================================================================
    
    def create_subscription(self, user_id: str, tier: SubscriptionTier) -> Dict[str, Any]:
        """Create monthly subscription"""
        try:
            stripe_customer_id = self.get_stripe_customer_id(user_id)
            if not stripe_customer_id:
                raise ValueError("No Stripe customer found")
            
            # Get or create price IDs from environment
            price_id = os.getenv(f"STRIPE_PRICE_{tier.value.upper()}", "")
            if not price_id:
                raise ValueError(f"No price configured for tier {tier.value}")
            
            subscription = stripe.Subscription.create(
                customer=stripe_customer_id,
                items=[{"price": price_id}],
                metadata={"user_id": user_id, "tier": tier.value}
            )
            
            # Update user tier
            if self.supabase:
                self.supabase.table("user_credits").update({
                    "subscription_tier": tier.value,
                    "subscription_expires_at": None,  # Active subscription
                }).eq("user_id", user_id).execute()
            
            return {
                "subscription_id": subscription.id,
                "status": subscription.status,
                "tier": tier.value
            }
        except stripe.error.StripeError as e:
            raise Exception(f"Failed to create subscription: {str(e)}")
    
    def cancel_subscription(self, user_id: str) -> bool:
        """Cancel user's subscription"""
        try:
            if self.supabase:
                response = self.supabase.table("stripe_customers").select(
                    "stripe_subscription_id"
                ).eq("user_id", user_id).single().execute()
                
                if response.data and response.data.get("stripe_subscription_id"):
                    stripe.Subscription.delete(response.data["stripe_subscription_id"])
                    
                    # Revert to free tier
                    self.supabase.table("user_credits").update({
                        "subscription_tier": "free",
                        "subscription_expires_at": datetime.utcnow().isoformat()
                    }).eq("user_id", user_id).execute()
            
            return True
        except stripe.error.StripeError as e:
            print(f"Error canceling subscription: {str(e)}")
            return False
    
    # =====================================================================
    # REFERRAL SYSTEM
    # =====================================================================
    
    def record_referral(self, referrer_id: str, referred_email: str) -> bool:
        """Record a referral link usage"""
        if not self.supabase:
            return True
        
        try:
            # This would be called when referred user signs up
            # Find the referred user by email then record the relationship
            # For now, just create entry (would need email matching in real implementation)
            
            self.supabase.table("referrals").insert({
                "referrer_id": referrer_id,
                "referred_id": str(uuid.uuid4()),  # Placeholder - would get real ID after signup
                "status": "pending",
                "created_at": datetime.utcnow().isoformat()
            }).execute()
            
            return True
        except Exception as e:
            print(f"Error recording referral: {str(e)}")
            return False
    
    def complete_referral(self, referrer_id: str, referred_id: str) -> bool:
        """Mark referral as completed and award commission"""
        if not self.supabase:
            return True
        
        try:
            # Award commission
            self.add_credits(
                referrer_id,
                REFERRAL_COMMISSION,
                reason="referral_commission"
            )
            
            # Mark as completed
            self.supabase.table("referrals").update({
                "status": "completed",
                "completed_at": datetime.utcnow().isoformat()
            }).eq("referrer_id", referrer_id).eq("referred_id", referred_id).execute()
            
            return True
        except Exception as e:
            print(f"Error completing referral: {str(e)}")
            return False
    
    def get_referral_link(self, user_id: str) -> str:
        """Generate referral link for user"""
        # Format: https://aiarchitect.com?ref=<user_id>
        return f"https://aiarchitect.com?ref={user_id}"
    
    # =====================================================================
    # RENDER COST TRACKING
    # =====================================================================
    
    def record_render_cost(self, render_request_id: str, 
                          cost_credits: Decimal = RENDER_COST_CREDITS,
                          model_used: str = ""):
        """Record cost of a render operation"""
        if not self.supabase:
            return
        
        try:
            self.supabase.table("render_costs").insert({
                "render_request_id": render_request_id,
                "cost_credits": float(cost_credits),
                "model_used": model_used,
                "created_at": datetime.utcnow().isoformat()
            }).execute()
        except Exception as e:
            print(f"Error recording render cost: {str(e)}")
    
    # =====================================================================
    # PRICING INFORMATION
    # =====================================================================
    
    @staticmethod
    def get_pricing_tiers() -> Dict[str, Any]:
        """Get all available pricing tiers"""
        free_renders = int(Decimal(FREE_TIER_MONTHLY_CREDITS) / RENDER_COST_CREDITS) if RENDER_COST_CREDITS > 0 else FREE_TIER_MONTHLY_CREDITS
        return {
            "free": {
                "name": "Free",
                "price_monthly": 0,
                "credits_monthly": FREE_TIER_MONTHLY_CREDITS,
                "renders": free_renders,
                "features": ["Basic renders", "Limited history"],
                "stripe_price_id": os.getenv("STRIPE_PRICE_FREE", "")
            },
            "starter": {
                "name": "Starter",
                "price_monthly": 9,
                "credits_monthly": 50,
                "renders": 100,
                "features": ["50 renders/month", "Full history", "Basic support"],
                "stripe_price_id": os.getenv("STRIPE_PRICE_STARTER", "")
            },
            "pro": {
                "name": "Professional",
                "price_monthly": 29,
                "credits_monthly": 500,
                "renders": 1000,
                "features": ["500 renders/month", "Advanced features", "Priority support", "Batch API access"],
                "stripe_price_id": os.getenv("STRIPE_PRICE_PRO", "")
            },
            "enterprise": {
                "name": "Enterprise",
                "price_monthly": None,
                "credits_monthly": None,
                "renders": "Unlimited",
                "features": ["Custom limits", "Dedicated support", "Custom integration", "100+ renders/month"],
                "contact": True
            }
        }
    
    @staticmethod
    def get_pricing_summary() -> Dict[str, Any]:
        """Quick pricing summary for API"""
        return {
            "per_render": 0.50,
            "payment_provider": PAYMENT_PROVIDER,
            "tiers": BillingClient.get_pricing_tiers()
        }


# Singleton instance for use throughout app
_billing_client = None

def get_billing_client(supabase_client=None) -> BillingClient:
    """Get or create billing client singleton"""
    global _billing_client
    if _billing_client is None:
        _billing_client = BillingClient(supabase_client)
    return _billing_client
