"""BTC/USD market data feed for TradeBot.

Provides historical bars and real-time streaming built on top of spec
``01-alpaca-client``. All market data is delivered to internal consumers through
a single, SDK-independent normalization format (:class:`Bar`, :class:`Quote`),
so no downstream component depends on Alpaca's specific data shapes.
"""
