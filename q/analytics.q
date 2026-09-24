/ Research queries, run inside the HDB process (see hdb.q). Each works on a
/ single date and callers loop over dates. Most return sums or bucket counts
/ so raw ticks never cross to Python; .spy.markouts returns one row per
/ order because the size bucketing is done on the Python side.

/ One q gotcha that matters a lot here: null compares as smaller than any
/ number, so 0n<-5 is 1b. Anything that tests a threshold filters nulls first.


/ ============ FX: quoted cross vs the cross implied by its legs ============

/ A triangle is (cross;leg1;leg2;op): EURJPY = EURUSD*USDJPY is
/ `EURJPY`EURUSD`USDJPY`mul, EURGBP = EURUSD%GBPUSD is `EURGBP`EURUSD`GBPUSD`div.

/ Latest quote of all three pairs on a regular time grid, from s to e (time
/ of day, UTC) every step. aj gives the last quote at or before each grid
/ time, so nothing here can see the future. aj will also carry a quote
/ forward however old it is, so grid points where any of the three hasn't
/ updated for maxage are blanked: the feed was down, not the market quiet.
.fx.grid:{[d;tri;step;s;e;maxage]
  g:([] time:(d+s)+step*til `long$(e-s)%step);
  pair:{[d;x] select time,qt:time,bid,ask from quote where date=d, sym=x};
  g:aj[`time;g;`time`t0`cb`ca xcol pair[d;tri 0]];
  g:aj[`time;g;`time`t1`b1`a1 xcol pair[d;tri 1]];
  g:aj[`time;g;`time`t2`b2`a2 xcol pair[d;tri 2]];
  g:update cb:0n,ca:0n,b1:0n,a1:0n,b2:0n,a2:0n from g where maxage<time-t0&t1&t2;
  / synthetic cross mid from the leg mids
  g:$[`mul~tri 3;
    update sm:(0.5*b1+a1)*0.5*b2+a2 from g;
    update sm:(0.5*b1+a1)%0.5*b2+a2 from g];
  / gap: quoted cross mid over synthetic mid, in bps
  update cm:0.5*cb+ca, gap:1e4*log (0.5*cb+ca)%sm from g}

/ Sums for regressing the moves over the next k grid steps on the current
/ gap. yc is the cross's move, ys the synthetic's (both bps). If the cross
/ does all the catching up, the slope of yc on gap is -1 and ys is 0.
.fx.closure:{[g;k]
  t:select x:gap, yc:1e4*log ((neg k) xprev cm)%cm, ys:1e4*log ((neg k) xprev sm)%sm from g;
  t:select from t where not null x, not null yc, not null ys;
  exec n:count x, sx:sum x, sxx:sum x*x, syc:sum yc, sxyc:sum x*yc, sys:sum ys, sxys:sum x*ys from t}

/ The same regressions, but using the gap `lag` steps earlier as an
/ instrument for the gap now. Quote noise that reverses within that time
/ moves the gap now but can't be predicted from the earlier gap, so this
/ only measures how the lasting part of the gap closes. The slope is
/ sum(z*y)/sum(z*x) after centring, instead of sum(x*y)/sum(x*x).
.fx.closureiv:{[g;k;lag]
  t:select x:gap, z:lag xprev gap, yc:1e4*log ((neg k) xprev cm)%cm, ys:1e4*log ((neg k) xprev sm)%sm from g;
  t:select from t where not null x, not null z, not null yc, not null ys;
  exec n:count x, sx:sum x, sz:sum z, szx:sum z*x, syc:sum yc, szyc:sum z*yc, sys:sum ys, szys:sum z*ys from t}

/ Size of the gap, and how often it's bigger than the cross's half-spread.
/ Also sums for the lag-1 autocorrelation of one-step returns of the quoted
/ and synthetic mids: if one of them reverses more (quote noise bouncing
/ back), part of what looks like it "closing the gap" is just that.
.fx.gapstats:{[g]
  g:update rc:1e4*log cm%prev cm, rs:1e4*log sm%prev sm from g;
  g:update prc:prev rc, prs:prev rs from g;
  select n:count gap, sgap:sum gap, sgap2:sum gap*gap, sabs:sum abs gap,
    shs:sum 1e4*0.5*(ca-cb)%cm, nwide:sum (abs gap)>1e4*0.5*(ca-cb)%cm,
    rcc:sum rc*prc, rc2:sum rc*rc, rss:sum rs*prs, rs2:sum rs*rs
    from g where not null gap, not null prc, not null prs}

/ Taker test on the cross alone. When the cross is more than th bps cheap
/ against the synthetic, buy it at the ask l steps later (latency) and sell
/ at the bid h steps after that; the mirror image when it's rich. A signal
/ only counts where the gap first crosses the threshold, and not at all
/ while the previous trade is still open, so a gap flickering around th
/ doesn't turn into a pile of overlapping trades.
.fx.taker:{[g;th;l;h]
  t:update inb:(neg l) xprev cb, ina:(neg l) xprev ca, outb:(neg l+h) xprev cb, outa:(neg l+h) xprev ca from g;
  t:update buy:(not null gap)&gap<neg th, sell:(not null gap)&gap>th from t;
  t:update buy:buy>prev buy, sell:sell>prev sell from t;
  sig:where t[`buy]|t`sell;
  / no signals at all happens at the higher thresholds; the scan below would
  / hand back an untyped empty list, so return zeros straight away
  if[not count sig; :`n`s`s2!(0;0f;0f)];
  / walk through the signals keeping the last one taken; a new one is taken
  / once the previous trade (l+h steps) has closed
  i:distinct {[w;a;b] $[b>=a+w;b;a]}[l+h]\[neg l+h; sig];
  t:t i;
  p:?[t`buy; 1e4*log t[`outb]%t`ina; 1e4*log t[`inb]%t`outa];
  p:p where not null p;
  `n`s`s2!(count p;sum p;sum p*p)}

/ Study settings. Everything here was fixed before running the study on the
/ real data, except the taker thresholds: they started as 0.5-5bp, but one
/ day in March showed the EURJPY gap almost never gets past 2bp, so they
/ were moved down. That's a choice made on Jan-Jun data, which is the half
/ used for picking settings, so the Jul-Dec test is still clean.
.fx.cfg:`step`start`end`maxage`ivlag`ks`ths`lats`holds!(
  0D00:00:00.1;                   / 100ms grid, finer than any pair updates (0.3-0.9s on average)
  0D07:00; 0D17:00;               / London open to New York lunchtime, UTC
  0D00:01;                        / stale-quote cut-off, same as the gap rule in checks.q
  10;                             / instrument: the gap 10 steps (1s) earlier
  1 2 5 10 20 50 100 300 600;     / horizons in grid steps, 0.1s to 60s
  0.25 0.5 0.75 1 1.5f;           / taker thresholds, bps
  0 1 5 10;                       / latency: 0, 0.1, 0.5, 1s
  10 50 300)                      / holding period: 1, 5, 30s

/ Everything the FX study needs from one date, building the grid once
.fx.day:{[d;tri]
  c:.fx.cfg;
  g:.fx.grid[d;tri;c`step;c`start;c`end;c`maxage];
  cl:([] k:c`ks),'.fx.closure[g] each c`ks;
  iv:([] k:c`ks),'.fx.closureiv[g;;c`ivlag] each c`ks;
  p:([] th:c`ths) cross ([] l:c`lats) cross ([] h:c`holds);
  tk:p,'{[g;r] .fx.taker[g;r`th;r`l;r`h]}[g] each p;
  `closure`closureiv`gap`taker!(cl;iv;.fx.gapstats g;tk)}


/ ============ SPY: trades and the order book ============

/ Markouts from the passive side's point of view, which is the one a market
/ maker cares about: what the fill was worth, marked to the mid at each
/ horizon, in bps. Starts around the half-spread and falls as the price
/ moves the aggressor's way. hs is the effective half-spread, the fill price
/ against the last mid strictly before the trade. (The book update caused
/ by the trade carries the same timestamp, so aj at the trade time itself
/ would already include it; time-1 is one nanosecond earlier.)

/ ITCH prints one execution per resting order, so a single aggressive order
/ that sweeps several orders shows up as several fills with the same
/ timestamp. Those are put back together first, weighting price by size.

/ aj on `sym`time needs an attribute on sym in the right table or it gets
/ very slow (minutes instead of milliseconds on this day). A select of a
/ whole partition keeps the p# from disk, but one that filters on sym drops
/ it, so g# is set here rather than relied on.
.spy.markouts:{[d;hz]
  t:0!select price:size wavg price, sum size by time,sym,side from trade where date=d, side in `B`S;
  q:update `g#sym from select time,sym,mid:0.5*bid+ask from quote where date=d;
  m0:exec mid from aj[`sym`time;update time:time-1 from t;q];
  s:?[`B=t`side;1f;-1f];
  mk:{[t;q;h] exec mid from aj[`sym`time;update time:time+h from t;q]}[t;q] each hz;
  t:update hs:1e4*s*log price%m0 from t;
  t,'flip (`$"mk",/:string til count hz)!{[s;p;m] 1e4*s*log p%m}[s;t`price] each mk}

/ Queue imbalance at the touch against the direction of the next mid
/ change. One row per top-of-book update (depth-only updates would repeat
/ the same observation), counted in ten equal-width imbalance bins on
/ [-1,1] and 5-minute blocks. Only one-tick spreads, where the mid can't
/ move without one side's queue being used up or a new level appearing.
.spy.qimb:{[d;s;e]
  q:select time,bid,ask,bsize,asize from quote where date=d, sym=`SPY, time within (d+s;d+e);
  q:select from q where differ flip (bid;ask;bsize;asize);
  q:update mid:0.5*bid+ask, spr:ask-bid, imb:(bsize-asize)%bsize+asize from q;
  / runs of constant mid. m holds one mid per run in order and r counts from
  / 1, so m r is the next run's mid, and null after the last run. st marks
  / the first row of each run so mid moves can be counted without counting
  / a run twice when it spans two buckets
  q:update st:differ mid from q;
  q:update r:sums st from q;
  m:exec mid from q where st;
  q:update nm:m r from q;
  q:select from q where not null nm, spr within 0.005 0.015;
  select n:count i, up:sum nm>mid, moves:sum st by blk:0D00:05 xbar time, bkt:9&floor 5*imb+1 from q}

/ Order flow imbalance (Cont, Kukanov & Stoikov 2014). Each book update
/ contributes e = eb - ea, where eb is the change in bid-side demand and ea
/ the change in ask-side supply. Summed per bucket of width w, alongside the
/ mid move over that bucket and over the next one.
.spy.ofi:{[d;s;e;w]
  q:select time,bid,ask,bsize,asize from quote where date=d, sym=`SPY, time within (d+s;d+e);
  q:update pb:prev bid, pbs:prev bsize, pa:prev ask, pas:prev asize from q;
  q:1_q;   / first row has no previous state
  q:update eb:((bid>=pb)*bsize)-(bid<=pb)*pbs, ea:((ask<=pa)*asize)-(ask>=pa)*pas from q;
  b:select ofi:sum eb-ea, mid:last 0.5*bid+ask by t:w xbar time from q;
  b:update dm:1e4*log mid%prev mid from b;
  update nextdm:next dm from b}
