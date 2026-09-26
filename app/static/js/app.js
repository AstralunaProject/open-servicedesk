(function () {
  "use strict";

  document.querySelectorAll("[data-toggle-sidebar]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.querySelector(".sidebar").classList.toggle("open");
    });
  });

  document.addEventListener("submit", function (ev) {
    var msg = ev.target.getAttribute("data-confirm");
    if (msg && !window.confirm(msg)) ev.preventDefault();
  });

  document.querySelectorAll("tr[data-href]").forEach(function (row) {
    row.addEventListener("click", function (ev) {
      if (ev.target.closest("a, button, input, select, label")) return;
      if (ev.ctrlKey || ev.metaKey) window.open(row.dataset.href, "_blank");
      else window.location = row.dataset.href;
    });
  });

  document.querySelectorAll("form[data-autosubmit] select").forEach(function (sel) {
    sel.addEventListener("change", function () { sel.form.submit(); });
  });

  var composer = document.querySelector(".composer");
  if (composer) {
    var input = composer.querySelector("input[name=internal]");
    var submit = composer.querySelector("[data-submit-label]");
    composer.querySelectorAll(".composer-tabs button").forEach(function (tab) {
      tab.addEventListener("click", function () {
        composer.querySelectorAll(".composer-tabs button").forEach(function (t) { t.classList.remove("active"); });
        tab.classList.add("active");
        var internal = tab.dataset.internal === "1";
        input.value = internal ? "1" : "0";
        composer.classList.toggle("internal", internal);
        if (submit) submit.textContent = internal ? "Salvar nota interna" : submit.dataset.submitLabel;
        var ta = composer.querySelector("textarea");
        ta.placeholder = internal ? "Nota visível somente para a equipe de T.I…" : "Escreva uma resposta ao solicitante…";
        ta.focus();
      });
    });
  }

  document.querySelectorAll("select[data-resolution-toggle]").forEach(function (sel) {
    var box = document.getElementById(sel.dataset.resolutionToggle);
    function sync() {
      var show = sel.value === "resolved";
      box.classList.toggle("hidden", !show);
      box.querySelectorAll("textarea").forEach(function (t) { t.required = show; });
    }
    sel.addEventListener("change", sync);
    sync();
  });

  var groupSel = document.querySelector("select[data-group-select]");
  var assigneeSel = document.querySelector("select[data-assignee-select]");
  if (groupSel && assigneeSel) {
    var sync = function () {
      var gid = groupSel.value;
      assigneeSel.querySelectorAll("option[data-groups]").forEach(function (opt) {
        var groups = opt.dataset.groups.split(",");
        var inGroup = !gid || groups.indexOf(gid) >= 0;
        opt.textContent = opt.dataset.name + (inGroup ? "" : "  (outro grupo)");
      });
    };
    groupSel.addEventListener("change", sync);
    sync();
  }

  document.querySelectorAll("input[type=file][data-file-list]").forEach(function (inp) {
    var out = document.getElementById(inp.dataset.fileList);
    inp.addEventListener("change", function () {
      out.textContent = Array.prototype.map.call(inp.files, function (f) { return f.name; }).join(", ");
    });
  });
})();
