(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);

  let lastProposal = null;
  let lastError = null;
  let selectedCount = 15;
  let deepCuts = false;
  let isPublic = false;
  let activeAbort = null;

  const LS = {
    count:       "sm_count",
    deepCuts:    "sm_deep_cuts",
    isPublic:    "sm_public",
    lastMood:    "sm_last_mood",
    lastPreview: "sm_last_preview",
    moodHistory: "sm_mood_history",
  };

  const MOOD_HISTORY_MAX = 20;

  function show() {
    const names = Array.prototype.slice.call(arguments);
    const stages = {
      input:   $("input-stage"),
      stream:  $("stream-stage"),
      preview: $("preview-stage"),
      result:  $("result-stage"),
    };
    Object.keys(stages).forEach(function (k) {
      const el = stages[k];
      if (el) el.classList.toggle("hidden", names.indexOf(k) === -1);
    });
  }

  function setError(msg) {
    const box = $("error-box");
    const txt = $("error-text");
    if (!box) return;
    if (!msg) { box.classList.add("hidden"); return; }
    if (txt) { txt.textContent = msg; } else { box.textContent = msg; }
    box.classList.remove("hidden");
  }

  function loadPrefs() {
    const c = parseInt(localStorage.getItem(LS.count) || "15", 10);
    if (!isNaN(c) && c >= 5 && c <= 100) selectedCount = c;
    deepCuts = localStorage.getItem(LS.deepCuts) === "1";
    isPublic = localStorage.getItem(LS.isPublic) === "1";

    const lastMood = localStorage.getItem(LS.lastMood) || "";
    if ($("mood")) $("mood").placeholder = lastMood || "mood";

    if ($("deep-cuts")) $("deep-cuts").checked = deepCuts;
    if ($("public-toggle")) $("public-toggle").checked = isPublic;
    updateCountButtons();
    refreshMoodDatalist();
  }

  function savePrefs() {
    localStorage.setItem(LS.count, String(selectedCount));
    localStorage.setItem(LS.deepCuts, deepCuts ? "1" : "0");
    localStorage.setItem(LS.isPublic, isPublic ? "1" : "0");
  }

  function updateCountButtons() {
    let matched = false;
    const pills = document.querySelectorAll("#count-buttons .count-pill:not(.count-custom)");
    Array.prototype.forEach.call(pills, function (b) {
      const n = parseInt(b.dataset.count, 10);
      const sel = n === selectedCount;
      b.classList.toggle("selected", sel);
      if (sel) matched = true;
    });
    const custom = $("count-custom");
    if (!custom) return;
    custom.classList.toggle("selected", !matched);
    if (!matched && document.activeElement !== custom) {
      custom.value = String(selectedCount);
    } else if (matched) {
      custom.value = "";
    }
    custom.classList.remove("over");
  }

  function refreshMoodDatalist() {
    const dl = $("mood-history");
    if (!dl) return;
    let list = [];
    try { list = JSON.parse(localStorage.getItem(LS.moodHistory) || "[]"); }
    catch (e) { list = []; }
    dl.innerHTML = "";
    list.forEach(function (m) {
      const opt = document.createElement("option");
      opt.value = m;
      dl.appendChild(opt);
    });
  }

  function pushMoodHistory(mood) {
    if (!mood) return;
    let list = [];
    try { list = JSON.parse(localStorage.getItem(LS.moodHistory) || "[]"); }
    catch (e) { list = []; }
    const filtered = list.filter(function (x) { return x !== mood; });
    filtered.unshift(mood);
    list = filtered.slice(0, MOOD_HISTORY_MAX);
    localStorage.setItem(LS.moodHistory, JSON.stringify(list));
    refreshMoodDatalist();
  }

  function wireCountButtons() {
    const pills = document.querySelectorAll("#count-buttons .count-pill:not(.count-custom)");
    Array.prototype.forEach.call(pills, function (btn) {
      btn.addEventListener("click", function () {
        selectedCount = parseInt(btn.dataset.count, 10);
        updateCountButtons();
        savePrefs();
      });
    });
  }

  function wireCustomCount() {
    const custom = $("count-custom");
    if (!custom) return;

    custom.addEventListener("focus", function () {
      if (custom.value) custom.select();
    });

    custom.addEventListener("input", function () {
      const cleaned = custom.value.replace(/[^0-9]/g, "");
      if (cleaned !== custom.value) {
        const pos = custom.selectionStart - (custom.value.length - cleaned.length);
        custom.value = cleaned;
        try { custom.setSelectionRange(pos, pos); } catch (e) {}
      }
      const v = parseInt(cleaned, 10);
      const over = !isNaN(v) && v > 100;
      custom.classList.toggle("over", over);
      if (!isNaN(v) && v >= 5 && v <= 100) {
        selectedCount = v;
        const pills = document.querySelectorAll("#count-buttons .count-pill:not(.count-custom)");
        Array.prototype.forEach.call(pills, function (b) { b.classList.remove("selected"); });
        custom.classList.add("selected");
      }
    });

    custom.addEventListener("blur", function () {
      const raw = custom.value.trim();
      if (raw === "") { updateCountButtons(); return; }
      let v = parseInt(raw, 10);
      if (isNaN(v)) { updateCountButtons(); return; }
      if (v < 5) v = 5;
      if (v > 100) v = 100;
      custom.value = String(v);
      custom.classList.remove("over");
      selectedCount = v;
      updateCountButtons();
      savePrefs();
    });

    custom.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();
        custom.blur();
        runPreview([]);
      }
    });
  }

  function wireToggles() {
    if ($("deep-cuts")) {
      $("deep-cuts").addEventListener("change", function (e) {
        deepCuts = e.target.checked;
        savePrefs();
      });
    }
    if ($("public-toggle")) {
      $("public-toggle").addEventListener("change", function (e) {
        isPublic = e.target.checked;
        savePrefs();
      });
    }
  }

  function wireMoodInput() {
    if (!$("mood")) return;
    $("mood").addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        runPreview([]);
      }
    });
  }

  function wireButtons() {
    if ($("generate")) {
      $("generate").addEventListener("click", function () { runPreview([]); });
    }
    if ($("regen")) {
      $("regen").addEventListener("click", function () {
        const avoid = lastProposal ? lastProposal.tracks : [];
        runPreview(avoid);
      });
    }
    if ($("create")) $("create").addEventListener("click", runCreate);
    if ($("again")) $("again").addEventListener("click", backToInput);
    if ($("error-home")) $("error-home").addEventListener("click", backToInput);
    if ($("stream-cancel")) $("stream-cancel").addEventListener("click", cancelStream);
    if ($("copy-list")) $("copy-list").addEventListener("click", copyTracklist);
    if ($("pv-name")) {
      $("pv-name").addEventListener("keydown", function (e) {
        if (e.key === "Enter") { e.preventDefault(); $("pv-name").blur(); }
      });
    }
  }

  function wireGlobalKeys() {
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        const streamEl = $("stream-stage");
        if (streamEl && !streamEl.classList.contains("hidden")) {
          e.preventDefault();
          cancelStream();
        }
      }
    });
  }

  function boot() {
    loadPrefs();
    wireCountButtons();
    wireCustomCount();
    wireToggles();
    wireMoodInput();
    wireButtons();
    wireGlobalKeys();

    window.initNav().then(function (state) {
      if (!state) return;
      if ($("generate")) $("generate").disabled = false;

      const url = new URL(location.href);
      if (url.searchParams.get("restore") === "1") {
        window.apiFetch("/api/preview/latest").then(function (res) {
          if (!res || !res.ok) return null;
          return res.json();
        }).then(function (data) {
          if (data && data.proposal && Array.isArray(data.proposal.tracks)
              && data.proposal.tracks.length) {
            lastProposal = data.proposal;
            renderPreview(data.proposal);
          }
        }).catch(function () {});
        history.replaceState({}, "", "/");
      }
    });
  }

  function cancelStream() {
    if (activeAbort) {
      try { activeAbort.abort(); } catch (e) {}
      activeAbort = null;
    }
    show("input");
  }

  function streamPost(url, body, onEvent) {
    activeAbort = new AbortController();
    const signal = activeAbort.signal;

    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: signal
    }).then(function (res) {
      if (res.status === 401) {
        location.href = "/login";
        return null;
      }
      if (!res.ok || !res.body) {
        activeAbort = null;
        return res.text().then(function (detail) {
          throw new Error("HTTP " + res.status + (detail ? " — " + detail : ""));
        });
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      function pump() {
        return reader.read().then(function (r) {
          if (r.done) {
            activeAbort = null;
            return;
          }
          buffer += decoder.decode(r.value, { stream: true });
          const chunks = buffer.split("\n\n");
          buffer = chunks.pop();
          for (let i = 0; i < chunks.length; i++) {
            const line = chunks[i].trim();
            if (line.indexOf("data:") !== 0) continue;
            try { onEvent(JSON.parse(line.slice(5).trim())); } catch (e) {}
          }
          return pump();
        });
      }
      return pump();
    });
  }

  function appendLog(text, cls) {
    const log = $("stream-log");
    if (!log) return;
    const div = document.createElement("div");
    div.className = "log-line " + (cls || "");
    div.textContent = text;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
  }

  function clearLog() {
    if ($("stream-log")) $("stream-log").innerHTML = "";
  }

  function handleEvent(evt) {
    const e = evt.event;
    if (e === "checking_keys") { appendLog("validating API keys"); }
    else if (e === "parse_started") {
      if ($("stream-status")) $("stream-status").textContent = "parsing mood…";
      appendLog("parsing mood");
    }
    else if (e === "parsed") {
      appendLog("  → artists: " + ((evt.artists || []).join(", ") || "—"));
      appendLog("  → genres:  " + ((evt.genres || []).join(", ") || "—"));
      if (evt.language) appendLog("  → language: " + evt.language);
    }
    else if (e === "resolve_started") {
      appendLog("  → resolving artist names with context…");
    }
    else if (e === "resolved") {
      const map = evt.resolved || {};
      const keys = Object.keys(map);
      keys.forEach(function (raw) {
        appendLog("    " + raw + " → " + map[raw]);
      });
      if (evt.dropped && evt.dropped.length) {
        appendLog("    dropped: " + evt.dropped.join(", "));
      }
    }
    else if (e === "seeds_started") {
      appendLog("  → resolving anchor artists…");
    }
    else if (e === "seeds") {
      appendLog("  → anchor artists: " + ((evt.artists || []).join(", ") || "none found"));
    }
    else if (e === "agent_started") {
      if ($("stream-status")) $("stream-status").textContent = "asking the agent…";
      appendLog("agent budget: " + evt.budget + " calls" +
                (evt.deep_cuts ? " · deep cuts" : ""));
    }
    else if (e === "tool") {
      let argStr = "";
      if (evt.args) {
        const keys = Object.keys(evt.args);
        argStr = keys.map(function (k) {
          return k + "=" + JSON.stringify(evt.args[k]);
        }).join(", ");
      }
      appendLog("[" + evt.step + "/" + evt.budget + "] " +
                evt.name + "(" + argStr + ") → " + evt.summary);
    }
    else if (e === "tool_cached") { appendLog("   (cached) " + evt.name); }
    else if (e === "agent_submitted") { appendLog("agent submitted " + evt.count + " tracks"); }
    else if (e === "avoided_filtered") { appendLog("filtered " + evt.count + " duplicate(s)", "warn"); }
    else if (e === "budget_exceeded") { appendLog("budget exceeded — forcing submit", "warn"); }
    else if (e === "empty_streak_nudge") { appendLog("empty results — nudging agent to submit", "warn"); }
    else if (e === "last_chance") { appendLog("no usable results — forcing submission", "warn"); }
    else if (e === "tagging_start") { appendLog("tagging " + evt.total + " track(s)…"); }
    else if (e === "spotify_auth") {
      if ($("stream-status")) $("stream-status").textContent = "authenticating with Spotify…";
      appendLog("spotify auth");
    }
    else if (e === "spotify_search_start") {
      if ($("stream-status")) $("stream-status").textContent = "searching Spotify…";
      appendLog("matching " + evt.total + " tracks on Spotify");
    }
    else if (e === "spotify_search") {
      const mark = evt.hit ? "✓" : "✗";
      appendLog("[" + evt.i + "/" + evt.total + "] " + mark + " " +
                evt.artist + " – " + evt.title, evt.hit ? "" : "warn");
    }
    else if (e === "catalog_start") { appendLog("filling " + evt.count + " gap(s)"); }
    else if (e === "catalog_pick") { appendLog("  ↳ " + evt.artist + " – " + evt.title); }
    else if (e === "spotify_create") {
      if ($("stream-status")) $("stream-status").textContent = "creating playlist…";
      appendLog("creating playlist on Spotify");
    }
    else if (e === "final") {
      if (evt.result && evt.result.spotify_url) {
        renderResult(evt.result);
      } else {
        lastProposal = evt.result;
        try { localStorage.setItem(LS.lastPreview, JSON.stringify(evt.result)); } catch (err) {}
        renderPreview(evt.result);
      }
    }
    else if (e === "error") {
      lastError = evt.message || "unknown error";
      appendLog("error: " + lastError, "error");
    }
  }

  function renderPreview(result) {
    if ($("pv-name")) $("pv-name").textContent = result.playlist_name || "Untitled";
    if ($("pv-meta")) {
      $("pv-meta").textContent =
        result.tracks.length + " of " + result.count_requested + " tracks" +
        (result.genre ? " · " + result.genre : "") +
        (result.deep_cuts ? " · deep cuts" : "");
    }
    renderTracks(result.tracks || []);
    show("preview");
  }

  function renderTracks(tracks) {
    const ol = $("pv-tracks");
    if (!ol) return;
    ol.innerHTML = "";

    if (!tracks.length) {
      const empty = document.createElement("li");
      empty.className = "empty-hint";
      empty.textContent = "No tracks returned. Last.fm may not know the requested artists, " +
                          "or all matches were filtered out.";
      ol.appendChild(empty);
      return;
    }

    tracks.forEach(function (t, i) {
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

      const open = document.createElement("a");
      open.className = "track-open";
      open.href = "https://open.spotify.com/search/" +
                  encodeURIComponent(t.artist + " " + t.title);
      open.target = "_blank";
      open.rel = "noopener";
      open.title = "Open in Spotify";
      open.innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" ' +
                       'stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
                       'stroke-linejoin="round" aria-hidden="true">' +
                       '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>' +
                       '<path d="M15 3h6v6"/><path d="M10 14L21 3"/></svg>';
      li.appendChild(open);

      const btn = document.createElement("button");
      btn.className = "track-remove";
      btn.textContent = "×";
      btn.title = "Remove";
      btn.addEventListener("click", function () {
        lastProposal.tracks.splice(i, 1);
        try { localStorage.setItem(LS.lastPreview, JSON.stringify(lastProposal)); } catch (err) {}
        window.apiFetch("/api/preview/save", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ proposal: lastProposal })
        }).catch(function () {});
        renderPreview(lastProposal);
      });
      li.appendChild(btn);

      ol.appendChild(li);
    });
  }

  function renderResult(result) {
    if ($("rs-meta")) {
      $("rs-meta").textContent =
        result.tracks.length + " tracks added to “" + result.playlist_name + "”" +
        (result.catalog_filled ? " (" + result.catalog_filled + " filled)" : "");
    }
    if ($("rs-link")) $("rs-link").href = result.spotify_url;
    show("result");
  }

  function copyTracklist() {
    if (!lastProposal || !lastProposal.tracks) return;
    const text = lastProposal.tracks.map(function (t) {
      return t.artist + " – " + t.title;
    }).join("\n");

    navigator.clipboard.writeText(text).then(function () {
      flashButton($("copy-list"), "Copied!");
    }).catch(function () {
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
        flashButton($("copy-list"), "Copied!");
      } catch (err) {
        setError("couldn't copy — " + err);
      }
      document.body.removeChild(ta);
    });
  }

  function flashButton(btn, text) {
    if (!btn) return;
    const original = btn.textContent;
    btn.textContent = text;
    btn.disabled = true;
    setTimeout(function () {
      btn.textContent = original;
      btn.disabled = false;
    }, 1200);
  }

  function runPreview(avoid) {
    avoid = avoid || [];
    let mood = $("mood") ? $("mood").value.trim() : "";
    if (!mood && $("mood")) {
      const ph = ($("mood").placeholder || "").trim();
      if (ph && ph !== "mood") mood = ph;
    }
    if (!mood) { setError("enter a mood"); return; }

    setError(null);
    lastError = null;
    clearLog();
    show("stream");
    if ($("stream-status")) $("stream-status").textContent = "starting…";

    streamPost("/api/preview",
               { mood: mood, count: selectedCount, avoid: avoid, deep_cuts: deepCuts },
               handleEvent
    ).then(function () {
      if (lastError) { setError(lastError); return; }
      if (!lastProposal) {
        show("input");
        setError("no result returned");
      } else if ((lastProposal.tracks || []).length > 0) {
        localStorage.setItem(LS.lastMood, mood);
        pushMoodHistory(mood);
        if ($("mood")) $("mood").placeholder = mood;
      }
    }).catch(function (e) {
      if (e && e.name === "AbortError") { show("input"); return; }
      setError(String(e));
      show("input");
    });
  }

  function runCreate() {
    if (!lastProposal) { setError("nothing to create"); return; }
    let mood = $("mood") ? $("mood").value.trim() : "";
    if (!mood && $("mood")) {
      const ph = ($("mood").placeholder || "").trim();
      if (ph && ph !== "mood") mood = ph;
    }

    const newName = $("pv-name") ? $("pv-name").textContent.trim() : "";
    if (newName) lastProposal.playlist_name = newName;

    setError(null);
    lastError = null;
    clearLog();
    show("stream");
    if ($("stream-status")) $("stream-status").textContent = "creating…";

    streamPost("/api/create",
               { proposal: lastProposal, mood: mood, public: isPublic },
               handleEvent
    ).then(function () {
      if (lastError) { setError(lastError); return; }
      if ($("result-stage") && $("result-stage").classList.contains("hidden")) {
        setError("create finished but no playlist URL returned");
      }
    }).catch(function (e) {
      if (e && e.name === "AbortError") { show("preview"); return; }
      setError(String(e));
      show("preview");
    });
  }

  function backToInput() {
    lastProposal = null;
    lastError = null;
    setError(null);
    show("input");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();