(function () {
  const dataNode = document.getElementById("parlay-data");
  const root = document.querySelector("[data-parlay]");
  if (!dataNode || !root) return;

  const stakeInput = root.querySelector("[data-stake]");
  const filterInput = root.querySelector("[data-filter50]");
  const result = root.querySelector("[data-result]");
  const picker = root.querySelector("[data-slate-picker]");

  function money(n) {
    if (n == null || Number.isNaN(n)) return "—";
    return (n < 0 ? "-$" : "$") + Math.abs(n).toFixed(2);
  }

  function american(dec) {
    if (dec == null || dec <= 1) return "unavailable";
    if (dec >= 2) return "+" + Math.round((dec - 1) * 100);
    return String(Math.round(-100 / (dec - 1)));
  }

  function activeSlate() {
    const id = picker ? picker.value : root.dataset.slate;
    return root.querySelector('[data-slate-panel="' + id + '"]');
  }

  function checkedLegs(panel) {
    return Array.from(panel.querySelectorAll("input[data-leg]:checked"));
  }

  function render() {
    const panel = activeSlate();
    if (!panel || !result) return;
    const legs = checkedLegs(panel);
    const stake = Math.max(0, Number(stakeInput && stakeInput.value !== "" ? stakeInput.value : 1) || 0);
    const filterOn = !!(filterInput && filterInput.checked);
    root.querySelectorAll("[data-preset]").forEach(function (el) {
      const onThis = !picker || el.dataset.slate === (picker ? picker.value : root.dataset.slate);
      const pays = el.dataset.pays50 === "1";
      el.hidden = !onThis || (filterOn && !pays);
    });
    if (!legs.length) {
      result.innerHTML = "<p>Pick at least one leg. Combined odds stay blank until you do.</p>";
      return;
    }
    let dec = 1;
    let implied = 1;
    legs.forEach(function (el) {
      dec *= Number(el.dataset.decimal);
      implied *= Number(el.dataset.novig);
    });
    const payout = stake * dec;
    const profit = payout - stake;
    const pays = dec >= 50;
    result.innerHTML =
      "<dl>" +
      "<div><dt>Combined American</dt><dd>" + american(dec) + "</dd></div>" +
      "<div><dt>Combined decimal</dt><dd>" + dec.toFixed(3) + "</dd></div>" +
      "<div><dt>Implied chance</dt><dd>" + (implied * 100).toFixed(2) + "%</dd></div>" +
      "<div><dt>Payout</dt><dd>" + money(payout) + "</dd></div>" +
      "<div><dt>Profit</dt><dd>" + money(profit) + "</dd></div>" +
      "<div><dt>Pays $50+ on $1</dt><dd>" + (pays ? "yes" : "no") + "</dd></div>" +
      "</dl>" +
      "<p class=\"fine\">Implied chance multiplies no-vig probabilities and assumes the legs are independent. Fights and games on the same card are correlated, so this chance is not a calibrated probability. Combined odds are the product of the listed moneylines (vig still inside each leg). A sportsbook parlay price will differ.</p>";
  }

  root.addEventListener("change", function (event) {
    const input = event.target;
    if (input && input.matches("input[data-leg]") && input.checked) {
      const panel = input.closest("[data-slate-panel]");
      panel.querySelectorAll('input[data-group="' + input.dataset.group + '"]').forEach(function (other) {
        if (other !== input) other.checked = false;
      });
    }
    if (picker && event.target === picker) {
      root.querySelectorAll("[data-slate-panel]").forEach(function (panel) {
        panel.hidden = panel.dataset.slatePanel !== picker.value;
      });
    }
    render();
  });

  root.addEventListener("click", function (event) {
    const btn = event.target.closest("[data-preset]");
    if (!btn) return;
    const panel = root.querySelector('[data-slate-panel="' + btn.dataset.slate + '"]');
    if (!panel) return;
    const ids = (btn.dataset.legIds || "").split(",").filter(Boolean);
    panel.querySelectorAll("input[data-leg]").forEach(function (el) {
      el.checked = ids.indexOf(el.dataset.leg) !== -1;
    });
    render();
  });

  if (picker) {
    root.querySelectorAll("[data-slate-panel]").forEach(function (panel) {
      panel.hidden = panel.dataset.slatePanel !== picker.value;
    });
  }
  render();
})();
