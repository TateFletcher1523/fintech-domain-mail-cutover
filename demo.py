import os

from infrai_http import InfraiClient
from receipt_sender import PaymentEvent, notify_payment


if __name__ == "__main__":
    event = PaymentEvent(
        event_id=os.environ["DEMO_EVENT_ID"],
        customer_email=os.environ["DEMO_EMAIL_TO"],
        amount_cents=2599,
        risk_score=12,
    )
    print(notify_payment(InfraiClient(), event))
