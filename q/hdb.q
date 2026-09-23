/ Historical database with the research functions loaded.

/   q q/hdb.q -p 5014 -db db

/ analytics.q is loaded first because \l on a database directory also
/ changes into it, after which relative script paths would no longer work.

\l q/analytics.q
system "l ",first (.Q.opt .z.x)`db
