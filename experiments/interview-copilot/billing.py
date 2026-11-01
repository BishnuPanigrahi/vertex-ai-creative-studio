# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Stripe Checkout subscriptions for the Pro plan."""

import logging
import os

import stripe
from fastapi import HTTPException

import db

logger = logging.getLogger(__name__)

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_PRICE_ID = os.environ.get("STRIPE_PRICE_ID", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
APP_URL = os.environ.get("APP_URL", "http://localhost:8080").rstrip("/")
# Lets you switch plans without Stripe while developing. Never enable in production.
ALLOW_DEV_UPGRADE = os.environ.get("ALLOW_DEV_UPGRADE", "0") == "1"

stripe.api_key = STRIPE_SECRET_KEY


def enabled() -> bool:
    """Whether Stripe is configured."""
    return bool(STRIPE_SECRET_KEY and STRIPE_PRICE_ID)


def _require_enabled() -> None:
    if not enabled():
        raise HTTPException(
            status_code=503,
            detail="Payments aren't configured yet. Set STRIPE_SECRET_KEY and STRIPE_PRICE_ID.",
        )


def checkout_url(user_id: int, email: str, customer_id: str | None) -> str:
    """Create a subscription Checkout session and return its URL."""
    _require_enabled()
    params = {
        "mode": "subscription",
        "line_items": [{"price": STRIPE_PRICE_ID, "quantity": 1}],
        "client_reference_id": str(user_id),
        "success_url": f"{APP_URL}/app.html?upgraded=1",
        "cancel_url": f"{APP_URL}/app.html",
    }
    if customer_id:
        params["customer"] = customer_id
    else:
        params["customer_email"] = email
    return stripe.checkout.Session.create(**params).url


def portal_url(customer_id: str | None) -> str:
    """Create a billing portal session for managing or cancelling a subscription."""
    _require_enabled()
    if not customer_id:
        raise HTTPException(
            status_code=400,
            detail="No subscription found for this account.",
        )
    return stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=f"{APP_URL}/app.html",
    ).url


def handle_webhook(payload: bytes, signature: str) -> None:
    """Apply plan changes from verified Stripe webhook events."""
    _require_enabled()
    try:
        event = stripe.Webhook.construct_event(
            payload,
            signature,
            STRIPE_WEBHOOK_SECRET,
        )
    except (ValueError, stripe.SignatureVerificationError) as e:
        raise HTTPException(status_code=400, detail="Invalid webhook signature.") from e
    obj = event["data"]["object"]
    with db.connect() as conn:
        if event["type"] == "checkout.session.completed" and obj.get(
            "client_reference_id",
        ):
            conn.execute(
                "UPDATE users SET plan = 'pro', stripe_customer_id = ? WHERE id = ?",
                (obj.get("customer"), int(obj["client_reference_id"])),
            )
        elif event["type"] == "customer.subscription.deleted":
            conn.execute(
                "UPDATE users SET plan = 'free' WHERE stripe_customer_id = ?",
                (obj.get("customer"),),
            )
        elif event["type"] == "customer.subscription.updated":
            plan = "pro" if obj.get("status") in ("active", "trialing") else "free"
            conn.execute(
                "UPDATE users SET plan = ? WHERE stripe_customer_id = ?",
                (plan, obj.get("customer")),
            )
    logger.info("Processed Stripe event %s", event["type"])
