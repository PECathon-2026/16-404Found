# FX3 Notes (Hidden)

## Planted Defect
- `word_freq` in `textstats/stats.py` uses `text.lower().split(" ")`.
- Splitting explicitly on `" "` does not handle multiple spaces, tabs, or newlines, leaving empty strings and multi-word tokens.
- Baseline is red on exactly two tests: `test_multiple_spaces` and `test_newlines`.
- Fix direction:
  Use `text.lower().split()` without arguments or regex `re.split(r'\s+', ...)`.
