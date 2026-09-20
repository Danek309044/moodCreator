(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);

  function buildHeader() {
    return `
      <a href="/" class="brand">moodCreator</a>
      <div class="menu">
        <button type="button" class="avatar-button" id="menu-trigger"
                aria-haspopup="true" aria-expanded="false">
          <span id="menu-user">·</span>
        </button>
        <div class="menu-items hidden" id="menu-items">
          <a href="/">New playlist</a>
          <a href="/history">History</a>
          <a href="/settings">Settings</a>
          <div class="menu-sep"></div>
          <a href="/auth/logout" class="menu-danger">Log out</a>
        </div>
      </div>
    `;
  }

  async function apiFetch(url, options) {
    const res = await fetch(url, options);
    if (res.status === 401) {
      location.href = "/login";
      return null;
    }
    return res;
  }

  async function initNav() {
    const header = document.querySelector("header.app-header");
    if (!header) return null;

    header.innerHTML = buildHeader();

    const trigger = $("menu-trigger");
    const items = $("menu-items");

    trigger.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const open = !items.classList.contains("hidden");
      items.classList.toggle("hidden", open);
      trigger.setAttribute("aria-expanded", String(!open));
    });

    document.addEventListener("click", (e) => {
      if (items.classList.contains("hidden")) return;
      if (items.contains(e.target) || trigger.contains(e.target)) return;
      items.classList.add("hidden");
      trigger.setAttribute("aria-expanded", "false");
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        items.classList.add("hidden");
        trigger.setAttribute("aria-expanded", "false");
      }
    });

    let state;
    try {
      const res = await apiFetch("/api/state");
      if (!res) return null;
      state = await res.json();
    } catch (err) {
      console.error("nav: state fetch failed", err);
      return null;
    }

    if (!state.configured) { location.href = "/setup"; return null; }
    if (!state.authed)     { location.href = "/login"; return null; }

    const slot = $("menu-user");
    if (state.profile && state.profile.image) {
      slot.innerHTML = "";
      const img = document.createElement("img");
      img.src = state.profile.image;
      img.alt = state.profile.display_name || "";
      slot.appendChild(img);
    } else {
      const source = (state.profile && state.profile.display_name) || state.user_id || "?";
      slot.textContent = source[0].toUpperCase();
    }

    return state;
  }

  window.apiFetch = apiFetch;
  window.initNav = initNav;
})();