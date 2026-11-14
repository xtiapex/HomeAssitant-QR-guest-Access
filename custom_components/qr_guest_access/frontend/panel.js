/* QR Guest Access - pannello laterale "Accessi ospiti".
 * Nessuna dipendenza e nessun build: un unico web component che usa
 * l'oggetto `hass` di Home Assistant (autenticazione e WebSocket inclusi). */

const STATUS = {
  active: { label: "Attivo", cls: "ok" },
  pending: { label: "In attesa", cls: "info" },
  exhausted: { label: "Esaurito", cls: "muted" },
  expired: { label: "Scaduto", cls: "muted" },
  revoked: { label: "Revocato", cls: "bad" },
};

const RESULT = {
  granted: { label: "Accesso consentito", cls: "ok" },
  denied_unknown: { label: "QR sconosciuto", cls: "bad" },
  denied_revoked: { label: "QR revocato", cls: "bad" },
  denied_expired: { label: "QR scaduto", cls: "bad" },
  denied_not_started: { label: "Non ancora valido", cls: "warn" },
  denied_exhausted: { label: "Accessi esauriti", cls: "bad" },
  error: { label: "Errore porta", cls: "warn" },
};

const PRESETS = {
  single24: { uses: 1, unlimited: false, hours: 24 },
  multi7: { uses: 5, unlimited: false, hours: 24 * 7 },
  unlimited30: { uses: 1, unlimited: true, hours: 24 * 30 },
};

// Tutto ciò che arriva dall'esterno (nomi, codici letti dalla camera) passa da qui.
function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

const pad = (n) => String(n).padStart(2, "0");
function toLocalInput(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

const TEMPLATE = `
<style>
  :host { display: block; min-height: 100%; background: var(--primary-background-color);
          color: var(--primary-text-color); font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif); }
  * { box-sizing: border-box; }
  .page { max-width: 1180px; margin: 0 auto; padding: 0 16px 48px; }
  header { display: flex; align-items: center; gap: 12px; height: 56px; padding: 0 4px; }
  header h1 { font-size: 20px; font-weight: 500; margin: 0; flex: 1; }
  .toggle { display: flex; align-items: center; gap: 8px; font-size: 14px; cursor: pointer; }
  .toggle input { width: 18px; height: 18px; accent-color: var(--primary-color); }
  .banner { border-radius: 10px; padding: 12px 16px; margin: 4px 0 16px; font-size: 14px; line-height: 1.45; }
  .banner.test { background: color-mix(in srgb, var(--warning-color, #ffa600) 18%, transparent);
                 border: 1px solid var(--warning-color, #ffa600); }
  .banner.live { background: color-mix(in srgb, var(--success-color, #43a047) 14%, transparent);
                 border: 1px solid var(--success-color, #43a047); }
  .banner.error { background: color-mix(in srgb, var(--error-color, #db4437) 16%, transparent);
                  border: 1px solid var(--error-color, #db4437); }
  .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px; }
  .tile { background: var(--card-background-color); border: 1px solid var(--divider-color);
          border-radius: var(--ha-card-border-radius, 12px); padding: 14px 16px; }
  .tile .v { font-size: 26px; font-weight: 500; line-height: 1.1; }
  .tile .l { font-size: 12px; color: var(--secondary-text-color); margin-top: 4px; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; align-items: start; }
  .card { background: var(--card-background-color); border: 1px solid var(--divider-color);
          border-radius: var(--ha-card-border-radius, 12px); padding: 16px; margin-bottom: 16px; }
  .grid .card { margin-bottom: 0; }
  .card h2 { font-size: 16px; font-weight: 500; margin: 0 0 12px; display: flex; align-items: center; gap: 8px; }
  .card h2 .spacer { flex: 1; }
  label.f { display: block; font-size: 12px; color: var(--secondary-text-color); margin: 12px 0 4px; }
  input[type=text], input[type=number], input[type=datetime-local], select {
    width: 100%; padding: 10px 12px; font: inherit; color: var(--primary-text-color);
    background: var(--secondary-background-color, transparent); border: 1px solid var(--divider-color);
    border-radius: 8px; }
  input:focus, select:focus { outline: 2px solid var(--primary-color); outline-offset: -1px; }
  input:disabled { opacity: .5; }
  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .inline { display: flex; align-items: center; gap: 8px; margin-top: 8px; font-size: 14px; }
  .inline input { width: 18px; height: 18px; accent-color: var(--primary-color); }
  .presets { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 4px; }
  button { font: inherit; cursor: pointer; border-radius: 8px; padding: 8px 14px; border: 1px solid var(--divider-color);
           background: transparent; color: var(--primary-text-color); }
  button:hover { border-color: var(--primary-color); }
  button.primary { background: var(--primary-color); color: var(--text-primary-color, #fff);
                   border-color: var(--primary-color); font-weight: 500; }
  button.primary:disabled { opacity: .6; cursor: default; }
  button.danger { color: var(--error-color, #db4437); }
  button.danger.armed { background: var(--error-color, #db4437); color: #fff; border-color: var(--error-color, #db4437); }
  button.small { padding: 5px 10px; font-size: 13px; }
  button.chip-btn { padding: 4px 10px; font-size: 13px; border-radius: 999px; }
  .msg { margin-top: 10px; font-size: 14px; min-height: 18px; }
  .msg.err { color: var(--error-color, #db4437); }
  .hint { font-size: 12px; color: var(--secondary-text-color); margin-top: 6px; line-height: 1.4; }
  .result { margin-top: 14px; padding: 14px; border: 1px dashed var(--divider-color); border-radius: 10px; text-align: center; }
  .result img, .modal img { width: 240px; max-width: 100%; image-rendering: pixelated; background: #fff;
                            border-radius: 8px; padding: 4px; }
  .result .actions, .modal .actions { display: flex; gap: 8px; justify-content: center; margin-top: 10px; }
  .cam { width: 100%; aspect-ratio: 16 / 9; background: #000; border-radius: 10px; object-fit: contain; display: block; }
  .cam-empty { padding: 28px 12px; text-align: center; color: var(--secondary-text-color); font-size: 14px; }
  .row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 16px; padding: 12px 0;
         border-top: 1px solid var(--divider-color); }
  .row:first-of-type { border-top: none; }
  .row .main { flex: 1 1 260px; min-width: 0; }
  .row .name { font-weight: 500; overflow-wrap: anywhere; }
  .row .meta { font-size: 13px; color: var(--secondary-text-color); margin-top: 2px; line-height: 1.4; }
  .row .actions { display: flex; gap: 6px; flex-wrap: wrap; }
  .row .time { flex: 0 0 130px; font-size: 13px; color: var(--secondary-text-color); }
  .row .door { flex: 0 0 90px; font-size: 13px; color: var(--secondary-text-color); }
  .chip { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 12px; font-weight: 500;
          vertical-align: middle; margin-left: 6px; border: 1px solid currentColor; white-space: nowrap; }
  .chip.ok { color: var(--success-color, #43a047); }
  .chip.bad { color: var(--error-color, #db4437); }
  .chip.warn { color: var(--warning-color, #ffa600); }
  .chip.info { color: var(--info-color, #039be5); }
  .chip.muted { color: var(--secondary-text-color); }
  .tag { font-size: 11px; padding: 1px 7px; border-radius: 6px; background: var(--secondary-background-color);
         color: var(--secondary-text-color); margin-left: 6px; }
  .empty { padding: 18px 0; color: var(--secondary-text-color); font-size: 14px; text-align: center; }
  .modal { position: fixed; inset: 0; background: rgba(0,0,0,.55); display: flex; align-items: center;
           justify-content: center; z-index: 20; padding: 16px; }
  .modal[hidden] { display: none; }
  .modal .box { background: var(--card-background-color); border-radius: 14px; padding: 20px; text-align: center;
                max-width: 340px; width: 100%; }
  .modal h3 { margin: 0 0 12px; font-size: 16px; font-weight: 500; overflow-wrap: anywhere; }
  @media (max-width: 900px) {
    .grid { grid-template-columns: 1fr; }
    .stats { grid-template-columns: repeat(2, 1fr); }
    .row .time, .row .door { flex: 1 1 auto; }
  }
</style>

<div class="page">
  <header>
    <ha-menu-button></ha-menu-button>
    <h1>Accessi ospiti</h1>
    <label class="toggle"><input type="checkbox" id="testToggle"><span>Modalità test</span></label>
  </header>

  <div id="banner"></div>
  <section class="stats" id="stats"></section>

  <div class="grid">
    <section class="card">
      <h2>Nuovo QR</h2>
      <label class="f" for="name">Nome</label>
      <input type="text" id="name" maxlength="60" placeholder="Es. Idraulico, Mario, Corriere" autocomplete="off">

      <label class="f">Scorciatoie</label>
      <div class="presets">
        <button class="chip-btn" data-preset="single24">Monouso · 24 ore</button>
        <button class="chip-btn" data-preset="multi7">5 accessi · 7 giorni</button>
        <button class="chip-btn" data-preset="unlimited30">Illimitato · 30 giorni</button>
      </div>

      <div class="two">
        <div><label class="f" for="from">Valido dal</label><input type="datetime-local" id="from"></div>
        <div><label class="f" for="until">Valido fino al</label><input type="datetime-local" id="until"></div>
      </div>
      <div class="hint">Se lasci vuoto "Valido dal", il QR vale da subito. Gli orari sono quelli del tuo dispositivo.</div>

      <label class="f" for="uses">Numero di accessi</label>
      <input type="number" id="uses" min="1" max="999" value="1">
      <label class="inline"><input type="checkbox" id="unlimited"> Accessi illimitati (richiede una data di fine)</label>

      <div style="margin-top:16px"><button class="primary" id="createBtn">Genera QR</button></div>
      <div class="msg" id="createMsg"></div>
      <div id="result"></div>
    </section>

    <section class="card">
      <h2>Telecamera <span class="spacer"></span><span class="hint" id="readerInfo"></span></h2>
      <div id="camBox"></div>
    </section>
  </div>

  <section class="card">
    <h2>QR creati</h2>
    <div id="tokens"></div>
  </section>

  <section class="card">
    <h2>Prova una scansione</h2>
    <div class="two">
      <div><label class="f" for="simToken">Scegli un QR</label><select id="simToken"></select></div>
      <div><label class="f" for="simCode">Oppure un testo qualsiasi</label>
           <input type="text" id="simCode" placeholder="Es. QR di un estraneo" autocomplete="off"></div>
    </div>
    <div style="margin-top:12px"><button id="simBtn">Simula scansione</button></div>
    <div class="hint" id="simHint"></div>
    <div class="msg" id="simResult"></div>
  </section>

  <section class="card">
    <h2>Storico <span class="spacer"></span><button class="small danger" id="clearLogs">Cancella</button></h2>
    <div id="logs"></div>
  </section>
</div>

<div class="modal" id="modal" hidden>
  <div class="box">
    <h3 id="modalTitle"></h3>
    <div id="modalBody"></div>
    <div class="actions"><button class="primary" id="modalDownload">Scarica PNG</button><button id="modalClose">Chiudi</button></div>
    <div class="hint">Su smartphone puoi anche tenere premuto sull'immagine per salvarla o condividerla.</div>
  </div>
</div>
`;

class QRGuestAccessPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._narrow = false;
    this._data = null;
    this._error = null;
    this._built = false;
    this._active = false;
    this._timers = [];
    this._unsubEvents = null;
    this._refreshDebounce = null;
    this._confirmKey = null;
    this._confirmTimer = null;
    this._modalImage = null;
  }

  // ---- proprietà impostate da Home Assistant -------------------------------
  set hass(hass) {
    this._hass = hass;
    if (this.isConnected && !this._active) this._start();
    this._onHass();
  }
  set narrow(value) {
    this._narrow = !!value;
    this._syncMenu();
  }
  set panel(value) {
    this._panel = value;
  }

  connectedCallback() {
    if (this._hass && !this._active) this._start();
  }
  disconnectedCallback() {
    this._stop();
  }

  // ---- ciclo di vita ----------------------------------------------------------
  _start() {
    this._active = true;
    if (!this._built) {
      this.shadowRoot.innerHTML = TEMPLATE;
      this._wire();
      this._built = true;
    }
    this._syncMenu();
    this._refresh();
    this._timers.push(setInterval(() => this._refresh(), 30000));
    this._timers.push(setInterval(() => this._refreshCam(), 2000));
    this._hass.connection
      .subscribeEvents(() => this._scheduleRefresh(), "qr_guest_access_update")
      .then((unsub) => {
        if (this._active) this._unsubEvents = unsub;
        else unsub();
      })
      .catch(() => {});
  }

  _stop() {
    this._active = false;
    this._timers.forEach(clearInterval);
    this._timers = [];
    clearTimeout(this._refreshDebounce);
    if (this._unsubEvents) {
      this._unsubEvents();
      this._unsubEvents = null;
    }
  }

  _q(selector) {
    return this.shadowRoot.querySelector(selector);
  }

  _syncMenu() {
    const menu = this.shadowRoot && this.shadowRoot.querySelector("ha-menu-button");
    if (menu) {
      menu.hass = this._hass;
      menu.narrow = this._narrow;
    }
  }

  // ---- collegamento degli eventi dell'interfaccia ------------------------------
  _wire() {
    this._q("#createBtn").addEventListener("click", () => this._create());
    this._q("#name").addEventListener("keydown", (e) => { if (e.key === "Enter") this._create(); });
    this._q("#unlimited").addEventListener("change", () => this._syncUnlimited());
    this._q("#testToggle").addEventListener("change", (e) => this._toggleTest(e.target));
    this._q("#simBtn").addEventListener("click", () => this._simulate());
    this._q("#clearLogs").addEventListener("click", (e) => this._clearLogs(e.currentTarget));
    this._q("#modalClose").addEventListener("click", () => this._closeModal());
    this._q("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") this._closeModal(); });
    this._q("#modalDownload").addEventListener("click", () => {
      if (this._modalImage) this._download(this._modalImage.filename, this._modalImage.b64);
    });
    this.shadowRoot.addEventListener("keydown", (e) => { if (e.key === "Escape") this._closeModal(); });

    this.shadowRoot.querySelectorAll("[data-preset]").forEach((btn) =>
      btn.addEventListener("click", () => this._applyPreset(btn.dataset.preset)));

    this._q("#tokens").addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-act]");
      if (btn) this._tokenAction(btn.dataset.act, btn.dataset.id);
    });
    this._q("#result").addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-res]");
      if (!btn) return;
      if (btn.dataset.res === "download" && this._lastCreated) {
        this._download(this._lastCreated.filename, this._lastCreated.png_base64);
      } else if (btn.dataset.res === "close") {
        this._q("#result").innerHTML = "";
      }
    });
  }

  // ---- dati -----------------------------------------------------------------------
  _scheduleRefresh() {
    clearTimeout(this._refreshDebounce);
    this._refreshDebounce = setTimeout(() => this._refresh(), 250);
  }

  async _refresh() {
    if (!this._hass) return;
    try {
      this._data = await this._hass.callWS({ type: "qr_guest_access/state" });
      this._error = null;
    } catch (err) {
      this._error = (err && err.message) || String(err);
    }
    this._renderAll();
  }

  _onHass() {
    // `hass` cambia a ogni variazione di stato: qui aggiorniamo solo cose leggere.
    this._syncMenu();
    this._renderLive();
  }

  // ---- disegno ----------------------------------------------------------------------
  _fmt(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "—";
    return d.toLocaleString((this._hass && this._hass.locale && this._hass.locale.language) || undefined, {
      day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit",
    });
  }

  _renderAll() {
    if (!this._built) return;
    this._renderBanner();
    this._renderStats();
    this._renderCamera();
    this._renderTokens();
    this._renderSim();
    this._renderLogs();
    this._renderLive();
  }

  _renderBanner() {
    const el = this._q("#banner");
    const toggle = this._q("#testToggle");
    if (this._error && !this._data) {
      el.innerHTML = `<div class="banner error">Non riesco a leggere i dati dell'integrazione: ${esc(this._error)}</div>`;
      return;
    }
    const test = !!(this._data && this._data.settings.test_mode);
    toggle.checked = test;
    if (this._error) {
      el.innerHTML = `<div class="banner error">Aggiornamento non riuscito: ${esc(this._error)}</div>`;
    } else if (test) {
      el.innerHTML = `<div class="banner test"><b>Modalità test attiva.</b> I QR validi vengono riconosciuti ma
        <b>la porta non si apre</b> e gli accessi <b>non vengono scalati</b>. Disattivala (in alto a destra) quando
        sei pronto a usare il sistema sul serio.</div>`;
    } else {
      el.innerHTML = `<div class="banner live"><b>Sistema attivo.</b> Un QR valido apre la porta per
        ${esc(this._data.settings.open_seconds)} secondi e scala un accesso.</div>`;
    }
  }

  _renderStats() {
    if (!this._data) return;
    const s = this._data.stats;
    const pending = s.pending ? ` <span class="l">(+${esc(s.pending)} in attesa)</span>` : "";
    this._q("#stats").innerHTML = `
      <div class="tile"><div class="v">${esc(s.active)}${pending}</div><div class="l">QR attivi</div></div>
      <div class="tile"><div class="v">${esc(s.granted)}</div><div class="l">Accessi consentiti</div></div>
      <div class="tile"><div class="v">${esc(s.denied)}</div><div class="l">Accessi negati</div></div>
      <div class="tile"><div class="v" id="doorState">—</div><div class="l">Relè porta</div></div>`;
  }

  _renderLive() {
    if (!this._built || !this._data || !this._hass) return;
    const ent = this._data.entities || {};
    const door = this._q("#doorState");
    if (door) {
      const st = this._hass.states[ent.door];
      door.textContent = !st ? "n/d" : st.state === "on" ? "Acceso" : st.state === "off" ? "Spento" : st.state;
    }
    const info = this._q("#readerInfo");
    if (info) {
      const st = this._hass.states[ent.reader];
      info.textContent = st ? `Lettore: ${st.state === "unknown" ? "nessun QR visibile" : "QR visibile"}` : "Lettore non trovato";
    }
  }

  _renderCamera() {
    const box = this._q("#camBox");
    const ent = this._data && this._data.entities && this._data.entities.camera;
    if (!ent) {
      if (!box.dataset.mode || box.dataset.mode !== "none") {
        box.dataset.mode = "none";
        box.innerHTML = `<div class="cam-empty">Nessuna telecamera selezionata.<br>Puoi aggiungerla dalle impostazioni
          dell'integrazione per inquadrare meglio il QR.</div>`;
      }
      return;
    }
    if (box.dataset.mode !== "cam") {
      box.dataset.mode = "cam";
      box.innerHTML = `<img class="cam" id="cam" alt="Anteprima della telecamera">
        <div class="hint">Anteprima aggiornata ogni 2 secondi: serve per controllare inquadratura e distanza del QR.</div>`;
      this._refreshCam();
    }
  }

  _refreshCam() {
    if (document.hidden || !this._hass || !this._data) return;
    const ent = this._data.entities && this._data.entities.camera;
    const img = this._q("#cam");
    if (!ent || !img) return;
    const st = this._hass.states[ent];
    const pic = st && st.attributes && st.attributes.entity_picture;
    if (!pic) return;
    const probe = new Image();
    probe.onload = () => { img.src = probe.src; };
    probe.src = `${pic}${pic.includes("?") ? "&" : "?"}_=${Date.now()}`;
  }

  _usesText(t) {
    if (t.max_uses === null) return `Accessi illimitati · usato ${t.uses_count} volte`;
    return `${t.uses_left} di ${t.max_uses} accessi rimasti`;
  }

  _renderTokens() {
    const box = this._q("#tokens");
    if (!this._data) return;
    const tokens = this._data.tokens;
    if (!tokens.length) {
      box.innerHTML = `<div class="empty">Nessun QR creato. Usa il modulo "Nuovo QR" per generarne uno.</div>`;
      return;
    }
    box.innerHTML = tokens.map((t) => {
      const st = STATUS[t.status] || { label: t.status, cls: "muted" };
      const validity = `Dal ${this._fmt(t.valid_from)}` + (t.valid_until ? ` al ${this._fmt(t.valid_until)}` : "");
      const last = t.last_used ? `Ultimo uso ${this._fmt(t.last_used)}` : "Mai usato";
      const live = t.status === "active" || t.status === "pending";
      const rKey = `revoke:${t.id}`;
      const dKey = `delete:${t.id}`;
      return `<div class="row">
        <div class="main">
          <div class="name">${esc(t.name)}<span class="chip ${st.cls}">${esc(st.label)}</span></div>
          <div class="meta">${esc(this._usesText(t))}<br>${esc(validity)} · ${esc(last)}</div>
        </div>
        <div class="actions">
          ${live ? `<button class="small" data-act="qr" data-id="${esc(t.id)}">Mostra QR</button>` : ""}
          ${t.status !== "revoked" ? `<button class="small danger ${this._confirmKey === rKey ? "armed" : ""}" data-act="revoke" data-id="${esc(t.id)}">${this._confirmKey === rKey ? "Conferma?" : "Revoca"}</button>` : ""}
          <button class="small danger ${this._confirmKey === dKey ? "armed" : ""}" data-act="delete" data-id="${esc(t.id)}">${this._confirmKey === dKey ? "Conferma?" : "Elimina"}</button>
        </div>
      </div>`;
    }).join("");
  }

  _renderSim() {
    if (!this._data) return;
    const select = this._q("#simToken");
    const previous = select.value;
    const opts = this._data.tokens.map((t) => {
      const st = STATUS[t.status] || { label: t.status };
      return `<option value="${esc(t.id)}">${esc(t.name)} (${esc(st.label)})</option>`;
    });
    select.innerHTML = opts.length ? opts.join("") : `<option value="">Nessun QR creato</option>`;
    if (previous && this._data.tokens.some((t) => t.id === previous)) select.value = previous;

    this._q("#simHint").innerHTML = this._data.settings.test_mode
      ? "Modalità test attiva: la simulazione controlla il QR ma non apre la porta e non scala accessi."
      : "<b>Attenzione:</b> la modalità test è disattivata, quindi la simulazione apre davvero la porta e scala un accesso.";
  }

  _renderLogs() {
    const box = this._q("#logs");
    if (!this._data) return;
    const logs = this._data.logs;
    if (!logs.length) {
      box.innerHTML = `<div class="empty">Nessuna scansione registrata.</div>`;
      return;
    }
    box.innerHTML = logs.map((l) => {
      const res = RESULT[l.result] || { label: l.result, cls: "muted" };
      const who = l.name ? esc(l.name) : `Codice sconosciuto <span class="tag">${esc(l.code || "")}</span>`;
      const tags = (l.source === "simulate" ? `<span class="tag">simulata</span>` : "") +
        (l.test ? `<span class="tag">test</span>` : "");
      return `<div class="row">
        <div class="time">${esc(this._fmt(l.ts))}</div>
        <div class="main"><span class="name">${who}</span>${tags}</div>
        <div><span class="chip ${res.cls}" style="margin-left:0">${esc(res.label)}</span></div>
        <div class="door">${l.door_opened ? "Porta aperta" : "Porta chiusa"}</div>
      </div>`;
    }).join("");
  }

  // ---- azioni ------------------------------------------------------------------------
  _syncUnlimited() {
    const unlimited = this._q("#unlimited").checked;
    this._q("#uses").disabled = unlimited;
  }

  _applyPreset(key) {
    const p = PRESETS[key];
    if (!p) return;
    const now = new Date();
    this._q("#from").value = "";
    this._q("#until").value = toLocalInput(new Date(now.getTime() + p.hours * 3600 * 1000));
    this._q("#uses").value = p.uses;
    this._q("#unlimited").checked = p.unlimited;
    this._syncUnlimited();
  }

  _setMsg(selector, text, isError) {
    const el = this._q(selector);
    el.textContent = text || "";
    el.className = "msg" + (isError ? " err" : "");
  }

  async _create() {
    const name = this._q("#name").value.trim();
    const from = this._q("#from").value;
    const until = this._q("#until").value;
    const unlimited = this._q("#unlimited").checked;
    const uses = parseInt(this._q("#uses").value, 10);

    if (!name) return this._setMsg("#createMsg", "Scrivi un nome per il QR.", true);
    if (!unlimited && !Number.isInteger(uses)) return this._setMsg("#createMsg", "Indica il numero di accessi.", true);

    const btn = this._q("#createBtn");
    btn.disabled = true;
    this._setMsg("#createMsg", "Genero il QR…", false);
    try {
      const res = await this._hass.callWS({
        type: "qr_guest_access/create",
        name,
        valid_from: from ? new Date(from).toISOString() : null,
        valid_until: until ? new Date(until).toISOString() : null,
        max_uses: unlimited ? null : uses,
      });
      this._lastCreated = res;
      this._showResult(res);
      this._q("#name").value = "";
      this._setMsg("#createMsg", "", false);
      await this._refresh();
    } catch (err) {
      this._setMsg("#createMsg", (err && err.message) || "Creazione non riuscita.", true);
    } finally {
      btn.disabled = false;
    }
  }

  _showResult(res) {
    const t = res.token;
    const box = this._q("#result");
    const validity = `Dal ${this._fmt(t.valid_from)}` + (t.valid_until ? ` al ${this._fmt(t.valid_until)}` : "");
    const uses = t.max_uses === null ? "Accessi illimitati" : `${t.max_uses} ${t.max_uses === 1 ? "accesso" : "accessi"}`;
    if (!res.png_base64) {
      box.innerHTML = `<div class="result"><div class="msg err">Il QR "${esc(t.name)}" è stato creato, ma non sono
        riuscito a disegnarlo: ${esc(res.qr_error || "errore sconosciuto")}. Troverai il token nell'elenco.</div></div>`;
      return;
    }
    box.innerHTML = `<div class="result">
      <img alt="QR di ${esc(t.name)}" src="data:image/png;base64,${res.png_base64}">
      <div class="name" style="margin-top:8px;font-weight:500">${esc(t.name)}</div>
      <div class="hint">${esc(uses)} · ${esc(validity)}</div>
      <div class="actions"><button class="primary" data-res="download">Scarica PNG</button><button data-res="close">Chiudi</button></div>
      <div class="hint">Su smartphone puoi anche tenere premuto sull'immagine per salvarla o condividerla.</div>
    </div>`;
  }

  _download(filename, b64) {
    const link = document.createElement("a");
    link.href = `data:image/png;base64,${b64}`;
    link.download = filename || "qr.png";
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  _armConfirm(key) {
    if (this._confirmKey === key) {
      clearTimeout(this._confirmTimer);
      this._confirmKey = null;
      return true;
    }
    this._confirmKey = key;
    clearTimeout(this._confirmTimer);
    this._confirmTimer = setTimeout(() => {
      this._confirmKey = null;
      this._renderTokens();
    }, 3000);
    this._renderTokens();
    return false;
  }

  async _tokenAction(action, id) {
    try {
      if (action === "qr") {
        const res = await this._hass.callWS({ type: "qr_guest_access/qr", id });
        const token = this._data.tokens.find((t) => t.id === id);
        this._openModal(token ? token.name : "QR", res);
      } else if (action === "revoke" || action === "delete") {
        if (!this._armConfirm(`${action}:${id}`)) return;
        await this._hass.callWS({ type: `qr_guest_access/${action}`, id });
        await this._refresh();
      }
    } catch (err) {
      this._error = (err && err.message) || String(err);
      this._renderBanner();
    }
  }

  _openModal(title, res) {
    this._modalImage = { filename: res.filename, b64: res.png_base64 };
    this._q("#modalTitle").textContent = title;
    this._q("#modalBody").innerHTML = `<img alt="QR di ${esc(title)}" src="data:image/png;base64,${res.png_base64}">`;
    this._q("#modal").hidden = false;
  }

  _closeModal() {
    this._q("#modal").hidden = true;
    this._q("#modalBody").innerHTML = "";
    this._modalImage = null;
  }

  async _toggleTest(input) {
    const enabled = input.checked;
    if (!enabled && !window.confirm(
      "Disattivare la modalità test? Da questo momento un QR valido aprirà davvero la porta e scalerà un accesso.")) {
      input.checked = true;
      return;
    }
    try {
      await this._hass.callWS({ type: "qr_guest_access/set_test_mode", enabled });
    } catch (err) {
      this._error = (err && err.message) || String(err);
    }
    await this._refresh();
  }

  async _simulate() {
    const code = this._q("#simCode").value.trim();
    const tokenId = this._q("#simToken").value;
    if (!code && !tokenId) return this._setMsg("#simResult", "Scegli un QR o scrivi un testo.", true);
    try {
      const res = await this._hass.callWS({
        type: "qr_guest_access/simulate",
        ...(code ? { code } : { token_id: tokenId }),
      });
      if (res.ignored) {
        this._setMsg("#simResult", "Testo ignorato: è uno dei valori che il lettore usa per dire \"nessun QR\".", false);
      } else {
        const r = RESULT[res.result] || { label: res.result };
        const door = res.test ? "porta non aperta (modalità test)" : res.door_opened ? "porta aperta" : "porta chiusa";
        this._setMsg("#simResult", `${r.label} · ${door}`, !(res.result === "granted"));
      }
    } catch (err) {
      this._setMsg("#simResult", (err && err.message) || "Simulazione non riuscita.", true);
    }
    await this._refresh();
  }

  async _clearLogs(button) {
    if (!button.dataset.armed) {
      button.dataset.armed = "1";
      button.textContent = "Conferma?";
      button.classList.add("armed");
      setTimeout(() => {
        delete button.dataset.armed;
        button.textContent = "Cancella";
        button.classList.remove("armed");
      }, 3000);
      return;
    }
    try {
      await this._hass.callWS({ type: "qr_guest_access/clear_logs" });
    } catch (err) {
      this._error = (err && err.message) || String(err);
    }
    delete button.dataset.armed;
    button.textContent = "Cancella";
    button.classList.remove("armed");
    await this._refresh();
  }
}

customElements.define("qr-guest-access-panel", QRGuestAccessPanel);
