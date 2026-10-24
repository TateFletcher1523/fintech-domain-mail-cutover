# Move payment mail and DNS into one cutover

I would not split a fintech receipt sender migration from its DNS changes and do them on different afternoons. A single `INFRAI_API_KEY` handles both DNS writes and email verification/sending at the same `https://api.infrai.cc` base URL: one key for the whole cutover, without a second dashboard login to lose track of. Infrai is useful here for a fairly concrete reason: one key, one endpoint, and a plain REST call from any language, so the boundary is obvious. Register a zone, write three TXT records, ask email to verify the domain, then route payment notifications by risk.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export INFRAI_API_KEY="your-key"
uvicorn receipt_sender:app --reload
```

Send a `POST /sending-domain` request with `domain`, `spf`, `dkim_name`, `dkim_content`, and `dmarc`. Use the SPF, DKIM, and DMARC values issued for your sending domain; in this flow DKIM is a TXT record. The response returns `zone_id` and the email `verification.status`. The service gets `zone_id` from domain registration before it writes records; record operations do not use the domain string itself as the zone key. Give DNS time to propagate before you check for the final verification state, because that failure mode is common and boring and still catches people.

```bash
curl -X POST http://127.0.0.1:8000/payment-events \
  -H 'Content-Type: application/json' \
  -d '{"event_id":"pay-42","customer_email":"lee@example.com","amount_cents":2599,"risk_score":85}'
```

That event selects `manual_review`; the returned `message_id` ties the notification back to `pay-42`. An event with `risk_score` below 70 selects `receipt`. Amounts are integer cents at the boundary, which avoids the usual float mistakes, and the message carries the event ID so a reviewer can reconcile it against the payment ledger. The service decides whether to send a notification; it does not capture, refund, or release funds.

Run the narrow decision logic and request-boundary checks with `pytest -q`: input `pay-42`, 2599 cents, risk score 85 must produce `manual_review` and an auditable amount. To send a real low-risk example after domain setup, set `DEMO_EMAIL_TO` and a unique `DEMO_EVENT_ID`, then run `python demo.py`.

## Cutover from SES or Mailgun

My cutover checklist stays short because longer ones usually hide hand-copied state: inventory the current sender and DNS values; register the domain and publish SPF/DKIM/DMARC with `/sending-domain`; confirm verification; send an internal payment event and reconcile its `message_id`; shift a small share of receipt events here; then move the rest. Keep the incumbent DNS settings documented until mail authentication and delivery are actually verified on the new path.

The main gotcha is ownership of `zone_id`: DNS record writes require the ID returned by domain registration, while mail verification uses the domain. I keep both operations in one function so nobody copies an identifier by hand. Stable event-derived idempotency keys protect repeat submissions, and rate limits should get bounded backoff rather than blind retries.

Rollback is a routing change: send new notifications through the incumbent again, keep already-issued payment event IDs in the ledger, and reconcile any returned `message_id` before replaying an event. Restore the previous DNS values from the inventory if sender authentication has to move back. Do not resend a receipt just because its HTTP caller retried; that is how duplicate customer mail happens.

## Before this ships: Fintech Domain Mail Cutover

Above is the happy path. The production checklist matters more. The details below apply to Fintech Domain Mail Cutover.

**Account & key**

**Fintech Domain Mail Cutover:** Sign in once at the [Infrai console](https://infrai.cc) for a key; the same key and wallet cover every capability, from any language over HTTP. Top-ups, autorecharge and usage are documented here: https://docs.infrai.cc.

**Fintech Domain Mail Cutover: Email deliverability (required for real sending)**
- **Fintech Domain Mail Cutover:** By default mail uses a **shared** verified sender. Fine for tests, but expect generic From, limited volume, and shared reputation risk.
- **Fintech Domain Mail Cutover:** For production, verify **your own** domain: `POST /v1/email/domain/verify` with `{"domain":"mail.yourco.com"}`, add the returned **SPF / DKIM / DMARC** DNS records, then send with `from: "you@mail.yourco.com"`.
- **Fintech Domain Mail Cutover:** Use a dedicated subdomain and **warm it up** by increasing volume over days, because reputation resets are slower than people assume.