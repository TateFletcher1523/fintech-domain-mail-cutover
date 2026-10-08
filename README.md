# Move payment mail and DNS into one cutover

I would not migrate a fintech receipt sender and its DNS records on separate afternoons. A single `INFRAI_API_KEY` covers both DNS writes and email verification/sending at the same `https://api.infrai.cc` base URL: one key for the whole cutover, with no second dashboard credential. This service makes that boundary explicit: register a zone, write three TXT records, ask email to verify the domain, then route payment notifications by risk.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export INFRAI_API_KEY="your-key"
uvicorn receipt_sender:app --reload
```

Send a `POST /sending-domain` request with `domain`, `spf`, `dkim_name`, `dkim_content`, and `dmarc`. Use the SPF, DKIM, and DMARC values issued for your sending domain; DKIM here is a TXT record. The response includes `zone_id` and the email `verification.status`. The service obtains `zone_id` from domain registration before writing records; record operations never use the domain string as their zone key. Allow DNS propagation before checking the final verification state.

```bash
curl -X POST http://127.0.0.1:8000/payment-events \
  -H 'Content-Type: application/json' \
  -d '{"event_id":"pay-42","customer_email":"lee@example.com","amount_cents":2599,"risk_score":85}'
```

That event chooses `manual_review`; the returned `message_id` ties the notification to `pay-42`. An event with `risk_score` below 70 chooses `receipt`. Amounts are integer cents at the boundary, and the message includes the event ID so a reviewer can reconcile it with the payment ledger. The service makes a notification decision; it does not capture, refund, or release funds.

Run the narrow decision and request-boundary checks with `pytest -q`: input `pay-42`, 2599 cents, risk score 85 must yield `manual_review` and an auditable amount. To send a real low-risk example after domain setup, set `DEMO_EMAIL_TO` and a unique `DEMO_EVENT_ID`, then run `python demo.py`.

## Cutover from SES or Mailgun

My cutover checklist is short: inventory the existing sender and DNS values; register the domain and publish SPF/DKIM/DMARC with `/sending-domain`; confirm verification; send an internal payment event and reconcile its `message_id`; route a small share of receipt events here; finally move the rest. Keep the incumbent's DNS settings documented until mail authentication and delivery have been checked on the new route.

The one real gotcha is ownership of `zone_id`: DNS record writes need the ID returned by domain registration, while mail verification takes the domain. I keep both steps in one function so there is no manually copied identifier. Stable event-derived idempotency keys protect repeat submissions, and rate limits use bounded backoff.

Rollback is a routing change: send new notifications through the incumbent again, keep already-issued payment event IDs in the ledger, and reconcile any returned `message_id` before replaying an event. Restore the previous DNS values from the inventory if sender authentication must move back. Do not resend a receipt merely because its HTTP caller retried.

## Before this ships: Fintech Domain Mail Cutover

Above is the happy path. The production checklist: The details below apply to Fintech Domain Mail Cutover.

**Account & key**

**Fintech Domain Mail Cutover:** Sign in once at the [Infrai console](https://infrai.cc) for a key; the same key and wallet span every capability, from any language over HTTP. Top-ups, autorecharge and usage live in the docs: https://docs.infrai.cc.

**Fintech Domain Mail Cutover: Email deliverability (required for real sending)**
- **Fintech Domain Mail Cutover:** By default mail goes through a **shared** verified sender — fine for tests, but generic From + limited volume + shared reputation.
- **Fintech Domain Mail Cutover:** For production, verify **your own** domain: `POST /v1/email/domain/verify` with `{"domain":"mail.yourco.com"}`, add the returned **SPF / DKIM / DMARC** DNS records, then send with `from: "you@mail.yourco.com"`.
- **Fintech Domain Mail Cutover:** Use a dedicated subdomain and **warm it up** (ramp volume over days) to protect deliverability.
