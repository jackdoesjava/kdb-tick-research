/ Sanity checks on the live quote stream. This is the layer that sits between
/ market data and a trading algo and switches the algo off for a symbol when
/ the data looks wrong.

/   q q/checks.q -p 5012 -tp 5010

/ Every quote is checked against per-symbol limits:
/   crossed  bid >= ask
/   badpx    bid or ask missing or not positive
/   wide     spread wider than maxspread (bps of mid)
/   jump     mid moved more than maxjump (bps) since the previous quote
/   gap      more than maxgap since the previous quote, i.e. the feed went quiet
/ The first four put the symbol on hold for .chk.cooldown. A gap is only
/ logged, because by the time we see it the feed has already come back.

/ All times are data time, not wall-clock, so a replay of history triggers
/ exactly what the live feed would have.

.chk.opts:.Q.opt .z.x

limits:([sym:`symbol$()] maxspread:`float$(); maxjump:`float$(); maxgap:`timespan$())
`limits upsert ([] sym:`SPY`EURUSD`USDJPY`EURJPY`GBPUSD`EURGBP;
  maxspread:5 3 4 6 4 6f;
  maxjump:20 20 20 20 20 20f;
  maxgap:6#0D00:01)
/ used for anything not in the table above
.chk.default:`maxspread`maxjump`maxgap!(10f;20f;0D00:01)
.chk.cooldown:0D00:00:05

alerts:([] time:`timestamp$(); sym:`symbol$(); rule:`symbol$(); val:`float$())
/ the symbol is not tradeable until `hold`
status:([sym:`symbol$()] time:`timestamp$(); hold:`timestamp$())
/ last quote seen per symbol, carried from one batch into the next
.chk.prev:([sym:`symbol$()] lt:`timestamp$(); lm:`float$())

upd:{[t;x]
  if[t<>`quote; :()];
  x:select time,sym,bid,ask,mid:0.5*bid+ask from x;
  / previous quote for the same symbol. prev gives null for the first row of
  / each symbol in the batch, so fill those from the carried state
  x:update pt:prev time, pm:prev mid by sym from x;
  x:update pt:lt^pt, pm:lm^pm from x lj .chk.prev;
  x:x lj limits;
  x:update maxspread:.chk.default[`maxspread]^maxspread, maxjump:.chk.default[`maxjump]^maxjump,
    maxgap:.chk.default[`maxgap]^maxgap from x;
  x:update spr:1e4*(ask-bid)%mid, jump:1e4*abs log mid%pm, gap:time-pt from x;

  / crossed needs both sides present: with a null ask, bid>=ask is true
  / (null is the smallest value), and a missing side is badpx's job
  a:(select time,sym,rule:`crossed,val:spr from x where (not null bid)&(not null ask)&bid>=ask),
    (select time,sym,rule:`badpx,val:bid from x where (null bid)|(null ask)|(bid<=0)|ask<=0),
    (select time,sym,rule:`wide,val:spr from x where spr>maxspread),
    (select time,sym,rule:`jump,val:jump from x where jump>maxjump),
    (select time,sym,rule:`gap,val:1e-9*`long$gap from x where gap>maxgap);
  `alerts insert `time xasc a;

  `status upsert select last time by sym from x;
  `status upsert select hold:max time+.chk.cooldown by sym from a where rule<>`gap;
  `.chk.prev upsert select lt:last time, lm:last mid by sym from x;
  }

/ what an algo would ask before quoting: is this symbol clear to trade?
tradeable:{select sym, ok:(null hold)|time>=hold from status}

/ Reset the carried state each day so the weekend doesn't count as a gap.
/ .u.end arrives after all of that day's data on the TP connection, so the
/ load scripts wait for .chk.ended before reading the alerts.
.chk.ended:0Nd
.u.end:{[d] delete from `.chk.prev; .chk.ended:d;}

.chk.tp:hopen "J"$first .chk.opts`tp
.chk.tp "(.u.sub[`quote;`])";
