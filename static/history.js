(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const LS_LAST_PREVIEW = "sm_last_preview";

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

  async function renderLastPreview() {
    let proposal = null;

    try {
      const res = await window.apiFetch("/api/preview/latest");
      if (res && res.ok) {
        const data = await res.json();
        proposal = data.proposal;
      }
    } catch (e) { /* ignore */ }

    if (!proposal || !Array.isArray(proposal.tracks) || !proposal.tracks.length) {
      try {
        const raw = localStorage.getItem(LS_LAST_PREVIEW);
        if (raw) proposal = JSON.parse(raw);
      } catch (e) { return; }
    }

    if (!proposal || !Array.isArray(proposal.tracks) || !proposal.tracks.length) return;

    const allTracks = proposal.tracks;
    const previewTracks = allTracks.slice(0, 3);
    const isFaded = allTracks.length > 3;

    const section = $("last-preview-section");
    if (section) section.classList.remove("hidden");

    $("lp-name").textContent = proposal.playlist_name || "Untitled";
    $("lp-meta").textContent =
      "Last preview · " + allTracks.length + " tracks" +
      (proposal.genre ? " · " + proposal.genre : "") +
      (proposal.deep_cuts ? " · deep cuts" : "");

    const ol = $("lp-tracks");
    ol.innerHTML = "";
    previewTracks.forEach((t, i) => {
      const li = document.createElement("li");
      const num = document.createElement("span");
      num.className = "track-num";
      num.textContent = String(i + 1);
      li.appendChild(num);
      if (t.tag) {
        const tag = document.createElement("span");
        tag.className = "track-tag";
        tag.textContent = t.tag;
        li.appendChild(tag);
      }
      const span = document.createElement("span");
      span.className = "track-text";
      span.textContent = t.artist + " – " + t.title;
      li.appendChild(span);
      ol.appendChild(li);
    });

    $("lp-preview").classList.toggle("faded", isFaded);

    const more = $("lp-more");
    if (isFaded) {
      more.textContent = "+" + (allTracks.length - 3) + " more";
      more.classList.remove("hidden");
    } else {
      more.classList.add("hidden");
    }

    $("lp-use").addEventListener("click", () => {
      location.href = "/?restore=1";
    });
  }

  async function boot() {
    const state = await window.initNav();
    if (!state) return;

    if ($("error-home")) {
      $("error-home").addEventListener("click", () => { location.href = "/"; });
    }

    try {
      await renderLastPreview();
    } catch (e) {
      console.error("last preview failed:", e);
    }

    let res;
    try {
      res = await window.apiFetch("/api/history");
      if (!res) return;
    } catch (e) {
      showError("could not reach server: " + e);
      return;
    }

    if (!res.ok) {
      showError("could not load history (HTTP " + res.status + ")");
      return;
    }

    let payload;
    try { payload = await res.json(); }
    catch (e) { showError("invalid response from server"); return; }

    const entries = Array.isArray(payload.entries) ? payload.entries : [];

    if (!entries.length) {
      const empty = $("empty");
      if (empty) empty.classList.remove("hidden");
      return;
    }

    render(entries);
  }

  function render(entries) {
    const list = $("list");
    list.innerHTML = "";

    for (const e of entries) {
      const card = document.createElement("div");
      card.className = "card history-card";

      const date = new Date(e.ts).toLocaleString();
      const allTracks = Array.isArray(e.tracks) ? e.tracks : [];
      const trackCount = allTracks.length;
      const previewTracks = allTracks.slice(0, 3);
      const isFaded = trackCount > 3;

      const previewHTML = previewTracks.map((t, i) =>
        "<li>" +
          '<span class="track-num">' + (i + 1) + "</span>" +
          (t.tag ? '<span class="track-tag">' + esc(t.tag) + "</span>" : "") +
          '<span class="track-text">' + esc(t.artist) + " – " + esc(t.title) + "</span>" +
        "</li>"
      ).join("");

      const moreHTML = isFaded
        ? '<div class="history-more">+' + (trackCount - 3) + " more</div>"
        : "";

      card.innerHTML =
        '<div class="history-head">' +
          "<div>" +
            "<h2>" + esc(e.playlist_name || "Untitled") + "</h2>" +
            '<div class="muted">' +
              esc(e.mood || "") + " · " + trackCount + " tracks · " + date +
              (e.public ? " · public" : "") +
              (e.deep_cuts ? " · deep cuts" : "") +
            "</div>" +
          "</div>" +
          '<div class="row">' +
            (e.spotify_url
              ? '<a class="btn" href="' + esc(e.spotify_url) + '" target="_blank">Open ↗</a>'
              : "") +
            '<button data-ts="' + esc(e.ts) + '" class="btn recreate">Recreate</button>' +
            '<button data-ts="' + esc(e.ts) + '" class="btn btn-danger delete">Delete</button>' +
          "</div>" +
        "</div>" +
        '<div class="history-preview' + (isFaded ? " faded" : "") + '">' +
          '<ol class="tracks">' + previewHTML + "</ol>" +
        "</div>" +
        moreHTML;

      list.appendChild(card);
    }

    list.querySelectorAll(".delete").forEach(btn => {
      btn.addEventListener("click", async () => {
        if (!confirm("Delete this entry?")) return;
        await window.apiFetch("/api/history/delete", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({ts: btn.dataset.ts}),
        });
        boot();
      });
    });

    list.querySelectorAll(".recreate").forEach(btn => {
      btn.addEventListener("click", async () => {
        if (!confirm("Re-create this playlist on Spotify?")) return;
        btn.disabled = true;
        btn.textContent = "creating…";
        try {
          const res = await window.apiFetch("/api/history/recreate", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({ts: btn.dataset.ts}),
          });
          if (!res) return;
          await res.text();
          boot();
        } catch (err) {
          alert("failed: " + err);
          btn.disabled = false;
          btn.textContent = "Recreate";
        }
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();