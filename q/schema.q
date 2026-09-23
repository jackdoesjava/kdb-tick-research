/ Table schemas, loaded by the tickerplant. Subscribers get them from the TP
/ when they subscribe, so this is the only place they're defined.

/ Equities and FX both go into quote so the same analytics run on either.
/ Only the equity feed has trades. Sizes are floats because Dukascopy gives
/ FX volume in millions (e.g. 1.35); SPY share counts are exact in a float.
/ bdepth/adepth are total size over the top 5 levels, null for FX.

quote:([] time:`timestamp$(); sym:`symbol$(); bid:`float$(); ask:`float$(); bsize:`float$(); asize:`float$(); bdepth:`float$(); adepth:`float$())

/ side is the aggressor: `B bought at the offer, `S sold at the bid,
/ ` for hidden/midpoint prints where it isn't known
trade:([] time:`timestamp$(); sym:`symbol$(); price:`float$(); size:`long$(); side:`symbol$())
