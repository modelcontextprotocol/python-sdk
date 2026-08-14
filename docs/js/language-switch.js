// The theme links each language-switcher entry to that language's home page.
// Point the entries at the current page on each language's site instead: every
// prose page exists at the same path on all of them. The API reference is
// English-only, so from there the entries keep pointing at the site roots.
// Instant navigation swaps the page but keeps the header, so re-run on every
// page the theme loads (`document$`) rather than once.
const base = JSON.parse(document.getElementById("__config").textContent).base;
// The site root as a directory path; `base` lacks the trailing slash on 404 pages.
const site = new URL(base.replace(/\/?$/, "/"), location).pathname;

document$.subscribe(() => {
  let page = location.pathname.slice(site.length);
  if (page.startsWith("api/")) page = "";
  for (const entry of document.querySelectorAll(".md-select__link[hreflang]")) {
    // The language root the theme rendered, relative to the page first shown.
    entry.dataset.site ??= new URL(entry.getAttribute("href"), location).pathname;
    entry.href = entry.dataset.site + page;
  }
});
