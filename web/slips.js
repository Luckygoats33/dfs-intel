/* My slips: local results and a $1 running P&L. Nothing leaves the browser. */
(function () {
  const KEY = "dfs-intel-slips-v1";
  const rowsEl = document.getElementById("slip-rows");
  if (!rowsEl) return;
  function load() {
    try { return JSON.parse(localStorage.getItem(KEY) || "[]"); }
    catch (err) { return []; }
  }
  function save(slips) {
    localStorage.setItem(KEY, JSON.stringify(slips.slice(0, 200)));
  }
  function profit(slip) {
    const decimal = Number(slip.decimal);
    if (!decimal || decimal <= 1) return null;
    if (slip.result === "won") return decimal - 1;
    if (slip.result === "lost") return -1;
    return null;
  }
  function american(decimal) {
    if (!decimal || decimal <= 1) return "";
    if (decimal >= 2) return "+" + Math.round((decimal - 1) * 100);
    return String(Math.round(-100 / (decimal - 1)));
  }
  function when(iso) {
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "unavailable";
    return new Intl.DateTimeFormat("en-US", {
      timeZone: "America/Los_Angeles",
      month: "short", day: "numeric", hour: "numeric", minute: "2-digit"
    }).format(date) + " PT";
  }
  function money(value) {
    const sign = value > 0 ? "+" : value < 0 ? "−" : "";
    return sign + "$" + Math.abs(value).toFixed(2);
  }
  function render() {
    const slips = load();
    const settled = slips.map(profit).filter(function (value) { return value != null; });
    const total = settled.reduce(function (sum, value) { return sum + value; }, 0);
    const pnl = document.getElementById("slip-pnl");
    pnl.textContent = money(total);
    pnl.classList.toggle("up", total > 0);
    pnl.classList.toggle("down", total < 0);
    const open = slips.length - settled.length;
    document.getElementById("slip-meta").textContent = settled.length + " settled at $1 stakes. " + open + " still open. Open slips stay out of the P&L.";
    if (!slips.length) {
      rowsEl.innerHTML = "<tr><td colspan='5'>No saved slips. Open a ticket and choose Save to My slips.</td></tr>";
      return;
    }
    rowsEl.innerHTML = slips.map(function (slip, index) {
      const legs = (slip.legs || []).map(function (leg) { return leg.label; }).join("; ");
      const result = slip.result || "open";
      return "<tr><td>" + when(slip.savedAt) + "</td><td>" + escapeHtml(slip.title || "Parlay") +
        "<span class='why'>" + escapeHtml(legs) + "</span></td><td>" + escapeHtml(american(Number(slip.decimal))) +
        "</td><td>" + (slip.legs || []).length + "</td><td><div class='slip-row-actions'>" +
        button(index, "won", "Won", result) + button(index, "lost", "Lost", result) + button(index, "open", "Open", result) +
        "</div></td></tr>";
    }).join("");
    rowsEl.querySelectorAll("[data-mark]").forEach(function (buttonEl) {
      buttonEl.addEventListener("click", function () {
        const slipsNow = load();
        const slip = slipsNow[Number(buttonEl.getAttribute("data-index"))];
        if (!slip) return;
        slip.result = buttonEl.getAttribute("data-mark");
        save(slipsNow);
        render();
      });
    });
  }
  function button(index, value, label, current) {
    const on = current === value ? "true" : "false";
    return "<button type='button' data-mark='" + value + "' data-index='" + index + "' aria-pressed='" + on + "'>" + label + "</button>";
  }
  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }
  function cell(value) {
    const text = value == null ? "" : String(value);
    if (/[",\n]/.test(text)) return '"' + text.replace(/"/g, '""') + '"';
    return text;
  }
  document.getElementById("slip-export").addEventListener("click", function () {
    const lines = ["saved_at_pt,title,decimal,american,model_p,result,profit_at_1,legs"];
    load().forEach(function (slip) {
      const gained = profit(slip);
      const legs = (slip.legs || []).map(function (leg) { return leg.label; }).join(" | ");
      lines.push([
        when(slip.savedAt), slip.title || "", slip.decimal, american(Number(slip.decimal)),
        slip.p == null ? "" : slip.p, slip.result || "open", gained == null ? "" : gained.toFixed(4), legs
      ].map(cell).join(","));
    });
    const blob = new Blob([lines.join("\n")], { type: "text/csv" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "dfs-intel-slips.csv";
    document.body.appendChild(link);
    link.click();
    link.remove();
  });
  render();
})();
