"""FX study: how fast do crosses catch up with their legs, and is the gap
worth trading?

Runs .fx.day from q/analytics.q over every FX date in the HDB for each
triangle, then pools the per-day sums in Python. Confidence intervals come
from resampling whole days. The first half of 2025 is used to pick the
taker settings and the second half only to report them.

Writes results/fx_*.md and results/fx_closure.png.
"""

import sys
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ktr import stats  # noqa: E402
from ktr.qproc import QProc, connect  # noqa: E402

HDB = 5014
TRIANGLES = {
    "EURJPY": ["EURJPY", "EURUSD", "USDJPY", "mul"],
    "EURGBP": ["EURGBP", "EURUSD", "GBPUSD", "div"],
}
SPLIT = pd.Timestamp("2025-07-01")
GRID_POINTS = 360_000   # 07:00-17:00 every 100ms
OUT = ROOT / "results"


def collect(hdb, tri):
    import pykx as kx
    fx_dates = hdb("exec date from (select n:count i by date from quote where sym=`EURUSD) where n>0").py()
    cl, gp, tk = [], [], []
    for d in fx_dates:
        r = hdb(".fx.day", kx.DateAtom(d), kx.SymbolVector(tri))
        # indexing a q dictionary by key doesn't work in pykx's unlicensed mode
        r = dict(zip(r.keys().py(), r.values()))
        # skip holidays (Christmas, New Year) where hardly anyone quotes:
        # need at least half the grid points to have fresh quotes on all three
        if r["gap"].pd()["n"].iloc[0] < 0.5 * GRID_POINTS:
            print("  skipping", d)
            continue
        for frames, key in [(cl, "closure"), (gp, "gap"), (tk, "taker")]:
            f = r[key].pd()
            f["date"] = pd.Timestamp(d)
            frames.append(f)
    return pd.concat(cl), pd.concat(gp), pd.concat(tk)


def closure_table(cl, step_s):
    """Slope of the cross's and the synthetic's move on the gap, per horizon."""
    rows = []
    for k, g in cl.groupby("k"):
        g = g[g.n > 0]
        cxx = stats.centred(g.n, g.sx, g.sx, g.sxx)
        cxc = stats.centred(g.n, g.sx, g.syc, g.sxyc)
        cxs = stats.centred(g.n, g.sx, g.sys, g.sxys)
        blocks = np.c_[cxc, cxs, cxx]

        def stat(t):
            bc, bs = t[0] / t[2], t[1] / t[2]
            # cross share, legs share, and rho = autocorrelation of the gap at this lag
            return np.array([-bc, bs, 1 + bc - bs])

        est, draws = stats.bootstrap(blocks, stat)
        lo, hi = stats.interval(draws)
        rows.append({"horizon_s": k * step_s, "days": len(g),
                     "cross": est[0], "cross_lo": lo[0], "cross_hi": hi[0],
                     "legs": est[1], "legs_lo": lo[1], "legs_hi": hi[1],
                     "rho": est[2], "rho_lo": lo[2], "rho_hi": hi[2]})
    return pd.DataFrame(rows)


def gap_summary(gp):
    t = gp.sum(numeric_only=True)
    mean = t.sgap / t.n
    return {"mean gap (bp)": mean,
            "sd gap (bp)": np.sqrt(t.sgap2 / t.n - mean ** 2),
            "mean |gap| (bp)": t.sabs / t.n,
            "mean cross half-spread (bp)": t.shs / t.n,
            "time |gap| > half-spread": t.nwide / t.n,
            "lag-1 autocorr, cross": t.rcc / t.rc2,
            "lag-1 autocorr, synthetic": t.rss / t.rs2}


def taker_tables(tk):
    """Pick threshold and holding period on H1 for each latency, report H2."""
    tk = tk.assign(half=np.where(tk.date < SPLIT, "H1", "H2"))
    g = tk.groupby(["half", "th", "l", "h"])[["n", "s", "s2"]].sum().reset_index()
    g["mean_bp"] = g.s / g.n.where(g.n > 0)
    h1 = g[(g.half == "H1") & (g.n >= 100)]
    best = h1.loc[h1.groupby("l").mean_bp.idxmax(), ["th", "l", "h"]]

    rows = []
    for _, b in best.iterrows():
        sel = tk[(tk.half == "H2") & (tk.th == b.th) & (tk.l == b.l) & (tk.h == b.h)]
        est, draws = stats.bootstrap(sel[["s", "n"]].to_numpy(), stats.mean)
        lo, hi = stats.interval(draws)
        rows.append({"latency_ms": int(b.l * 100), "threshold_bp": b.th, "hold_s": b.h / 10,
                     "H2 trades": int(sel.n.sum()), "H2 mean P&L (bp)": est, "lo": lo, "hi": hi})
    return pd.DataFrame(rows), g


def plot(tables):
    fig, axes = plt.subplots(1, len(tables), figsize=(5 * len(tables), 3.6), sharey=True)
    for ax, (name, t) in zip(np.atleast_1d(axes), tables.items()):
        x = t.horizon_s
        for col, label in [("cross", "closed by the cross"), ("legs", "closed by the legs")]:
            ax.plot(x, t[col], marker="o", ms=3, label=label)
            ax.fill_between(x, t[col + "_lo"], t[col + "_hi"], alpha=0.25)
        ax.plot(x, 1 - t.rho, "k--", lw=1, label="total (1 - autocorrelation)")
        ax.set_xscale("log")
        ax.set_xlabel("horizon (s)")
        ax.set_title(name)
        ax.axhline(0, color="grey", lw=0.5)
    np.atleast_1d(axes)[0].set_ylabel("fraction of gap closed")
    np.atleast_1d(axes)[0].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "fx_closure.png", dpi=130)


def md(df, floatfmt=".3f"):
    return df.to_markdown(index=False, floatfmt=floatfmt)


def main():
    OUT.mkdir(exist_ok=True)
    closure, report = {}, []
    with QProc("q/hdb.q", HDB, ["-db", "db"]):
        hdb = connect(HDB)
        step_s = hdb(".fx.cfg`step").py().total_seconds()
        for name, tri in TRIANGLES.items():
            print("running", name, flush=True)
            cl, gp, tk = collect(hdb, tri)
            closure[name] = closure_table(cl, step_s)
            h1 = closure_table(cl[cl.date < SPLIT], step_s)
            h2 = closure_table(cl[cl.date >= SPLIT], step_s)
            best, grid = taker_tables(tk)
            grid.to_csv(OUT / f"fx_taker_grid_{name}.csv", index=False)

            hl = stats.half_life(closure[name].horizon_s, closure[name].rho)
            report += [f"## {name}", "",
                       f"{cl.date.nunique()} days, grid every {step_s:g}s, 07:00-17:00 UTC.", "",
                       md(pd.DataFrame([gap_summary(gp)])), "",
                       f"Half-life of the gap: {hl:.2f}s", "",
                       "Full year:", "", md(closure[name]), "",
                       "Jan-Jun only:", "", md(h1[["horizon_s", "cross", "legs", "rho"]]), "",
                       "Jul-Dec only:", "", md(h2[["horizon_s", "cross", "legs", "rho"]]), "",
                       "Taker test, settings picked on Jan-Jun, reported on Jul-Dec:", "",
                       md(best), ""]
    plot(closure)
    (OUT / "fx_study.md").write_text("\n".join(report))
    print("\n".join(report))


if __name__ == "__main__":
    main()
