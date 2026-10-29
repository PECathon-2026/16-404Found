# FX2 Notes (Hidden)

## Planted Defect
- In `pager/paginate.py`:
  `page_count = total // per_page`
  Integer division truncates any remainder when `total` is not an exact multiple of `per_page`.
- Fix direction:
  Use ceiling division: `math.ceil(total / per_page)` (or `(total + per_page - 1) // per_page`), while preserving `0` pages when `total == 0`.
