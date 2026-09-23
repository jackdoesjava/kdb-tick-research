"""SPY study, Nasdaq book on 2021-01-28, regular hours only.

1. Markouts: what a passive fill was worth marked to the mid at later
   horizons, by order size.
2. Queue imbalance at the touch vs the direction of the next mid move.
3. Order flow imbalance vs the mid move in the same and the next bucket.

It's one day on one venue, and a very unusual day (the GameStop squeeze),
so the point is to show the method end to end rather than to claim a
general result. Everything is fitted on the morning and checked on the
afternoon, and confidence intervals resample 5-minute blocks.

Writes results/spy_study.md and results/spy_*.png.
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
DAY = "2021.01.28"
OPEN, CLOSE = pd.Timestamp("2021-01-28 14:30"), pd.Timestamp("2021-01-28 21:00")
SPLIT = pd.Timestamp("2021-01-28 17:45")      # halfway through the session
HORIZONS = ["0D00:00:00", "0D00:00:00.1", "0D00:00:01", "0D00:00:10", "0D00:01:00"]
HORIZON_LABELS = ["0", "100ms", "1s", "10s", "60s"]
OUT = ROOT / "results"


def block(times):
    return pd.to_datetime(times).dt.floor("5min")


def markouts(hdb):
    m = hdb(f".spy.markouts[{DAY};{' '.join(HORIZONS)}]").pd()
    # skip the last minute so the 60s markout never runs past the close
    m = m[(m.time >= OPEN) & (m.time < CLOSE - pd.Timedelta("1min"))].copy()
    # size is an integer, so (99, 100] is exactly one round lot
    m["bucket"] = pd.cut(m["size"], [0, 99, 100, 500, np.inf], labels=["<100", "100", "101-500", ">500"])
    m["blk"] = block(m.time)
    rows = []
    for name, g in [("all", m)] + list(m.groupby("bucket", observed=True)):
        row = {"size": name, "orders": len(g)}
        for col, lab in [("hs", "half-spread")] + [(f"mk{i}", h) for i, h in enumerate(HORIZON_LABELS)]:
            b = g.groupby("blk")[col].agg(["sum", "count"]).to_numpy()
            est, draws = stats.bootstrap(b, stats.mean)
            lo, hi = stats.interval(draws)
            row[lab] = f"{est:.2f} [{lo:.2f}, {hi:.2f}]"
            row[f"_{lab}"] = (est, lo, hi)
        rows.append(row)
    t = pd.DataFrame(rows)

    fig, ax = plt.subplots(figsize=(5.5, 3.6))
    x = np.arange(len(HORIZON_LABELS))
    for j, (_, r) in enumerate(t.iterrows()):
        est, lo, hi = np.array([r[f"_{h}"] for h in HORIZON_LABELS]).T
        # small sideways shift so the error bars don't sit on top of each other
        ax.errorbar(x + 0.06 * (j - 2), est, yerr=[est - lo, hi - est], marker="o", ms=3,
                    capsize=2, label=r["size"])
    ax.set_xticks(x, HORIZON_LABELS)
    ax.set_xlabel("time after trade")
    ax.set_ylabel("passive side's markout (bp)")
    ax.legend(title="trade size", fontsize=8)
    ax.axhline(0, color="grey", lw=0.5)
    fig.tight_layout()
    fig.savefig(OUT / "spy_markouts.png", dpi=130)
    return t[[c for c in t.columns if not c.startswith("_")]]


def queue_imbalance(hdb):
    c = hdb(f".spy.qimb[{DAY};0D14:30;0D21:00]").pd().reset_index()
    c["half"] = np.where(c.blk < SPLIT, "morning", "afternoon")
    mids = (np.arange(10) + 0.5) / 5 - 1
    rows, curves = [], {}
    for half, g in c.groupby("half"):
        p = []
        for b in range(10):
            s = g[g.bkt == b]
            est, draws = stats.bootstrap(s[["up", "n"]].to_numpy(), stats.mean, n=1000)
            lo, hi = stats.interval(draws)
            p.append((est, lo, hi))
        curves[half] = np.array(p)

    # out of sample: predict "up" in the afternoon when the morning's
    # probability for that bucket is above a half, and count how often it's right
    a = c[c.half == "afternoon"]
    pred_up = curves["morning"][:, 0] > 0.5
    right = np.where(pred_up[a.bkt], a.up, a.n - a.up)
    blocks = np.c_[pd.Series(right).groupby(a.blk.to_numpy()).sum(), a.groupby("blk").n.sum()]
    est, draws = stats.bootstrap(blocks, stats.mean)
    lo, hi = stats.interval(draws)
    rows.append({"afternoon top-of-book updates": int(a.n.sum()), "mid moves": int(a.moves.sum()),
                 "direction called right": f"{est:.3f} [{lo:.3f}, {hi:.3f}]"})

    fig, ax = plt.subplots(figsize=(5, 3.6))
    for half, p in curves.items():
        ax.errorbar(mids, p[:, 0], yerr=[p[:, 0] - p[:, 1], p[:, 2] - p[:, 0]], marker="o", ms=3, capsize=2, label=half)
    ax.axhline(0.5, color="grey", lw=0.5)
    ax.set_xlabel("queue imbalance (bid - ask) / (bid + ask)")
    ax.set_ylabel("P(next mid move is up)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "spy_queue_imbalance.png", dpi=130)
    return pd.DataFrame(rows)


def ofi(hdb):
    rows = []
    for w in ["0D00:00:01", "0D00:00:10"]:
        b = hdb(f".spy.ofi[{DAY};0D14:30;0D21:00;{w}]").pd().reset_index().dropna()
        b["blk"] = block(b.t)
        for target in ["dm", "nextdm"]:
            am, pm = b[b.t < SPLIT], b[b.t >= SPLIT]
            slope, icpt = np.polyfit(am.ofi, am[target], 1)
            ins_r2 = np.corrcoef(am.ofi, am[target])[0, 1] ** 2

            # out-of-sample R^2 on the afternoon with the morning's line held fixed
            def sums(g):
                x, y = g.ofi.to_numpy(), g[target].to_numpy()
                return [len(x), x.sum(), y.sum(), (x * x).sum(), (x * y).sum(), (y * y).sum()]
            blocks = np.array([sums(g) for _, g in pm.groupby("blk")])

            def oos_r2(t, a=icpt, b_=slope):
                n, sx, sy, sxx, sxy, syy = t
                sse = syy - 2 * a * sy - 2 * b_ * sxy + n * a * a + 2 * a * b_ * sx + b_ * b_ * sxx
                return 1 - sse / (syy - sy * sy / n)

            est, draws = stats.bootstrap(blocks, oos_r2)
            lo, hi = stats.interval(draws)
            rows.append({"bucket": w.split(":")[-1] + "s", "target": "same bucket" if target == "dm" else "next bucket",
                         "morning R2": ins_r2, "afternoon R2 (morning fit)": f"{est:.3f} [{lo:.3f}, {hi:.3f}]",
                         "buckets": len(b)})
    return pd.DataFrame(rows)


def main():
    OUT.mkdir(exist_ok=True)
    with QProc("q/hdb.q", HDB, ["-db", "db"]):
        hdb = connect(HDB)
        mk = markouts(hdb)
        qi = queue_imbalance(hdb)
        of = ofi(hdb)
    text = ["## Passive-side markouts (bp, 95% CI)", "", mk.to_markdown(index=False), "",
            "## Queue imbalance, one-tick spreads", "", qi.to_markdown(index=False), "",
            "## Order flow imbalance", "", of.to_markdown(index=False, floatfmt=".3f"), ""]
    (OUT / "spy_study.md").write_text("\n".join(text))
    print("\n".join(text))


if __name__ == "__main__":
    main()
