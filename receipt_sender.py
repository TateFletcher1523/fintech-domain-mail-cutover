import hashlib
from decimal import Decimal
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from infrai_http import InfraiClient, InfraiError


class SendingDomain(BaseModel):
    domain: str
    spf: str
    dkim_name: str
    dkim_content: str
    dmarc: str


class PaymentEvent(BaseModel):
    event_id: str
    customer_email: str = Field(pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    amount_cents: int = Field(ge=1)
    risk_score: int = Field(ge=0, le=100)


class PaymentDecision(BaseModel):
    action: Literal["receipt", "manual_review"]
    subject: str
    text: str


def decide(event: PaymentEvent) -> PaymentDecision:
    amount = Decimal(event.amount_cents) / 100
    if event.risk_score >= 70:
        return PaymentDecision(
            action="manual_review",
            subject=f"Payment {event.event_id} needs review",
            text=f"Payment {event.event_id} for USD {amount:.2f} is held for manual review.",
        )
    return PaymentDecision(
        action="receipt",
        subject=f"Payment receipt {event.event_id}",
        text=f"Payment {event.event_id} for USD {amount:.2f} was received.",
    )


def operation_key(*parts: str) -> str:
    return hashlib.sha256(": ".join(parts).encode()).hexdigest()


def onboard_domain(client: InfraiClient, domain: SendingDomain) -> dict:
    zone = client.request(
        "POST", "/v1/dns/domain/add", payload={"domain": domain.domain},
        idempotency_key=operation_key("zone", domain.domain),
    )
    zone_id = zone["zone_id"]
    for name, content in (
        (domain.domain, domain.spf),
        (domain.dkim_name, domain.dkim_content),
        (f"_dmarc.{domain.domain}", domain.dmarc),
    ):
        client.request(
            "PUT", "/v1/dns/record/upsert",
            payload={"zone_id": zone_id, "record_type": "TXT", "name": name, "content": content},
            idempotency_key=operation_key("record", zone_id, name, content),
        )
    verified = client.request(
        "POST", "/v1/email/domain/verify", payload={"domain": domain.domain},
        idempotency_key=operation_key("verify", domain.domain),
    )
    return {"domain": domain.domain, "zone_id": zone_id, "status": verified["verification"]["status"]}


def notify_payment(client: InfraiClient, event: PaymentEvent) -> dict:
    decision = decide(event)
    sent = client.request(
        "POST", "/v1/email/send",
        payload={"to": event.customer_email, "subject": decision.subject, "body": decision.text},
        idempotency_key=operation_key("payment", event.event_id, decision.action),
    )
    return {"event_id": event.event_id, "action": decision.action, "message_id": sent["message_id"]}


app = FastAPI(title="Payment mail cutover")


def run_with_errors(call, value):
    try:
        return call(InfraiClient(), value)
    except InfraiError as error:
        raise HTTPException(
            status_code=error.status if 400 <= error.status < 500 else 502,
            detail={"code": error.code, "error": error.detail},
        ) from error


@app.post("/sending-domain")
def create_sending_domain(domain: SendingDomain) -> dict:
    return run_with_errors(onboard_domain, domain)


@app.post("/payment-events")
def create_payment_notification(event: PaymentEvent) -> dict:
    return run_with_errors(notify_payment, event)
