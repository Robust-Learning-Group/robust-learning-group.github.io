/* Theme toggle and publication filters. No dependencies. */
(function () {
  "use strict";

  // ---------- Theme ----------
  var root = document.documentElement;
  var toggle = document.querySelector(".theme-toggle");
  var media = window.matchMedia("(prefers-color-scheme: dark)");

  function currentTheme() {
    return root.dataset.theme || (media.matches ? "dark" : "light");
  }
  if (toggle) {
    toggle.addEventListener("click", function () {
      var next = currentTheme() === "dark" ? "light" : "dark";
      root.dataset.theme = next;
      try { localStorage.setItem("theme", next); } catch (e) {}
      document.dispatchEvent(new CustomEvent("themechange"));
    });
  }
  media.addEventListener("change", function () {
    document.dispatchEvent(new CustomEvent("themechange"));
  });

  // ---------- Theme preview picker (only present when theme_switcher is on) ----------
  var picker = document.getElementById("palette-select");
  if (picker && window.__paletteFonts) {
    picker.value = root.dataset.palette;
    picker.addEventListener("change", function () {
      var name = picker.value;
      (window.__paletteFonts[name] || []).forEach(function (href) {
        if (!document.querySelector('link[href="' + href + '"]')) {
          var l = document.createElement("link");
          l.rel = "stylesheet"; l.href = href;
          document.head.appendChild(l);
        }
      });
      root.dataset.palette = name;
      try { localStorage.setItem("palette", name); } catch (e) {}
      document.dispatchEvent(new CustomEvent("themechange"));
      // Redraw again once the new fonts have arrived
      if (document.fonts) document.fonts.ready.then(function () {
        document.dispatchEvent(new CustomEvent("themechange"));
      });
    });
  }

  // ---------- Publication filters ----------
  var chips = document.querySelectorAll(".chip[data-area]");
  var search = document.getElementById("pub-search");
  if (!chips.length || !search) return;

  var pubs = document.querySelectorAll(".pub[data-areas]");
  var groups = document.querySelectorAll("[data-year-group]");
  var status = document.getElementById("pub-status");
  var empty = document.getElementById("pub-empty");
  var area = "";

  function apply() {
    var q = search.value.trim().toLowerCase();
    var shown = 0;
    pubs.forEach(function (el) {
      var areas = el.dataset.areas.split(" ");
      var ok = (!area || areas.indexOf(area) !== -1) && (!q || el.dataset.search.indexOf(q) !== -1);
      el.hidden = !ok;
      if (ok) shown++;
    });
    groups.forEach(function (g) {
      g.hidden = !g.querySelector(".pub:not([hidden])");
    });
    empty.hidden = shown !== 0;
    status.textContent = (area || q) ? shown + " of " + pubs.length + " publications" : "";

    var params = new URLSearchParams(location.search);
    area ? params.set("area", area) : params.delete("area");
    var qs = params.toString();
    history.replaceState(null, "", location.pathname + (qs ? "?" + qs : ""));
  }

  function setArea(slug) {
    area = slug;
    chips.forEach(function (c) { c.setAttribute("aria-pressed", String(c.dataset.area === slug)); });
    apply();
  }

  chips.forEach(function (c) {
    c.addEventListener("click", function () { setArea(c.dataset.area); });
  });
  search.addEventListener("input", apply);

  var initial = new URLSearchParams(location.search).get("area") || "";
  var valid = Array.prototype.some.call(chips, function (c) { return c.dataset.area === initial; });
  setArea(valid ? initial : "");
})();
