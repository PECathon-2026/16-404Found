"""Revision repo rules."""
# apply_tax is used in BOTH pricing.py AND invoice.py.
# Any change to tax logic must be reflected in both places.
# Use pytest. Never break the invoice module when fixing pricing.
