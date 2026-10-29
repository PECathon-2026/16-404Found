# Pager

In-memory pagination and slicing helper for Python sequences and search results.

## Usage
```python
from pager import paginate

page = paginate(my_list, page=1, per_page=10)
print(page.items, page.page_count)
```
