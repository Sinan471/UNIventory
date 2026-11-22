/*
 * UNIventory progressive enhancement (owner: Jesher).
 * Every page works without this file. Nothing here grants or hides access;
 * the server checks every action.
 */
(function () {
  "use strict";

  // ---- Theme toggle (dark default; choice kept in a first-party cookie) --
  document.querySelectorAll("[data-theme-toggle]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var root = document.documentElement;
      var next = root.getAttribute("data-theme") === "light" ? "dark" : "light";
      root.setAttribute("data-theme", next);
      document.cookie = "uv_theme=" + next + "; Max-Age=31536000; Path=/; SameSite=Lax";
    });
  });

  // ---- Menus (profile, mobile "more") --------------------------------
  document.querySelectorAll("[data-menu-button]").forEach(function (button) {
    var panel = document.getElementById(button.getAttribute("aria-controls"));
    if (!panel) return;
    function close(returnFocus) {
      panel.hidden = true;
      button.setAttribute("aria-expanded", "false");
      if (returnFocus) button.focus();
    }
    button.addEventListener("click", function () {
      var open = panel.hidden;
      panel.hidden = !open;
      button.setAttribute("aria-expanded", String(open));
      if (open) {
        var first = panel.querySelector("a, button");
        if (first) first.focus();
      }
    });
    document.addEventListener("click", function (e) {
      if (!panel.hidden && !panel.contains(e.target) && !button.contains(e.target)) close(false);
    });
    panel.addEventListener("keydown", function (e) {
      if (e.key === "Escape") close(true);
    });
  });

  // ---- Dialogs with focus return ---------------------------------------
  var lastOpener = null;
  document.querySelectorAll("[data-dialog-open]").forEach(function (opener) {
    var dialog = document.getElementById(opener.getAttribute("data-dialog-open"));
    if (!dialog || typeof dialog.showModal !== "function") return;
    opener.addEventListener("click", function (e) {
      e.preventDefault();
      lastOpener = opener;
      dialog.showModal();
      var focusTarget = dialog.querySelector("[autofocus], input:not([type=hidden]), select, textarea, button");
      if (focusTarget) focusTarget.focus();
    });
    dialog.addEventListener("close", function () {
      if (lastOpener) lastOpener.focus();
    });
  });
  document.querySelectorAll("[data-dialog-close]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var dialog = btn.closest("dialog");
      if (dialog) dialog.close();
    });
  });

  // ---- Tabs (WAI-ARIA tabs pattern) -----------------------------------
  document.querySelectorAll("[role=tablist]").forEach(function (list) {
    var tabs = Array.prototype.slice.call(list.querySelectorAll("[role=tab]"));
    function select(tab, focus, initial) {
      tabs.forEach(function (t) {
        var on = t === tab;
        t.setAttribute("aria-selected", String(on));
        t.tabIndex = on ? 0 : -1;
        var panel = document.getElementById(t.getAttribute("aria-controls"));
        if (panel) panel.hidden = !on;
      });
      if (focus) tab.focus();
      if (!initial && history.replaceState) history.replaceState(null, "", "#" + tab.getAttribute("aria-controls"));
    }
    tabs.forEach(function (tab, i) {
      tab.addEventListener("click", function (e) { e.preventDefault(); select(tab, false); });
      tab.addEventListener("keydown", function (e) {
        var rtl = document.documentElement.dir === "rtl";
        var next = { ArrowRight: rtl ? -1 : 1, ArrowLeft: rtl ? 1 : -1, Home: -i, End: tabs.length - 1 - i }[e.key];
        if (next === undefined) return;
        e.preventDefault();
        select(tabs[(i + next + tabs.length) % tabs.length], true);
      });
    });
    var hash = location.hash.slice(1);
    var initial = tabs.filter(function (t) { return t.getAttribute("aria-controls") === hash; })[0];
    select(initial || tabs.filter(function (t) { return t.getAttribute("aria-selected") === "true"; })[0] || tabs[0], false, true);
    // Panels are anchors only for no-JS use; keep the page at the top.
    if (initial && location.hash && window.scrollY > 0) window.scrollTo(0, 0);
  });

  // ---- Submit feedback: avoid accidental double clicks ------------------
  // Feedback only. Duplicate protection is the operation key on the server.
  document.querySelectorAll("form[method=post]").forEach(function (form) {
    form.addEventListener("submit", function () {
      var btn = form.querySelector("[type=submit]:not([data-no-busy])");
      if (!btn) return;
      setTimeout(function () { btn.setAttribute("aria-disabled", "true"); btn.disabled = true; }, 0);
    });
  });

  // ---- Asset editor: show only the selected category's specifications --
  var categorySelect = document.querySelector("[data-category-select]");
  if (categorySelect) {
    var groups = document.querySelectorAll("[data-spec-group]");
    var subList = document.getElementById("subcategory-options");
    var subData = {};
    try { subData = JSON.parse(document.getElementById("subcategory-data").textContent); } catch (e) { subData = {}; }
    function syncSpecs() {
      var id = categorySelect.value;
      groups.forEach(function (g) { g.hidden = g.getAttribute("data-spec-group") !== id; });
      var none = document.querySelector("[data-spec-none]");
      if (none) none.hidden = !!document.querySelector("[data-spec-group='" + id + "']");
      if (subList) {
        subList.innerHTML = "";
        (subData[id] || []).forEach(function (s) {
          var o = document.createElement("option");
          o.value = s;
          subList.appendChild(o);
        });
      }
    }
    categorySelect.addEventListener("change", syncSpecs);
    syncSpecs();
  }

  // ---- Individual vs batch quantity --------------------------------------
  var tracking = document.querySelectorAll("input[name=tracking_type]");
  var qty = document.getElementById("id_quantity");
  if (tracking.length && qty) {
    function syncQty() {
      var checked = document.querySelector("input[name=tracking_type]:checked");
      var individual = checked && checked.value === "INDIVIDUAL";
      if (individual) { qty.value = "1"; }
      qty.readOnly = individual;
      qty.setAttribute("aria-describedby", individual ? "qty-individual-note" : "");
      var note = document.getElementById("qty-individual-note");
      if (note) note.hidden = !individual;
    }
    tracking.forEach(function (r) { r.addEventListener("change", syncQty); });
    syncQty();
  }

  // ---- Remember catalogue view preference (per viewer convenience) -----
  try {
    var params = new URLSearchParams(location.search);
    if (document.querySelector("[data-catalogue]")) {
      if (params.get("view")) localStorage.setItem("univentory.view", params.get("view"));
      else if (localStorage.getItem("univentory.view") === "list" && !params.has("view")) {
        params.set("view", "list");
        location.replace(location.pathname + "?" + params.toString());
      }
    }
  } catch (e) { /* storage unavailable: default grid view */ }

  // ---- Multi-tab demo persona preservation -----------------------------
  // Keeps tabs isolated to their chosen demo accounts while sharing live data
  try {
    var searchParams = new URLSearchParams(window.location.search);
    var asUser = searchParams.get("as_user");
    if (asUser) {
      sessionStorage.setItem("uv_as_user", asUser);
    } else {
      asUser = sessionStorage.getItem("uv_as_user");
      if (asUser && !window.location.pathname.startsWith("/identity/sign-in")) {
        searchParams.set("as_user", asUser);
        if (history.replaceState) {
          var updated = window.location.pathname + "?" + searchParams.toString() + window.location.hash;
          history.replaceState(null, "", updated);
        }
      }
    }

    if (asUser && !window.location.pathname.startsWith("/identity/sign-in")) {
      document.addEventListener("click", function (e) {
        var a = e.target.closest("a");
        if (!a || !a.href || a.target === "_blank") return;
        try {
          var targetUrl = new URL(a.href, window.location.origin);
          if (targetUrl.origin === window.location.origin && !targetUrl.pathname.startsWith("/identity/sign-in")) {
            if (!targetUrl.searchParams.has("as_user")) {
              targetUrl.searchParams.set("as_user", asUser);
              a.href = targetUrl.pathname + targetUrl.search + targetUrl.hash;
            }
          }
        } catch (err) {}
      }, true);

      document.addEventListener("submit", function (e) {
        var form = e.target;
        if (!form) return;
        if (!form.querySelector("input[name='as_user']")) {
          var input = document.createElement("input");
          input.type = "hidden";
          input.name = "as_user";
          input.value = asUser;
          form.appendChild(input);
        }
      }, true);
    }
  } catch (err) { /* sessionStorage unavailable */ }
})();
