import httpx

from infrai_http import InfraiClient, InfraiError
from receipt_sender import PaymentEvent, SendingDomain, decide, notify_payment, onboard_domain


def test_high_risk_payment_is_held_and_auditable():
    event = PaymentEvent(event_id="pay-42", customer_email="lee@example.com", amount_cents=2599, risk_score=85)
    decision = decide(event)
    assert decision.action == "manual_review"
    assert "pay-42" in decision.text
    assert "25.99" in decision.text


def test_domain_zone_precedes_records_and_email_review():
    calls = []

    def reply(request):
        calls.append(request)
        if request.url.path == "/v1/dns/domain/add":
            data = {"zone_id": "zone-7"}
        elif request.url.path == "/v1/email/domain/verify":
            data = {"verification": {"status": "verified"}}
        else:
            assert request.method == "PUT"
            assert '"zone_id":"zone-7"' in request.content.decode()
            data = {}
        return httpx.Response(200, json={"ok": True, "data": data, "error": None, "metadata": {}})

    client = InfraiClient(key="test-key", transport=httpx.MockTransport(reply))
    result = onboard_domain(client, SendingDomain(
        domain="example.com", spf="v=spf1 include:mail.example.com -all",
        dkim_name="mail._domainkey.example.com", dkim_content="v=DKIM1; p=abc",
        dmarc="v=DMARC1; p=quarantine",
    ))
    assert result["status"] == "verified"
    assert [call.url.path for call in calls] == [
        "/v1/dns/domain/add", *["/v1/dns/record/upsert"] * 3, "/v1/email/domain/verify"
    ]
    assert all("Idempotency-Key" in call.headers for call in calls)


def test_payment_notification_uses_stable_key():
    calls = []

    def reply(request):
        calls.append(request)
        return httpx.Response(200, json={"ok": True, "data": {"message_id": "msg-7"}, "error": None, "metadata": {}})

    client = InfraiClient(key="test-key", transport=httpx.MockTransport(reply))
    event = PaymentEvent(event_id="pay-42", customer_email="lee@example.com", amount_cents=2599, risk_score=12)
    assert notify_payment(client, event)["message_id"] == "msg-7"
    assert notify_payment(client, event)["action"] == "receipt"
    assert calls[0].headers["Idempotency-Key"] == calls[1].headers["Idempotency-Key"]


def test_envelope_rejection_is_preserved_on_http_400():
    def reply(request):
        return httpx.Response(400, json={"ok": False, "data": None, "error": {"code": "INVALID_ARGUMENT"}, "metadata": {}})

    client = InfraiClient(key="test-key", transport=httpx.MockTransport(reply))
    try:
        client.request("POST", "/v1/email/send", payload={"to": "lee@example.com"})
        assert False, "Expected the rejection"
    except InfraiError as error:
        assert error.status == 400
        assert error.code == "INVALID_ARGUMENT"
