import uuid


class MockPaymentGateway:
    """Stand-in for the Razorpay SDK.

    Swap the two methods below for real `razorpay.Client` calls
    (orders.create / utility.verify_payment_signature) once gateway
    credentials are available - the router code calling this doesn't need
    to change shape.
    """

    name = "razorpay"

    def create_order(self, amount_inr, currency: str) -> str:
        return f"order_mock_{uuid.uuid4().hex[:16]}"

    def verify_payment(self, order_id: str, payment_id: str, signature: str | None) -> bool:
        return bool(order_id and payment_id)


gateway = MockPaymentGateway()
