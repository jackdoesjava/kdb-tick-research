/ Real-time database. Subscribes to the tickerplant, holds the current day
/ in memory and writes it to the HDB when the TP says the day is over.

/   q q/rdb.q -p 5011 -tp 5010 -hdb db

/ On startup it replays whatever the TP has already logged today, so it can
/ be killed and restarted mid-day without losing anything.

.rdb.opts:.Q.opt .z.x
.rdb.hdb:hsym `$first .rdb.opts`hdb
.rdb.saved:0Nd       / last date written, the load scripts wait on this

upd:insert

/ Called by the TP at end of day. .Q.dpft enumerates sym against db/sym,
/ sorts on sym (a stable sort, so rows stay in time order within each sym),
/ puts p# on sym and writes each table splayed into db/<date>/.
.u.end:{[d]
  t:tables`.;
  .Q.dpft[.rdb.hdb;d;`sym;] each t;
  / empty the tables for the next day, keeping g# on sym
  {x set @[0#value x;`sym;`g#]} each t;
  .Q.gc[];
  .rdb.saved:d;
  -1 string[.z.p]," saved ",string d;
  }

/ Subscribe and ask for the log position in the same synchronous call.
/ Everything logged before the call gets replayed from the file, everything
/ after arrives as a normal update, so nothing is missed or counted twice.
.rdb.start:{[r]
  (.[;();:;].) each r 0;          / r 0 is a list of (table name;empty table)
  n:r[1;0]; f:r[1;1];
  if[not null f; -1 "replaying ",string[n]," messages from ",string f; -11!(n;f)];
  }

.rdb.tp:hopen "J"$first .rdb.opts`tp
.rdb.start .rdb.tp "(.u.sub[`;`];`.u `i`L)"
