// Kaynt Live Observer – phía trình duyệt (nhiều phòng: tab + lưới)
(() => {
  const $ = (id) => document.getElementById(id);
  const fmt = (n) => Number(n || 0).toLocaleString("vi-VN");
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const hhmm = (ts) => new Date(ts * 1000).toLocaleTimeString("vi-VN", { hour12: false });
  const enc = encodeURIComponent;
  const ic = (name, cls = "") => `<svg class="ic ${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
  const TOAST_IC = { ok: "check", err: "alert", info: "info" };
  function toast(msg, kind = "info", ms = 4500) {
    const el = document.createElement("div");
    el.className = "toast " + kind;
    el.setAttribute("role", kind === "err" ? "alert" : "status");
    el.innerHTML = ic(TOAST_IC[kind] || "info") + `<div>${esc(msg)}</div>`;
    $("toasts").appendChild(el);
    setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 200); }, ms);
  }
  const initials = (s) => (String(s || "?").replace(/^@/, "").trim()[0] || "?");

  const STATUS_TEXT = {
    idle: "Chưa kết nối", connecting: "Đang kết nối…", connected: "Đang theo dõi",
    reconnecting: "Đang kết nối lại…", disconnected: "Mất kết nối", offline: "Không live",
    ended: "Live đã kết thúc", stopped: "Đã ngắt", error: "Lỗi", choose: "Chờ chọn phiên",
  };
  const BUSY = ["connecting", "connected", "reconnecting"];
  const MAX_FEED = 500;          // sự kiện giữ cho mỗi phòng (phía trình duyệt)
  const MINI_FEED = 6;           // số dòng trong ô lưới
  const MINI_KINDS = new Set(["comment", "gift", "follow", "share", "barrage", "system"]);
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
    metric: "viewers", topTab: "live",
    filters: new Set(["comment", "gift", "follow", "share", "barrage", "system"]),
    search: "", giftRows: new Map(),  // gift key -> <li> (của phòng đang mở)
    detailPlayer: null, detailWanted: true,
    tilePlayers: new Map(),           // uid -> {player, q}
    playerErrAt: new Map(),           // uid -> thời điểm lỗi gần nhất (tránh thử lại liên tục)
  };

  function newRoom(s) {
    return {
      uid: s.unique_id, status: s.status, message: s.message, room: s.room || { unique_id: s.unique_id },
      qualities: s.qualities || [], auto_reconnect: s.auto_reconnect,
      using_session: s.using_session, choice: s.choice || null,
      stats: s.stats || {},
      top: { gifters: s.top_gifters || [], live: s.live_rank || [] },
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
  function tabInner(r) {
    const room = r.room || {};
    const av = room.avatar
      ? `<img src="${esc(room.avatar)}" alt="" onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'ph',textContent:'${esc(initials(r.uid))}'}))">`
      : `<span class="ph">${esc(initials(room.nickname || r.uid))}</span>`;
    const sub = r.status === "connected"
      ? `${ic("eye")}${fmt(r.stats.viewers)} đang xem`
      : esc(STATUS_TEXT[r.status] || r.status);
    return `
      <span class="tav">${av}<span class="sdot ${esc(r.status)}"></span></span>
      <span class="tinfo"><span class="tname">${esc(room.nickname || "@" + r.uid)}</span><span class="tsub">${sub}</span></span>
      <span class="tflags">${r.using_session ? `<span class="tlock" title="Đang dùng sessionid">${ic("lock")}</span>` : ""}</span>
      <span class="tclose" data-close="${esc(r.uid)}" role="button" aria-label="Đóng phòng @${esc(r.uid)}" title="Đóng phòng">${ic("x")}</span>`;
  }
  function renderTabs() {
    $("roomCount").textContent = rooms.size;
    $("roomTabs").innerHTML = rooms.size
      ? [...rooms.values()].map((r) => `<button class="tab" data-room="${esc(r.uid)}" title="@${esc(r.uid)}">${tabInner(r)}</button>`).join("")
      : `<div class="room-empty">Chưa theo dõi phòng nào</div>`;
    markActiveTab();
    updateSummary();
  }
  function markActiveTab() {
    document.querySelectorAll("#tabs .tab").forEach((b) => {
      const on = b.dataset.room === ui.active;
      b.classList.toggle("on", on);
      if (on) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
    });
  }
  function tabEl(uid) { return document.querySelector(`#roomTabs .tab[data-room="${CSS.escape(uid)}"]`); }
  function updateTab(r) {
    const t = tabEl(r.uid); if (!t) return;
    const room = r.room || {};
    const sig = [r.status, room.avatar, room.nickname, !!r.using_session].join("|");
    if (t._sig !== sig) { t._sig = sig; t.innerHTML = tabInner(r); return; }
    const sub = t.querySelector(".tsub");  // chỉ đổi số người xem, không dựng lại ảnh (tránh nháy)
    if (sub && r.status === "connected") sub.innerHTML = `${ic("eye")}${fmt(r.stats.viewers)} đang xem`;
  }
  function updateRunbar() {
    const all = [...rooms.values()];
    const idle = all.filter((r) => !BUSY.includes(r.status)).length;
    const busy = all.length - idle;
    const go = $("btnStartAll"), stop = $("btnStopAll");
    go.hidden = idle === 0 && all.length > 0;
    go.disabled = all.length === 0;
    go.title = all.length ? `Kết nối ${idle} phòng chưa chạy` : "Chưa có phòng nào – thêm phòng trước";
    go.querySelector("span").textContent = busy && idle ? `Bắt đầu (${idle})` : "Bắt đầu";
    stop.hidden = busy === 0;
  }
  function updateSummary() {
    updateRunbar();
    const live = [...rooms.values()].filter((r) => r.status === "connected").length;
    const el = $("summary");
    el.innerHTML = rooms.size ? `<b>${live}</b>/${rooms.size} phòng đang live` : "Chưa có phòng nào";
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
    if (uid && rooms.get(uid).status === "choose") askChoice(uid);   // phòng đang chờ chọn phiên -> hỏi luôn
  }

  // ------------------------------------------------------------ wall (lưới)
  function tileHTML(r) {
    return `
      <div class="tile-head" data-open title="Mở chi tiết phòng">
        <img class="avatar" alt="" onerror="this.style.visibility='hidden'">
        <div class="tmeta"><b class="tn"></b><span class="tt"></span></div>
        <button class="tx" aria-label="Đóng phòng" title="Đóng phòng">${ic("x")}</button>
      </div>
      <div class="video-wrap">
        <video muted playsinline></video>
        <div class="video-empty ve"></div>
        <div class="tile-over"><span class="chip sm st"></span></div>
        <button class="vbtn mute" aria-label="Bật/tắt tiếng" title="Bật/tắt tiếng">${ic("mute")}</button>
      </div>
      <div class="tile-stats">
        <span class="v-eye" title="Đang xem">${ic("eye")}<b data-s="viewers">0</b></span>
        <span class="v-msg" title="Bình luận">${ic("msg")}<b data-s="comments">0</b></span>
        <span class="v-gem" title="Kim cương">${ic("gem")}<b data-s="diamonds">0</b></span>
        <span class="v-heart" title="Lượt thích">${ic("heart")}<b data-s="likes">0</b></span>
      </div>
      <ul class="mini-feed"></ul>`;
  }
  function tileEl(uid) { return document.querySelector(`#wall .tile[data-room="${CSS.escape(uid)}"]`); }

  function addTile(r) {
    if (r.status !== "connected" || tileEl(r.uid)) return;
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
      document.querySelectorAll("#wall .mute").forEach((x) => { x.innerHTML = ic("mute"); });
      v.muted = !turnOn;
      t.querySelector(".mute").innerHTML = ic(v.muted ? "mute" : "sound");
    });
    $("wall").appendChild(t);
    updateTile(r);
    updateTileStats(r);
    r.events.filter((ev) => MINI_KINDS.has(ev.kind) && !ev.streaking).slice(-MINI_FEED).forEach((ev) => addMini(r, ev));
    updateWallEmpty();
  }

  function updateTile(r) {
    const t = tileEl(r.uid); if (!t) return;
    const room = r.room || {};
    const img = t.querySelector(".avatar");
    if (room.avatar) { img.src = room.avatar; img.style.visibility = "visible"; } else img.style.visibility = "hidden";
    t.querySelector(".tn").textContent = room.nickname ? `${room.nickname} · @${r.uid}` : "@" + r.uid;
    t.querySelector(".tt").textContent = room.title || r.message || "";
    const st = t.querySelector(".st");
    st.className = "chip sm st " + r.status;
    st.textContent = STATUS_TEXT[r.status] || r.status;
    st.title = r.message || "";
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
      case "gift": txt = `${ic("gift")}${esc(ev.gift)} ×${ev.count}` + (ev.diamonds ? ` · ${fmt(ev.diamonds * ev.count)}` : ""); break;
      case "follow": txt = `${ic("user-plus")}đã theo dõi`; break;
      case "share": txt = `${ic("share")}đã chia sẻ`; break;
      case "barrage": txt = `${ic("star")}${barrageText(ev)}`; break;
      case "system": txt = `<i>${esc(ev.text)}</i>`; break;
    }
    li.innerHTML = name + txt;
    li._user = ev.user;
    ul.appendChild(li);
    while (ul.children.length > MINI_FEED) ul.firstElementChild.remove();
  }
  function removeTile(uid) {
    tileEl(uid)?.remove();
    updateWallEmpty();
  }
  function updateWallEmpty() {
    $("wallEmpty").hidden = [...rooms.values()].some((r) => r.status === "connected");
  }
  function renderWall() {
    $("wall").innerHTML = "";
    rooms.forEach((r) => { if (r.status === "connected") addTile(r); });
    updateWallEmpty();
  }

  // ------------------------------------------------------------ detail (một phòng)
  function renderDetail() {
    const r = cur(); if (!r) return;
    setRoomHeader(r);
    setQualities(r);
    setStatus(r);
    setStats(r.stats, true);
    renderTop();
    $("feed").innerHTML = ""; ui.giftRows.clear();
    r.events.forEach((ev) => addEventLi(ev, true));
    $("feed").scrollTop = $("feed").scrollHeight;
    $("uptime").textContent = "00:00:00";
  }

  function setStatus(r) {
    const el = $("status");
    el.className = "chip " + r.status;
    el.textContent = STATUS_TEXT[r.status] || r.status;
    el.title = r.message || "";
    $("btnDisconnect").disabled = !BUSY.includes(r.status);
  }

  function setRoomHeader(r) {
    const room = r.room || {};
    $("roomName").textContent = room.nickname ? `${room.nickname}  ·  @${r.uid}` : "@" + r.uid;
    $("roomTitle").textContent = room.title || r.message || "";
    const a = $("roomAvatar");
    if (room.avatar) { a.src = room.avatar; a.style.visibility = "visible"; } else { a.removeAttribute("src"); a.style.visibility = "hidden"; }
  }

  function blockHTML(roomUid, u) {
    if (!u || !u.id) return "";
    const r = rooms.get(roomUid);
    if (r && r.room && String(r.room.owner_id) === String(u.id)) return "";
    return `
      <div class="uc-mod">
        <div class="uc-sub">${ic("ban")}Chặn khỏi phòng này</div>
        <div class="uc-mod-row">
          <button class="btn sm danger" data-act="block">${ic("ban")}Chặn user</button>
        </div>
      </div>`;
  }
  async function blockUser(roomUid, u, btn) {
    const old = btn.innerHTML; btn.disabled = true; btn.textContent = "Đang gửi…";
    try {
      const j = await (await fetch(`/api/rooms/${enc(roomUid)}/block-user`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: String(u.id) })
      })).json();
      if (!j.ok) throw new Error(j.error || "Thất bại");
    } catch (ex) { toast(ex.message, "err"); }
    finally { btn.disabled = false; btn.innerHTML = old; }
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
  /** Danh sách chuẩn hoá cho bảng xếp hạng: [{rank, user, value, delta}] */
  function topItems(r) {
    if (!r) return [];
    if (ui.topTab === "live") return (r.top.live || []).map((x, i) => ({ rank: x.rank || i + 1, user: x.user, value: x.score, delta: x.delta }));
    return (r.top.gifters || []).map((u, i) => ({ rank: i + 1, user: u, value: u.value }));
  }
  function renderTop() {
    const r = cur();
    const items = topItems(r);
    const live = ui.topTab === "live";
    $("topNote").textContent = live
      ? "Bảng xếp hạng TikTok đang hiện trong phòng (theo điểm đóng góp của phiên live), cập nhật liên tục."
      : "Tổng kim cương mỗi người đã tặng kể từ lúc bắt đầu theo dõi phòng này.";
    $("topList").innerHTML = items.length
      ? items.map((x, i) => {
          const u = x.user || {};
          const val = live
            ? `<span class="v"><b>${fmt(x.value)}</b><small>điểm</small>${x.delta > 0 ? `<em class="up">+${fmt(x.delta)}</em>` : ""}</span>`
            : `<span class="v">${fmt(x.value)}${ic("gem")}</span>`;
          return `<li data-i="${i}" data-rank="${x.rank}"><span class="rk">${x.rank}</span>
            <img class="avatar" data-user src="${esc(u.avatar || "")}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">
            <span class="n"><span class="l1">${badgesHTML(u)}<span class="name" data-user>${esc(u.nickname || "")}</span></span>
            <span class="muted small">@${esc(u.unique_id || "")}</span></span>${val}</li>`;
        }).join("")
      : `<li class="empty">${live ? "Chưa có dữ liệu xếp hạng từ TikTok (phòng chưa có ai đóng góp hoặc chưa kết nối)" : "Chưa có ai tặng quà"}</li>`;
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
  /** Màu TikTok dạng #AARRGGBB -> rgba() (giữ đậm tối thiểu 85% cho dễ đọc trên nền tối). */
  function tkColor(c) {
    c = String(c || "").trim().replace(/^#/, "");
    if (/^[0-9a-f]{6}$/i.test(c)) return "#" + c;
    if (!/^[0-9a-f]{8}$/i.test(c)) return "";
    const n = (i) => parseInt(c.slice(i, i + 2), 16);
    return `rgba(${n(2)},${n(4)},${n(6)},${Math.max(n(0) / 255, 0.85).toFixed(2)})`;
  }
  const bgStyle = (c) => { const v = tkColor(c); return v ? ` style="background:${v}"` : ""; };
  const bimg = (src, fallback) => src ? `<img src="${esc(src)}" alt="" loading="lazy" onerror="this.remove()">` : (fallback ? ic(fallback) : "");
  function badgesHTML(u, full = false) {
    if (!u) return "";
    const out = [];
    if (u.mod) out.push(`<span class="bdg b-mod" title="Quản trị viên phòng">${ic("shield")}Mod</span>`);
    if (u.gift_level) out.push(`<span class="bdg b-lv"${bgStyle(u.gift_bg)} title="Level tặng quà ${u.gift_level}">${bimg(u.gift_icon, "gem")}${u.gift_level}</span>`);
    const f = u.fan;
    if (f && (f.name || f.level)) out.push(`<span class="bdg b-fan"${bgStyle(f.bg)} title="Fan club${f.name ? " " + esc(f.name) : ""} · level ${f.level || "?"}">` +
      `${bimg(f.icon, "heart")}${esc(f.name || "Fan")}${f.level ? `<i>${f.level}</i>` : ""}</span>`);
    if (u.rank) out.push(`<span class="bdg b-rank"${bgStyle(u.rank_bg)} title="Hạng ${u.rank} bảng xếp hạng tặng quà của phòng">${bimg(u.rank_icon, "medal")}Hạng ${u.rank}</span>`);
    if (u.sub) out.push(`<span class="bdg b-sub" title="Subscriber">${ic("star")}Sub</span>`);
    if (full) (u.badges || []).filter((b) => !KNOWN_SCENES.has(b.scene) && (b.label || b.icon)).forEach((b) => {
      out.push(`<span class="bdg b-other"${bgStyle(b.bg)} title="${esc(b.scene)}">${bimg(b.icon)}${esc(b.label || "")}</span>`);
    });
    return out.length ? `<span class="bdgs">${out.join("")}</span>` : "";
  }

  // ------------------------------------------------------------ feed
  const ACT = {
    like: { icon: "heart", text: (ev) => `thả ${fmt(ev.count)} tim` },
    join: { icon: "login", text: () => "vừa vào phòng" },
    follow: { icon: "user-plus", text: () => "đã theo dõi chủ phòng" },
    share: { icon: "share", text: () => "đã chia sẻ phiên live" },
    barrage: { icon: "star", text: (ev) => barrageText(ev) },
  };
  function barrageText(ev) {
    const g = ev.grade ? ev.grade : "";
    switch (ev.sub) {
      case "entrance":
      case "fan_entrance":
      case "enigma_entrance": return "đã tham gia";
      case "level_up": return `vừa lên level ${g}`;
      case "fan_level_up": return `vừa lên level fan ${g}`;
      case "subscribe": return "vừa đăng ký thành viên (subscribe)";
      default: return "thông báo nổi bật";
    }
  }
  function eventHTML(ev) {
    const u = ev.user;
    const t = `<time>${hhmm(ev.ts)}</time>`;
    if (ev.kind === "system") return `<div class="sys">${ic("info")}<span>${esc(ev.text)}</span>${t}</div>`;
    const av = u ? `<img class="avatar" data-user src="${esc(u.avatar || "")}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">` : "";
    const who = u ? `${badgesHTML(u)}<span class="name" data-user title="Xem thông tin">${esc(u.nickname)}</span>` : "";
    if (ev.kind === "comment") {
      return `${av}<div class="body"><div class="meta">${who}${t}</div><div class="bubble">${esc(ev.text)}</div></div>`;
    }
    if (ev.kind === "gift") {
      const total = ev.diamonds ? fmt(ev.diamonds * ev.count) : "";
      return `${av}<div class="body"><div class="meta">${who}${t}</div>
        <div class="gift-line">tặng <b>${esc(ev.gift)}</b>${total ? `<span class="dm">${ic("gem")}${total}</span>` : ""}</div></div>
        <div class="gift-art">${ev.gift_img ? `<img src="${esc(ev.gift_img)}" alt="">` : ic("gift")}<span class="gx">×${ev.count}</span></div>`;
    }
    const a = ACT[ev.kind] || { icon: "info", text: () => ev.kind };
    // "bay vào": giống dòng vào phòng nhưng hiện ảnh đại diện (kèm dấu sao nhỏ)
    const lead = (ev.kind === "barrage" || ev.kind === "join") && u
      ? `<span class="act-av">${av}<span class="act-star">${ic(a.icon)}</span></span>`
      : `<span class="act-ic">${ic(a.icon)}</span>`;
    return `${lead}<div class="body line">${who}<span class="act">${a.text(ev)}</span></div>${t}`;
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
    li.className = ev.kind + (ACT[ev.kind] ? " compact" : "") + (ev.streaking ? " streak" : "");
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
  const KIND_ICON = { comment: "msg", gift: "gift", follow: "user-plus", share: "share", barrage: "star" };

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
                                        (a.diamonds ? ` <span class="muted">· ${fmt(a.diamonds * a.count)} kim cương</span>` : "");
        else if (a.kind === "follow") t = "đã theo dõi chủ phòng";
        else if (a.kind === "share") t = "đã chia sẻ live";
        else if (a.kind === "barrage") t = barrageText(a);
        return `<li class="${a.kind}"><span class="k">${ic(KIND_ICON[a.kind] || "info")}</span><span class="t">${t}</span><span class="time">${hhmm(a.ts)}</span></li>`;
      }).join("");
      body = `
        <div class="uc-stats">
          ${stat(ic("msg"), "Bình luận", fmt(st.comments))}${stat(ic("gem"), "Kim cương", fmt(st.diamonds))}${stat(ic("gift"), "Quà", fmt(st.gifts))}
          ${stat(ic("heart"), "Tim", fmt(st.likes))}${stat(ic("login"), "Vào phòng", fmt(st.joins))}${stat(ic("share"), "Chia sẻ", fmt(st.shares))}
        </div>
        <div class="uc-meta muted small">
          ${ranks ? `<div>${ic("trophy")}${ranks} trong phiên</div>` : ""}
          <div>${ic("clock")}Lần đầu ${hhmm(st.first)} · gần nhất ${hhmm(st.last)}${st.followed ? " · <span class='ok'>đã follow</span>" : ""}</div>
        </div>
        ${recent ? `<div class="uc-sub">Hoạt động gần đây</div><ul class="uc-recent">${recent}</ul>` : ""}`;
    }
    return `
      <div class="uc-head">
        <img class="avatar xl" src="${esc(u.avatar || "")}" alt="" onerror="this.style.visibility='hidden'">
        <div class="uc-id"><b>${esc(u.nickname)}</b><span class="muted">@${esc(u.unique_id || "")}</span>
          ${u.followers || u.following ? `<span class="muted small">${fmt(u.followers)} follower · ${fmt(u.following)} đang follow</span>` : ""}</div>
        <button class="uc-x" data-close aria-label="Đóng" title="Đóng (Esc)">${ic("x")}</button>
      </div>
      <div class="uc-badges">${badgesHTML(u, true) || `<span class="muted small">Không có huy hiệu</span>`}</div>
      ${blockHTML(ucard._ctx && ucard._ctx.roomUid, u)}
      ${body}
      <div class="uc-actions">
        <a class="btn sm primary" href="${link}" target="_blank" rel="noopener noreferrer">${ic("external")}Mở TikTok</a>
        <button class="btn sm" data-act="filter">${ic("filter")}Lọc bình luận</button>
        <button class="btn sm" data-act="copy">${ic("copy")}Copy @id</button>
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
      try { await navigator.clipboard.writeText("@" + ctx.u.unique_id); e.target.closest("button").innerHTML = ic("check") + "Đã copy"; }
      catch (_) { prompt("Copy:", "@" + ctx.u.unique_id); }
    } else if (act === "block") {
      blockUser(ctx.roomUid, ctx.u, e.target.closest("button"));
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
      if (!u && li && li.dataset.i !== undefined) { const it = topItems(cur())[+li.dataset.i]; u = it && it.user; }
      const tile = trg.closest(".tile"); if (tile) room = tile.dataset.room;
      if (u && room) { e.stopPropagation(); openUserCard(room, u, trg); }
      return;
    }
    if (!ucard.hidden && !e.target.closest("#userCard")) closeUserCard();
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeUserCard(); });
  window.addEventListener("resize", () => { if (!ucard.hidden) closeUserCard(); });

  // ------------------------------------------------------------ video players
  const canPlay = () => window.mpegts && mpegts.isSupported();

  function makePlayer(video, uid, q, onError) {
    // WebSocket: trình duyệt giới hạn 6 kết nối HTTP / địa chỉ (video thứ 6 sẽ bị treo), WebSocket thì không
    const wsBase = (location.protocol === "https:" ? "wss://" : "ws://") + location.host;
    const p = mpegts.createPlayer({ type: "flv", isLive: true, url: `${wsBase}/ws/video/${enc(uid)}/${enc(q)}?_=${Date.now()}` },
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
        const j = await api("POST", "/api/rooms", { unique_id: n, auto_reconnect: $("autoRe").checked });
        last = j.unique_id;
        if (j.need_choice) askChoice(j.unique_id, j);
      } catch (err) { errors.push(`${n}: ${err.message}`); }
    }
    if (!errors.length) $("uid").value = "";
    if (errors.length) toast(errors.join("\n"), "err", 7000);
    else if (names.length) toast(names.length > 1 ? `Đã thêm ${names.length} phòng` : `Đang kết nối @${last}…`, "ok", 2500);
    if (names.length === 1 && last && ui.active) switchTo(last);  // đang ở tab 1 phòng → chuyển sang phòng mới
  });

  async function closeRoom(uid) {
    const r = rooms.get(uid);
    if (r && BUSY.includes(r.status) && !confirm(`Đóng phòng @${uid}? Phòng sẽ bị ngắt và xoá khỏi danh sách.`)) return;
    try { await api("DELETE", roomUrl(uid)); toast(`Đã đóng phòng @${uid}`, "ok", 2500); } catch (err) { toast(err.message, "err"); }
  }

  $("btnClose").onclick = () => ui.active && closeRoom(ui.active);
  $("btnReconnect").onclick = () => ui.active && connectRoom(ui.active);

  // ------------------------------------------------------------ nối tiếp phiên cũ / phiên mới
  // Backend tự nối tiếp nếu phòng mới ngừng hoạt động <= 1 giờ, tự tạo phiên mới nếu > 3 giờ;
  // ở giữa thì trả về need_choice -> hỏi người dùng.
  let askChain = Promise.resolve();
  const asking = new Set();
  function askChoice(uid, info) {
    if (asking.has(uid)) return askChain;
    asking.add(uid);
    askChain = askChain.then(() => new Promise((resolve) => {
      const r = rooms.get(uid);
      if (!r || (r.status !== "choose" && !info)) { asking.delete(uid); resolve(); return; }
      info = info || r.choice || {};
      const st = info.stats || {};
      const parts = [["comments", "bình luận"], ["diamonds", "kim cương"], ["gifts", "quà"], ["follows", "theo dõi"]]
        .filter(([k]) => st[k]).map(([k, t]) => `${fmt(st[k])} ${t}`);
      const last = info.last_active ? new Date(info.last_active * 1000).toLocaleString("vi-VN", { hour12: false }) : "";
      const bg = document.createElement("div");
      bg.className = "modal-bg";
      bg.innerHTML = `<div class="modal" role="dialog" aria-modal="true" aria-labelledby="mdT">
        <h3 id="mdT">${ic("clock")}Phiên cũ của @${esc(uid)}</h3>
        <p>Lần cuối phòng có hoạt động cách đây <b>${esc(info.gap_text || "?")}</b>${last ? ` <span class="muted">(${esc(last)})</span>` : ""}.</p>
        ${parts.length ? `<p class="muted">Phiên cũ đang có: ${parts.join(" · ")}</p>` : ""}
        <p class="muted">Đồng bộ = lấy lại số liệu, bảng xếp hạng, hoạt động của phiên cũ và ghi tiếp vào file log cũ.</p>
        <div class="modal-actions">
          <button class="btn primary" data-c="resume">${ic("refresh")}OK – Đồng bộ phiên cũ</button>
          <button class="btn" data-c="new">${ic("play")}Bắt đầu phiên mới</button>
          <button class="btn ghost" data-c="">Để sau</button>
        </div></div>`;
      const done = async (c) => {
        bg.remove(); document.removeEventListener("keydown", onKey); asking.delete(uid);
        if (c) await connectRoom(uid, c);
        resolve();
      };
      const onKey = (e) => { if (e.key === "Escape") done(""); };
      bg.addEventListener("click", (e) => { const b = e.target.closest("[data-c]"); if (b) done(b.dataset.c); else if (e.target === bg) done(""); });
      document.addEventListener("keydown", onKey);
      document.body.appendChild(bg);
      bg.querySelector("[data-c=resume]").focus();
    }));
    return askChain;
  }
  async function connectRoom(uid, choice = "auto") {
    try {
      const j = await api("POST", roomUrl(uid, "/reconnect"), { choice });
      if (j.need_choice) askChoice(uid, j);
      else if (j.resumed) toast(`@${uid}: nối tiếp phiên cũ`, "ok", 2500);
    } catch (err) { toast(err.message, "err"); }
  }
  async function reloadRoom(uid) {
    try {
      const s = await api("GET", roomUrl(uid, "/snapshot"));
      const r = rooms.get(uid); if (!r) return;
      r.stats = s.stats || {};
      r.top = { gifters: s.top_gifters || [], live: s.live_rank || [] };
      r.room = s.room || r.room;
      r.events = []; r.giftIdx.clear();
      (s.recent || []).forEach((ev) => storeEvent(r, ev));
      updateTab(r); updateTileStats(r);
      if (ui.active === uid) renderDetail();
    } catch (_) {}
  }
  $("btnDisconnect").onclick = () => ui.active && api("POST", roomUrl(ui.active, "/disconnect")).catch((err) => toast(err.message, "err"));

  // ------------------------------------------------------------ sessionid
  const MODE_TEXT = { auto: "tự động khi bị giới hạn tuổi", always: "luôn dùng", off: "đang tắt" };
  function setCfg(el, state, label, title, icon) {
    if (!el) return;   // các mục cấu hình đã bỏ khỏi web (cấu hình trong cửa sổ Kaynt LiveHub)
    el.className = "cfg" + (state ? " " + state : "");
    el.querySelector(".cfg-t").textContent = label;
    if (icon) el.querySelector("use").setAttribute("href", "#i-" + icon);
    el.title = title;
  }
  function setSession(info) {
    info = info || {};
    if (!info.configured) setCfg($("sessionPill"), "", "Chưa có sessionid",
      "Chưa có sessionid (dùng cho live giới hạn độ tuổi).\nNhập trong cửa sổ Kaynt LiveHub → tab Cài đặt.", "unlock");
    else if (info.problem) setCfg($("sessionPill"), "bad", "sessionid lỗi", info.problem + "\n(Cấu hình trong cửa sổ Kaynt LiveHub)", "lock");
    else setCfg($("sessionPill"), info.mode === "off" ? "" : "ok", "sessionid " + info.masked,
      "Chế độ: " + (MODE_TEXT[info.mode] || info.mode) + "\n(Cấu hình trong cửa sổ Kaynt LiveHub)", "lock");
  }
  function setSign(info) {
    info = info || {};
    if (info.configured) setCfg($("signPill"), "ok", "API key " + info.masked, "Đang dùng SIGN_API_KEY của Euler Stream (" + info.url + ")\n(Cấu hình trong cửa sổ Kaynt LiveHub)");
    else setCfg($("signPill"), "", "Chưa có API key", "Đang dùng máy chủ ký Euler Stream miễn phí (dễ bị giới hạn khi xem nhiều phòng).\nNhập API key trong cửa sổ Kaynt LiveHub → tab Cài đặt.");
  }
  async function reloadConfig() {
    try {
      const j = await api("POST", "/api/config/reload");
      setSession(j.session); setSign(j.sign);
      const s = j.session, g = j.sign;
      const lines = [
        g.configured ? `• API key Euler Stream: ${g.masked}` : "• Chưa có SIGN_API_KEY (dùng gói miễn phí)",
        !s.configured ? "• Chưa có TIKTOK_SESSIONID"
          : s.problem ? "• sessionid chưa dùng được: " + s.problem
          : `• sessionid ${s.masked} – ${MODE_TEXT[s.mode] || s.mode}`,
        "", "Áp dụng cho lần kết nối sau – phòng đang mở bấm \"Kết nối lại\".",
      ];
      toast("Đã đọc lại .env\n" + lines.filter(Boolean).join("\n"), "ok", 7000);
    } catch (err) { toast(err.message, "err"); }
  }

  // ------------------------------------------------------------ truy cập qua WiFi
  let lanInfo = null;
  function setLan(info) {
    lanInfo = info;
    const el = $("lanPill");
    if (!el) return;
    if (!info || !info.urls || !info.urls.length) { el.hidden = true; return; }
    el.hidden = false;
    setCfg(el, info.password ? "ok" : "bad", info.urls[0].replace("http://", ""),
      (info.password ? "Máy khác cùng WiFi vào bằng link này (cần mật khẩu)" : "Chưa đặt mật khẩu truy cập – ai cùng WiFi cũng điều khiển được (đặt trong cửa sổ Kaynt LiveHub)") + "\nBấm để copy link");
  }
  if ($("lanPill")) $("lanPill").onclick = async () => {
    if (!lanInfo) return;
    const url = lanInfo.urls[0];
    let copied = false;
    try { await navigator.clipboard.writeText(url); copied = true; } catch (_) {}
    toast((copied ? "Đã copy link cho máy khác cùng WiFi:\n" : "Link cho máy khác cùng WiFi:\n") + lanInfo.urls.join("\n") +
      (lanInfo.password ? "\nMáy khác sẽ được hỏi mật khẩu truy cập."
                        : "\nChưa đặt mật khẩu truy cập (cửa sổ Kaynt LiveHub) – ai cùng WiFi cũng xem & điều khiển được."),
      lanInfo.password ? "ok" : "err", 8000);
  };

  // ------------------------------------------------------------ Bắt đầu / Dừng tất cả
  $("btnStartAll").onclick = async () => {
    const b = $("btnStartAll");
    b.classList.add("busy"); b.disabled = true;
    try {
      ui.askUntil = Date.now() + 90000;   // phòng nào cần chọn phiên trong lúc kết nối lần lượt -> hỏi
      const j = await api("POST", "/api/start_all");
      toast(j.count ? `Đang kết nối ${j.count} phòng (lần lượt vài giây một phòng)…` : "Tất cả phòng đã đang chạy", "ok", 3500);
    } catch (err) { toast(err.message, "err"); }
    finally { b.classList.remove("busy"); updateRunbar(); }
  };
  $("btnStopAll").onclick = async () => {
    const busy = [...rooms.values()].filter((r) => BUSY.includes(r.status)).length;
    const msg = `Dừng kết nối ${busy} phòng đang chạy?` +
      "\n\nCác phòng vẫn được lưu, bấm Bắt đầu để chạy lại.";
    if (!confirm(msg)) return;
    try {
      const j = await api("POST", "/api/stop_all");
      toast(`Đã dừng ${j.count} phòng. Các phòng vẫn được lưu, bấm Bắt đầu để chạy lại.`, "ok", 4000);
    } catch (err) { toast(err.message, "err"); }
  };

  // ------------------------------------------------------------ cấu hình nằm ở cửa sổ Kaynt LiveHub (Python)
  const cfgHint = () => toast("sessionid, API key và mật khẩu WiFi được cấu hình trong cửa sổ Kaynt LiveHub (tab Cài đặt) trên máy chạy app.", "info", 6000);
  if ($("sessionPill")) $("sessionPill").onclick = cfgHint;
  if ($("signPill")) $("signPill").onclick = cfgHint;

  // ------------------------------------------------------------ realtime
  function applySnapshot(s) {
    setSession(s.session); setSign(s.sign); setLan(s.lan);
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
      renderTabs(); updateWallEmpty();
      return;
    }
    if (type === "config") {
      setSession(data.session); setSign(data.sign);
      if (lanInfo && data.lan_password !== undefined) { lanInfo.password = data.lan_password; setLan(lanInfo); }
      return;
    }
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
      r.top = { gifters: data.top_gifters || [], live: data.live_rank || [] };
      updateTileStats(r); updateTab(r);
      if (isActive) { setStats(r.stats); renderTop(); }
    } else if (type === "sample") {
      // biểu đồ "Diễn biến" đã bỏ – bỏ qua dữ liệu mẫu
    } else if (type === "status") {
      Object.assign(r, {
        status: data.status, message: data.message, room: data.room || r.room, qualities: data.qualities || [],
        auto_reconnect: data.auto_reconnect,
        using_session: data.using_session, choice: data.choice || null,
      });
      if (data.status === "connecting") {
        if (data.resumed) reloadRoom(uid);   // nối tiếp phiên cũ: lấy lại số liệu + feed đã có, không xoá
        else { r.stats = {}; r.top = { gifters: [], live: [] }; r.events = []; r.giftIdx.clear(); }
      }
      if (data.status === "choose" && (ui.askUntil || 0) > Date.now()) askChoice(uid);
      updateTab(r);
      if (data.status === "connected") {
        if (tileEl(uid)) updateTile(r);
        else addTile(r);
      } else removeTile(uid);
      updateSummary();
      if (isActive) {
        if (data.status === "connecting") renderDetail();
        else { setRoomHeader(r); setQualities(r); setStatus(r); }
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
