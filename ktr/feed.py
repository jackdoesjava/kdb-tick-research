"""Replay recorded market data into the tickerplant, standing in for a live
feed handler.

Data goes out in time windows (a minute by default), each window sending
quotes then trades, so the TP and its subscribers see the tables roughly
interleaved the way a live feed would deliver them rather than all quotes
for the day followed by all trades.

The calls are synchronous. A real feed would publish async and not wait, but
for a replay the round trip gives us flow control for free: we can never get
more than one window ahead of the tickerplant.
"""

import numpy as np
import pandas as pd

from .qproc import connect


class Feed:
    def __init__(self, port):
        self.q = connect(port)
        import pykx as kx
        self.kx = kx

    def publish(self, table, df):
        if len(df):
            # pykx turns a frame whose index isn't 0..n-1 into a keyed table,
            # which the TP rightly rejects, so slices need a fresh index
            self.q(".u.upd", self.kx.SymbolAtom(table), df.reset_index(drop=True))

    def replay_day(self, tables, window="1min"):
        """tables: {name: DataFrame} for a single date, each sorted on time.
        Returns the number of rows sent."""
        live = [df for df in tables.values() if len(df)]
        if not live:
            return 0
        start = min(df["time"].iloc[0] for df in live).floor(window)
        end = max(df["time"].iloc[-1] for df in live)
        edges = pd.date_range(start, end + pd.Timedelta(window), freq=window).to_numpy()
        cuts = {name: np.searchsorted(df["time"].to_numpy(), edges) for name, df in tables.items()}
        sent = 0
        for i in range(len(edges) - 1):
            for name, df in tables.items():
                a, b = cuts[name][i], cuts[name][i + 1]
                if b > a:
                    self.publish(name, df.iloc[a:b])
                    sent += b - a
        return sent

    def end_of_day(self):
        self.q(".u.endofday[]")

    def close(self):
        self.q.close()
