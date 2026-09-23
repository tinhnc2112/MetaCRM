# Payment

Facebook sales:
- method COD
- UNPAID / COLLECTED / FAILED

COD is not considered collected merely because an order exists.
Collection comes from shipment/provider confirmation or explicit admin confirmation.

POS may use a local payment method but shares PaymentService and Payment model.
No external payment gateway is required.
