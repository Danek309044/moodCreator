(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const LS_LAST_PREVIEW = "sm_last_preview";
  const HISTORY_LIMIT = 5;

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function showError(msg) {
    const box = $("error-box");
    const txt = $("error-text");
    if (!box) return;
    if (txt) txt.textContent = msg; else box.textContent = msg;
    box.classList.remove("hidden");
  }

  function fmtDate(ts) {
    try {
      const d = new Date(ts);
      const pad = (n) => String(n).padStart(2, "0");
      return pad(d.getDate()) + "." + pad(d.getMonth() + 1) + "." + d.getFullYear() +
             ", " + pad(d.getHours()) + ":" + pad(d.getMinutes());
    } catch (e) { return ts; }
  }

  function trackPreviewHTML(tracks, count) {
    return tracks.slice(0, count).map(function (t, i) {
      return "<li>" +
        '<span class="track-num">' + (i + 1) + "</span>" +
        (t.tag ? '<span class="track-tag">' + esc(t.tag) + "</span>" : "") +
        '<span class="track-text">' + esc(t.artist) + " – " + esc(t.title) + "</span>" +
      "</li>";
    }).join("");
  }

  async function renderLastPreview() {
    let proposal = null;
    try {
      const res = await window.apiFetch("/api/preview/latest");
      if (res && res.ok) {
        const data = await res.json();
        proposal = data.proposal;
      }
    } catch (e) {}

    if (!proposal || !Array.isArray(proposal.tracks) || !proposal.tracks.length) {
      try {
        const raw = localStorage.getItem(LS_LAST_PREVIEW);
        if (raw) proposal = JSON.parse(raw);
      } catch (e) { return; }
    }
    if (!proposal || !Array.isArray(proposal.tracks) || !proposal.tracks.length) return;

    const allTracks = proposal.tracks;
    const isFaded = allTracks.length > 3;

    $("last-preview-section").classList.remove("hidden");
    $("lp-name").textContent = proposal.playlist_name || "Untitled";

    const metaParts = [allTracks.length + " tracks"];
    if (proposal.genre) metaParts.push(proposal.genre);
    if (proposal.deep_cuts) metaParts.push("deep cuts");
    if (proposal.public) metaParts.push("public");
    $("lp-meta").textContent = metaParts.join(" · ");

    $("lp-tracks").innerHTML = trackPreviewHTML(allTracks, 3);
    $("lp-preview").classList.toggle("faded", isFaded);

    const more = $("lp-more");
    if (isFaded) {
      more.textContent = "+" + (allTracks.length - 3) + " more";
      more.classList.remove("hidden");
    } else {
      more.classList.add("hidden");
    }

    $("lp-use").addEventListener("click", function () {
      location.href = "/?restore=1";
    });
  }

  async function boot() {
    const state = await window.initNav();
    if (!state) return;

    if ($("error-home")) {
      $("error-home").addEventListener("click", function () { location.href = "/"; });
    }

    try { await renderLastPreview(); }
    catch (e) { console.error("last preview failed:", e); }

    let res;
    try {
      res = await window.apiFetch("/api/history");
      if (!res) return;
    } catch (e) { showError("could not reach server: " + e); return; }

    if (!res.ok) { showError("could not load history (HTTP " + res.status + ")"); return; }

    let payload;
    try { payload = await res.json(); }
    catch (e) { showError("invalid response from server"); return; }

    let entries = Array.isArray(payload.entries) ? payload.entries : [];
    entries = entries.slice(0, HISTORY_LIMIT);

    if (!entries.length) {
      $("empty").classList.remove("hidden");
      return;
    }

    render(entries);
  }

  function render(entries) {
    const list = $("list");
    list.innerHTML = "";

    entries.forEach(function (e) {
      const card = document.createElement("div");
      card.className = "card history-card";

      const date = fmtDate(e.ts);
      const allTracks = Array.isArray(e.tracks) ? e.tracks : [];
      const trackCount = allTracks.length;
      const isFaded = trackCount > 3;

      const metaParts = [date, trackCount + " tracks"];
      if (e.genre) metaParts.push(e.genre);
      if (e.deep_cuts) metaParts.push("deep cuts");
      if (e.public) metaParts.push("public");
      const metaLine = metaParts.join(" · ");

      const previewHTML = trackPreviewHTML(allTracks, 3);
      const moreHTML = isFaded
        ? '<div class="history-more">+' + (trackCount - 3) + " more</div>"
        : "";

      const openBtn = e.spotify_url
        ? '<a class="btn history-btn history-btn-open" href="' + esc(e.spotify_url) +
          '" target="_blank" rel="noopener">Open ↗</a>'
        : "";
      const recreateBtn = '<button data-ts="' + esc(e.ts) +
                          '" class="btn history-btn recreate">Recreate</button>';
      const deleteBtn =
        '<button data-ts="' + esc(e.ts) +
        '" class="btn history-btn-icon delete" title="Delete">' +
        '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" ' +
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
        'stroke-linejoin="round" aria-hidden="true">' +
        '<polyline points="3 6 5 6 21 6"/>' +
        '<path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>' +
        '<path d="M10 11v6M14 11v6"/>' +
        '</svg></button>';

      card.innerHTML =
        '<div class="history-head">' +
          '<div class="history-info">' +
            "<h2>" + esc(e.playlist_name || "Untitled") + "</h2>" +
            '<div class="muted">' + esc(metaLine) + "</div>" +
          "</div>" +
          '<div class="history-actions">' +
            openBtn + recreateBtn + deleteBtn +
          "</div>" +
        "</div>" +
        '<div class="history-preview' + (isFaded ? " faded" : "") + '">' +
          '<ol class="tracks">' + previewHTML + "</ol>" +
        "</div>" +
        moreHTML;

      list.appendChild(card);
    });

    list.querySelectorAll(".delete").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const ts = btn.dataset.ts;
        window.showConfirm(
          "Delete entry?",
          "This will remove the history entry. The playlist on Spotify stays.",
          "Delete",
          async function () {
            const res = await window.apiFetch("/api/history/delete", {
              method: "POST",
              headers: {"Content-Type": "application/json"},
              body: JSON.stringify({ ts: ts }),
            });
            if (res && res.ok) {
              const card = btn.closest(".history-card");
              if (card) card.remove();
              if (!list.querySelectorAll(".history-card").length) {
                $("empty").classList.remove("hidden");
              }
            }
          },
          "danger"
        );
      });
    });

    list.querySelectorAll(".recreate").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const ts = btn.dataset.ts;
        window.showConfirm(
          "Recreate playlist?",
          "This will create a new playlist on Spotify with the same tracks.",
          "Recreate",
          async function () {
            btn.disabled = true;
            const original = btn.textContent;
            btn.textContent = "creating…";
            try {
              const res = await window.apiFetch("/api/history/recreate", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({ ts: ts }),
              });
              if (!res) return;
              await res.text();
              boot();
            } catch (err) {
              alert("failed: " + err);
              btn.disabled = false;
              btn.textContent = original;
            }
          }
        );
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();