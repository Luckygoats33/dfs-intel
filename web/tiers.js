/* Tier pages: filter the precomputed band, sample a random ticket, and open the slip. */
(function () {
  const dataEl = document.getElementById("tier-data");
  if (!dataEl) return;
  const data = JSON.parse(dataEl.textContent);
  const root = document.querySelector(".builder") || document.body;
  const live = root.querySelector("[data-live]");
  const PRESET_KEY = "dfs-intel-filter-presets";
  const SLIP_KEY = "dfs-intel-slips-v1";
  const filters = {
    sport: "", event: "", minLegs: 2, maxLegs: 10, minP: 0, minEdge: 0,
    style: "any", types: {}, include: "", exclude: "", marketOnly: false, same: false, sort: "chance"
  };
  const lookup = {};
  (data.sections || []).forEach(function (section) {
    (section.parlays || []).forEach(function (ticket) {
      lookup[section.id + "|" + ticket.key] = { section: section, ticket: ticket };
    });
  });
  let stake = 1;
  let open = null;
  let locked = [];
  let history = [];
  let currentRandom = null;

  function announce(text) {
    if (live) live.textContent = text;
  }
  function tokens(text) {
    return String(text || "").toLowerCase().split(",").map(function (part) { return part.trim(); }).filter(Boolean);
  }
  function readPresets() {
    try { return JSON.parse(localStorage.getItem(PRESET_KEY) || "[]"); }
    catch (err) { return []; }
  }
  function readNumber(selector, fallback) {
    const el = root.querySelector(selector);
    if (!el || el.value === "") return fallback;
    const value = Number(el.value);
    return Number.isNaN(value) ? fallback : value;
  }
  function syncFilters() {
    filters.sport = root.querySelector("[data-tier-sport]").value;
    filters.event = root.querySelector("[data-tier-event]").value;
    filters.minLegs = Math.min(10, Math.max(2, readNumber("[data-min-legs]", 2)));
    filters.maxLegs = Math.min(10, Math.max(filters.minLegs, readNumber("[data-max-legs]", 10)));
    filters.minP = Number(root.querySelector("[data-min-p]").value) / 100;
    filters.minEdge = Number(root.querySelector("[data-min-edge]").value) / 100;
    root.querySelector("[data-min-p-out]").textContent = root.querySelector("[data-min-p]").value + "%";
    root.querySelector("[data-min-edge-out]").textContent = root.querySelector("[data-min-edge]").value + " pts";
    filters.include = root.querySelector("[data-tier-include]").value;
    filters.exclude = root.querySelector("[data-tier-exclude]").value;
    filters.sort = root.querySelector("[data-sort]").value;
  }
  function namesOf(ticket) {
    return (ticket.legs || []).map(function (leg) { return (leg.label || "").toLowerCase(); }).join(" ");
  }
  function styleOf(ticket) {
    const decimals = (ticket.legs || []).map(function (leg) { return Number(leg.decimal); }).filter(function (value) { return value > 0; });
    if (!decimals.length) return "mixed";
    if (decimals.every(function (value) { return value < 2; })) return "fav";
    if (decimals.every(function (value) { return value >= 2; })) return "dog";
    return "mixed";
  }
  function ticketOk(ticket) {
    const legs = ticket.legs || [];
    if (ticket.n < filters.minLegs || ticket.n > filters.maxLegs) return false;
    if (filters.minEdge > 0 && (ticket.edge == null || ticket.edge < filters.minEdge)) return false;
    if (!filters.same && (ticket.same || ticket.nfl_same)) return false;
    if (filters.marketOnly && legs.some(function (leg) { return !leg.market; })) return false;
    if (legs.some(function (leg) { return filters.types[leg.type] === false; })) return false;
    if (legs.some(function (leg) { return leg.p == null || leg.p < filters.minP; })) return false;
    if (filters.style !== "any" && styleOf(ticket) !== filters.style) return false;
    const names = namesOf(ticket);
    if (tokens(filters.exclude).some(function (token) { return names.indexOf(token) !== -1; })) return false;
    const need = tokens(filters.include);
    if (need.some(function (token) { return names.indexOf(token) === -1; })) return false;
    if (locked.length && locked.some(function (id) { return !legs.some(function (leg) { return leg.id === id; }); })) return false;
    return true;
  }
  function sectionOk(section) {
    if (filters.sport && section.sport !== filters.sport) return false;
    if (filters.event && section.id !== filters.event) return false;
    return true;
  }
  function cardOk(card) {
    const n = Number(card.dataset.n);
    if (n < filters.minLegs || n > filters.maxLegs) return false;
    if (filters.minEdge > 0 && (card.dataset.edge === "" || Number(card.dataset.edge) < filters.minEdge)) return false;
    if (!filters.same && card.dataset.same === "1") return false;
    if (filters.marketOnly && card.dataset.market !== "1") return false;
    if (card.dataset.minp !== "" && Number(card.dataset.minp) < filters.minP) return false;
    if (filters.style !== "any" && card.dataset.style !== filters.style) return false;
    const types = (card.dataset.types || "").split(/\s+/).filter(Boolean);
    if (types.some(function (type) { return filters.types[type] === false; })) return false;
    const names = (card.dataset.names || "").toLowerCase();
    if (tokens(filters.exclude).some(function (token) { return names.indexOf(token) !== -1; })) return false;
    const need = tokens(filters.include);
    if (need.some(function (token) { return names.indexOf(token) === -1; })) return false;
    return true;
  }
  function sorters(a, b) {
    if (filters.sort === "payout") return Number(b.dataset.decimal) - Number(a.dataset.decimal);
    if (filters.sort === "edge") {
      const ae = a.dataset.edge === "" ? -999 : Number(a.dataset.edge);
      const be = b.dataset.edge === "" ? -999 : Number(b.dataset.edge);
      return be - ae;
    }
    if (filters.sort === "legs") return Number(a.dataset.n) - Number(b.dataset.n) || Number(b.dataset.p) - Number(a.dataset.p);
    return Number(b.dataset.p) - Number(a.dataset.p);
  }
  function apply() {
    syncFilters();
    let shown = 0;
    let cardsOn = 0;
    document.querySelectorAll(".tier-block").forEach(function (section) {
      const sport = section.dataset.sport;
      const id = section.dataset.event;
      const keep = (!filters.sport || sport === filters.sport) && (!filters.event || id === filters.event);
      section.hidden = !keep;
      if (!keep) return;
      cardsOn += 1;
      const list = section.querySelector(".result-list");
      const cards = Array.from(section.querySelectorAll(".pcard"));
      cards.sort(sorters);
      cards.forEach(function (card) {
        const ok = cardOk(card);
        card.hidden = !ok;
        if (ok) {
          shown += 1;
          list.appendChild(card);
        }
      });
      const empty = section.querySelector("[data-section-empty]");
      if (empty) empty.hidden = cards.some(function (card) { return !card.hidden; });
    });
    const count = root.querySelector("[data-tier-count]");
    if (count) count.textContent = shown + " ticket" + (shown === 1 ? "" : "s") + " across " + cardsOn + " card" + (cardsOn === 1 ? "" : "s") + ".";
  }
  function pool() {
    const rows = [];
    (data.sections || []).forEach(function (section) {
      if (!sectionOk(section)) return;
      (section.parlays || []).forEach(function (ticket) {
        if (ticketOk(ticket)) rows.push({ section: section, ticket: ticket });
      });
    });
    return rows;
  }
  function weight(ticket) {
    return Math.max(1e-6, Number(ticket.p) || 0) * (1 + Math.max(0, Number(ticket.edge) || 0) * 8);
  }
  function sample(rows) {
    let total = 0;
    rows.forEach(function (row) { total += weight(row.ticket); });
    let roll = Math.random() * total;
    for (let i = 0; i < rows.length; i++) {
      roll -= weight(rows[i].ticket);
      if (roll <= 0) return rows[i];
    }
    return rows[rows.length - 1];
  }
  function money(decimal) {
    return "$" + (stake * decimal).toFixed(2);
  }
  function renderRandomCard(row) {
    const box = root.querySelector("[data-tier-random-card]");
    if (!box) return;
    if (!row) {
      box.innerHTML = "<p class='fine'>No ticket in this band matches the filters" + (locked.length ? " with those locked legs" : "") + ".</p>";
      return;
    }
    currentRandom = row;
    const ticket = row.ticket;
    const legs = (ticket.legs || []).map(function (leg) {
      const on = locked.indexOf(leg.id) !== -1;
      return "<li><b>" + escapeHtml(leg.label) + "</b> · " + escapeHtml(leg.price || "—") +
        "<span class='why'>" + escapeHtml(leg.why || "") + "</span>" +
        "<button type='button' class='lock' data-lock='" + escapeHtml(leg.id) + "' aria-pressed='" + (on ? "true" : "false") + "'>Lock leg</button></li>";
    }).join("");
    box.innerHTML = "<article class='random-card'><p class='kicker'>" + escapeHtml(row.section.title) + "</p>" +
      "<div class='pcard-top'><strong>" + escapeHtml(ticket.american) + "</strong><span>" + Number(ticket.decimal).toFixed(2) + " back on $1</span></div>" +
      "<p>Our chance " + (ticket.p * 100).toFixed(2) + "%</p><ul>" + legs + "</ul>" +
      "<div class='random-actions'><button type='button' data-shuffle>Shuffle again</button>" +
      "<button type='button' data-random-add>Add to slip</button></div></article>";
    box.querySelectorAll("[data-lock]").forEach(function (button) {
      button.addEventListener("click", function () {
        const id = button.getAttribute("data-lock");
        const on = locked.indexOf(id) === -1;
        locked = on ? locked.concat([id]) : locked.filter(function (item) { return item !== id; });
        button.setAttribute("aria-pressed", on ? "true" : "false");
        announce(on ? "Leg locked" : "Leg unlocked");
      });
    });
    box.querySelector("[data-shuffle]").addEventListener("click", shuffle);
    box.querySelector("[data-random-add]").addEventListener("click", function () {
      showSlip(row.section, row.ticket);
      announce("Random pick added to the slip");
    });
  }
  function renderHistory() {
    const row = root.querySelector("[data-tier-history]");
    if (!row) return;
    row.innerHTML = "";
    history.forEach(function (item, index) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "Pick " + (history.length - index) + " · " + item.ticket.american;
      button.addEventListener("click", function () {
        currentRandom = item;
        renderRandomCard(item);
        announce("Showing an earlier random pick");
      });
      row.appendChild(button);
    });
  }
  function shuffle() {
    const rows = pool();
    if (!rows.length) {
      renderRandomCard(null);
      announce("No ticket matches these filters");
      return;
    }
    let row = sample(rows);
    let guard = 0;
    while (currentRandom && row.ticket.key === currentRandom.ticket.key && row.section.id === currentRandom.section.id && rows.length > 1 && guard < 5) {
      row = sample(rows);
      guard += 1;
    }
    history = [{ section: row.section, ticket: row.ticket }].concat(history).slice(0, 5);
    renderRandomCard(row);
    renderHistory();
    announce("New random pick " + row.ticket.american);
  }
  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }
  function showSlip(section, ticket) {
    open = { section: section, ticket: ticket };
    const list = root.querySelector("[data-slip-legs]");
    list.innerHTML = (ticket.legs || []).map(function (leg) {
      return "<li><span>" + escapeHtml(leg.label) + "</span><span>" + escapeHtml(leg.price || "—") + "</span></li>";
    }).join("");
    const payout = stake * ticket.decimal;
    const profit = payout - stake;
    root.querySelector("[data-slip-nums]").innerHTML =
      "<div><dt>Odds</dt><dd>" + escapeHtml(ticket.american) + "</dd></div>" +
      "<div><dt>Our chance</dt><dd>" + (ticket.p * 100).toFixed(2) + "%</dd></div>" +
      "<div><dt>Payout</dt><dd>" + money(ticket.decimal) + "</dd></div>" +
      "<div><dt>Profit</dt><dd>" + (profit >= 0 ? "+" : "−") + "$" + Math.abs(profit).toFixed(2) + "</dd></div>";
    const note = ticket.same ? "Same-fight legs use the joint model." : (ticket.nfl_same ? "Same-game props are correlated. The price is still a product." : "One leg per fight or game.");
    root.querySelector("[data-slip-note]").textContent = (section.title || "") + ". " + note + " Research only.";
    root.querySelector("[data-peek-count]").textContent = "Slip · " + ticket.n + " legs";
    root.querySelector("[data-peek-pay]").textContent = ticket.american + " · " + money(ticket.decimal);
    const slip = document.getElementById("slip");
    const peek = root.querySelector("[data-peek]");
    if (slip && window.matchMedia("(max-width: 899px)").matches) {
      slip.classList.add("open");
      if (peek) peek.setAttribute("aria-expanded", "true");
    }
    document.querySelectorAll(".pcard.on").forEach(function (card) { card.classList.remove("on"); });
    const match = document.querySelector("[data-open-ticket='" + CSS.escape(section.id + "|" + ticket.key) + "']");
    if (match) match.classList.add("on");
  }
  function clearSlip() {
    open = null;
    root.querySelector("[data-slip-legs]").innerHTML = "";
    root.querySelector("[data-slip-nums]").innerHTML = "";
    root.querySelector("[data-slip-note]").textContent = "Open a ranked ticket or a random pick. Saving keeps it on this device under My slips.";
    root.querySelector("[data-peek-count]").textContent = "Slip · empty";
    root.querySelector("[data-peek-pay]").textContent = "Open a ticket";
    document.querySelectorAll(".pcard.on").forEach(function (card) { card.classList.remove("on"); });
  }
  function fillEvents() {
    const menu = root.querySelector("[data-tier-event]");
    (data.sections || []).forEach(function (section) {
      const option = document.createElement("option");
      option.value = section.id;
      option.textContent = section.title;
      menu.appendChild(option);
    });
  }
  function fillTypes() {
    const box = root.querySelector("[data-type-chips]");
    const seen = {};
    (data.sections || []).forEach(function (section) {
      (section.parlays || []).forEach(function (ticket) {
        (ticket.legs || []).forEach(function (leg) { if (leg.type) seen[leg.type] = true; });
      });
    });
    Object.keys(seen).sort().forEach(function (type) {
      filters.types[type] = true;
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = type;
      button.setAttribute("aria-pressed", "true");
      button.setAttribute("data-filter-type", type);
      button.addEventListener("click", function () {
        const on = button.getAttribute("aria-pressed") !== "true";
        button.setAttribute("aria-pressed", on ? "true" : "false");
        filters.types[type] = on;
        apply();
      });
      box.appendChild(button);
    });
  }
  function fillPresetMenu() {
    const menu = root.querySelector("[data-preset-load]");
    const current = menu.value;
    menu.innerHTML = '<option value="">Choose a preset</option>';
    readPresets().forEach(function (preset, index) {
      if (preset.page !== "tier") return;
      const option = document.createElement("option");
      option.value = String(index);
      option.textContent = preset.name;
      menu.appendChild(option);
    });
    if (current) menu.value = current;
  }
  function snapshot() {
    syncFilters();
    return {
      page: "tier", name: "", sport: filters.sport, event: filters.event,
      minLegs: filters.minLegs, maxLegs: filters.maxLegs, minP: filters.minP, minEdge: filters.minEdge,
      style: filters.style, types: Object.assign({}, filters.types), include: filters.include,
      exclude: filters.exclude, marketOnly: filters.marketOnly, same: filters.same, sort: filters.sort
    };
  }
  function applyPreset(preset) {
    root.querySelector("[data-tier-sport]").value = preset.sport || "";
    root.querySelector("[data-tier-event]").value = preset.event || "";
    root.querySelector("[data-min-legs]").value = preset.minLegs;
    root.querySelector("[data-max-legs]").value = preset.maxLegs;
    root.querySelector("[data-min-p]").value = Math.round((preset.minP || 0) * 100);
    root.querySelector("[data-min-edge]").value = Math.round((preset.minEdge || 0) * 100);
    root.querySelector("[data-tier-include]").value = preset.include || "";
    root.querySelector("[data-tier-exclude]").value = preset.exclude || "";
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
    apply();
    announce("Loaded filter preset " + (preset.name || ""));
  }

  fillEvents();
  fillTypes();
  fillPresetMenu();
  root.querySelectorAll("[data-style]").forEach(function (button) {
    button.addEventListener("click", function () {
      filters.style = button.getAttribute("data-style");
      root.querySelectorAll("[data-style]").forEach(function (other) {
        other.setAttribute("aria-pressed", other === button ? "true" : "false");
      });
      apply();
    });
  });
  ["[data-tier-sport]", "[data-tier-event]", "[data-min-legs]", "[data-max-legs]", "[data-min-p]", "[data-min-edge]", "[data-tier-include]", "[data-tier-exclude]", "[data-sort]"].forEach(function (selector) {
    const el = root.querySelector(selector);
    el.addEventListener("input", apply);
    el.addEventListener("change", apply);
  });
  root.querySelector("[data-market-only]").addEventListener("click", function (event) {
    filters.marketOnly = event.currentTarget.getAttribute("aria-checked") !== "true";
    event.currentTarget.setAttribute("aria-checked", filters.marketOnly ? "true" : "false");
    apply();
  });
  root.querySelector("[data-same]").addEventListener("click", function (event) {
    filters.same = event.currentTarget.getAttribute("aria-checked") !== "true";
    event.currentTarget.setAttribute("aria-checked", filters.same ? "true" : "false");
    apply();
  });
  root.querySelector("[data-preset-save]").addEventListener("click", function () {
    const name = (root.querySelector("[data-preset-name]").value || "").trim();
    if (!name) { announce("Name the filter preset before saving."); return; }
    const presets = readPresets().filter(function (preset) { return !(preset.page === "tier" && preset.name === name); });
    const next = snapshot();
    next.name = name;
    presets.unshift(next);
    localStorage.setItem(PRESET_KEY, JSON.stringify(presets.slice(0, 30)));
    fillPresetMenu();
    announce("Saved filter preset " + name);
  });
  root.querySelector("[data-preset-load]").addEventListener("change", function (event) {
    const preset = readPresets()[Number(event.target.value)];
    if (preset && preset.page === "tier") applyPreset(preset);
  });
  root.querySelector("[data-tier-random]").addEventListener("click", shuffle);
  document.querySelectorAll("[data-open]").forEach(function (button) {
    button.addEventListener("click", function (event) {
      event.stopPropagation();
      const card = button.closest("[data-open-ticket]");
      const found = lookup[card.getAttribute("data-open-ticket")];
      if (!found) return;
      showSlip(found.section, found.ticket);
      announce("Ticket opened in the slip");
    });
  });
  const stakeEl = root.querySelector("[data-stake]");
  stakeEl.addEventListener("input", function () {
    stake = Math.max(0, Number(stakeEl.value) || 0);
    if (open) showSlip(open.section, open.ticket);
  });
  root.querySelectorAll("[data-chip]").forEach(function (chip) {
    chip.addEventListener("click", function () {
      stake = Number(chip.getAttribute("data-chip"));
      stakeEl.value = String(stake);
      root.querySelectorAll("[data-chip]").forEach(function (other) {
        other.setAttribute("aria-pressed", other === chip ? "true" : "false");
      });
      if (open) showSlip(open.section, open.ticket);
    });
  });
  root.querySelector("[data-clear]").addEventListener("click", clearSlip);
  root.querySelector("[data-save]").addEventListener("click", function () {
    if (!open) { announce("Open a ticket before saving."); return; }
    const slips = JSON.parse(localStorage.getItem(SLIP_KEY) || "[]");
    slips.unshift({
      id: Date.now().toString(36),
      savedAt: new Date().toISOString(),
      title: (open.section.title || "Parlay") + " · " + (data.label || ""),
      legs: (open.ticket.legs || []).map(function (leg) { return { label: leg.label, price: leg.price, why: leg.why }; }),
      decimal: open.ticket.decimal,
      p: open.ticket.p,
      result: "open"
    });
    localStorage.setItem(SLIP_KEY, JSON.stringify(slips.slice(0, 200)));
    const copied = root.querySelector("[data-copied]");
    copied.hidden = false;
    copied.textContent = "Saved to My slips.";
    announce("Saved to My slips");
  });
  const peek = root.querySelector("[data-peek]");
  if (peek) peek.addEventListener("click", function () {
    const slip = document.getElementById("slip");
    const isOpen = slip.classList.toggle("open");
    peek.setAttribute("aria-expanded", isOpen ? "true" : "false");
  });
  apply();
})();
