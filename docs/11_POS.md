# POS

Fast desktop POS for internal use.

Flow:
Search product/SKU -> cart -> quantity -> optional customer -> discount -> payment -> complete.

POS uses:
ProductService
InventoryService
OrderService
PaymentService

No separate PosOrder.

Walk-in sale may have customer_id null.
MVP receipt is on-screen/order number; printing is optional later.
