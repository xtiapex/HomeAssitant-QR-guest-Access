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
  denied_no_door: { label: "Nessuna porta abilitata", cls: "warn" },
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
  [hidden] { display: none !important; }
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
  .row .door { flex: 0 0 170px; font-size: 13px; color: var(--secondary-text-color); line-height: 1.35; }
  .row .door .fail { color: var(--warning-color, #ffa600); }
  .checks { display: flex; flex-wrap: wrap; gap: 4px 16px; margin-top: 6px; }
  .checks .inline { margin-top: 0; }
  .search { width: 100%; margin-bottom: 4px; }
  .count { font-size: 12px; color: var(--secondary-text-color); margin: 4px 0 6px; }
  .modal.edit .box select, .modal.edit .box input[type=text] { margin-bottom: 0; }
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
  .modal.edit .box { max-width: 420px; text-align: left; max-height: 92vh; overflow-y: auto; }
  .modal.edit h3 { margin-bottom: 4px; }
  .toast { position: fixed; left: 50%; bottom: 24px; transform: translateX(-50%); z-index: 30; max-width: min(92vw, 520px);
           background: var(--error-color, #db4437); color: #fff; padding: 12px 18px; border-radius: 10px; font-size: 14px;
           box-shadow: 0 4px 16px rgba(0,0,0,.35); }
  .toast[hidden] { display: none; }
  @media (max-width: 900px) {
    .grid { grid-template-columns: 1fr; }
    .stats { grid-template-columns: repeat(2, 1fr); }
    .row .time, .row .door { flex: 1 1 auto; }
  }
</style>

<div class="page">
  <header>
    <ha-menu-button></ha-menu-button>
    <h1 id="title">Accessi ospiti</h1>
    <label class="toggle" id="testWrap"><input type="checkbox" id="testToggle"><span>Modalità test</span></label>
    <button id="settingsBtn">⚙ Impostazioni</button>
    <button id="backBtn" hidden>← Indietro</button>
  </header>

  <div id="banner"></div>

  <div id="settingsView" hidden>
    <section class="card">
      <h2>Porte <span class="spacer"></span><button class="small" id="doorAddBtn">+ Aggiungi porta</button></h2>
      <div class="hint" style="margin:0 0 6px">Un solo lettore QR apre tutte le porte autorizzate dal QR (ognuna col suo relè): un passaggio conta come un solo accesso.</div>
      <div id="doorList"></div>
    </section>
    <section class="card">
      <h2>Lettore e telecamera</h2>
      <label class="f" for="setReader">Lettore QR (image_processing)</label>
      <select id="setReader"></select>
      <label class="f" for="setCamera">Telecamera per l'anteprima (facoltativa)</label>
      <select id="setCamera"></select>
      <div style="margin-top:14px"><button class="primary" id="readerSave">Salva</button></div>
      <div class="msg" id="readerMsg"></div>
    </section>
    <section class="card">
      <h2>Notifiche sul telefono</h2>
      <div class="hint" style="margin:0 0 6px">Scegli i telefoni (app Home Assistant) che ricevono un avviso con il nome di chi ha aperto e la porta.</div>
      <div class="checks" id="notifyDevices"></div>
      <label class="inline"><input type="checkbox" id="notifyGranted"> Avvisa quando qualcuno entra</label>
      <label class="inline"><input type="checkbox" id="notifyDenied"> Avvisa anche per i tentativi negati (QR scaduto, sconosciuto…)</label>
      <div class="hint">Se una porta non risponde ricevi sempre un avviso. In modalità test non parte nessuna notifica.</div>
      <div style="margin-top:14px;display:flex;gap:8px;flex-wrap:wrap">
        <button class="primary" id="notifySave">Salva</button>
        <button id="notifyTest">Invia notifica di prova</button>
      </div>
      <div class="msg" id="notifyMsg"></div>
    </section>
  </div>

  <div id="mainView">
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

      <div id="createDoors" hidden>
        <label class="f">Porte che apre</label>
        <div class="checks" id="createDoorChecks"></div>
        <div class="hint">Un passaggio apre tutte le porte spuntate e consuma un solo accesso.</div>
      </div>

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
    <input type="text" class="search" id="logSearch" placeholder="Cerca per nome, porta o codice…" autocomplete="off">
    <div class="count" id="logCount"></div>
    <div id="logs"></div>
  </section>
  </div>
</div>

<div class="toast" id="toast" role="alert" hidden></div>

<div class="modal edit" id="editModal" hidden>
  <div class="box">
    <h3 id="editTitle"></h3>
    <div class="hint" id="editInfo"></div>
    <div class="two">
      <div><label class="f" for="editFrom">Valido dal</label><input type="datetime-local" id="editFrom"></div>
      <div><label class="f" for="editUntil">Valido fino al</label><input type="datetime-local" id="editUntil"></div>
    </div>
    <label class="f" for="editUses">Accessi disponibili da adesso</label>
    <input type="number" id="editUses" min="1" max="999" value="1">
    <label class="inline"><input type="checkbox" id="editUnlimited"> Accessi illimitati (richiede una data di fine)</label>
    <div id="editDoors" hidden>
      <label class="f">Porte che apre</label>
      <div class="checks" id="editDoorChecks"></div>
    </div>
    <div class="hint">Gli accessi già usati restano nello storico. Un QR scaduto o esaurito torna attivo se le nuove date e i nuovi accessi lo permettono.</div>
    <div class="msg" id="editMsg"></div>
    <div class="actions" style="justify-content:flex-end"><button id="editCancel">Annulla</button><button class="primary" id="editSave">Salva</button></div>
  </div>
</div>

<div class="modal edit" id="doorModal" hidden>
  <div class="box">
    <h3 id="doorModalTitle">Porta</h3>
    <label class="f" for="doorName">Nome (es. Cancello, Garage)</label>
    <input type="text" id="doorName" maxlength="40" autocomplete="off">
    <label class="f" for="doorEntity">Relè (interruttore della Shelly)</label>
    <select id="doorEntity"></select>
    <label class="f" for="doorSeconds">Secondi di apertura</label>
    <input type="number" id="doorSeconds" min="1" max="30" value="3">
    <div class="hint">Per quanto tempo il relè resta acceso dopo un QR valido. Consiglio: imposta lo stesso tempo anche come auto-spegnimento sulla Shelly.</div>
    <div class="msg" id="doorMsg"></div>
    <div class="actions" style="justify-content:flex-end"><button id="doorCancel">Annulla</button><button class="primary" id="doorSave">Salva</button></div>
  </div>
</div>

<div class="modal" id="modal" hidden>
  <div class="box">
    <h3 id="modalTitle"></h3>
    <div id="modalBody"></div>
    <div class="actions"><button class="primary" id="modalDownload">Scarica PNG</button><button id="modalShare" hidden>Condividi</button><button id="modalClose">Chiudi</button></div>
    <div class="hint">Dal telefono usa «Condividi» (WhatsApp, Foto…) oppure «Scarica PNG».</div>
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
    this._view = "main";
    this._logQuery = "";
    this._searchRes = null;
    this._searchSeq = 0;
    this._searchDebounce = null;
    this._doorEditId = null;
    this._createDoorsSig = null;
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
    clearTimeout(this._searchDebounce);
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
    this._q("#settingsBtn").addEventListener("click", () => this._showView("settings"));
    this._q("#backBtn").addEventListener("click", () => this._showView("main"));
    this._q("#doorAddBtn").addEventListener("click", () => this._openDoor(null));
    this._q("#doorCancel").addEventListener("click", () => this._closeDoor());
    this._q("#doorSave").addEventListener("click", () => this._saveDoor());
    this._q("#doorModal").addEventListener("click", (e) => { if (e.target.id === "doorModal") this._closeDoor(); });
    this._q("#readerSave").addEventListener("click", () => this._saveReader());
    this._q("#notifySave").addEventListener("click", () => this._saveNotify());
    this._q("#notifyTest").addEventListener("click", () => this._testNotify());
    this._q("#doorList").addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-door]");
      if (btn) this._doorAction(btn.dataset.door, btn.dataset.id);
    });
    this._q("#logSearch").addEventListener("input", () => {
      clearTimeout(this._searchDebounce);
      this._searchDebounce = setTimeout(() => this._runLogSearch(), 250);
    });
    this._q("#clearLogs").addEventListener("click", (e) => this._clearLogs(e.currentTarget));
    this._q("#modalClose").addEventListener("click", () => this._closeModal());
    this._q("#editCancel").addEventListener("click", () => this._closeEdit());
    this._q("#editSave").addEventListener("click", () => this._saveEdit());
    this._q("#editUnlimited").addEventListener("change", () => this._syncEditUnlimited());
    this._q("#editModal").addEventListener("click", (e) => { if (e.target.id === "editModal") this._closeEdit(); });
    this._q("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") this._closeModal(); });
    this._q("#modalDownload").addEventListener("click", () => {
      if (this._modalImage) this._download(this._modalImage);
    });
    this._q("#modalShare").addEventListener("click", () => {
      if (this._modalImage) this._share(this._modalImage);
    });
    this.shadowRoot.addEventListener("keydown", (e) => { if (e.key === "Escape") { this._closeModal(); this._closeEdit(); this._closeDoor(); } });

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
        this._download(this._createdImage());
      } else if (btn.dataset.res === "share" && this._lastCreated) {
        this._share(this._createdImage());
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
    if (this._logQuery) await this._runLogSearch(true);
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
    this._renderCreateDoors();
    this._renderTokens();
    this._renderSim();
    this._renderLogs();
    this._renderDoorList();
    if (this._view === "settings" && !this._formsReady) this._renderSettingsForms();
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
      const names = this._data.doors.map((d) => d.name).join(" + ");
      const nodoor = !this._data.doors.length ? " <b>Nessuna porta configurata: aggiungila dalle Impostazioni.</b>" : "";
      el.innerHTML = `<div class="banner live"><b>Sistema attivo.</b> Un QR valido apre ${esc(names || "la porta")}
        e scala un accesso.${nodoor}</div>`;
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
      <div class="tile"><div class="v" id="doorState">—</div><div class="l">Relè porte</div></div>`;
  }

  _renderLive() {
    if (!this._built || !this._data || !this._hass) return;
    const door = this._q("#doorState");
    if (door) {
      const doors = this._data.doors;
      const states = doors.map((d) => this._hass.states[d.door_entity]);
      const on = states.filter((st) => st && st.state === "on").length;
      const missing = states.filter((st) => !st).length;
      door.textContent = !doors.length ? "—"
        : on ? (doors.length > 1 ? `${on} accesi` : "Acceso")
        : missing === doors.length ? "n/d" : "Spenti";
      if (doors.length === 1) door.textContent = on ? "Acceso" : missing ? "n/d" : "Spento";
    }
    const info = this._q("#readerInfo");
    if (info) {
      const reader = this._data.reader.reader_entity;
      const st = reader ? this._hass.states[reader] : null;
      info.textContent = !reader ? "Lettore non impostato"
        : st ? `Lettore: ${st.state === "unknown" ? "nessun QR visibile" : "QR visibile"}` : "Lettore non trovato";
    }
  }

  _renderCamera() {
    const box = this._q("#camBox");
    const ent = this._data && this._data.reader && this._data.reader.camera_entity;
    if (!ent) {
      if (!box.dataset.mode || box.dataset.mode !== "none") {
        box.dataset.mode = "none";
        box.innerHTML = `<div class="cam-empty">Nessuna telecamera selezionata.<br>Puoi sceglierla da ⚙ Impostazioni
          per inquadrare meglio il QR.</div>`;
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
    const ent = this._data.reader && this._data.reader.camera_entity;
    const img = this._q("#cam");
    if (!ent || !img) return;
    const st = this._hass.states[ent];
    const pic = st && st.attributes && st.attributes.entity_picture;
    if (!pic) return;
    const probe = new Image();
    probe.onload = () => { img.src = probe.src; };
    probe.src = `${pic}${pic.includes("?") ? "&" : "?"}_=${Date.now()}`;
  }

  _doorsText(t) {
    const doors = (this._data && this._data.doors) || [];
    if (doors.length < 2) return "";
    if (t.doors === null) return "Tutte le porte";
    const names = t.doors.map((id) => (doors.find((d) => d.id === id) || {}).name).filter(Boolean);
    return names.length ? `Apre: ${names.join(", ")}` : "Nessuna porta abilitata";
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
          <div class="meta">${esc(this._usesText(t))}${this._doorsText(t) ? ` · ${esc(this._doorsText(t))}` : ""}<br>${esc(validity)} · ${esc(last)}</div>
        </div>
        <div class="actions">
          ${live ? `<button class="small" data-act="qr" data-id="${esc(t.id)}">Mostra QR</button>` : ""}
          <button class="small" data-act="edit" data-id="${esc(t.id)}">Modifica</button>
          ${t.status === "revoked"
            ? `<button class="small" data-act="restore" data-id="${esc(t.id)}">Riabilita</button>`
            : `<button class="small danger ${this._confirmKey === rKey ? "armed" : ""}" data-act="revoke" data-id="${esc(t.id)}">${this._confirmKey === rKey ? "Conferma?" : "Revoca"}</button>`}
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
      ? "Modalità test attiva: la simulazione controlla il QR ma non apre le porte e non scala accessi."
      : "<b>Attenzione:</b> la modalità test è disattivata, quindi la simulazione apre davvero le porte e scala un accesso.";
  }

  async _runLogSearch(silent) {
    const query = this._q("#logSearch").value.trim();
    this._logQuery = query;
    if (!query) {
      this._searchRes = null;
      if (!silent) this._renderLogs();
      return;
    }
    const seq = ++this._searchSeq;
    try {
      const res = await this._hass.callWS({ type: "qr_guest_access/logs", query, limit: 200 });
      if (seq !== this._searchSeq) return;  // è partita una ricerca più recente
      this._searchRes = res.logs;
    } catch (err) {
      if (seq !== this._searchSeq) return;
      this._searchRes = null;
      this._toast((err && err.message) || "Ricerca non riuscita.");
    }
    if (!silent) this._renderLogs();
  }

  _doorCell(l) {
    const doors = (l.doors || []).join(", ");
    const failed = (l.doors_failed || []).join(", ");
    let text;
    if (l.door_opened) text = doors ? `Aperta: ${esc(doors)}` : "Porta aperta";
    else if (l.test && doors) text = `Test: ${esc(doors)}`;
    else text = "Porta chiusa";
    return text + (failed ? `<br><span class="fail">Non si è aperta: ${esc(failed)}</span>` : "");
  }

  _renderLogs() {
    const box = this._q("#logs");
    if (!this._data) return;
    const searching = !!this._logQuery;
    const logs = searching && this._searchRes ? this._searchRes : this._data.logs;
    const count = this._q("#logCount");
    if (searching && this._searchRes) {
      count.textContent = `${logs.length}${logs.length >= 200 ? "+" : ""} ${logs.length === 1 ? "risultato" : "risultati"} per “${this._logQuery}”`;
    } else if (this._data.logs.length >= 100) {
      count.textContent = "Mostro le ultime 100 scansioni: usa la ricerca per trovare anche le precedenti (fino a 500).";
    } else {
      count.textContent = "";
    }
    if (!logs.length) {
      box.innerHTML = `<div class="empty">${searching ? "Nessun risultato." : "Nessuna scansione registrata."}</div>`;
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
        <div class="door">${this._doorCell(l)}</div>
      </div>`;
    }).join("");
  }

  // ---- porte: scelta per QR ----------------------------------------------------------------
  _doorChecksHtml(selected) {
    // selected: null = tutte; altrimenti lista di id
    return this._data.doors.map((d) => {
      const on = selected === null || selected.includes(d.id);
      return `<label class="inline"><input type="checkbox" data-door-id="${esc(d.id)}" ${on ? "checked" : ""}> ${esc(d.name)}</label>`;
    }).join("");
  }

  _readDoorChecks(boxSelector) {
    const boxes = [...this._q(boxSelector).querySelectorAll("input[data-door-id]")];
    if (boxes.length < 2) return null;
    const ids = boxes.filter((b) => b.checked).map((b) => b.dataset.doorId);
    return ids.length === boxes.length ? null : ids;
  }

  _renderCreateDoors() {
    if (!this._data) return;
    const doors = this._data.doors;
    const sig = doors.map((d) => `${d.id}:${d.name}`).join("|");
    const wrap = this._q("#createDoors");
    wrap.hidden = doors.length < 2;
    if (sig !== this._createDoorsSig) {  // si ridisegna solo se le porte cambiano: le spunte restano
      this._createDoorsSig = sig;
      this._q("#createDoorChecks").innerHTML = this._doorChecksHtml(null);
    }
  }

  // ---- impostazioni --------------------------------------------------------------------------
  _showView(view) {
    this._view = view;
    const settings = view === "settings";
    this._q("#mainView").hidden = settings;
    this._q("#settingsView").hidden = !settings;
    this._q("#settingsBtn").hidden = settings;
    this._q("#backBtn").hidden = !settings;
    this._q("#testWrap").hidden = settings;
    this._q("#title").textContent = settings ? "Impostazioni" : "Accessi ospiti";
    if (settings) {
      this._formsReady = false;
      if (this._data) this._renderSettingsForms();
    }
  }

  _entityOptions(domains, current, emptyLabel) {
    const states = Object.values((this._hass && this._hass.states) || {})
      .filter((st) => domains.includes(st.entity_id.split(".")[0]))
      .map((st) => ({ id: st.entity_id, name: (st.attributes && st.attributes.friendly_name) || st.entity_id }))
      .sort((a, b) => a.name.localeCompare(b.name));
    if (current && !states.some((x) => x.id === current)) states.unshift({ id: current, name: `${current} (non trovata)` });
    const opts = states.map((x) =>
      `<option value="${esc(x.id)}" ${x.id === current ? "selected" : ""}>${esc(x.name)} · ${esc(x.id)}</option>`);
    if (emptyLabel) opts.unshift(`<option value="" ${current ? "" : "selected"}>${esc(emptyLabel)}</option>`);
    return opts.join("");
  }

  _notifyServices() {
    const svc = (this._hass && this._hass.services && this._hass.services.notify) || {};
    return Object.keys(svc).filter((n) => n.startsWith("mobile_app_")).sort().map((n) => `notify.${n}`);
  }

  _renderSettingsForms() {
    if (!this._data || !this._hass) return;
    this._formsReady = true;
    const reader = this._data.reader;
    this._q("#setReader").innerHTML = this._entityOptions(["image_processing"], reader.reader_entity, reader.reader_entity ? "" : "— scegli —");
    this._q("#setCamera").innerHTML = this._entityOptions(["camera"], reader.camera_entity, "Nessuna");
    const notify = this._data.settings.notify;
    const available = this._notifyServices();
    const all = [...available, ...notify.services.filter((s) => !available.includes(s))];
    this._q("#notifyDevices").innerHTML = all.length
      ? all.map((s) => `<label class="inline"><input type="checkbox" data-notify="${esc(s)}" ${notify.services.includes(s) ? "checked" : ""}>
          ${esc(s.replace("notify.mobile_app_", "").replace("notify.", ""))}${available.includes(s) ? "" : " (non trovato)"}</label>`).join("")
      : `<div class="hint">Nessun telefono trovato. Installa l'app Home Assistant sul telefono e accedi: comparirà qui.</div>`;
    this._q("#notifyGranted").checked = !!notify.on_granted;
    this._q("#notifyDenied").checked = !!notify.on_denied;
  }

  _renderDoorList() {
    const box = this._q("#doorList");
    if (!this._data) return;
    const doors = this._data.doors;
    if (!doors.length) {
      box.innerHTML = `<div class="empty">Nessuna porta. Aggiungine una per poter aprire con i QR.</div>`;
      return;
    }
    box.innerHTML = doors.map((d) => {
      const key = `doordel:${d.id}`;
      const armed = this._confirmKey === key;
      return `<div class="row">
        <div class="main"><div class="name">${esc(d.name)}</div>
          <div class="meta">${esc(d.door_entity)} · ${esc(d.open_seconds)} s</div></div>
        <div class="actions">
          <button class="small" data-door="edit" data-id="${esc(d.id)}">Modifica</button>
          <button class="small danger ${armed ? "armed" : ""}" data-door="delete" data-id="${esc(d.id)}" ${doors.length < 2 ? "disabled title=\"Deve restare almeno una porta\"" : ""}>${armed ? "Conferma?" : "Elimina"}</button>
        </div></div>`;
    }).join("");
  }

  _openDoor(id) {
    const d = id ? this._data.doors.find((x) => x.id === id) : null;
    this._doorEditId = d ? d.id : null;
    this._q("#doorModalTitle").textContent = d ? `Modifica "${d.name}"` : "Nuova porta";
    this._q("#doorName").value = d ? d.name : "";
    this._q("#doorEntity").innerHTML = this._entityOptions(["switch", "light", "input_boolean"], d ? d.door_entity : null, d ? "" : "— scegli —");
    this._q("#doorSeconds").value = d ? d.open_seconds : 3;
    this._setMsg("#doorMsg", "", false);
    this._q("#doorModal").hidden = false;
  }

  _closeDoor() {
    const modal = this._q("#doorModal");
    if (modal) modal.hidden = true;
    this._doorEditId = null;
  }

  async _saveDoor() {
    const name = this._q("#doorName").value.trim();
    const entity = this._q("#doorEntity").value;
    const seconds = parseInt(this._q("#doorSeconds").value, 10);
    if (!name) return this._setMsg("#doorMsg", "Scrivi un nome per la porta.", true);
    if (!entity) return this._setMsg("#doorMsg", "Scegli il relè.", true);
    if (!Number.isInteger(seconds)) return this._setMsg("#doorMsg", "Indica i secondi di apertura.", true);
    const btn = this._q("#doorSave");
    btn.disabled = true;
    try {
      if (this._doorEditId) {
        await this._hass.callWS({
          type: "qr_guest_access/door_update", door_id: this._doorEditId,
          name, door_entity: entity, open_seconds: seconds,
        });
      } else {
        await this._hass.callWS({
          type: "qr_guest_access/door_add", name, door_entity: entity, open_seconds: seconds,
        });
      }
      this._closeDoor();
      await this._refresh();
    } catch (err) {
      this._setMsg("#doorMsg", (err && err.message) || "Salvataggio non riuscito.", true);
    } finally {
      btn.disabled = false;
    }
  }

  async _doorAction(action, id) {
    try {
      if (action === "edit") {
        this._openDoor(id);
      } else if (action === "delete") {
        if (!this._armConfirm(`doordel:${id}`)) return;
        await this._hass.callWS({ type: "qr_guest_access/door_delete", door_id: id });
        await this._refresh();
      }
    } catch (err) {
      this._toast((err && err.message) || "Operazione non riuscita.");
    }
  }

  async _saveReader() {
    const reader = this._q("#setReader").value;
    const camera = this._q("#setCamera").value;
    if (!reader) return this._setMsg("#readerMsg", "Scegli il lettore QR.", true);
    try {
      await this._hass.callWS({
        type: "qr_guest_access/set_reader", reader_entity: reader, camera_entity: camera || null,
      });
      this._setMsg("#readerMsg", "Salvato.", false);
      this._q("#camBox").dataset.mode = "";
      await this._refresh();
    } catch (err) {
      this._setMsg("#readerMsg", (err && err.message) || "Salvataggio non riuscito.", true);
    }
  }

  _readNotify() {
    return {
      services: [...this._q("#notifyDevices").querySelectorAll("input[data-notify]")]
        .filter((b) => b.checked).map((b) => b.dataset.notify),
      on_granted: this._q("#notifyGranted").checked,
      on_denied: this._q("#notifyDenied").checked,
    };
  }

  async _saveNotify() {
    try {
      await this._hass.callWS({ type: "qr_guest_access/set_notify", ...this._readNotify() });
      this._setMsg("#notifyMsg", "Salvato.", false);
      await this._refresh();
    } catch (err) {
      this._setMsg("#notifyMsg", (err && err.message) || "Salvataggio non riuscito.", true);
    }
  }

  async _testNotify() {
    try {
      // la prova usa ciò che è salvato: salviamo prima la scelta attuale
      await this._hass.callWS({ type: "qr_guest_access/set_notify", ...this._readNotify() });
      const res = await this._hass.callWS({ type: "qr_guest_access/test_notify" });
      this._setMsg("#notifyMsg", res.failed.length
        ? `Non raggiunti: ${res.failed.join(", ")}`
        : "Notifica inviata: controlla il telefono.", res.failed.length > 0);
      await this._refresh();
    } catch (err) {
      this._setMsg("#notifyMsg", (err && err.message) || "Invio non riuscito.", true);
    }
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

  _toast(text) {
    const el = this._q("#toast");
    if (!el) return;
    el.textContent = text;
    el.hidden = false;
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => { el.hidden = true; }, 6000);
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
    const doors = this._readDoorChecks("#createDoorChecks");
    if (doors && !doors.length) return this._setMsg("#createMsg", "Scegli almeno una porta.", true);

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
        doors,
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
      <div class="actions"><button class="primary" data-res="download">Scarica PNG</button>${this._canShare() ? `<button data-res="share">Condividi</button>` : ""}<button data-res="close">Chiudi</button></div>
      <div class="hint">Dal telefono usa «Condividi» (WhatsApp, Foto…) oppure «Scarica PNG».</div>
    </div>`;
  }

  _createdImage() {
    const r = this._lastCreated;
    return { filename: r.filename, b64: r.png_base64, tokenId: r.token.id };
  }

  _canShare() {
    try {
      if (!navigator.share || !navigator.canShare) return false;
      return navigator.canShare({ files: [new File([""], "qr.png", { type: "image/png" })] });
    } catch (_e) {
      return false;
    }
  }

  async _share(img) {
    try {
      const bytes = Uint8Array.from(atob(img.b64), (c) => c.charCodeAt(0));
      const file = new File([bytes], img.filename || "qr.png", { type: "image/png" });
      await navigator.share({ files: [file], title: "QR di accesso" });
    } catch (err) {
      if (err && err.name === "AbortError") return;  // l'utente ha annullato
      this._toast("Condivisione non riuscita: prova «Scarica PNG».");
    }
  }

  async _download(img) {
    // Indirizzo firmato (vale 1 minuto): è un vero file, e funziona anche nell'app mobile.
    // Se non riesce, ripieghiamo sul download diretto dal browser.
    let href = `data:image/png;base64,${img.b64}`;
    if (img.tokenId) {
      try {
        const signed = await this._hass.callWS({
          type: "auth/sign_path", path: `/api/qr_guest_access/qr/${img.tokenId}`, expires: 60,
        });
        href = signed.path;
      } catch (_e) { /* si usa il data: URL */ }
    }
    const link = document.createElement("a");
    link.href = href;
    link.download = img.filename || "qr.png";
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
      this._renderDoorList();
    }, 3000);
    this._renderTokens();
    this._renderDoorList();
    return false;
  }

  async _tokenAction(action, id) {
    try {
      if (action === "edit") {
        this._openEdit(id);
      } else if (action === "qr") {
        const res = await this._hass.callWS({ type: "qr_guest_access/qr", token_id: id });
        const token = this._data.tokens.find((t) => t.id === id);
        this._openModal(token ? token.name : "QR", res, id);
      } else if (action === "restore") {
        await this._hass.callWS({ type: "qr_guest_access/restore", token_id: id });
        await this._refresh();
      } else if (action === "revoke" || action === "delete") {
        if (!this._armConfirm(`${action}:${id}`)) return;
        await this._hass.callWS({ type: `qr_guest_access/${action}`, token_id: id });
        await this._refresh();
      }
    } catch (err) {
      this._toast((err && err.message) || "Operazione non riuscita.");
    }
  }

  _openModal(title, res, tokenId) {
    this._modalImage = { filename: res.filename, b64: res.png_base64, tokenId };
    this._q("#modalShare").hidden = !this._canShare();
    this._q("#modalTitle").textContent = title;
    this._q("#modalBody").innerHTML = `<img alt="QR di ${esc(title)}" src="data:image/png;base64,${res.png_base64}">`;
    this._q("#modal").hidden = false;
  }

  _closeModal() {
    this._q("#modal").hidden = true;
    this._q("#modalBody").innerHTML = "";
    this._modalImage = null;
  }

  _openEdit(id) {
    const t = this._data && this._data.tokens.find((x) => x.id === id);
    if (!t) return;
    this._editId = id;
    const unlimited = t.max_uses === null;
    this._q("#editTitle").textContent = `Modifica "${t.name}"`;
    this._q("#editInfo").textContent = unlimited
      ? `Usato ${t.uses_count} volte · accessi illimitati`
      : `Usato ${t.uses_count} ${t.uses_count === 1 ? "volta" : "volte"} · ${t.uses_left} ${t.uses_left === 1 ? "accesso rimasto" : "accessi rimasti"}`;
    this._q("#editFrom").value = t.valid_from ? toLocalInput(new Date(t.valid_from)) : "";
    this._q("#editUntil").value = t.valid_until ? toLocalInput(new Date(t.valid_until)) : "";
    this._q("#editDoors").hidden = this._data.doors.length < 2;
    this._q("#editDoorChecks").innerHTML = this._doorChecksHtml(t.doors);
    this._q("#editUnlimited").checked = unlimited;
    this._q("#editUses").value = unlimited ? 1 : Math.max(t.uses_left, 1);
    this._syncEditUnlimited();
    this._setMsg("#editMsg", "", false);
    this._q("#editModal").hidden = false;
  }

  _closeEdit() {
    const modal = this._q("#editModal");
    if (modal) modal.hidden = true;
    this._editId = null;
  }

  _syncEditUnlimited() {
    this._q("#editUses").disabled = this._q("#editUnlimited").checked;
  }

  async _saveEdit() {
    if (!this._editId) return;
    const from = this._q("#editFrom").value;
    const until = this._q("#editUntil").value;
    const unlimited = this._q("#editUnlimited").checked;
    const uses = parseInt(this._q("#editUses").value, 10);
    if (!unlimited && !Number.isInteger(uses)) return this._setMsg("#editMsg", "Indica il numero di accessi.", true);
    const doors = this._readDoorChecks("#editDoorChecks");
    if (doors && !doors.length) return this._setMsg("#editMsg", "Scegli almeno una porta.", true);

    const btn = this._q("#editSave");
    btn.disabled = true;
    this._setMsg("#editMsg", "Salvo…", false);
    try {
      await this._hass.callWS({
        type: "qr_guest_access/update",
        token_id: this._editId,
        valid_from: from ? new Date(from).toISOString() : null,
        valid_until: until ? new Date(until).toISOString() : null,
        uses_left: unlimited ? null : uses,
        doors,
      });
      this._closeEdit();
      await this._refresh();
    } catch (err) {
      this._setMsg("#editMsg", (err && err.message) || "Salvataggio non riuscito.", true);
    } finally {
      btn.disabled = false;
    }
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
      this._toast((err && err.message) || "Operazione non riuscita.");
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
        const names = (res.doors || []).join(", ");
        const door = res.test ? `porte non aperte (modalità test)${names ? `: ${names}` : ""}`
          : res.door_opened ? `aperta: ${names}` : "porta chiusa";
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
      this._toast((err && err.message) || "Operazione non riuscita.");
    }
    delete button.dataset.armed;
    button.textContent = "Cancella";
    button.classList.remove("armed");
    await this._refresh();
  }
}

customElements.define("qr-guest-access-panel", QRGuestAccessPanel);
