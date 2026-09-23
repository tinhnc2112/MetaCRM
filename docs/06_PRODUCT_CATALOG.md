# Product Catalog

Product:
id, name, description, image_url, active.

Variant:
product_id, name, sku, barcode(optional), weight_grams, selling_price, cost_price, active.

Example:
Bột hành
- 100g
- 200g

Rules:
- SKU unique.
- Money uses Decimal/Numeric.
- Historical orders snapshot product/variant/name/SKU/price/cost.
- Inactive variants cannot be sold.
- Cost changes affect future orders only.

No complex option matrix in MVP.
