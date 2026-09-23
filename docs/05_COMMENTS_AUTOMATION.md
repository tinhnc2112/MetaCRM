# Comments & Automation

## Comments
First-class channel interaction:
- list comments
- reply
- link customer
- assign
- tag
- create/open conversation where supported
- create order

## Automation MVP
Rule based, not AI autonomous.

Triggers:
MESSAGE_RECEIVED
COMMENT_RECEIVED

Conditions:
KEYWORD
PAGE
TAG
CUSTOMER_STATUS

Actions:
SEND_MESSAGE
ADD_TAG
ASSIGN_STAFF
CREATE_ORDER_DRAFT

Rules require priority, cooldown, idempotency, audit and loop prevention.
