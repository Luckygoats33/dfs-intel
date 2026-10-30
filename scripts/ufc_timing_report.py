"""Writes the observed fight-end timing section (markdown) to stdout."""
from dfs_intel.ufc_timing import *
f=load(); f=f[f.event_date<="2026-10-25"]
def fmt(t):
    t=t.copy()
    for fl in FLAGS: t[fl]=[f"{int(s)}/{n} ({m:.2%})" for s,n,m in zip(t[fl+"_sum"],t.n_fights,t[fl+"_mean"])]
    return t[["n_fights"]+FLAGS].to_markdown()
o=rates(f).iloc[0]
print("\n## Fight-end timing — OBSERVED historical frequencies (not predictions)\n")
print(f"Source: `ufc_fights` (UFCStats data via GitHub mirror Greco1899/scrape_ufc_stats, kept as-is with Will's approval), events {f.event_date.min():%Y-%m-%d} to {f.event_date.max():%Y-%m-%d} (through UFC 333), {len(f)} fights. "
      "Finish = KO/TKO, Submission, or TKO-Doctor's Stoppage (DQ, Overturned, Could Not Continue excluded from numerators; all fights in denominators). "
      "Last-10s = finish at >= 4:50 of a 5:00 round. Code: `dfs_intel/ufc_timing.py`, `scripts/ufc_timing_report.py`.\n")
print("### Overall, with fair American odds implied by the observed rate (no vig; a historical base rate, not a price)\n")
print("| Event | Count / fights | Rate | Fair odds |\n|---|---|---|---|")
lab={"finish_r1_le60":"Finish within first 60s of round 1","finish_any_rnd_le60":"Finish within first 60s of any round","finish_last10":"Finish in last 10s of any round"}
for fl in FLAGS: print(f"| {lab[fl]} | {int(o[fl+'_sum'])}/{int(o.n_fights)} | {o[fl+'_mean']:.2%} | {american_odds(o[fl+'_mean'])} |")
print("\n### By scheduled format\n"); print(fmt(rates(f,"format")))
print("\n### By weight class (small samples are noisy)\n"); print(fmt(rates(f,"weight_class").sort_values("n_fights",ascending=False)))
card={"Moicano":["Renato Moicano"],"Nolan":["Tom Nolan","Eric Nolan"],"Brown":["Randy Brown","TJ Brown","Matt Brown"],"Jacobe Smith":["Jacobe Smith"],
"Osbourne":["Ode Osbourne"],"Durden":["Cody Durden"],"Yana Santos":["Yana Santos"],"Luana Santos":["Luana Santos"],"Lebosnoyani":["Jean-Paul Lebosnoyani"],
"Hasanov":["Farman Hasanov"],"Francis Marshall":["Francis Marshall"],"Dakota Hope":["Dakota Hope"],"Sezinando":["Rodrigo Sezinando"],"Berggren":["Theodor Berggren"],
"Erosa":["Julian Erosa"],"Lee":["Andrea Lee","ChangHo Lee","JeongYeong Lee","YiSak Lee"],"Reese":["Zach Reese"],"Gall":["Mickey Gall"],"Klein":["Ludovit Klein","Nick Klein"],
"Kropschot":[],"Alencar":["Talita Alencar"],"Rodriguez":["Christian Rodriguez","Daniel Rodriguez","Imanol Rodriguez","Marina Rodriguez","Piera Rodriguez","Ronaldo Rodriguez","Yair Rodriguez","Pete Rodriguez"],
"Szabova":[],"Lisboa":["Tainara Lisboa"]}
print("\n### Card fighters (UFC Fight Night: Moicano vs. Nolan, Oct 31, 2026) — own counts in UFC fights 2022 to UFC 333\n")
print("Cells are `total (won by this fighter)`. Surname-only entries with several UFC fighters in the data list every candidate; the card's full names were not verified (ufcstats.com unreachable from this box). No fights in data = UFC debut or no UFC fight in the 2022+ window.\n")
print("| Card name | Matched fighter | Fights | R1 ≤60s finish | Any rnd ≤60s finish | Last-10s finish |\n|---|---|---|---|---|---|")
for k,vs in card.items():
    if not vs: print(f"| {k} | none found | 0 | – | – | – |"); continue
    for v in vs:
        c=fighter_counts(f,v); amb=" (candidate)" if len(vs)>1 else ""
        print(f"| {k} | {v}{amb} | {c['n_fights']} | "+" | ".join(f"{c[x]} ({c[x+'_won']})" for x in FLAGS)+" |")
