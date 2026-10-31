(function () {
  const dataNode = document.getElementById("parlay-data");
  const root = document.querySelector(".builder");
  if (!dataNode || !root) return;
  const data = JSON.parse(dataNode.textContent);
  const slates = data.slates || [];
  const emptyEl = root.querySelector("[data-empty]");
  if (!slates.length) {
    if (emptyEl) { emptyEl.hidden = false; emptyEl.textContent = "No priced legs on this card."; }
    return;
  }
  let slate = slates.find(function (item) { return item.id === data.default; }) || slates[0];
  const byId = new Map();
  slate.groups.forEach(function (group) {
    group.legs.forEach(function (leg) { byId.set(leg.id, { leg: leg, group: group }); });
  });

  const resultsEl = root.querySelector("[data-results]");
  const randomCardEl = root.querySelector("[data-random-card]");
  const randomHistoryEl = root.querySelector("[data-random-history]");
  const countEl = root.querySelector("[data-result-count]");
  const boardEl = root.querySelector("[data-board]");
  const tabsEl = root.querySelector("[data-tabs]");
  const searchEl = root.querySelector("[data-search]");
  const stakeEl = root.querySelector("[data-stake]");
  const slipLegs = root.querySelector("[data-slip-legs]");
  const slipNums = root.querySelector("[data-slip-nums]");
  const slipWarn = root.querySelector("[data-slip-warn]");
  const slipNote = root.querySelector("[data-slip-note]");
  const live = root.querySelector("[data-live]");
  const peek = root.querySelector("[data-peek]");
  const slip = document.getElementById("slip");
  const marketNote = root.querySelector("[data-market-note]");

  const filters = {
    minPay: 50, maxPay: null, minLegs: 2, maxLegs: 5, minP: 0.02, minEdge: 0,
    style: "any", marketOnly: false, same: false, sort: "chance",
    types: {}, events: {}, include: "", exclude: ""
  };
  const selected = [];
  let stake = 1;
  let mode = "results";
  let manualTab = "moneyline";
  let cards = [];
  let activeKey = "";
  let randomTicket = null;
  let randomHistory = [];
  const lockedIds = {};

  const TYPE_LABELS = {
    moneyline: "Moneyline", method: "Method", distance: "Distance", round: "Round",
    "method-round": "Method + round", timing: "Timing", passing: "Pass yds",
    rushing: "Rush yds", receiving: "Rec yds", receptions: "Receptions", "anytime-td": "Anytime TD"
  };

  function money(n) {
    if (n == null || Number.isNaN(n)) return "—";
    return (n < 0 ? "−$" : "$") + Math.abs(n).toFixed(2);
  }
  function american(dec) {
    if (dec == null || dec <= 1) return "—";
    if (dec >= 2) return "+" + Math.round((dec - 1) * 100);
    return String(Math.round(-100 / (dec - 1)));
  }
  function pct(p) {
    if (p == null || Number.isNaN(p)) return "unavailable";
    return (p * 100).toFixed(1) + "%";
  }
  function priceText(leg) {
    if (leg.price_kind === "market" && leg.market_american) return leg.market_american;
    return leg.fair_american || "—";
  }
  function marketImplied(leg) {
    if (!leg.market_american) return null;
    const n = Number(String(leg.market_american).replace("+", ""));
    if (!n) return null;
    return n > 0 ? 100 / (n + 100) : (-n) / ((-n) + 100);
  }
  function legEdge(leg) {
    const market = marketImplied(leg);
    if (market == null || leg.model_p == null) return null;
    return leg.model_p - market;
  }
  function why(leg) {
    if (leg.samples) return pct(leg.model_p) + " of the last " + leg.samples.length + " games at this line.";
    if (leg.type === "timing") return "Observed rate " + pct(leg.model_p) + (leg.thin ? " (thin sample)." : ".");
    if (leg.market_american && leg.type !== "moneyline") return "Model " + pct(leg.model_p) + " against the market " + leg.market_american + ".";
    if (leg.type === "moneyline") return "No-vig " + pct(leg.model_p) + " at " + (leg.market_american || "the listed price") + ".";
    return "Model " + pct(leg.model_p) + ", fair " + (leg.fair_american || "—") + ".";
  }
  function announce(text) { if (live) live.textContent = text; }
  function tokens(text) {
    return String(text || "").toLowerCase().split(",").map(function (part) { return part.trim(); }).filter(Boolean);
  }
  function blob(leg, group) {
    return (leg.label + " " + (leg.player || "") + " " + group.label).toLowerCase();
  }

  function timingOk(atom, kind) {
    const finish = atom.method === "ko" || atom.method === "sub";
    if (kind === "r1_le60") return finish && atom.round === 1;
    if (kind === "any_le60" || kind === "last10") return finish;
    return false;
  }
  function joint(atoms, legs, timingP) {
    if (!legs.length) return { status: "empty", p: null };
    let allowed = null;
    const kinds = [];
    const rates = Object.assign({}, timingP || {});
    for (let i = 0; i < legs.length; i++) {
      const leg = legs[i];
      if (leg.timing) { kinds.push(leg.timing); if (leg.model_p != null) rates[leg.timing] = leg.model_p; }
      if (!leg.atoms) continue;
      const chosen = new Set(leg.atoms);
      allowed = allowed === null ? chosen : new Set(Array.from(allowed).filter(function (id) { return chosen.has(id); }));
      if (!allowed.size) return { status: "contradictory", p: 0, reason: "Those legs cannot happen together." };
    }
    if (kinds.indexOf("r1_le60") !== -1 && kinds.indexOf("last10") !== -1) return { status: "contradictory", p: 0, reason: "First 60s and last 10s cannot both hit." };
    if (kinds.indexOf("any_le60") !== -1 && kinds.indexOf("last10") !== -1) return { status: "contradictory", p: 0, reason: "A first-60s finish is not a last-10s finish." };
    const tight = kinds.indexOf("r1_le60") !== -1 ? "r1_le60" : (kinds.indexOf("last10") !== -1 ? "last10" : (kinds.indexOf("any_le60") !== -1 ? "any_le60" : null));
    if (tight) {
      const compatible = new Set((atoms || []).filter(function (atom) { return timingOk(atom, tight); }).map(function (atom) { return atom.id; }));
      if (allowed && !Array.from(allowed).some(function (id) { return compatible.has(id); })) return { status: "contradictory", p: 0, reason: "That result cannot land in this timing window." };
      if (allowed && !Array.from(compatible).every(function (id) { return allowed.has(id); })) return { status: "unidentified", p: null, reason: "Clock time is not split by fighter. Chance withheld." };
      if (rates[tight] == null) return { status: "unidentified", p: null, reason: "Timing rate unavailable." };
      return { status: "ok", p: rates[tight] };
    }
    if (!allowed) return { status: "ok", p: 1 };
    let prob = 0;
    (atoms || []).forEach(function (atom) { if (allowed.has(atom.id)) prob += atom.p; });
    return { status: "ok", p: prob };
  }
  function quote(groups) {
    let prob = 1, decimal = 1, same = false, nflSame = false, bad = null;
    groups.forEach(function (group) {
      const legs = group.selected;
      if (group.atoms && group.atoms.length) {
        const result = joint(group.atoms, legs, group.timing_p);
        if (result.status !== "ok") bad = result;
        else prob *= result.p;
        if (legs.length > 1) same = true;
      } else {
        if (legs.length > 1) nflSame = true;
        legs.forEach(function (leg) { prob *= leg.model_p; });
      }
      legs.forEach(function (leg) { if (leg.decimal) decimal *= leg.decimal; });
    });
    if (bad) return bad;
    return { status: "ok", p: prob, decimal: decimal, same: same, nflSame: nflSame };
  }

  function legOk(leg, group) {
    if (!filters.types[leg.type]) return false;
    if (!filters.events[group.id]) return false;
    if (leg.model_p == null || leg.model_p < filters.minP || leg.model_p >= 1 || !leg.decimal) return false;
    if (filters.marketOnly && !leg.market_american) return false;
    if (filters.minEdge > 0) {
      const edge = legEdge(leg);
      if (edge == null || edge < filters.minEdge) return false;
    }
    const text = blob(leg, group);
    const skip = tokens(filters.exclude);
    for (let i = 0; i < skip.length; i++) if (text.indexOf(skip[i]) !== -1) return false;
    return true;
  }
  function candidates(group) {
    const pool = group.legs.filter(function (leg) { return legOk(leg, group); });
    const byP = pool.slice().sort(function (a, b) { return b.model_p - a.model_p; }).slice(0, 3);
    const byDec = pool.slice().sort(function (a, b) { return b.decimal - a.decimal; }).slice(0, 3);
    const byEdge = pool.filter(function (leg) { return legEdge(leg) != null; }).sort(function (a, b) { return legEdge(b) - legEdge(a); }).slice(0, 2);
    const seen = {};
    const out = [];
    byP.concat(byDec, byEdge).forEach(function (leg) {
      if (seen[leg.id]) return;
      seen[leg.id] = 1;
      out.push(leg);
    });
    return out.slice(0, 6);
  }
  function slotsFor(group) {
    const legs = candidates(group);
    const slots = legs.map(function (leg) {
      return { legs: [leg], p: leg.model_p, decimal: leg.decimal, group: group };
    });
    if (filters.same && group.atoms && group.atoms.length) {
      const pairs = [];
      for (let i = 0; i < legs.length; i++) {
        for (let j = i + 1; j < legs.length; j++) {
          const result = joint(group.atoms, [legs[i], legs[j]], group.timing_p);
          if (result.status !== "ok" || !(result.p > 0)) continue;
          const decimal = legs[i].decimal * legs[j].decimal;
          pairs.push({ legs: [legs[i], legs[j]], p: result.p, decimal: decimal, group: group });
        }
      }
      pairs.sort(function (a, b) { return b.p - a.p; });
      pairs.slice(0, 4).forEach(function (pair) { slots.push(pair); });
    }
    return slots;
  }
  function styleOk(legs) {
    if (filters.style === "any") return true;
    const fav = legs.some(function (leg) { return leg.model_p >= 0.5; });
    const dog = legs.some(function (leg) { return leg.model_p < 0.5; });
    if (filters.style === "fav") return fav && !dog;
    if (filters.style === "dog") return dog && !fav;
    return fav && dog;
  }
  function namesOk(legs, groups) {
    const need = tokens(filters.include);
    if (!need.length) return true;
    const text = legs.map(function (leg, i) { return blob(leg, groups[i] || { label: "" }); }).join(" ");
    return need.every(function (token) { return text.indexOf(token) !== -1; });
  }
  function badge(ticket) {
    if (ticket.nflSame) return "Same-game props, correlated";
    if (ticket.same) return "Same-fight joint, not a product";
    return slate.sport === "nfl" ? "One leg per game" : "One leg per fight";
  }
  function marketChance(legs) {
    let prob = 1;
    for (let i = 0; i < legs.length; i++) {
      const implied = marketImplied(legs[i]);
      if (implied == null) return null;
      prob *= implied;
    }
    return prob;
  }
  function ticketEdge(legs) {
    const edges = legs.map(legEdge).filter(function (edge) { return edge != null; });
    if (!edges.length) return null;
    return edges.reduce(function (sum, edge) { return sum + edge; }, 0) / edges.length;
  }

  function generate() {
    const groups = slate.groups.map(function (group) {
      return { id: group.id, slots: filters.events[group.id] ? slotsFor(group) : [] };
    }).filter(function (group) { return group.slots.length; });
    let beam = [{ slots: [], used: {}, p: 1, decimal: 1, n: 0 }];
    const found = [];
    const seen = {};
    for (let depth = 0; depth < filters.maxLegs; depth++) {
      const next = [];
      beam.forEach(function (partial) {
        groups.forEach(function (group) {
          if (partial.used[group.id]) return;
          group.slots.forEach(function (slot) {
            const n = partial.n + slot.legs.length;
            if (n > filters.maxLegs) return;
            const decimal = partial.decimal * slot.decimal;
            if (filters.maxPay && decimal > filters.maxPay) return;
            const item = {
              slots: partial.slots.concat([slot]),
              used: Object.assign({}, partial.used, (function () { const o = {}; o[group.id] = 1; return o; })()),
              p: partial.p * slot.p,
              decimal: decimal,
              n: n
            };
            next.push(item);
            if (n >= filters.minLegs && decimal >= filters.minPay) {
              const legs = item.slots.reduce(function (all, one) { return all.concat(one.legs); }, []);
              const owners = item.slots.reduce(function (all, one) { return all.concat(one.legs.map(function () { return one.group; })); }, []);
              if (!styleOk(legs) || !namesOk(legs, owners)) return;
              const key = legs.map(function (leg) { return leg.id; }).sort().join("|");
              if (seen[key]) return;
              seen[key] = 1;
              found.push({
                key: key, legs: legs, groups: item.slots.map(function (one) { return one.group; }),
                p: item.p, decimal: decimal, n: n,
                same: item.slots.some(function (one) { return one.legs.length > 1 && one.group.sport !== "nfl"; }),
                nflSame: item.slots.some(function (one) { return one.legs.length > 1 && one.group.sport === "nfl"; }),
                edge: ticketEdge(legs), marketP: marketChance(legs)
              });
            }
          });
        });
      });
      next.sort(function (a, b) { return b.p - a.p; });
      const rich = next.slice().sort(function (a, b) { return b.decimal - a.decimal; });
      const merged = [];
      const ids = {};
      next.slice(0, 50).concat(rich.slice(0, 30)).forEach(function (item) {
        const id = item.slots.map(function (slot) { return slot.legs.map(function (leg) { return leg.id; }).join("+"); }).join("|");
        if (ids[id]) return;
        ids[id] = 1;
        merged.push(item);
      });
      beam = merged.slice(0, 70);
      if (!beam.length || found.length > 180) break;
    }
    cards = found;
    sortCards();
  }
  function sortCards() {
    const sorters = {
      chance: function (a, b) { return b.p - a.p; },
      payout: function (a, b) { return b.decimal - a.decimal; },
      edge: function (a, b) { return (b.edge == null ? -1 : b.edge) - (a.edge == null ? -1 : a.edge); },
      legs: function (a, b) { return a.n - b.n || b.p - a.p; }
    };
    cards.sort(sorters[filters.sort] || sorters.chance);
    cards = cards.slice(0, 24);
  }

  function slotWeight(slot) {
    const edge = ticketEdge(slot.legs);
    const boost = 1 + Math.max(0, edge || 0) * 8;
    return Math.max(0.00005, slot.p) * boost;
  }
  function pickWeighted(items, weightOf) {
    let total = 0;
    const weights = items.map(function (item) {
      const weight = weightOf(item);
      total += weight;
      return weight;
    });
    if (!total) return items[0];
    let roll = Math.random() * total;
    for (let i = 0; i < items.length; i++) {
      roll -= weights[i];
      if (roll <= 0) return items[i];
    }
    return items[items.length - 1];
  }
  function toTicket(slots) {
    const legs = slots.reduce(function (all, slot) { return all.concat(slot.legs); }, []);
    return {
      key: legs.map(function (leg) { return leg.id; }).sort().join("|"),
      legs: legs,
      groups: slots.map(function (slot) { return slot.group; }),
      p: slots.reduce(function (prob, slot) { return prob * slot.p; }, 1),
      decimal: slots.reduce(function (dec, slot) { return dec * slot.decimal; }, 1),
      n: legs.length,
      same: slots.some(function (slot) { return slot.legs.length > 1 && slot.group.sport !== "nfl"; }),
      nflSame: slots.some(function (slot) { return slot.legs.length > 1 && slot.group.sport === "nfl"; }),
      edge: ticketEdge(legs),
      marketP: marketChance(legs)
    };
  }
  function lockedSlots(pools) {
    const byGroup = {};
    const ids = Object.keys(lockedIds).filter(function (id) { return lockedIds[id]; });
    ids.forEach(function (id) {
      const found = byId.get(id);
      if (!found) return;
      if (!byGroup[found.group.id]) byGroup[found.group.id] = [];
      byGroup[found.group.id].push(found.leg);
    });
    const slots = [];
    const groupIds = Object.keys(byGroup);
    for (let i = 0; i < groupIds.length; i++) {
      const group = slate.groups.filter(function (item) { return item.id === groupIds[i]; })[0];
      const legs = byGroup[groupIds[i]];
      if (!group || legs.some(function (leg) { return !legOk(leg, group); })) return { error: "A locked leg no longer passes the filters." };
      let slot;
      if (legs.length === 1) slot = { legs: legs, p: legs[0].model_p, decimal: legs[0].decimal, group: group };
      else if (!filters.same) return { error: "Unlock one leg, or allow same-fight parlays, before shuffling." };
      else {
        const result = joint(group.atoms, legs, group.timing_p);
        if (result.status !== "ok") return { error: result.reason || "Those locked legs conflict." };
        slot = { legs: legs, p: result.p, decimal: legs.reduce(function (dec, leg) { return dec * leg.decimal; }, 1), group: group };
      }
      slots.push(slot);
    }
    return { slots: slots, pools: pools };
  }
  function sampleTicket() {
    const floorPay = Math.max(50, filters.minPay || 0);
    if (filters.maxPay && filters.maxPay < floorPay) return { error: "Max payout is below the $50 floor." };
    const pools = slate.groups.map(function (group) {
      return { id: group.id, group: group, slots: filters.events[group.id] ? slotsFor(group) : [] };
    }).filter(function (pool) { return pool.slots.length; });
    const locked = lockedSlots(pools);
    if (locked.error) return locked;
    let lastKey = randomTicket ? randomTicket.key : "";
    for (let attempt = 0; attempt < 80; attempt++) {
      const used = {};
      const chosen = locked.slots.slice();
      chosen.forEach(function (slot) { used[slot.group.id] = 1; });
      let decimal = chosen.reduce(function (dec, slot) { return dec * slot.decimal; }, 1);
      let n = chosen.reduce(function (count, slot) { return count + slot.legs.length; }, 0);
      const order = pools.filter(function (pool) { return !used[pool.id]; }).sort(function () { return Math.random() - 0.5; });
      while (n < filters.maxLegs && (n < filters.minLegs || decimal < floorPay)) {
        const open = order.filter(function (pool) { return !used[pool.id]; });
        if (!open.length) break;
        const pool = pickWeighted(open, function (item) {
          return item.slots.reduce(function (sum, slot) { return sum + slotWeight(slot); }, 0);
        });
        const room = pool.slots.filter(function (slot) {
          const nextN = n + slot.legs.length;
          const nextDec = decimal * slot.decimal;
          if (nextN > filters.maxLegs) return false;
          if (filters.maxPay && nextDec > filters.maxPay) return false;
          return true;
        });
        if (!room.length) { used[pool.id] = 1; continue; }
        const slot = pickWeighted(room, slotWeight);
        chosen.push(slot);
        used[pool.id] = 1;
        decimal *= slot.decimal;
        n += slot.legs.length;
      }
      if (n < filters.minLegs || n > filters.maxLegs || decimal < floorPay) continue;
      if (filters.maxPay && decimal > filters.maxPay) continue;
      const ticket = toTicket(chosen);
      if (ticket.key === lastKey) continue;
      const owners = chosen.reduce(function (all, slot) { return all.concat(slot.legs.map(function () { return slot.group; })); }, []);
      if (!styleOk(ticket.legs) || !namesOk(ticket.legs, owners)) continue;
      return { ticket: ticket };
    }
    return { error: "No fresh ticket clears $50 on $1 with these filters and locks." };
  }
  function renderRandom() {
    if (!randomCardEl) return;
    randomCardEl.innerHTML = "";
    if (!randomTicket) {
      randomCardEl.innerHTML = "<p class='fine' data-random-msg>Press Random pick for a ticket at +5000 or longer.</p>";
    } else {
      const card = document.createElement("article");
      card.className = "random-card";
      card.setAttribute("aria-label", "Random parlay");
      const payout = stake * randomTicket.decimal;
      card.innerHTML = "<div class='pcard-top'><strong>" + american(randomTicket.decimal) + "</strong><span>" + money(payout) + " back on " + money(stake) + "</span></div>";
      const meta = document.createElement("div");
      meta.className = "badges";
      meta.appendChild(chip("model", "Chance " + pct(randomTicket.p)));
      meta.appendChild(chip(randomTicket.marketP == null ? "missing" : "market", randomTicket.marketP == null ? "Market chance unavailable" : "Market " + pct(randomTicket.marketP)));
      meta.appendChild(chip(randomTicket.same || randomTicket.nflSame ? "inference" : "observed", badge(randomTicket)));
      card.appendChild(meta);
      const list = document.createElement("ul");
      randomTicket.legs.forEach(function (leg) {
        const item = document.createElement("li");
        item.innerHTML = "<b>" + escapeHtml(leg.label) + "</b> · " + escapeHtml(priceText(leg)) + "<span class='why'>" + escapeHtml(why(leg)) + "</span>";
        const lock = document.createElement("button");
        lock.type = "button";
        lock.className = "lock";
        lock.textContent = lockedIds[leg.id] ? "Locked" : "Lock leg";
        lock.setAttribute("aria-pressed", lockedIds[leg.id] ? "true" : "false");
        lock.addEventListener("click", function () {
          lockedIds[leg.id] = !lockedIds[leg.id];
          renderRandom();
        });
        item.appendChild(lock);
        list.appendChild(item);
      });
      card.appendChild(list);
      const actions = document.createElement("div");
      actions.className = "random-actions";
      actions.appendChild(actionButton("Shuffle again", shuffleRandom));
      actions.appendChild(actionButton("Add to slip", function () { openCard(randomTicket); }));
      card.appendChild(actions);
      randomCardEl.appendChild(card);
    }
    if (randomHistoryEl) {
      randomHistoryEl.innerHTML = "";
      randomHistory.forEach(function (ticket, index) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = "Pick " + (randomHistory.length - index) + " · " + american(ticket.decimal);
        button.addEventListener("click", function () {
          randomTicket = ticket;
          renderRandom();
          announce("Showing an earlier random pick");
        });
        randomHistoryEl.appendChild(button);
      });
    }
  }
  function actionButton(label, onClick) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.addEventListener("click", onClick);
    return button;
  }
  function rememberTicket(ticket) {
    randomHistory = [ticket].concat(randomHistory.filter(function (item) { return item.key !== ticket.key; })).slice(0, 5);
  }
  function shuffleRandom() {
    const result = sampleTicket();
    const msg = randomCardEl.querySelector("[data-random-msg]");
    if (result.error) {
      if (!randomTicket) randomCardEl.innerHTML = "<p class='fine'>" + escapeHtml(result.error) + "</p>";
      else if (msg) msg.textContent = result.error;
      else {
        const note = document.createElement("p");
        note.className = "fine";
        note.textContent = result.error;
        randomCardEl.appendChild(note);
      }
      announce(result.error);
      return;
    }
    randomTicket = result.ticket;
    rememberTicket(randomTicket);
    renderRandom();
    announce("New random parlay, " + american(randomTicket.decimal));
  }

  function renderResults() {
    generate();
    resultsEl.innerHTML = "";
    countEl.textContent = cards.length ? cards.length + " parlays. Tap one to open the slip." : "";
    emptyEl.hidden = cards.length > 0;
    emptyEl.textContent = "No parlays match these filters. Lower the minimum payout or turn more leg types on.";
    cards.forEach(function (card) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "pcard" + (card.key === activeKey ? " on" : "");
      const payout = stake * card.decimal;
      const top = document.createElement("div");
      top.className = "pcard-top";
      top.innerHTML = "<strong>" + american(card.decimal) + "</strong><span>" + money(payout) + " back on " + money(stake) + "</span>";
      const meta = document.createElement("div");
      meta.className = "badges";
      meta.appendChild(chip("model", "Chance " + pct(card.p)));
      meta.appendChild(chip(card.marketP == null ? "missing" : "market", card.marketP == null ? "Market chance unavailable" : "Market " + pct(card.marketP)));
      meta.appendChild(chip(card.same || card.nflSame ? "inference" : "observed", badge(card)));
      const list = document.createElement("ul");
      card.legs.forEach(function (leg) {
        const item = document.createElement("li");
        item.innerHTML = "<b>" + escapeHtml(leg.label) + "</b> · " + escapeHtml(priceText(leg)) + "<span class='why'>" + escapeHtml(why(leg)) + "</span>";
        list.appendChild(item);
      });
      button.appendChild(top);
      button.appendChild(meta);
      button.appendChild(list);
      button.addEventListener("click", function () { openCard(card); });
      resultsEl.appendChild(button);
    });
  }
  function escapeHtml(text) {
    return String(text).replace(/[&<>"]/g, function (ch) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[ch];
    });
  }
  function chip(kind, text) {
    const span = document.createElement("span");
    span.className = "chip chip-" + kind;
    span.textContent = text;
    return span;
  }

  function openCard(card) {
    activeKey = card.key;
    selected.length = 0;
    card.legs.forEach(function (leg) {
      const found = byId.get(leg.id);
      selected.push({ leg: leg, group: found ? found.group : card.groups[0] });
    });
    renderResults();
    renderSlip();
    announce("Opened a " + card.n + "-leg parlay");
    if (window.matchMedia("(max-width: 899px)").matches && slip) {
      slip.classList.add("open");
      if (peek) peek.setAttribute("aria-expanded", "true");
    }
  }

  function renderSlip() {
    slipLegs.innerHTML = "";
    if (!selected.length) {
      const item = document.createElement("li");
      item.textContent = mode === "results" ? "Tap a parlay card to open it here." : "Slip is empty. Add a leg.";
      slipLegs.appendChild(item);
    }
    selected.forEach(function (entry, index) {
      const item = document.createElement("li");
      const text = document.createElement("div");
      text.innerHTML = "<b>" + escapeHtml(entry.leg.label) + "</b><div class='why'>" + escapeHtml(why(entry.leg)) + " · " + escapeHtml(priceText(entry.leg)) + "</div>";
      const swap = document.createElement("button");
      swap.type = "button";
      swap.className = "textish";
      swap.textContent = "Swap";
      swap.setAttribute("aria-expanded", "false");
      const alts = document.createElement("div");
      alts.className = "alts";
      alts.hidden = true;
      swap.addEventListener("click", function () {
        const open = alts.hidden;
        alts.hidden = !open;
        swap.setAttribute("aria-expanded", open ? "true" : "false");
        if (open && !alts.childElementCount) fillAlts(alts, entry, index);
      });
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "×";
      remove.setAttribute("aria-label", "Remove " + entry.leg.label);
      remove.addEventListener("click", function () {
        selected.splice(index, 1);
        activeKey = "";
        renderSlip();
        if (mode === "manual") renderManual();
      });
      text.appendChild(swap);
      text.appendChild(alts);
      item.appendChild(text);
      item.appendChild(remove);
      slipLegs.appendChild(item);
    });
    const grouped = groupSelected();
    const result = selected.length ? quote(grouped) : { status: "empty", decimal: null, p: null };
    const payout = result.decimal != null ? stake * result.decimal : null;
    slipNums.innerHTML =
      stat("American", result.decimal != null ? american(result.decimal) : "—") +
      stat("Chance", result.status === "ok" ? pct(result.p) : "Withheld") +
      stat("Payout", payout != null ? money(payout) : "—") +
      stat("On $1", result.decimal != null ? money(result.decimal) : "—");
    const warnings = [];
    if (result.status === "unidentified" || result.status === "contradictory") warnings.push(result.reason);
    if (result.nflSame) warnings.push("Same-game props are correlated. This chance is a product, not a joint model.");
    slipWarn.hidden = !warnings.length;
    slipWarn.textContent = warnings.join(" ");
    slipNote.textContent = selected.length && result.same ? "Same-fight legs use the joint from method-split-v0, not a product." : "Separate fights are treated as independent. A book will price this differently.";
    root.querySelector("[data-peek-count]").textContent = "Slip · " + selected.length + (selected.length === 1 ? " leg" : " legs");
    root.querySelector("[data-peek-pay]").textContent = payout != null ? money(payout) + " back" : "Open a parlay";
  }
  function stat(label, value) { return "<div><dt>" + label + "</dt><dd>" + value + "</dd></div>"; }
  function groupSelected() {
    const map = new Map();
    selected.forEach(function (entry) {
      if (!map.has(entry.group.id)) map.set(entry.group.id, { atoms: entry.group.atoms, timing_p: entry.group.timing_p, sport: entry.group.sport, selected: [] });
      map.get(entry.group.id).selected.push(entry.leg);
    });
    return Array.from(map.values());
  }
  function fillAlts(box, entry, index) {
    const pool = entry.group.legs.filter(function (leg) {
      return leg.id !== entry.leg.id && leg.decimal && leg.model_p > 0 && leg.model_p < 1;
    }).slice(0, 8);
    if (!pool.length) {
      box.textContent = "No other priced leg in this fight.";
      return;
    }
    pool.forEach(function (leg) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = leg.label + " " + priceText(leg);
      button.addEventListener("click", function () {
        const snapshot = selected.map(function (item) { return item; });
        selected[index] = { leg: leg, group: entry.group };
        const result = quote(groupSelected());
        if (result.status === "contradictory" || result.status === "unidentified") {
          selected.length = 0;
          snapshot.forEach(function (item) { selected.push(item); });
          announce(result.reason || "That swap does not have a safe joint.");
          return;
        }
        activeKey = "";
        renderSlip();
        announce("Swapped in " + leg.label);
      });
      box.appendChild(button);
    });
  }

  function renderManual() {
    const q = (searchEl.value || "").trim().toLowerCase();
    boardEl.innerHTML = "";
    let shown = 0;
    slate.groups.forEach(function (group) {
      const legs = group.legs.filter(function (leg) {
        if (!manualMatch(leg)) return false;
        if (q && blob(leg, group).indexOf(q) === -1) return false;
        return true;
      });
      if (!legs.length) return;
      const open = q ? true : shown === 0;
      shown += legs.length;
      const block = document.createElement("section");
      const title = document.createElement("button");
      title.type = "button";
      title.className = "bout-toggle";
      title.textContent = group.label;
      title.setAttribute("aria-expanded", open ? "true" : "false");
      const body = document.createElement("div");
      body.hidden = !open;
      title.addEventListener("click", function () {
        body.hidden = !body.hidden;
        title.setAttribute("aria-expanded", body.hidden ? "false" : "true");
      });
      legs.slice(0, 12).forEach(function (leg) { body.appendChild(manualCard(leg, group)); });
      block.appendChild(title);
      block.appendChild(body);
      boardEl.appendChild(block);
    });
  }
  function manualMatch(leg) {
    if (manualTab === "props") return leg.type !== "moneyline" && slate.sport === "nfl";
    if (manualTab === "method") return leg.type === "method" || leg.type === "distance";
    if (manualTab === "round") return leg.type === "round" || leg.type === "method-round";
    return leg.type === manualTab;
  }
  function manualCard(leg, group) {
    const card = document.createElement("article");
    const on = selected.some(function (entry) { return entry.leg.id === leg.id; });
    card.className = "leg" + (on ? " on" : "");
    const main = document.createElement("div");
    main.innerHTML = "<div class='badges'></div><div class='leg-title'>" + escapeHtml(leg.label) + "</div><div class='meta'><div>Our number <b>" + pct(leg.model_p) + "</b></div><div>Price <b>" + escapeHtml(priceText(leg)) + "</b></div></div><div class='src'>" + escapeHtml(why(leg)) + "</div>";
    main.querySelector(".badges").appendChild(chipEl(leg.kind));
    const button = document.createElement("button");
    button.type = "button";
    button.className = "add";
    button.textContent = on ? "Remove" : priceText(leg);
    button.addEventListener("click", function () {
      const at = selected.findIndex(function (entry) { return entry.leg.id === leg.id; });
      if (at >= 0) selected.splice(at, 1);
      else {
        selected.push({ leg: leg, group: group });
        const result = quote(groupSelected());
        if (result.status === "contradictory" || result.status === "unidentified") {
          selected.pop();
          announce(result.reason || "That leg conflicts with the slip.");
          return;
        }
      }
      activeKey = "";
      renderManual();
      renderSlip();
    });
    card.appendChild(main);
    card.appendChild(button);
    return card;
  }
  function chipEl(kind) {
    const span = document.createElement("span");
    span.className = "chip chip-" + (kind || "model");
    span.textContent = kind || "model";
    return span;
  }

  function renderManualTabs() {
    const items = slate.sport === "nfl" ? [["moneyline", "Moneyline"], ["props", "NFL Player Props"]] : [["moneyline", "Moneyline"], ["method", "Method"], ["round", "Round"], ["timing", "Timing"]];
    tabsEl.innerHTML = "";
    items.forEach(function (pair) {
      const button = document.createElement("button");
      button.type = "button";
      button.setAttribute("role", "tab");
      button.setAttribute("aria-selected", pair[0] === manualTab ? "true" : "false");
      button.textContent = pair[1];
      button.addEventListener("click", function () { manualTab = pair[0]; renderManualTabs(); renderManual(); });
      tabsEl.appendChild(button);
    });
  }

  function setupFilters() {
    const types = {};
    const events = {};
    slate.groups.forEach(function (group) {
      events[group.id] = true;
      group.legs.forEach(function (leg) { types[leg.type] = true; });
    });
    filters.types = {};
    filters.events = {};
    Object.keys(types).forEach(function (type) { filters.types[type] = true; });
    Object.keys(events).forEach(function (id) { filters.events[id] = true; });
    const typeBox = root.querySelector("[data-type-chips]");
    Object.keys(types).forEach(function (type) {
      typeBox.appendChild(pressChip(TYPE_LABELS[type] || type, true, function (on) {
        filters.types[type] = on;
        schedule();
      }, "data-filter-type", type));
    });
    const eventBox = root.querySelector("[data-event-chips]");
    slate.groups.forEach(function (group) {
      eventBox.appendChild(pressChip(group.label, true, function (on) {
        filters.events[group.id] = on;
        schedule();
      }, "data-filter-event", group.id));
    });
  }
  function pressChip(label, start, onChange, attr, value) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.setAttribute("aria-pressed", start ? "true" : "false");
    if (attr) button.setAttribute(attr, value);
    button.addEventListener("click", function () {
      const on = button.getAttribute("aria-pressed") !== "true";
      button.setAttribute("aria-pressed", on ? "true" : "false");
      onChange(on);
    });
    return button;
  }

  let timer = 0;
  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(renderResults, 120);
  }
  function readNumber(selector, fallback) {
    const value = Number(root.querySelector(selector).value);
    return Number.isNaN(value) || root.querySelector(selector).value === "" ? fallback : value;
  }
  function syncFilters() {
    filters.minPay = Math.max(1, readNumber("[data-min-pay]", 50));
    filters.maxPay = readNumber("[data-max-pay]", null);
    filters.minLegs = Math.min(10, Math.max(2, readNumber("[data-min-legs]", 2)));
    filters.maxLegs = Math.min(10, Math.max(filters.minLegs, readNumber("[data-max-legs]", 5)));
    filters.minP = Number(root.querySelector("[data-min-p]").value) / 100;
    filters.minEdge = Number(root.querySelector("[data-min-edge]").value) / 100;
    root.querySelector("[data-min-p-out]").textContent = root.querySelector("[data-min-p]").value + "%";
    root.querySelector("[data-min-edge-out]").textContent = root.querySelector("[data-min-edge]").value + " pts";
    filters.include = root.querySelector("[data-include]").value;
    filters.exclude = root.querySelector("[data-exclude]").value;
    filters.sort = root.querySelector("[data-sort]").value;
    const tierSel = root.querySelector("[data-pay-tier]");
    if (tierSel && document.activeElement !== tierSel) {
      const max = filters.maxPay == null ? "" : String(filters.maxPay);
      const key = String(filters.minPay) + "," + max;
      tierSel.value = Array.from(tierSel.options).some(function (option) { return option.value === key; }) ? key : "";
    }
  }

  root.querySelectorAll("[data-style]").forEach(function (button) {
    button.addEventListener("click", function () {
      filters.style = button.getAttribute("data-style");
      root.querySelectorAll("[data-style]").forEach(function (other) {
        other.setAttribute("aria-pressed", other === button ? "true" : "false");
      });
      schedule();
    });
  });
  ["[data-min-pay]", "[data-max-pay]", "[data-min-legs]", "[data-max-legs]", "[data-min-p]", "[data-min-edge]", "[data-include]", "[data-exclude]", "[data-sort]"].forEach(function (selector) {
    root.querySelector(selector).addEventListener("input", function () { syncFilters(); schedule(); });
    root.querySelector(selector).addEventListener("change", function () { syncFilters(); schedule(); });
  });
  root.querySelector("[data-market-only]").addEventListener("click", function (event) {
    filters.marketOnly = event.currentTarget.getAttribute("aria-checked") !== "true";
    event.currentTarget.setAttribute("aria-checked", filters.marketOnly ? "true" : "false");
    schedule();
  });
  root.querySelector("[data-same]").addEventListener("click", function (event) {
    filters.same = event.currentTarget.getAttribute("aria-checked") !== "true";
    event.currentTarget.setAttribute("aria-checked", filters.same ? "true" : "false");
    schedule();
  });
  const tierSel = root.querySelector("[data-pay-tier]");
  if (tierSel) tierSel.addEventListener("change", function () {
    if (!tierSel.value) return;
    const parts = tierSel.value.split(",");
    root.querySelector("[data-min-pay]").value = parts[0];
    root.querySelector("[data-max-pay]").value = parts[1] || "";
    syncFilters();
    schedule();
  });
  const PRESET_KEY = "dfs-intel-filter-presets";
  function readPresets() {
    try { return JSON.parse(localStorage.getItem(PRESET_KEY) || "[]"); }
    catch (err) { return []; }
  }
  function fillPresetMenu() {
    const menu = root.querySelector("[data-preset-load]");
    if (!menu) return;
    const current = menu.value;
    menu.innerHTML = '<option value="">Choose a preset</option>';
    readPresets().forEach(function (preset, index) {
      if (preset.page !== "builder") return;
      const option = document.createElement("option");
      option.value = String(index);
      option.textContent = preset.name;
      menu.appendChild(option);
    });
    menu.value = current;
  }
  function snapshotFilters() {
    return {
      page: "builder",
      minPay: filters.minPay, maxPay: filters.maxPay, minLegs: filters.minLegs, maxLegs: filters.maxLegs,
      minP: filters.minP, minEdge: filters.minEdge, style: filters.style,
      types: Object.assign({}, filters.types), events: Object.assign({}, filters.events),
      include: filters.include, exclude: filters.exclude, marketOnly: filters.marketOnly, same: filters.same, sort: filters.sort
    };
  }
  function applyBuilderPreset(preset) {
    root.querySelector("[data-min-pay]").value = preset.minPay;
    root.querySelector("[data-max-pay]").value = preset.maxPay == null ? "" : preset.maxPay;
    root.querySelector("[data-min-legs]").value = preset.minLegs;
    root.querySelector("[data-max-legs]").value = preset.maxLegs;
    root.querySelector("[data-min-p]").value = Math.round((preset.minP || 0) * 100);
    root.querySelector("[data-min-edge]").value = Math.round((preset.minEdge || 0) * 100);
    root.querySelector("[data-include]").value = preset.include || "";
    root.querySelector("[data-exclude]").value = preset.exclude || "";
    root.querySelector("[data-sort]").value = preset.sort || "chance";
    filters.style = preset.style || "any";
    root.querySelectorAll("[data-style]").forEach(function (button) {
      button.setAttribute("aria-pressed", button.getAttribute("data-style") === filters.style ? "true" : "false");
    });
    filters.marketOnly = !!preset.marketOnly;
    filters.same = !!preset.same;
    root.querySelector("[data-market-only]").setAttribute("aria-checked", filters.marketOnly ? "true" : "false");
    root.querySelector("[data-same]").setAttribute("aria-checked", filters.same ? "true" : "false");
    root.querySelectorAll("[data-filter-type]").forEach(function (button) {
      const type = button.getAttribute("data-filter-type");
      const on = !preset.types || preset.types[type] !== false;
      filters.types[type] = on;
      button.setAttribute("aria-pressed", on ? "true" : "false");
    });
    root.querySelectorAll("[data-filter-event]").forEach(function (button) {
      const id = button.getAttribute("data-filter-event");
      const on = !preset.events || preset.events[id] !== false;
      filters.events[id] = on;
      button.setAttribute("aria-pressed", on ? "true" : "false");
    });
    syncFilters();
    schedule();
    announce("Loaded filter preset " + (preset.name || ""));
  }
  const savePreset = root.querySelector("[data-preset-save]");
  if (savePreset) savePreset.addEventListener("click", function () {
    syncFilters();
    const name = (root.querySelector("[data-preset-name]").value || "").trim();
    if (!name) { announce("Name the filter preset before saving."); return; }
    const presets = readPresets().filter(function (preset) { return !(preset.page === "builder" && preset.name === name); });
    presets.unshift(Object.assign({ name: name }, snapshotFilters()));
    localStorage.setItem(PRESET_KEY, JSON.stringify(presets.slice(0, 30)));
    fillPresetMenu();
    announce("Saved filter preset " + name);
  });
  const loadPreset = root.querySelector("[data-preset-load]");
  if (loadPreset) loadPreset.addEventListener("change", function () {
    const presets = readPresets();
    const preset = presets[Number(loadPreset.value)];
    if (preset && preset.page === "builder") applyBuilderPreset(preset);
  });
  document.getElementById("mode-results").addEventListener("click", function () { setMode("results"); });
  document.getElementById("mode-manual").addEventListener("click", function () { setMode("manual"); });
  function setMode(next) {
    mode = next;
    document.getElementById("mode-results").setAttribute("aria-selected", next === "results" ? "true" : "false");
    document.getElementById("mode-manual").setAttribute("aria-selected", next === "manual" ? "true" : "false");
    root.querySelector("[data-results-panel]").hidden = next !== "results";
    root.querySelector("[data-manual-panel]").hidden = next !== "manual";
    emptyEl.hidden = true;
    if (next === "manual") { renderManualTabs(); renderManual(); }
    else renderResults();
  }

  stakeEl.addEventListener("input", function () {
    stake = Math.max(0, Number(stakeEl.value) || 0);
    root.querySelectorAll("[data-chip]").forEach(function (chip) {
      chip.setAttribute("aria-pressed", Number(chip.getAttribute("data-chip")) === stake ? "true" : "false");
    });
    if (mode === "results") renderResults();
    renderRandom();
    renderSlip();
  });
  root.querySelectorAll("[data-chip]").forEach(function (chip) {
    chip.addEventListener("click", function () {
      stake = Number(chip.getAttribute("data-chip"));
      stakeEl.value = String(stake);
      root.querySelectorAll("[data-chip]").forEach(function (other) {
        other.setAttribute("aria-pressed", other === chip ? "true" : "false");
      });
      if (mode === "results") renderResults();
      renderRandom();
      renderSlip();
    });
  });
  root.querySelector("[data-clear]").addEventListener("click", function () {
    selected.length = 0;
    activeKey = "";
    renderSlip();
    if (mode === "results") renderResults();
    else renderManual();
  });
  root.querySelector("[data-share]").addEventListener("click", function () {
    const ids = selected.map(function (entry) { return entry.leg.id; }).join(",");
    const next = "#stake=" + encodeURIComponent(String(stake)) + "&legs=" + encodeURIComponent(ids);
    history.replaceState(null, "", location.pathname + location.search + next);
    const url = location.href;
    const done = function () {
      root.querySelector("[data-copied]").hidden = false;
      announce("Slip link copied");
    };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(url).then(done).catch(done);
    else done();
  });
  if (peek) {
    peek.addEventListener("click", function () {
      const open = slip.classList.toggle("open");
      peek.setAttribute("aria-expanded", open ? "true" : "false");
      if (open) stakeEl.focus();
    });
  }
  const saveButton = root.querySelector("[data-save]");
  if (saveButton) saveButton.addEventListener("click", function () {
    if (!selected.length) { announce("Open or build a parlay before saving."); return; }
    const result = quote(groupSelected());
    if (result.status !== "ok" || result.decimal == null) { announce("This slip has no settled chance, so it was not saved."); return; }
    const key = "dfs-intel-slips-v1";
    const slips = JSON.parse(localStorage.getItem(key) || "[]");
    slips.unshift({
      id: Date.now().toString(36),
      savedAt: new Date().toISOString(),
      title: slate.title,
      legs: selected.map(function (entry) { return { label: entry.leg.label, price: priceText(entry.leg), why: why(entry.leg) }; }),
      decimal: result.decimal,
      p: result.p,
      result: "open"
    });
    localStorage.setItem(key, JSON.stringify(slips.slice(0, 200)));
    root.querySelector("[data-copied]").hidden = false;
    root.querySelector("[data-copied]").textContent = "Saved to My slips.";
    announce("Saved to My slips");
  });
  if (searchEl) searchEl.addEventListener("input", renderManual);
  if (marketNote) {
    marketNote.textContent = slate.sport === "ufc"
      ? "Ranked tickets from this card. Method prices are the GAPOdds consensus when the public page has them. Our chance is method-split-v0, and same-fight legs use the joint."
      : "Ranked tickets from this week. Player-prop lines are the trailing-game rate at a line you can edit in Build your own. Same-game props stay labeled as correlated.";
  }
  const randomButton = root.querySelector("[data-random]");
  if (randomButton) randomButton.addEventListener("click", shuffleRandom);
  setupFilters();
  fillPresetMenu();
  syncFilters();
  renderResults();
  renderRandom();
  renderSlip();
})();
