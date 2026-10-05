"use strict";
const search = document.getElementById("search");
const filter = document.getElementById("filter");
const rows = [...document.querySelectorAll("tbody tr[data-search]")];
function applyFilter() {
  const query = search.value.toLocaleLowerCase();
  let visible = 0;
  for (const row of rows) {
    const active = row.dataset.active === "true";
    const verified = row.dataset.verified === "true";
    const selected = filter.value === "all" || (active &&
      (filter.value === "active" || (filter.value === "verified" ? verified : !verified)));
    row.hidden = !selected || !row.dataset.search.includes(query);
    if (!row.hidden) visible++;
  }
  document.getElementById("no-matches").hidden = visible > 0 || rows.length === 0;
}
search.addEventListener("input", applyFilter);
filter.addEventListener("change", applyFilter);
function revealTarget() {
  const row = document.getElementById(location.hash.slice(1));
  if (row && row.matches("tr[data-search]")) {
    filter.value = "all";
    search.value = "";
    applyFilter();
    row.querySelector("details").open = true;
    row.scrollIntoView({block: "center"});
  }
}
applyFilter();
revealTarget();
window.addEventListener("hashchange", revealTarget);
const age = Date.now() - Date.parse(document.body.dataset.updated);
document.getElementById("stale").hidden = document.body.dataset.lifecycle !== "running" || age < Number(document.body.dataset.staleAfter || 1800) * 1000;
// Do not discard an in-progress search or an expanded proof while someone reads it.
setInterval(() => {
  if (!search.value && filter.value === "active" && !document.querySelector("details[open]") && document.activeElement !== search && document.activeElement !== filter) {
    location.reload();
  }
}, 60000);
