"""Non-classifier suggested replies by ticket category."""
_REPLIES = {
    "ACCOUNT": "We can help with your account access. Please do not share your password in this ticket.",
    "ORDER": "Our team can review your order details and available options.",
    "INVOICE": "Our team can check your invoice or receipt and help with a correction.",
    "CONTACT": "A support team member will review your message and explain how to get in touch.",
    "PAYMENT": "Our team can investigate the payment or charge. Please do not share full card details.",
    "FEEDBACK": "Thank you for your feedback. Our team will review it.",
    "REFUND": "Our team can review your return or refund options.",
    "DELIVERY": "Our team can check the delivery status and tracking information.",
    "SHIPPING": "Our team can explain shipping methods, destinations and costs.",
}


def suggest_customer_reply(category):
    return _REPLIES.get(category, _REPLIES["CONTACT"])
