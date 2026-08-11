// The theme links each language-switcher entry to that language's home page.
// Point the entries at the current page on each language's site instead: every
// prose page exists at the same path on all of them. The API reference is
// English-only, so from there the entries keep pointing at the site roots.
// Instant navigation swaps the page but keeps the header, so re-run on every
// page the theme loads (`document$`) rather than once.
const base = JSON.parse(document.getElementById("__config").textContent).base;
// The site root as a directory path; `base` lacks the trailing slash on 404 pages.
const site = new URL(base.replace(/\/?$/, "/"), location).pathname;
const entries = ".md-select__link[hreflang]";

function samePage(entry) {
  const page = location.pathname.slice(site.length);
  return entry.dataset.site + (page.startsWith("api/") ? "" : page);
}

document$.subscribe(() => {
  for (const entry of document.querySelectorAll(entries)) {
    entry.dataset.site ??= entry.getAttribute("href"); // the language root the theme rendered
    entry.href = samePage(entry);
  }
});

// Headings carry the same ids on every site, so the reader's place carries over
// too: query and fragment as they are when the switch happens, not at page load.
function aim(event) {
  const entry = event.target instanceof Element ? event.target.closest(entries) : null;
  if (entry?.dataset.site && (event.type !== "keydown" || event.key === "Enter"))
    entry.href = samePage(entry) + location.search + location.hash;
}
for (const type of ["click", "auxclick", "keydown"]) document.addEventListener(type, aim, true);
