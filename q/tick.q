/ A cut-down tickerplant. Same shape as kx's kdb+tick (tick.q + u.q), small
/ enough to read in one go.

/   q q/tick.q -p 5010 [-log logs/tp]

/ Where it differs from kdb+tick:
/  * timestamps come from the feed rather than .z.p, because we're replaying
/    history and the exchange/capture time is the one that matters
/  * the day rolls when data for a later date turns up (or the feed calls
/    .u.endofday), not at wall-clock midnight
/  * updates are published as soon as they arrive, no batching timer
/  * the feed sends whole tables rather than lists of columns. A bit slower
/    but every message carries its column names, so it's easy to validate
/  * with no -log nothing goes to disk. The FX backfill runs like that since
/    the downloaded files are already the recovery path

\l q/schema.q

if[not system"p"; system"p 5010"];

.u.t:tables`.
.u.w:.u.t!(count .u.t)#()      / per table, a list of (handle;syms) subscriptions
.u.d:0Nd                        / date currently open, null before the first update
.u.i:0                          / number of messages in today's log
.u.L:`                          / today's log file, null when logging is off
.u.l:0                          / handle to today's log

.u.opts:.Q.opt .z.x
.u.logdir:$[`log in key .u.opts; hsym `$first .u.opts`log; `]


/ --- subscriptions, as in u.q ---

.u.sel:{[x;s] $[s~`; x; select from x where sym in s]}

.u.pub:{[t;x] {[t;x;w] if[count x:.u.sel[x;w 1]; (neg first w)(`upd;t;x)]}[t;x] each .u.w t}

.u.del:{[t;h] .u.w[t]_:.u.w[t;;0]?h}

.z.pc:{[h] .u.del[;h] each .u.t}

/ t is a table name (` for all), s a list of syms (` for all).
/ Returns (name;empty table) so the subscriber gets the schema in the same call
.u.sub:{[t;s]
  if[t~`; :.u.sub[;s] each .u.t];
  if[not t in .u.t; 'string t];
  .u.del[t;.z.w];
  .u.w[t],:enlist(.z.w;s);
  (t;@[0#value t;`sym;`g#])}


/ --- log file ---

/ Open the log for date d, creating it if it isn't there. If the TP is
/ restarted mid-day it counts what's already in the file and appends to it.
.u.ld:{[d]
  if[null .u.logdir; :0];
  .u.L:` sv .u.logdir,`$"tp",string d;
  if[not type key .u.L; .u.L set ()];
  .u.i:-11!(-2;.u.L);
  / -11!(-2;f) gives (valid messages;valid bytes) instead of a count if the tail is bad
  if[0<=type .u.i; -2 "corrupt log ",string[.u.L],", valid up to byte ",string last .u.i; exit 1];
  hopen .u.L}


/ --- end of day ---

.u.startday:{[d] .u.d:d; .u.l:.u.ld d}

/ Tell every subscriber the day is over (they write to disk), close the log.
/ The feed calls this itself after the last day of a replay.
.u.endofday:{[]
  if[null .u.d; :()];
  (neg distinct raze value .u.w[;;0])@\:(`.u.end;.u.d);
  if[.u.l; hclose .u.l];
  .u.l:0; .u.i:0; .u.L:`; .u.d:0Nd;
  }


/ --- updates from the feed ---

/ column name -> type char, e.g. `time`sym`bid!"psf"
.u.types:{exec c!t from meta x}

.u.upd:{[t;x]
  if[not t in .u.t; '"unknown table ",string t];
  if[98h<>type x; '"expected an unkeyed table"];
  if[not count x; :()];
  / check the columns and types before anything reaches the log, since one
  / bad message in there breaks every replay of it afterwards
  if[not .u.types[x]~.u.types value t; '"schema mismatch on ",string t];
  d:"d"$first x`time;
  if[d<>"d"$last x`time; '"batch crosses midnight"];
  if[d<.u.d; '"got ",string[d]," but ",string[.u.d]," is already open"];
  if[d>.u.d; .u.endofday[]; .u.startday d];
  / log before publishing: if we fall over in between, the log has it and
  / a restarted RDB will pick it up
  if[.u.l; .u.l enlist(`upd;t;x); .u.i+:1];
  .u.pub[t;x];
  }
