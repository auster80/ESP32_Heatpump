"""Drive a heat pump from Tibber spot prices.

Tibber's own heat pump integrations (NIBE S-series, CTC, ...) run cloud-to-cloud
through the manufacturer's API. This package does the local equivalent: it reads
the price curve from the Tibber GraphQL API, plans a per-slot heat pump mode
(block / reduce / normal / boost / force) and pushes that mode to the heat pump
through SG Ready contacts, Modbus TCP, MQTT or plain HTTP calls.
"""

__version__ = "0.1.0"
