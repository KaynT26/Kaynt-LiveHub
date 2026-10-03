// Kaynt Live Observer – phía trình duyệt (nhiều phòng: tab + lưới)
(() => {
  const $ = (id) => document.getElementById(id);
  const fmt = (n) => Number(n || 0).toLocaleString("vi-VN");
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const hhmm = (ts) => new Date(ts * 1000).toLocaleTimeString("vi-VN", { hour12: false });
  const enc = encodeURIComponent;

  const STATUS_TEXT = {
    idle: "Chưa kết nối", connecting: "Đang kết nối…", connected: "Đang theo dõi",
    reconnecting: "Đang kết nối lại…", disconnected: "Mất kết nối", offline: "Không live",
    ended: "Live đã kết thúc", stopped: "Đã ngắt", error: "Lỗi",
  };
  const BUSY = ["connecting", "connected", "reconnecting"];
  const MAX_FEED = 500;          // sự kiện giữ cho mỗi phòng (phía trình duyệt)
  const MINI_FEED = 6;           // số dòng trong ô lưới
  const MINI_KINDS = new Set(["comment", "gift", "follow", "share", "system"]);
  const WALL_Q = {
    low: ["ld", "sd2", "sd1", "sd", "hd1", "hd"],
    mid: ["sd", "sd1", "hd1", "hd", "ld"],
    high: ["hd", "full_hd1", "hd1", "origin", "uhd", "sd"],
  };

  // ------------------------------------------------------------ state
  /** @type {Map<string, any>} uid -> room state */
  const rooms = new Map();
  const ui = {
    active: "",                       // "" = tab Tất cả
    metric: "viewers", topTab: "gifters",
    filters: new Set(["comment", "gift", "follow", "share", "system"]),
    search: "", giftRows: new Map(),  // gift key -> <li> (của phòng đang mở)
    detailPlayer: null, detailWanted: true,
    tilePlayers: new Map(),           // uid -> {player, q}
    playerErrAt: new Map(),           // uid -> thời điểm lỗi gần nhất (tránh thử lại liên tục)
    ffmpeg: true,
  };

  function newRoom(s) {
    return {
      uid: s.unique_id, status: s.status, message: s.message, room: s.room || { unique_id: s.unique_id },
      qualities: s.qualities || [], recording: s.recording, auto_reconnect: s.auto_reconnect, auto_record: s.auto_record,
      using_session: s.using_session,
      stats: s.stats || {}, samples: s.samples || [],
      top: { gifters: s.top_gifters || [], commenters: s.top_commenters || [] },
      events: [], giftIdx: new Map(),
    };
  }
  const cur = () => rooms.get(ui.active);

  // ------------------------------------------------------------ events store
  function storeEvent(r, ev) {
    if (ev.kind === "gift" && ev.key) {
      const old = r.giftIdx.get(ev.key);
      if (old) { Object.assign(old, ev); if (!ev.streaking) r.giftIdx.delete(ev.key); return old; }
      if (ev.streaking) r.giftIdx.set(ev.key, ev);
    }
    r.events.push(ev);
    if (r.events.length > MAX_FEED) {
      const gone = r.events.shift();
      if (gone.key && r.giftIdx.get(gone.key) === gone) r.giftIdx.delete(gone.key);
    }
    return ev;
  }

  // ------------------------------------------------------------ tabs
  function renderTabs() {
    $("roomCount").textContent = rooms.size;
    $("roomTabs").innerHTML = [...rooms.values()].map((r) => `
      <button class="tab" data-room="${esc(r.uid)}">
        <span class="sdot ${esc(r.status)}"></span>
        <span class="tname">@${esc(r.uid)}</span>
        <span class="tview" data-v>${r.stats.viewers ? "👁 " + fmt(r.stats.viewers) : ""}</span>
        ${r.using_session ? '<span class="tlock" title="Đang dùng sessionid">🔐</span>' : ""}
        ${r.recording ? '<span class="trec">●</span>' : ""}
        <span class="tclose" data-close="${esc(r.uid)}" title="Đóng phòng">×</span>
      </button>`).join("");
    markActiveTab();
    updateSummary();
  }
  function markActiveTab() {
    document.querySelectorAll("#tabs .tab").forEach((b) => b.classList.toggle("on", b.dataset.room === ui.active));
  }
  function tabEl(uid) { return document.querySelector(`#roomTabs .tab[data-room="${CSS.escape(uid)}"]`); }
  function updateTab(r) {
    const t = tabEl(r.uid); if (!t) return;
    t.querySelector(".sdot").className = "sdot " + r.status;
    t.querySelector("[data-v]").textContent = r.stats.viewers ? "👁 " + fmt(r.stats.viewers) : "";
    const lock = t.querySelector(".tlock");
    if (r.using_session && !lock) t.querySelector(".tclose").insertAdjacentHTML("beforebegin", '<span class="tlock" title="Đang dùng sessionid">🔐</span>');
    if (!r.using_session && lock) lock.remove();
    const rec = t.querySelector(".trec");
    if (r.recording && !rec) t.querySelector(".tclose").insertAdjacentHTML("beforebegin", '<span class="trec">●</span>');
    if (!r.recording && rec) rec.remove();
  }
  function updateSummary() {
    const live = [...rooms.values()].filter((r) => r.status === "connected").length;
    const el = $("summary");
    el.textContent = rooms.size ? `${live}/${rooms.size} phòng đang theo dõi` : "0 phòng";
    el.className = "pill " + (live ? "connected" : "idle");
  }

  $("tabs").addEventListener("click", (e) => {
    const x = e.target.closest("[data-close]");
    if (x) { e.stopPropagation(); closeRoom(x.dataset.close); return; }
    const b = e.target.closest(".tab"); if (!b) return;
    switchTo(b.dataset.room);
  });

  function switchTo(uid) {
    if (uid && !rooms.has(uid)) uid = "";
    ui.active = uid;
    try { history.replaceState(null, "", uid ? "#" + uid : location.pathname); } catch (_) {}
    markActiveTab();
    $("viewAll").hidden = !!uid;
    $("viewRoom").hidden = !uid;
    ui.detailWanted = true;
    if (uid) renderDetail();
    syncPlayers();
  }

  // ------------------------------------------------------------ wall (lưới)
  function tileHTML(r) {
    return `
      <div class="tile-head" data-open>
        <img class="avatar" alt="" onerror="this.style.visibility='hidden'">
        <div class="tmeta"><b class="tn"></b><span class="muted small tt"></span></div>
        <span class="pill sm st"></span>
        <button class="tx" title="Đóng phòng">×</button>
      </div>
      <div class="video-wrap">
        <video muted playsinline></video>
        <div class="video-empty ve"></div>
        <button class="vbtn mute" title="Bật/tắt tiếng">🔇</button>
        <span class="rec-badge" hidden>● REC</span>
      </div>
      <div class="tile-stats">
        <span title="Đang xem">👁 <b data-s="viewers">0</b></span>
        <span title="Bình luận">💬 <b data-s="comments">0</b></span>
        <span title="Kim cương">💎 <b data-s="diamonds">0</b></span>
        <span title="Lượt thích">❤ <b data-s="likes">0</b></span>
      </div>
      <ul class="mini-feed"></ul>`;
  }
  function tileEl(uid) { return document.querySelector(`#wall .tile[data-room="${CSS.escape(uid)}"]`); }

  function addTile(r) {
    const t = document.createElement("div");
    t.className = "tile";
    t.dataset.room = r.uid;
    t.innerHTML = tileHTML(r);
    t.querySelector("[data-open]").addEventListener("click", (e) => {
      if (e.target.closest(".tx")) { closeRoom(r.uid); return; }
      switchTo(r.uid);
    });
    t.querySelector(".mute").addEventListener("click", () => {
      const v = t.querySelector("video");
      // chỉ bật tiếng 1 ô, các ô khác tắt
      const turnOn = v.muted;
      document.querySelectorAll("#wall video").forEach((x) => { x.muted = true; });
      document.querySelectorAll("#wall .mute").forEach((x) => { x.textContent = "🔇"; });
      v.muted = !turnOn;
      t.querySelector(".mute").textContent = v.muted ? "🔇" : "🔊";
    });
    $("wall").appendChild(t);
    updateTile(r);
    updateTileStats(r);
    r.events.filter((ev) => MINI_KINDS.has(ev.kind) && !ev.streaking).slice(-MINI_FEED).forEach((ev) => addMini(r, ev));
    $("wallEmpty").hidden = rooms.size > 0;
  }

  function updateTile(r) {
    const t = tileEl(r.uid); if (!t) return;
    const room = r.room || {};
    const img = t.querySelector(".avatar");
    if (room.avatar) { img.src = room.avatar; img.style.visibility = "visible"; } else img.style.visibility = "hidden";
    t.querySelector(".tn").textContent = room.nickname ? `${room.nickname} · @${r.uid}` : "@" + r.uid;
    t.querySelector(".tt").textContent = room.title || r.message || "";
    const st = t.querySelector(".st");
    st.className = "pill sm st " + r.status;
    st.textContent = STATUS_TEXT[r.status] || r.status;
    st.title = r.message || "";
    t.querySelector(".rec-badge").hidden = !r.recording;
    t.classList.toggle("dead", !BUSY.includes(r.status));
    if (!ui.tilePlayers.has(r.uid)) setTileEmpty(r);
  }
  function setTileEmpty(r, text) {
    const t = tileEl(r.uid); if (!t) return;
    const ve = t.querySelector(".ve");
    ve.style.display = "grid";
    t.querySelector(".mute").hidden = true;
    ve.textContent = text || (r.status !== "connected" ? (STATUS_TEXT[r.status] || r.status)
      : !canPlay() ? "Trình duyệt không hỗ trợ phát FLV"
      : !r.qualities.length ? "Không có luồng video"
      : $("wallVideo").checked ? "Đang mở video…" : "Video trong lưới đang tắt");
  }
  function updateTileStats(r) {
    const t = tileEl(r.uid); if (!t) return;
    t.querySelectorAll("[data-s]").forEach((el) => { el.textContent = fmt(r.stats[el.dataset.s]); });
  }
  function addMini(r, ev) {
    if (!MINI_KINDS.has(ev.kind) || ev.streaking) return;
    const t = tileEl(r.uid); if (!t) return;
    const ul = t.querySelector(".mini-feed");
    const li = document.createElement("li");
    li.className = ev.kind;
    const name = ev.user ? `<b class="name" data-user>${esc(ev.user.nickname)}</b> ` : "";
    let txt = "";
    switch (ev.kind) {
      case "comment": txt = esc(ev.text); break;
      case "gift": txt = `🎁 ${esc(ev.gift)} ×${ev.count}` + (ev.diamonds ? ` (${fmt(ev.diamonds * ev.count)}💎)` : ""); break;
      case "follow": txt = "➕ theo dõi"; break;
      case "share": txt = "↗ chia sẻ"; break;
      case "system": txt = `<i>${esc(ev.text)}</i>`; break;
    }
    li.innerHTML = name + txt;
    li._user = ev.user;
    ul.appendChild(li);
    while (ul.children.length > MINI_FEED) ul.firstElementChild.remove();
  }
  function removeTile(uid) {
    tileEl(uid)?.remove();
    $("wallEmpty").hidden = rooms.size > 0;
  }
  function renderWall() {
    $("wall").innerHTML = "";
    rooms.forEach(addTile);
    $("wallEmpty").hidden = rooms.size > 0;
  }

  // ------------------------------------------------------------ detail (một phòng)
  function renderDetail() {
    const r = cur(); if (!r) return;
    setRoomHeader(r);
    setQualities(r);
    setStatus(r);
    setRecording(r);
    setStats(r.stats, true);
    renderTop();
    drawChart();
    $("feed").innerHTML = ""; ui.giftRows.clear();
    r.events.forEach((ev) => addEventLi(ev, true));
    $("feed").scrollTop = $("feed").scrollHeight;
    $("uptime").textContent = "00:00:00";
  }

  function setStatus(r) {
    const el = $("status");
    el.className = "pill " + r.status;
    el.textContent = STATUS_TEXT[r.status] || r.status;
    el.title = r.message || "";
    $("btnDisconnect").disabled = !BUSY.includes(r.status);
    $("btnRec").disabled = !r.recording && (r.status !== "connected" || !r.qualities.length || !ui.ffmpeg);
    $("btnRec").title = ui.ffmpeg ? "" : "Cần cài ffmpeg và thêm vào PATH";
    $("roomAutoRec").checked = !!r.auto_record;
  }

  function setRoomHeader(r) {
    const room = r.room || {};
    $("roomName").textContent = room.nickname ? `${room.nickname}  ·  @${r.uid}` : "@" + r.uid;
    $("roomTitle").textContent = room.title || r.message || "";
    const a = $("roomAvatar");
    if (room.avatar) { a.src = room.avatar; a.style.visibility = "visible"; } else { a.removeAttribute("src"); a.style.visibility = "hidden"; }
  }

  function setQualities(r) {
    const sel = $("quality");
    const list = r.qualities || [];
    const prev = sel.value;
    if (sel.dataset.room !== r.uid || sel.dataset.list !== list.join()) {
      sel.innerHTML = list.map((q) => `<option value="${esc(q)}">${esc(q.toUpperCase())}</option>`).join("");
      sel.dataset.room = r.uid; sel.dataset.list = list.join();
      const pick = [prev, "hd", "sd", "hd1", "sd1"].find((q) => list.includes(q));
      if (pick) sel.value = pick;
    }
    $("btnPlay").disabled = !list.length;
  }

  function setRecording(r) {
    const b = $("btnRec");
    b.classList.toggle("on", !!r.recording);
    b.textContent = r.recording ? "■ Dừng ghi" : "● Ghi hình";
    $("recInfo").textContent = r.recording ? "Đang ghi: " + r.recording.split(/[\\/]/).pop() : "";
  }

  let prevStats = {};
  function setStats(s, reset = false) {
    const map = {
      viewers: "s-viewers", viewers_peak: "s-peak", comments: "s-comments", diamonds: "s-diamonds",
      gifts: "s-gifts", likes: "s-likes", likes_total: "s-likesTotal", joins: "s-joins",
      follows: "s-follows", shares: "s-shares",
    };
    for (const [k, id] of Object.entries(map)) {
      const el = $(id);
      el.textContent = fmt(s[k]);
      if (!reset && prevStats[k] !== undefined && prevStats[k] !== s[k]) {
        const card = el.closest(".stat");
        card.classList.add("bump");
        setTimeout(() => card.classList.remove("bump"), 250);
      }
    }
    prevStats = { ...s };
  }

  setInterval(() => {
    const r = cur(); if (!r) return;
    const t0 = r.stats.connected_at;
    if (!t0 || !["connected", "reconnecting"].includes(r.status)) return;
    const d = Math.max(0, Math.floor(Date.now() / 1000 - t0));
    $("uptime").textContent = [d / 3600, (d % 3600) / 60, d % 60].map((x) => String(Math.floor(x)).padStart(2, "0")).join(":");
  }, 1000);

  // ------------------------------------------------------------ top lists
  function renderTop() {
    const r = cur();
    const list = (r && r.top[ui.topTab]) || [];
    const unit = ui.topTab === "gifters" ? "💎" : "💬";
    $("topList").innerHTML = list.length
      ? list.map((u, i) => `<li data-i="${i}"><img class="avatar" data-user src="${esc(u.avatar || "")}" alt="" onerror="this.style.visibility='hidden'">
          <span class="n"><span class="l1">${badgesHTML(u)}<span class="name" data-user>${esc(u.nickname)}</span></span>
          <span class="muted small">@${esc(u.unique_id || "")}</span></span>
          <span class="v">${fmt(u.value)} ${unit}</span></li>`).join("")
      : `<li class="empty" style="counter-increment:none">Chưa có dữ liệu</li>`;
  }
  $("topTabs").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    ui.topTab = b.dataset.t;
    [...$("topTabs").children].forEach((x) => x.classList.toggle("on", x === b));
    renderTop();
  });

  // ------------------------------------------------------------ feed
  // ------------------------------------------------------------ badge / level
  const lvTier = (n) => (n >= 50 ? "t5" : n >= 40 ? "t4" : n >= 30 ? "t3" : n >= 20 ? "t2" : n >= 10 ? "t1" : "t0");
  const KNOWN_SCENES = new Set(["USER_GRADE", "FANS", "RANK_LIST", "ADMIN", "SUBSCRIBER", "NEW_SUBSCRIBER"]);
  function badgesHTML(u, full = false) {
    if (!u) return "";
    const out = [];
    if (u.mod) out.push(`<span class="bdg b-mod" title="Quản trị viên phòng">🛡 Mod</span>`);
    if (u.gift_level) out.push(`<span class="bdg b-lv ${lvTier(u.gift_level)}" title="Level tặng quà: ${u.gift_level}">` +
      `${u.gift_icon ? `<img src="${esc(u.gift_icon)}" alt="" onerror="this.remove()">` : "💎"}${u.gift_level}</span>`);
    const f = u.fan;
    if (f && (f.name || f.level)) out.push(`<span class="bdg b-fan" title="Fan club${f.name ? " " + esc(f.name) : ""} · level ${f.level || "?"}">` +
      `${f.icon ? `<img src="${esc(f.icon)}" alt="" onerror="this.remove()">` : "♥"}${esc(f.name || "Fan")}` +
      `${f.level ? `<i>${f.level}</i>` : ""}</span>`);
    if (u.rank) out.push(`<span class="bdg b-rank" title="Hạng ${u.rank} trong bảng xếp hạng của phòng">🏅 Hạng ${u.rank}</span>`);
    if (u.sub) out.push(`<span class="bdg b-sub" title="Subscriber">⭐ Sub</span>`);
    if (full) (u.badges || []).filter((b) => !KNOWN_SCENES.has(b.scene) && (b.label || b.icon)).forEach((b) => {
      out.push(`<span class="bdg b-other" title="${esc(b.scene)}">${b.icon ? `<img src="${esc(b.icon)}" alt="" onerror="this.remove()">` : ""}${esc(b.label || "")}</span>`);
    });
    return out.length ? `<span class="bdgs">${out.join("")}</span>` : "";
  }

  // ------------------------------------------------------------ feed
  function eventHTML(ev) {
    const u = ev.user;
    if (ev.kind === "system") return `<div class="body">— ${esc(ev.text)} · ${hhmm(ev.ts)} —</div>`;
    const who = u ? `<img class="avatar" data-user src="${esc(u.avatar || "")}" alt="" onerror="this.style.visibility='hidden'">` : "";
    const name = u ? `<span class="name" data-user title="Xem thông tin">${esc(u.nickname)}</span>` : "";
    let txt = "", inline = true;
    switch (ev.kind) {
      case "comment": txt = esc(ev.text); inline = false; break;
      case "gift": txt = `tặng${ev.gift_img ? `<img class="g" src="${esc(ev.gift_img)}" alt="">` : " "}<b>${esc(ev.gift)}</b> ×${ev.count}` +
                         (ev.diamonds ? ` <span class="muted small">(${fmt(ev.diamonds * ev.count)} 💎)</span>` : ""); inline = false; break;
      case "like": txt = `thả ${fmt(ev.count)} ❤`; break;
      case "join": txt = "vừa vào phòng"; break;
      case "follow": txt = "đã theo dõi chủ phòng"; break;
      case "share": txt = "đã chia sẻ phiên live"; break;
    }
    const line1 = `<div class="l1">${badgesHTML(u)}${name}${inline ? `<span class="txt">${txt}</span>` : ""}</div>`;
    return `${who}<div class="body">${line1}${inline ? "" : `<div class="txt">${txt}</div>`}</div><span class="time">${hhmm(ev.ts)}</span>`;
  }

  function matches(li) {
    if (!ui.filters.has(li.dataset.kind)) return false;
    if (!ui.search) return true;
    return li.dataset.q.includes(ui.search);
  }

  function addEventLi(ev, bulk = false) {
    const feed = $("feed");
    let li = null;
    if (ev.kind === "gift" && ev.key) {
      li = ui.giftRows.get(ev.key);
      if (li && !li.isConnected) li = null;
    }
    if (!li) {
      li = document.createElement("li");
      if (ev.kind === "gift" && ev.key) ui.giftRows.set(ev.key, li);
      feed.appendChild(li);
    }
    li.className = ev.kind + (ev.streaking ? " streak" : "");
    li.dataset.kind = ev.kind;
    li.dataset.q = [ev.user?.nickname, ev.user?.unique_id, ev.text, ev.gift].filter(Boolean).join(" ").toLowerCase();
    li.innerHTML = eventHTML(ev);
    li._user = ev.user;
    li.classList.toggle("hide", !matches(li));
    if (ev.kind === "gift" && !ev.streaking) ui.giftRows.delete(ev.key);

    while (feed.children.length > MAX_FEED) feed.firstElementChild.remove();
    if (!bulk && $("autoScroll").checked) feed.scrollTop = feed.scrollHeight;
  }

  function refilter() { for (const li of $("feed").children) li.classList.toggle("hide", !matches(li)); }
  $("filters").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    const k = b.dataset.k;
    ui.filters.has(k) ? ui.filters.delete(k) : ui.filters.add(k);
    b.classList.toggle("on", ui.filters.has(k));
    refilter();
  });
  $("search").addEventListener("input", (e) => { ui.search = e.target.value.trim().toLowerCase(); refilter(); });

  // ------------------------------------------------------------ cửa sổ thông tin người xem
  const ucard = $("userCard");
  let ucardSeq = 0;
  const KIND_ICON = { comment: "💬", gift: "🎁", follow: "➕", share: "↗" };

  function closeUserCard() { ucard.hidden = true; ucardSeq++; }

  function placeCard(anchor) {
    if (window.innerWidth <= 600 || !anchor) { ucard.classList.add("sheet"); ucard.style.left = ucard.style.top = ""; return; }
    ucard.classList.remove("sheet");
    const r = anchor.getBoundingClientRect();
    const W = ucard.offsetWidth, H = ucard.offsetHeight;
    let left = Math.min(Math.max(8, r.left), window.innerWidth - W - 8);
    let top = r.bottom + 6;
    if (top + H > window.innerHeight - 8) top = Math.max(8, r.top - H - 6);
    ucard.style.left = left + "px"; ucard.style.top = top + "px";
  }

  function cardHTML(u, d) {
    const st = d && d.stats;
    const link = `https://www.tiktok.com/@${encodeURIComponent(u.unique_id || "")}`;
    const stat = (icon, label, v) => `<div><span>${icon} ${label}</span><b>${v}</b></div>`;
    let body;
    if (d === undefined) body = `<div class="muted small uc-pad">Đang tải…</div>`;
    else if (!st) body = `<div class="muted small uc-pad">Chưa có hoạt động nào của người này trong phiên theo dõi hiện tại.</div>`;
    else {
      const ranks = [d.rank_gift ? `#${d.rank_gift} tặng quà` : "", d.rank_comment ? `#${d.rank_comment} bình luận` : ""].filter(Boolean).join(" · ");
      const recent = (st.recent || []).slice(-12).reverse().map((a) => {
        let t = "";
        if (a.kind === "comment") t = esc(a.text);
        else if (a.kind === "gift") t = `${a.gift_img ? `<img class="g" src="${esc(a.gift_img)}" alt="">` : ""}<b>${esc(a.gift)}</b> ×${a.count}` +
                                        (a.diamonds ? ` <span class="muted">(${fmt(a.diamonds * a.count)}💎)</span>` : "");
        else if (a.kind === "follow") t = "đã theo dõi chủ phòng";
        else if (a.kind === "share") t = "đã chia sẻ live";
        return `<li class="${a.kind}"><span class="k">${KIND_ICON[a.kind] || "•"}</span><span class="t">${t}</span><span class="time">${hhmm(a.ts)}</span></li>`;
      }).join("");
      body = `
        <div class="uc-stats">
          ${stat("💬", "Bình luận", fmt(st.comments))}${stat("💎", "Kim cương", fmt(st.diamonds))}${stat("🎁", "Quà", fmt(st.gifts))}
          ${stat("❤", "Tim", fmt(st.likes))}${stat("👋", "Vào phòng", fmt(st.joins))}${stat("↗", "Chia sẻ", fmt(st.shares))}
        </div>
        <div class="uc-meta muted small">
          ${ranks ? `<div>🏆 ${ranks} trong phiên</div>` : ""}
          <div>🕒 Lần đầu ${hhmm(st.first)} · gần nhất ${hhmm(st.last)}${st.followed ? " · <span class='ok'>đã follow</span>" : ""}</div>
        </div>
        ${recent ? `<div class="uc-sub">Hoạt động gần đây</div><ul class="uc-recent">${recent}</ul>` : ""}`;
    }
    return `
      <div class="uc-head">
        <img class="avatar xl" src="${esc(u.avatar || "")}" alt="" onerror="this.style.visibility='hidden'">
        <div class="uc-id"><b>${esc(u.nickname)}</b><span class="muted">@${esc(u.unique_id || "")}</span>
          ${u.followers || u.following ? `<span class="muted small">${fmt(u.followers)} follower · ${fmt(u.following)} đang follow</span>` : ""}</div>
        <button class="uc-x" data-close title="Đóng">×</button>
      </div>
      <div class="uc-badges">${badgesHTML(u, true) || `<span class="muted small">Không có huy hiệu</span>`}</div>
      ${body}
      <div class="uc-actions">
        <a class="btn sm primary" href="${link}" target="_blank" rel="noopener noreferrer">Mở TikTok ↗</a>
        <button class="btn sm" data-act="filter">Lọc bình luận</button>
        <button class="btn sm" data-act="copy">Copy @id</button>
      </div>`;
  }

  async function openUserCard(roomUid, u, anchor) {
    if (!u || !u.id) return;
    const seq = ++ucardSeq;
    ucard._ctx = { roomUid, u };
    ucard.innerHTML = cardHTML(u, undefined);
    ucard.hidden = false;
    placeCard(anchor);
    let d = null;
    try {
      const r = await fetch(`/api/rooms/${enc(roomUid)}/users/${enc(u.id)}`);
      const j = await r.json();
      if (j.ok) d = j;
    } catch (_) {}
    if (seq !== ucardSeq) return;
    const user = (d && d.user) ? { ...u, ...d.user } : u;
    ucard._ctx.u = user;
    ucard.innerHTML = cardHTML(user, d);
    placeCard(anchor);
  }

  ucard.addEventListener("click", async (e) => {
    if (e.target.closest("[data-close]")) { closeUserCard(); return; }
    const act = e.target.closest("[data-act]")?.dataset.act;
    const ctx = ucard._ctx; if (!act || !ctx) return;
    if (act === "copy") {
      try { await navigator.clipboard.writeText("@" + ctx.u.unique_id); e.target.textContent = "Đã copy ✓"; }
      catch (_) { prompt("Copy:", "@" + ctx.u.unique_id); }
    } else if (act === "filter") {
      if (ui.active !== ctx.roomUid) switchTo(ctx.roomUid);
      $("search").value = ctx.u.unique_id; ui.search = String(ctx.u.unique_id).toLowerCase(); refilter();
      closeUserCard();
    }
  });
  document.addEventListener("click", (e) => {
    const trg = e.target.closest("[data-user]");
    if (trg) {
      const li = trg.closest("li");
      let u = li && li._user, room = ui.active;
      if (!u && li && li.dataset.i !== undefined) { const r = cur(); u = r && r.top[ui.topTab][+li.dataset.i]; }
      const tile = trg.closest(".tile"); if (tile) room = tile.dataset.room;
      if (u && room) { e.stopPropagation(); openUserCard(room, u, trg); }
      return;
    }
    if (!ucard.hidden && !e.target.closest("#userCard")) closeUserCard();
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeUserCard(); });
  window.addEventListener("resize", () => { if (!ucard.hidden) closeUserCard(); });

  // ------------------------------------------------------------ chart (canvas thuần)
  function drawChart() {
    const r = cur();
    const cv = $("chart");
    if (!r || cv.offsetParent === null) return;
    const samples = r.samples;
    const dpr = window.devicePixelRatio || 1;
    const W = cv.clientWidth, H = 160;
    cv.width = W * dpr; cv.height = H * dpr;
    const ctx = cv.getContext("2d");
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, W, H);
    const data = samples.map((s) => s[ui.metric] || 0);
    const padL = 44, padB = 18, padT = 8, w = W - padL - 6, h = H - padB - padT;
    ctx.font = "11px Segoe UI, system-ui, sans-serif";
    ctx.fillStyle = "#8b93a5";
    if (data.length < 2) { ctx.fillText("Chưa đủ dữ liệu (mỗi 10 giây thêm 1 điểm)", padL, H / 2); return; }
    const max = Math.max(1, ...data), min = ui.metric === "viewers" ? Math.min(...data) * 0.95 : 0;
    const range = Math.max(1, max - min);
    const x = (i) => padL + (i / (data.length - 1)) * w;
    const y = (v) => padT + h - ((v - min) / range) * h;
    ctx.strokeStyle = "#262c38"; ctx.lineWidth = 1;
    for (let g = 0; g <= 3; g++) {
      const yy = padT + (h * g) / 3;
      ctx.beginPath(); ctx.moveTo(padL, yy); ctx.lineTo(padL + w, yy); ctx.stroke();
      ctx.fillText(fmt(Math.round(max - (range * g) / 3)), 2, yy + 4);
    }
    const t0 = samples[0].t, t1 = samples.at(-1).t;
    ctx.fillText(hhmm(t0), padL, H - 3);
    const lbl = hhmm(t1); ctx.fillText(lbl, padL + w - ctx.measureText(lbl).width, H - 3);
    const grad = ctx.createLinearGradient(0, padT, 0, padT + h);
    grad.addColorStop(0, "rgba(37,244,238,.28)"); grad.addColorStop(1, "rgba(37,244,238,0)");
    ctx.beginPath();
    data.forEach((v, i) => (i ? ctx.lineTo(x(i), y(v)) : ctx.moveTo(x(i), y(v))));
    ctx.lineTo(x(data.length - 1), padT + h); ctx.lineTo(x(0), padT + h); ctx.closePath();
    ctx.fillStyle = grad; ctx.fill();
    ctx.beginPath();
    data.forEach((v, i) => (i ? ctx.lineTo(x(i), y(v)) : ctx.moveTo(x(i), y(v))));
    ctx.strokeStyle = "#25f4ee"; ctx.lineWidth = 2; ctx.stroke();
  }
  $("chartMetric").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    ui.metric = b.dataset.m;
    [...$("chartMetric").children].forEach((x) => x.classList.toggle("on", x === b));
    drawChart();
  });
  window.addEventListener("resize", drawChart);

  // ------------------------------------------------------------ video players
  const canPlay = () => window.mpegts && mpegts.isSupported();

  function makePlayer(video, uid, q, onError) {
    const p = mpegts.createPlayer({ type: "flv", isLive: true, url: `/video/${enc(uid)}/${enc(q)}.flv?_=${Date.now()}` },
      { enableStashBuffer: false, liveBufferLatencyChasing: true, liveBufferLatencyMaxLatency: 4, liveBufferLatencyMinRemain: 1 });
    p.attachMediaElement(video);
    p.on(mpegts.Events.ERROR, (t, d) => onError(String(d || t)));
    p.load();
    p.play()?.catch?.(() => {});
    return p;
  }
  function killPlayer(p) {
    if (!p) return;
    try { p.pause(); p.unload(); p.detachMediaElement(); p.destroy(); } catch (_) {}
  }

  function stopDetail(text) {
    killPlayer(ui.detailPlayer?.player);
    ui.detailPlayer = null;
    $("videoEmpty").style.display = "grid";
    $("videoEmpty").textContent = text || "Video sẽ hiện ở đây khi đã kết nối";
  }
  function playDetail() {
    const r = cur(); if (!r) return;
    const q = $("quality").value;
    stopDetail();
    if (!q) return;
    if (!canPlay()) { $("videoEmpty").textContent = "Trình duyệt không hỗ trợ phát FLV (cần Chrome/Edge/Firefox)"; return; }
    const uid = r.uid;
    const player = makePlayer($("video"), uid, q, (msg) => {
      if (ui.detailPlayer?.player !== player) return;
      stopDetail("Lỗi phát video: " + msg);
      ui.playerErrAt.set("detail:" + uid, Date.now());
    });
    ui.detailPlayer = { uid, q, player };
    $("videoEmpty").style.display = "none";
  }

  function wallQuality(r) {
    const pref = WALL_Q[$("wallQuality").value] || WALL_Q.low;
    return pref.find((q) => r.qualities.includes(q)) || r.qualities[r.qualities.length - 1] || r.qualities[0];
  }
  function stopTile(uid, text) {
    const tp = ui.tilePlayers.get(uid);
    if (tp) killPlayer(tp.player);
    ui.tilePlayers.delete(uid);
    const r = rooms.get(uid);
    if (r) setTileEmpty(r, text);
  }
  function startTile(r) {
    const t = tileEl(r.uid); if (!t) return;
    const q = wallQuality(r); if (!q) return;
    const uid = r.uid;
    const player = makePlayer(t.querySelector("video"), uid, q, (msg) => {
      if (ui.tilePlayers.get(uid)?.player !== player) return;
      ui.playerErrAt.set("tile:" + uid, Date.now());
      stopTile(uid, "Lỗi video – thử lại sau ít giây");
      setTimeout(syncPlayers, 10000);
    });
    ui.tilePlayers.set(uid, { player, q });
    t.querySelector(".ve").style.display = "none";
    t.querySelector(".mute").hidden = false;
  }

  /** Bật/tắt player cho khớp với tab đang mở & trạng thái phòng (chỉ mở luồng khi cần, đỡ tốn mạng). */
  function syncPlayers() {
    const recentErr = (k) => Date.now() - (ui.playerErrAt.get(k) || 0) < 9000;
    // lưới
    const wallOn = !ui.active && $("wallVideo").checked && canPlay();
    for (const [uid, tp] of [...ui.tilePlayers]) {
      const r = rooms.get(uid);
      if (!wallOn || !r || r.status !== "connected" || !r.qualities.includes(tp.q) || tp.q !== wallQuality(r)) stopTile(uid);
    }
    if (wallOn) {
      rooms.forEach((r) => {
        if (r.status === "connected" && r.qualities.length && !ui.tilePlayers.has(r.uid) && !recentErr("tile:" + r.uid)) startTile(r);
        else if (!ui.tilePlayers.has(r.uid)) setTileEmpty(r);
      });
    } else rooms.forEach((r) => setTileEmpty(r));
    // chi tiết
    const r = cur();
    const want = r && r.status === "connected" && r.qualities.length && ui.detailWanted;
    if (!want) { if (ui.detailPlayer) stopDetail(r && r.status !== "connected" ? (STATUS_TEXT[r.status] || r.status) : undefined); }
    else if (!ui.detailPlayer || ui.detailPlayer.uid !== r.uid) { if (!recentErr("detail:" + r.uid)) playDetail(); }
  }

  $("btnPlay").onclick = () => { ui.detailWanted = true; ui.playerErrAt.delete("detail:" + ui.active); playDetail(); };
  $("btnStopVideo").onclick = () => { ui.detailWanted = false; stopDetail("Đã tắt video"); };
  $("quality").onchange = () => ui.detailPlayer && playDetail();
  $("wallVideo").onchange = syncPlayers;
  $("wallQuality").onchange = syncPlayers;

  // ------------------------------------------------------------ actions
  async function api(method, url, body) {
    const r = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
    const j = await r.json().catch(() => ({}));
    if (!r.ok || j.ok === false) throw new Error(j.error || r.statusText);
    return j;
  }
  const roomUrl = (uid, tail = "") => `/api/rooms/${enc(uid)}${tail}`;

  $("addForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const names = $("uid").value.split(/[\s,;]+/).map((s) => s.trim()).filter(Boolean);
    const errors = [];
    let last = "";
    for (const n of names) {
      try {
        const j = await api("POST", "/api/rooms", { unique_id: n, auto_reconnect: $("autoRe").checked, auto_record: $("autoRec").checked });
        last = j.unique_id;
      } catch (err) { errors.push(`${n}: ${err.message}`); }
    }
    if (!errors.length) $("uid").value = "";
    if (errors.length) alert(errors.join("\n"));
    if (names.length === 1 && last && ui.active) switchTo(last);  // đang ở tab 1 phòng → chuyển sang phòng mới
  });

  async function closeRoom(uid) {
    const r = rooms.get(uid);
    if (r?.recording && !confirm(`@${uid} đang ghi hình. Đóng phòng sẽ dừng ghi. Tiếp tục?`)) return;
    try { await api("DELETE", roomUrl(uid)); } catch (err) { alert(err.message); }
  }

  $("btnClose").onclick = () => ui.active && closeRoom(ui.active);
  $("btnReconnect").onclick = () => ui.active && api("POST", roomUrl(ui.active, "/reconnect")).catch((err) => alert(err.message));
  $("btnDisconnect").onclick = () => ui.active && api("POST", roomUrl(ui.active, "/disconnect")).catch((err) => alert(err.message));
  $("roomAutoRec").onchange = (e) => ui.active && api("POST", roomUrl(ui.active, "/auto_record"), { value: e.target.checked }).catch((err) => alert(err.message));
  $("btnRec").onclick = async () => {
    const r = cur(); if (!r) return;
    try {
      if (r.recording) await api("POST", roomUrl(r.uid, "/record/stop"));
      else await api("POST", roomUrl(r.uid, "/record/start"), { quality: $("quality").value });
    } catch (err) { alert("Không ghi được: " + err.message); }
  };

  // ------------------------------------------------------------ sessionid
  const MODE_TEXT = { auto: "tự động khi bị giới hạn tuổi", always: "luôn dùng", off: "đang tắt" };
  function setSession(info) {
    const el = $("sessionPill");
    info = info || {};
    if (!info.configured) {
      el.className = "pill idle sess"; el.textContent = "🔓 Chưa có sessionid";
      el.title = "Chưa cấu hình sessionid (dùng cho live giới hạn độ tuổi). Điền TIKTOK_SESSIONID / TIKTOK_TARGET_IDC trong .env rồi bấm vào đây để tải lại.";
    } else if (info.problem) {
      el.className = "pill error sess"; el.textContent = "⚠ sessionid lỗi";
      el.title = info.problem + "\n(Bấm để đọc lại .env)";
    } else {
      el.className = "pill " + (info.mode === "off" ? "idle" : "connected") + " sess";
      el.textContent = "🔐 sessionid " + info.masked;
      el.title = "Chế độ: " + (MODE_TEXT[info.mode] || info.mode) + "\n(Bấm để đọc lại .env)";
    }
  }
  function setSign(info) {
    const el = $("signPill");
    info = info || {};
    if (info.configured) {
      el.className = "pill connected sess"; el.textContent = "🔑 API key " + info.masked;
      el.title = "Đang dùng SIGN_API_KEY của Euler Stream (" + info.url + ")\n(Bấm để đọc lại .env)";
    } else {
      el.className = "pill idle sess"; el.textContent = "🔑 Chưa có API key";
      el.title = "Đang dùng máy chủ ký Euler Stream miễn phí (dễ bị giới hạn khi xem nhiều phòng).\nĐiền SIGN_API_KEY trong .env rồi bấm vào đây để tải lại.";
    }
  }
  async function reloadConfig() {
    try {
      const j = await api("POST", "/api/config/reload");
      setSession(j.session); setSign(j.sign);
      const s = j.session, g = j.sign;
      const lines = [
        g.configured ? `🔑 API key Euler Stream: ${g.masked}` : "🔑 Chưa có SIGN_API_KEY (dùng gói miễn phí)",
        !s.configured ? "🔓 Chưa có TIKTOK_SESSIONID"
          : s.problem ? "⚠ sessionid chưa dùng được: " + s.problem
          : `🔐 sessionid ${s.masked} – ${MODE_TEXT[s.mode] || s.mode}`,
        "", "Áp dụng cho lần kết nối sau – phòng đang mở bấm \"Kết nối lại\".",
      ];
      alert("Đã đọc lại .env\n\n" + lines.join("\n"));
    } catch (err) { alert(err.message); }
  }
  $("sessionPill").onclick = reloadConfig;

  // ------------------------------------------------------------ truy cập qua WiFi
  let lanInfo = null;
  function setLan(info) {
    lanInfo = info;
    const el = $("lanPill");
    if (!info || !info.urls || !info.urls.length) { el.hidden = true; return; }
    el.hidden = false;
    el.className = "pill sess " + (info.password ? "connected" : "error");
    el.textContent = "📶 " + info.urls[0].replace("http://", "");
    el.title = (info.password ? "Máy khác cùng WiFi vào bằng link này (cần mật khẩu)"
                              : "⚠ Chưa đặt ACCESS_PASSWORD – ai cùng WiFi cũng điều khiển được") + "\nBấm để copy link";
  }
  $("lanPill").onclick = async () => {
    if (!lanInfo) return;
    const url = lanInfo.urls[0];
    try { await navigator.clipboard.writeText(url); } catch (_) {}
    alert("Link cho máy khác cùng WiFi:\n" + lanInfo.urls.join("\n") +
      (lanInfo.password ? "\n\nMáy khác sẽ được hỏi mật khẩu (ACCESS_PASSWORD), tên đăng nhập gõ gì cũng được."
                        : "\n\n⚠ Chưa đặt ACCESS_PASSWORD trong .env – ai cùng WiFi cũng xem & điều khiển được."));
  };
  $("signPill").onclick = reloadConfig;

  // ------------------------------------------------------------ realtime
  function applySnapshot(s) {
    setSession(s.session); setSign(s.sign); setLan(s.lan);
    ui.ffmpeg = !!s.ffmpeg;
    $("ffmpegWarn").hidden = ui.ffmpeg;
    $("autoRecWrap").title = ui.ffmpeg ? "" : "Chưa có ffmpeg – sẽ không ghi được";
    // dọn player cũ
    ui.tilePlayers.forEach((tp) => killPlayer(tp.player)); ui.tilePlayers.clear();
    stopDetail();
    rooms.clear();
    (s.rooms || []).forEach((snap) => {
      const r = newRoom(snap);
      (snap.recent || []).forEach((ev) => storeEvent(r, ev));
      rooms.set(r.uid, r);
    });
    renderTabs();
    renderWall();
    const want = ui.active || decodeURIComponent(location.hash.slice(1));
    switchTo(rooms.has(want) ? want : "");
  }

  function onMessage(m) {
    const { type, room: uid, data } = JSON.parse(m.data);
    if (type === "added") {
      if (rooms.has(uid)) return;
      const r = newRoom(data);
      rooms.set(uid, r);
      renderTabs(); addTile(r); syncPlayers();
      return;
    }
    if (type === "config") { setSession(data.session); setSign(data.sign); return; }
    if (type === "removed") {
      stopTile(uid);
      if (ui.detailPlayer?.uid === uid) stopDetail();
      rooms.delete(uid);
      renderTabs(); removeTile(uid);
      if (ui.active === uid) switchTo("");
      return;
    }
    const r = rooms.get(uid); if (!r) return;
    const isActive = ui.active === uid;
    if (type === "event") {
      const ev = storeEvent(r, data);
      addMini(r, ev);
      if (isActive) addEventLi(ev);
    } else if (type === "stats") {
      r.stats = data.stats;
      r.top = { gifters: data.top_gifters, commenters: data.top_commenters };
      updateTileStats(r); updateTab(r);
      if (isActive) { setStats(r.stats); renderTop(); }
    } else if (type === "sample") {
      r.samples.push(data);
      if (r.samples.length > 360) r.samples.shift();
      if (isActive) drawChart();
    } else if (type === "status") {
      Object.assign(r, {
        status: data.status, message: data.message, room: data.room || r.room, qualities: data.qualities || [],
        recording: data.recording, auto_reconnect: data.auto_reconnect, auto_record: data.auto_record,
        using_session: data.using_session,
      });
      if (data.status === "connecting") { r.stats = {}; r.samples = []; r.top = { gifters: [], commenters: [] }; r.events = []; r.giftIdx.clear(); }
      updateTab(r); updateTile(r); updateSummary();
      if (isActive) {
        if (data.status === "connecting") renderDetail();
        else { setRoomHeader(r); setQualities(r); setStatus(r); setRecording(r); }
      }
      syncPlayers();
    }
  }

  function connectSSE() {
    const es = new EventSource("/api/events");
    es.onopen = () => fetch("/api/state").then((r) => r.json()).then(applySnapshot);
    es.onmessage = onMessage;
  }

  renderTop();
  connectSSE();
})();
