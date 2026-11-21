/* HA-AlarmClock — no external JavaScript dependencies or credentials. */
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
})[char]);
const clone = (value) => JSON.parse(JSON.stringify(value));
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const ACTIVE = new Set(["ringing", "snoozed"]);

class HouseholdAlarmsCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._data = null;
    this._draft = null;
    this._busy = false;
    this._generation = 0;
    this._previewGeneration = 0;
    this._message = "";
    this._messageError = false;
    this._openSections = new Set();
    this._tracks = [];
    this._trackQuery = "";
    this._trackStatus = "";
    this._trackError = false;
    this._trackSearching = false;
    this._choosingTrack = false;
    this._entityPickerHistoryEntry = false;
    this._entityPickerHistoryCleanup = false;
    this._activeEntityPicker = null;
    this.shadowRoot.addEventListener("click", (event) => this._click(event));
    this.shadowRoot.addEventListener("input", (event) => this._input(event));
    this.shadowRoot.addEventListener("change", (event) => this._change(event));
    this.shadowRoot.addEventListener("value-changed", (event) => this._entityChanged(event));
    this.shadowRoot.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && event.target.hasAttribute("data-track-query")) {
        event.preventDefault();
        this.shadowRoot.querySelector('[data-action="search-tracks"]')?.click();
      }
    });
    this.shadowRoot.addEventListener("toggle", (event) => {
      const id = event.target.dataset.section;
      if (id) event.target.open ? this._openSections.add(id) : this._openSections.delete(id);
    }, true);
    this.shadowRoot.addEventListener("submit", (event) => {
      event.preventDefault();
      this._save();
    });
  }

  setConfig(config) { this._config = config; }
  getCardSize() { return 5; }
  static getStubConfig() { return { type: "custom:household-alarms-card" }; }

  set hass(hass) {
    if (!hass) return;
    const reconnect = this._hass?.connection !== hass.connection;
    this._hass = hass;
    if (this.isConnected && (reconnect || !this._connection)) this._connect();
  }

  connectedCallback() {
    window.addEventListener("popstate", this._handleEntitySearchBack);
    window.addEventListener("picker-opened", this._entityPickerOpened);
    window.addEventListener("picker-closed", this._entityPickerClosed);
    this._render();
    if (this._hass) this._connect();
    // Re-evaluate local calendar dates even if HA sends no alarm state change.
    clearInterval(this._dateTimer);
    this._dateTimer = setInterval(() => {
      const day = new Intl.DateTimeFormat("en-GB", {
        timeZone: this._hass?.config?.time_zone || "UTC",
      }).format(new Date());
      if (day !== this._renderedDay) this._renderList();
    }, 30000);
  }

  disconnectedCallback() {
    window.removeEventListener("popstate", this._handleEntitySearchBack);
    window.removeEventListener("picker-opened", this._entityPickerOpened);
    window.removeEventListener("picker-closed", this._entityPickerClosed);
    clearInterval(this._dateTimer);
    this._closePreview();
    this._generation++;
    this._unsubscribe?.();
    this._unsubscribe = null;
    this._connection = null;
  }

  _entityPickerOpened = (event) => {
    const path = event.composedPath();
    const selector = path.find((element) => element?.matches?.("ha-selector[data-entity-selector]"));
    const picker = path.find((element) => element?.localName === "ha-generic-picker");
    if (!selector || !picker) return;
    this._activeEntityPicker = {
      selector,
      picker,
      sheet: picker.shadowRoot?.querySelector("ha-bottom-sheet"),
      popover: picker.shadowRoot?.querySelector("wa-popover"),
    };
    if (this._entityPickerHistoryEntry) return;
    const state = history.state && typeof history.state === "object" ? history.state : {};
    history.pushState({ ...state, householdAlarmEntityPicker: true }, "");
    this._entityPickerHistoryEntry = true;
  };

  _entityPickerClosed = (event) => {
    const picker = event.composedPath().find((element) => element?.localName === "ha-generic-picker");
    if (!picker || picker !== this._activeEntityPicker?.picker) return;
    this._activeEntityPicker = null;
    if (!this._entityPickerHistoryEntry) return;
    this._entityPickerHistoryCleanup = true;
    history.back();
  };

  _handleEntitySearchBack = () => {
    if (!this._entityPickerHistoryEntry) return;
    this._entityPickerHistoryEntry = false;
    if (this._entityPickerHistoryCleanup) {
      this._entityPickerHistoryCleanup = false;
      return;
    }
    const { sheet, popover } = this._activeEntityPicker || {};
    if (sheet?.open) sheet.open = false;
    else if (popover?.open) popover.open = false;
  };

  async _connect() {
    const connection = this._hass.connection;
    if (this._connection === connection) return;
    this._unsubscribe?.();
    this._unsubscribe = null;
    this._connection = connection;
    const generation = ++this._generation;
    try {
      const unsubscribe = await connection.subscribeMessage((data) => {
        if (generation !== this._generation || !this.isConnected) return;
        this._data = data;
        this._loadError = "";
        if (!this.shadowRoot.querySelector("#list")) this._render();
        else { this._renderList(); this._syncPower(); this._renderMusic(); }
      }, { type: "household_alarms/subscribe" });
      if (generation !== this._generation || !this.isConnected) unsubscribe();
      else this._unsubscribe = unsubscribe;
    } catch (error) {
      if (generation !== this._generation) return;
      this._connection = null;
      this._loadError = error.message || "Could not open your alarms. Please refresh the page and try again.";
      this._render();
    }
  }

  _choices(domain) {
    return Object.values(this._hass?.states || {})
      .filter((state) => state.entity_id.startsWith(domain + "."))
      .sort((a, b) => (a.attributes.friendly_name || a.entity_id).localeCompare(b.attributes.friendly_name || b.entity_id));
  }

  _select(field, label, options, optional = true, emptyLabel = "None", required = false) {
    const current = String(this._draft[field] ?? "");
    const values = options.map((item) => typeof item === "string" ? [item, item] : item);
    if (current && !values.some(([id]) => id === current)) values.push([current, current + " (not currently available)"]);
    return `<label>${esc(label)}<select data-field="${esc(field)}" ${required ? "required" : ""}>${optional ? `<option value="">${esc(emptyLabel)}</option>` : `<option value="" disabled ${current ? "" : "selected"}>${esc(required ? emptyLabel : "Choose…")}</option>`}${values.map(([id, text]) => `<option value="${esc(id)}" ${current === id ? "selected" : ""}>${esc(text)}</option>`).join("")}</select></label>`;
  }

  _entity(field, label, domain, optional = true) {
    return `<ha-selector data-field="${esc(field)}" data-entity-selector data-entity-domain="${esc(domain)}" label="${esc(label)}"></ha-selector>`;
  }

  _configureEntitySelectors() {
    for (const selector of this.shadowRoot.querySelectorAll("ha-selector[data-entity-selector]")) {
      const field = selector.dataset.field;
      const domain = selector.dataset.entityDomain;
      const value = this._draft[field] || "";
      const missing = value && !this._hass?.states?.[value];
      selector.hass = this._hass;
      selector.selector = { entity: { filter: { domain }, ...(missing ? { extra_options: [{ id: value, primary: value, secondary: "Not currently available" }] } : {}) } };
      selector.value = value || undefined;
      selector.required = field === "speaker";
      selector.disabled = this._busy;
      selector.placeholder = value ? undefined : "None";
    }
  }

  _entityChanged(event) {
    const selector = event.target;
    const field = selector.dataset?.field;
    if (!field || !this._draft) return;
    const value = event.detail?.value || "";
    this._draft[field] = value;
    if (field === "speaker") {
      this._draft.music_track = ""; this._draft.music_track_name = ""; this._draft.music_server = "";
      this._tracks = []; this._trackStatus = ""; this._trackError = false; this._choosingTrack = false;
      this._renderEditor();
    } else if (["calendar", "bedtime_entity"].includes(field)) {
      if (field === "calendar" && !value && this._draft.calendar_rule === "allow") this._draft.calendar_rule = "block";
      if (field === "bedtime_entity" && !value) this._draft.clear_sleep_on_dismiss = false;
      this._renderEditor();
    }
  }

  _field(field, label, type = "text", extra = "") {
    return `<label>${esc(label)}<input data-field="${esc(field)}" type="${type}" value="${esc(this._draft[field])}" ${extra}></label>`;
  }

  _check(field, label) {
    return `<label class="check"><input data-field="${esc(field)}" type="checkbox" ${this._draft[field] ? "checked" : ""}>${esc(label)}</label>`;
  }

  _power(enabled, id = "", disabled = false, label = "Alarm on or off") {
    return `<button type="button" class="power ${enabled ? "is-on" : ""}" role="switch" aria-checked="${enabled}" aria-label="${esc(label)}" title="${esc(label)}" data-action="toggle" data-toggle-id="${esc(id)}" ${disabled ? "disabled" : ""}><span class="track" aria-hidden="true"><span></span></span><strong>${enabled ? "On" : "Off"}</strong></button>`;
  }

  _alarmAction(action, label, icon) {
    return `<button type="button" class="icon-button" data-action="${action}" aria-label="${esc(label)}" title="${esc(label)}"><svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">${icon}</svg></button>`;
  }

  _modeButtons(group, selected, options) {
    return `<div class="mode-select" role="group" aria-label="${group === "sound" ? "Sound mode" : "Morning message mode"}">${options.map(([value, label]) => `<button type="button" data-action="editor-mode" data-mode-group="${group}" data-mode="${value}" aria-pressed="${selected === value}">${label}</button>`).join("")}</div>`;
  }

  _changeEditorMode(group, mode) {
    if (!this._draft || !this._editorModeMemory) return;
    if (group === "sound") {
      if (this._draft.tone !== "none") this._editorModeMemory.tone = this._draft.tone;
      this._draft.music_enabled = mode === "music";
      this._draft.tone = mode === "voice" ? "none" : this._editorModeMemory.tone || "chime";
      return;
    }
    if (this._draft.assistant_id) this._editorModeMemory.assistantId = this._draft.assistant_id;
    this._editorModeMemory.messageMode = mode;
    if (!this._draft.assistant_id && this._editorModeMemory.assistantId) this._draft.assistant_id = this._editorModeMemory.assistantId;
    this._draft.briefing_enabled = mode === "assistant";
  }

  _captureEditorFocus(editor) {
    const active = this.shadowRoot.activeElement;
    if (!active || !editor.contains(active)) return null;
    const descriptor = { selectionStart: active.selectionStart, selectionEnd: active.selectionEnd };
    if (active.dataset.field) return { ...descriptor, field: active.dataset.field };
    if (active.dataset.modeGroup) return { ...descriptor, group: active.dataset.modeGroup, mode: active.dataset.mode };
    if (active.dataset.action === "editor-mode") return { ...descriptor, group: active.dataset.modeGroup, mode: active.dataset.mode };
    if (active.dataset.section) return { ...descriptor, section: active.dataset.section };
    if (active.closest?.("summary")) {
      const section = active.closest("details[data-section]")?.dataset.section;
      if (section) return { ...descriptor, section };
    }
    if (active.dataset.action) return { ...descriptor, action: active.dataset.action };
    return null;
  }

  _restoreEditorFocus(focus, editor) {
    const field = this._focusAfterEditorRender;
    this._focusAfterEditorRender = null;
    const target = field
      ? editor.querySelector(`[data-field="${field}"]`)
      : focus?.field ? editor.querySelector(`[data-field="${focus.field}"]`)
      : focus?.group ? editor.querySelector(`[data-mode-group="${focus.group}"][data-mode="${focus.mode}"]`)
      : focus?.section ? editor.querySelector(`[data-section="${focus.section}"] summary`)
      : focus?.action ? editor.querySelector(`[data-action="${focus.action}"]`)
      : null;
    if (!target) return;
    target.focus({ preventScroll: true });
    if (!field && focus?.field && Number.isInteger(focus.selectionStart) && target.setSelectionRange) {
      try { target.setSelectionRange(focus.selectionStart, focus.selectionEnd); } catch (_) { /* not a text control */ }
    }
  }

  _updateRampSummary() {
    const summary = this.shadowRoot.querySelector("[data-ramp-summary]");
    if (!summary || !this._draft) return;
    const d = this._draft;
    summary.textContent = `Starts at ${d.start_volume}%, rises by ${d.music_ramp_step} percentage points every ${d.music_ramp_seconds} seconds, up to ${d.max_volume}%. It does not restart music or repeat the voice. Snooze starts again at the starting volume; changing volume yourself pauses increases for that ring. Requires the updated MA companion.`;
  }

  _updateSectionSummaries() {
    if (!this._draft) return;
    const d = this._draft;
    const snooze = d.snooze_enabled
      ? `${d.snooze_minutes} minutes · ${d.max_snoozes} snoozes`
      : "Snooze off";
    const wake = d.deadline ? ` · Get up by ${d.deadline}` : "";
    const phone = d.phone_enabled
      ? `Phone controls on · ${d.phone_service ? this._serviceName(d.phone_service) : "Choose a phone"}${d.phone_wake_screen ? " · Screen wake on" : ""}`
      : "Phone controls off";
    const alerts = d.notify_enabled
      ? `Help alerts on · ${this._serviceName(d.notify_service || "Home Assistant")}`
      : "Help alerts off";
    const sleepName = d.bedtime_entity
      ? (this._hass?.states?.[d.bedtime_entity]?.attributes?.friendly_name || d.bedtime_entity)
      : "No sleep switch selected";
    const sleep = d.bedtime_entity && d.clear_sleep_on_dismiss
      ? `${sleepName} · Turn off on dismissal`
      : sleepName;
    const summaries = {
      "wake-limits": `${snooze}${wake}`,
      "phone-controls": phone,
      "help-alerts": alerts,
      "sleep-switch": sleep,
    };
    for (const [section, text] of Object.entries(summaries)) {
      const element = this.shadowRoot.querySelector(`[data-summary="${section}"]`);
      if (element) element.textContent = text;
    }
  }

  _serviceName(service) {
    if (!service || service === "Home Assistant") return "Home Assistant only";
    return service.replace(/^notify\.(mobile_app_)?/, "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  }

  _syncPower() {
    if (!this._draft || !this._editingId) return;
    const alarm = this._data?.alarms.find((item) => item.id === this._editingId);
    if (!alarm) return;
    this._draft.enabled = alarm.enabled;
  }

  _render() {
    this._closePreview();
    this.shadowRoot.innerHTML = `<style>
      .selected-track{border:2px solid var(--primary-color);border-radius:12px;padding:12px;margin:12px 0;background:var(--secondary-background-color);overflow-wrap:anywhere}.selected-track strong{display:block;margin-bottom:8px}#track-feedback{white-space:pre-wrap;overflow-wrap:anywhere}
      :host{display:block;color:var(--primary-text-color);font-family:var(--paper-font-body1_-_font-family,system-ui)}
      ha-card{display:block;padding:18px;border-radius:var(--ha-card-border-radius,16px);background:var(--ha-card-background,var(--card-background-color));border:1px solid var(--divider-color)}
      header,.row,.actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap}header{justify-content:space-between}h2{font-size:21px;margin:0}h3{font-size:17px;margin:0 0 8px}
      p,.muted{color:var(--secondary-text-color);font-size:15px;line-height:1.5}button{font:inherit;font-size:16px;min-height:48px;padding:10px 16px;border:1px solid var(--divider-color);border-radius:10px;color:var(--primary-text-color);background:transparent;cursor:pointer}button.primary{background:var(--primary-color);color:var(--text-primary-color,#fff);border-color:transparent}button:disabled{opacity:.45;cursor:default}
      button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible,summary:focus-visible{outline:2px solid var(--primary-color);outline-offset:2px}.alarm{border-top:1px solid var(--divider-color);padding:14px 0}.alarm-row{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:16px}.alarm-copy{min-width:0}.alarm-heading{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap}.time{font-size:26px;font-weight:650}.name{font-size:17px}.alarm-meta{margin:3px 0;color:var(--secondary-text-color);font-size:14px;line-height:1.45;overflow-wrap:anywhere}.alarm-tools{display:grid;grid-template-columns:repeat(4,44px);align-items:center;justify-content:end;gap:4px}.alarm-tools .power,.alarm-tools .icon-button{position:relative;box-sizing:border-box;width:44px;height:44px;min-width:44px;min-height:44px;padding:0;border:1px solid transparent;display:grid;place-items:center}.alarm-tools .power{gap:0}.alarm-tools .power strong{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap}.alarm-tools .track{width:30px;height:18px;padding:2px}.alarm-tools .track span{width:14px;height:14px}.alarm-tools .is-on .track span{transform:translateX(12px)}.alarm-tools .icon-button::before{content:"";position:absolute;inset:5px;border:1px solid var(--divider-color);border-radius:8px;pointer-events:none}.alarm-tools .icon-button svg{width:20px;height:20px}.icon-button svg{fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}.pill{padding:4px 8px;background:var(--secondary-background-color);border-radius:8px;font-size:12px}.active-actions{justify-content:flex-start;margin-top:10px}.active-actions button{font-size:14px}.playback-warning{margin:5px 0 0;color:var(--error-color,#db4437);font-size:14px}.playback-warning summary{cursor:pointer;min-height:32px;line-height:32px}.playback-warning p{margin:4px 0 0;color:var(--error-color,#db4437);font-size:13px;white-space:pre-wrap;overflow-wrap:anywhere}.notice{white-space:pre-wrap;background:var(--secondary-background-color);padding:10px;border-radius:10px;font-size:13px;line-height:1.5;margin:8px 0}.error{color:var(--error-color,#db4437)}[hidden]{display:none!important}form{margin-top:18px;border-top:1px solid var(--divider-color);padding-top:18px}fieldset{border:1px solid var(--divider-color);border-radius:12px;margin:12px 0;padding:14px}legend{font-weight:600;padding:0 6px}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.mode-select{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:4px;margin:10px 0}.mode-select button{min-width:0;padding:8px 10px;font-size:14px}.mode-select button[aria-pressed="true"]{background:var(--primary-color);border-color:var(--primary-color);color:var(--text-primary-color,#fff)}.mode-help{margin:4px 0 10px;font-size:13px}label{display:flex;flex-direction:column;gap:6px;font-size:13px;min-width:0}input,select,textarea{box-sizing:border-box;width:100%;min-height:44px;font:inherit;color:var(--primary-text-color);background:var(--secondary-background-color);border:1px solid var(--divider-color);border-radius:8px;padding:10px}input[type=checkbox]{width:22px;min-height:22px;accent-color:var(--primary-color)}.check{flex-direction:row;align-items:center;gap:10px;padding:6px 0;min-height:32px}.days{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0}.days label{position:relative;display:grid;place-items:center;box-sizing:border-box;min-width:44px;min-height:44px;padding:0 12px;border:1px solid var(--divider-color);border-radius:10px;cursor:pointer;user-select:none}.days label.selected{background:var(--primary-color);border-color:var(--primary-color);color:var(--text-primary-color,#fff)}.days label:focus-within{outline:2px solid var(--primary-color);outline-offset:2px}.days input[type=checkbox]{position:absolute;width:1px;height:1px;min-height:1px;margin:-1px;padding:0;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}textarea{min-height:110px;resize:vertical}.full{grid-column:1/-1}.preview{white-space:pre-wrap}.right{margin-left:auto}
      :host{font-size:16px}label,.actions button{font-size:16px}input,select,textarea{font-size:16px;min-height:48px}input[type=checkbox]{min-height:24px;width:24px}.check{min-height:44px}.power{display:inline-flex;align-items:center;gap:10px;min-width:104px;border:none}.track{display:inline-flex;align-items:center;width:46px;height:28px;border-radius:18px;background:var(--disabled-color,#777);padding:3px;box-sizing:border-box}.track span{display:block;width:22px;height:22px;border-radius:50%;background:#fff}.is-on .track{background:var(--primary-color)}.is-on .track span{transform:translateX(18px)}details{margin:18px 0;border-top:1px solid var(--divider-color);padding-top:14px}summary{font-weight:600;cursor:pointer;min-height:44px;line-height:44px}.settings-panel summary{height:auto;line-height:1.3;padding:5px 0;box-sizing:border-box}.settings-summary{display:block;margin-top:4px;color:var(--secondary-text-color);font-size:13px;font-weight:400;line-height:1.4}.editor-header{justify-content:space-between}.section-help{margin-bottom:0}a{color:var(--primary-color);display:inline-block;min-height:32px;line-height:32px}.notification-help{font-size:15px;line-height:1.6;padding-left:22px}
      .alarm-actions{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:12px;align-items:stretch}.alarm-actions button{width:100%;box-sizing:border-box;white-space:nowrap}.alarm-actions [data-action=delete]{grid-column:1/-1}
      dialog{box-sizing:border-box;width:min(560px,calc(100vw - 24px));max-height:85vh;overflow:auto;border:1px solid var(--divider-color);border-radius:16px;padding:20px;background:var(--card-background-color,#191919);color:var(--primary-text-color)}dialog::backdrop{background:#0009}dialog audio{width:100%;margin:12px 0}dialog .preview-text{white-space:pre-wrap;overflow-wrap:anywhere}
      @media(max-width:520px){.grid{grid-template-columns:1fr}.full{grid-column:auto}ha-card{padding:14px}.alarm-heading{gap:8px}.time{font-size:25px}.name{font-size:16px}.active-actions button{flex:1}}
      .next-occurrence{display:inline-block;max-width:100%;white-space:nowrap;font-weight:400;font-size:clamp(11px,3cqi,14px)}
      ha-card{container-type:inline-size}
      @container (max-width:520px){.grid{grid-template-columns:1fr}.full{grid-column:auto}.alarm-row{grid-template-columns:minmax(0,1fr) auto;gap:8px}.alarm-tools{grid-template-columns:repeat(2,44px);grid-template-rows:repeat(2,44px)}}
    </style><ha-card><header><h2>Alarms</h2><button class="primary" data-action="new" ${!this._data ? "disabled" : ""}>＋ Add alarm</button></header>
      <div id="message" role="status" aria-live="polite"></div>
      ${this._loadError ? `<div class="notice error">${esc(this._loadError)}</div><button data-action="retry">Retry connection</button>` : ""}
      <div id="list"></div><div id="editor"></div><div id="music-test"></div></ha-card>`;
    this._renderList();
    this._renderEditor();
    this._renderMusic();
    this._showMessage();
    this._configureEntitySelectors();
  }

  _nextOccurrence(alarm, now = new Date()) {
    if (!alarm.enabled || !alarm.next) return "Not scheduled";
    const next = new Date(alarm.next);
    if (!Number.isFinite(next.getTime())) return "Not scheduled";
    const timeZone = this._hass?.config?.time_zone || "UTC";
    const parts = (date) => Object.fromEntries(new Intl.DateTimeFormat("en-GB", {
      timeZone, year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hourCycle: "h23",
    }).formatToParts(date).map(({ type, value }) => [type, value]));
    const n = parts(next), today = parts(now);
    // Compare calendar dates, not elapsed hours: DST days need not be 24 hours.
    const day = (p) => Date.UTC(Number(p.year), Number(p.month) - 1, Number(p.day));
    const delta = Math.round((day(n) - day(today)) / 86400000);
    const label = delta === 0 ? "Today" : delta === 1 ? "Tomorrow"
      : `${n.day}/${n.month}/${n.year.slice(-2)}`;
    return `${label} at ${Number(n.hour)}:${n.minute}`;
  }

  _renderList() {
    this._renderedDay = new Intl.DateTimeFormat("en-GB", {
      timeZone: this._hass?.config?.time_zone || "UTC",
    }).format(new Date());
    const list = this.shadowRoot.querySelector("#list");
    if (!list) return;
    list.hidden = !!this._draft;
    const add = this.shadowRoot.querySelector('[data-action="new"]');
    if (add) { add.hidden = !!this._draft; add.disabled = this._busy || !this._data; }
    if (!this._data) { list.textContent = this._loadError ? "" : "Connecting…"; return; }
    list.innerHTML = (this._data.warnings || []).map((text) => `<div class="notice">${esc(text)}</div>`).join("") +
      (this._data.alarms.length ? this._data.alarms.map((alarm) => {
        const run = alarm.run;
        const active = ACTIVE.has(run?.status);
        const speaker = this._hass.states[alarm.speaker]?.attributes.friendly_name || alarm.speaker;
        const weekdays = alarm.weekdays || [];
        const schedule = { school: "School days", non_school: "Non-school days", once: alarm.date,
          weekdays: weekdays.length === 5 && weekdays.every((day, index) => day === index)
            ? "Weekdays" : weekdays.map((day) => DAYS[day]).join(", ") }[alarm.mode];
        const next = this._nextOccurrence(alarm);
        const label = alarm.name;
        return `<section class="alarm" data-id="${esc(alarm.id)}"><div class="alarm-row"><div class="alarm-copy">
          <div class="alarm-heading"><span class="time">${esc(alarm.time)}</span><span class="name">${esc(label)}</span>${active ? `<span class="pill">${run.status === "snoozed" ? "Snoozing" : "Ringing"}</span>` : ""}</div>
          <p class="alarm-meta">${esc(schedule)} · ${esc(speaker)}</p>
          <p class="alarm-meta"><span class="next-occurrence"><strong>Next:</strong> ${esc(next)}</span>${alarm.deadline ? " · Get up by " + esc(alarm.deadline) : ""}</p>
          ${run?.error ? `<details class="playback-warning"><summary>Playback failed — details</summary><p>${esc(run.error)}</p></details>` : ""}
          ${alarm.assistant_warning ? `<div class="notice">${esc(alarm.assistant_warning)}</div>` : ""}
          ${this._data.test_results?.[alarm.id] ? `<div class="notice">${esc(this._data.test_results[alarm.id])}</div>` : ""}
          </div><div class="alarm-tools">${this._power(alarm.enabled, alarm.id, active || this._busy, `Turn ${alarm.name} ${alarm.enabled ? "off" : "on"}`)}
          ${active ? "" : `${this._alarmAction("edit", `Edit ${label}`, '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4Z"/>')}${this._alarmAction("test", `Test ${label}`, '<path d="M11 5 6 9H3v6h3l5 4Z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M18.5 5.5a9 9 0 0 1 0 13"/>')}${this._alarmAction("delete", `Delete ${label}`, '<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="m19 6-1 14H6L5 6"/><path d="M10 11v5M14 11v5"/>')}`}</div></div>
          ${active ? `<div class="actions active-actions"><button data-action="snooze" ${!alarm.snooze_enabled || run.snoozes >= alarm.max_snoozes || run.escalated ? "disabled" : ""}>Snooze</button><button class="primary" data-action="dismiss">Stop alarm</button>${alarm.allow_sleep_in && alarm.mode !== "school" ? '<button data-action="sleep_in">Sleep in</button>' : ""}</div>` : ""}</section>`;
      }).join("") : '<p>No alarms yet. Add an alarm, save it, then test the sound before turning it on.</p>');
  }

  _renderEditor() {
    const editor = this.shadowRoot.querySelector("#editor");
    if (!editor) return;
    const focus = this._captureEditorFocus(editor);
    this._renderList();
    if (!this._draft) { editor.innerHTML = ""; return; }
    const d = this._draft;
    const saved = this._data.alarms.find((alarm) => alarm.id === this._editingId);
    const people = [...new Set(this._data.alarms.map((alarm) => alarm.person).filter(Boolean))];
    const section = (id) => this._openSections.has(id) ? "open" : "";
    const soundMode = d.music_enabled ? "music" : d.tone === "none" ? "voice" : "tone";
    const messageMode = this._editorModeMemory?.messageMode ?? (d.briefing_enabled ? "assistant" : d.assistant_id ? "greeting" : "off");
    const wakeSummary = d.snooze_enabled
      ? `${d.snooze_minutes} minutes · ${d.max_snoozes} snoozes`
      : "Snooze off";
    const phoneSummary = d.phone_enabled
      ? `Phone controls on · ${d.phone_service ? this._serviceName(d.phone_service) : "Choose a phone"}${d.phone_wake_screen ? " · Screen wake on" : ""}`
      : "Phone controls off";
    const alertSummary = d.notify_enabled
      ? `Help alerts on · ${this._serviceName(d.notify_service || "Home Assistant")}`
      : "Help alerts off";
    const sleepName = d.bedtime_entity
      ? (this._hass?.states?.[d.bedtime_entity]?.attributes?.friendly_name || d.bedtime_entity)
      : "No sleep switch selected";
    const sleepSummary = d.bedtime_entity && d.clear_sleep_on_dismiss
      ? `${sleepName} · Turn off on dismissal`
      : sleepName;
    const repeats = [["weekdays", "Choose days"], ["once", "Just once"]];
    if (["school", "non_school"].includes(d.mode)) repeats.push([d.mode, "Keep current schedule"]);
    const calendarHelp = d.calendar_rule === "allow"
      ? "By default, the alarm rings only on selected days when this calendar has an event. If you choose specific calendar-match days, only those selected days need an event; other selected days ring regardless. Add phrases to match only event titles that include them; leave blank to match every event."
      : "Selected days with any event on this calendar will be skipped. Add one or more phrases to skip only days whose event titles match. Leave blank to skip every event.";
    const calendarMatchDays = d.calendar_days_custom
      ? `<div class="days" role="group" aria-label="Days that require a calendar match">${DAYS.map((day, i) => `<label class="day-option${(d.calendar_match_days || []).includes(i) ? " selected" : ""}"><input type="checkbox" data-calendar-match-day="${i}" ${(d.calendar_match_days || []).includes(i) ? "checked" : ""} ${!d.weekdays.includes(i) ? "disabled" : ""}>${day}</label>`).join("")}</div><p>Checked days need a matching event. Other selected repeat days ring without one.</p>`
      : "";
    const musicRampFields = d.music_ramp_enabled
       ? `<div class="grid">${this._field("music_ramp_step", "Increase by (percentage points)", "number", 'min="1" max="25" required')}${this._field("music_ramp_seconds", "Every (seconds)", "number", 'min="30" max="300" required')}${this._field("max_volume", "Maximum speaker volume (%)", "number", 'min="1" max="100" required')}</div><p class="mode-help" data-ramp-summary>Starts at ${esc(d.start_volume)}%, rises by ${esc(d.music_ramp_step)} percentage points every ${esc(d.music_ramp_seconds)} seconds, up to ${esc(d.max_volume)}%. It does not restart music or repeat the voice. Snooze starts again at the starting volume; changing volume yourself pauses increases for that ring. Requires the updated MA companion.</p>`
      : `<div class="grid">${this._field("max_volume", "Maximum speaker volume (%)", "number", 'min="1" max="100" required')}${this._field("volume_step", "Increase per resumed ring (percentage points)", "number", 'min="0" max="25" required')}</div><p class="mode-help">No timed increases. Existing resume-volume behaviour is unchanged.</p>`;
    const soundFields = [
      `<div class="grid">${this._entity("speaker", "Play on", "media_player", false)}</div>`,
      this._modeButtons("sound", soundMode, [["tone", "Tone"], ["music", "Music"], ["voice", "Voice only"]]),
      soundMode === "tone" ? `<div class="grid">${this._select("tone", "Tone", [["chime", "Chime"], ["bell", "Bell"], ["digital", "Digital"]], false)}</div>` : "",
      soundMode === "voice" ? `<p class="mode-help">Voice only uses your selected morning message. Choose one below.</p>` : "",
      soundMode === "voice" && messageMode === "off" ? '<p class="error" role="alert">Choose a morning message to use Voice only.</p>' : "",
      soundMode === "music" ? [
        '<p class="mode-help">Requires the updated HA-AlarmClock MA companion and one ungrouped speaker. Snooze and Dismiss remove only the alarm item and resume the music it interrupted. A snooze wake-up starts a fresh alarm segment, preserving the music then playing. Playback changes made elsewhere are left alone.</p>',
        this._songPicker(),
        `<div class="grid">${this._field("start_volume", "Starting speaker volume (%)", "number", 'min="1" max="100" required')}</div>`,
        this._check("music_ramp_enabled", "Increase speaker volume over time"), musicRampFields,
        messageMode !== "off"
          ? `<h4>Music and voice</h4><div class="grid">${this._field("music_gain", "Music level under the voice (%)", "number", 'min="1" max="30" required')}${this._field("speech_delay", "Seconds of music before the voice", "number", 'min="0" max="120" required')}</div>`
          : `<h4>Music settings</h4><div class="grid">${this._field("music_gain", "Music level (%)", "number", 'min="1" max="30" required')}</div>`,
      ].join("") : `<div class="grid">${this._field("start_volume", "Starting speaker volume (%)", "number", 'min="1" max="100" required')}${this._field("max_volume", "Maximum speaker volume (%)", "number", 'min="1" max="100" required')}${this._field("volume_step", soundMode === "tone" ? "Increase per tone repeat (percentage points)" : "Increase per tone fallback (percentage points)", "number", 'min="0" max="25" required')}${this._field("repeat_seconds", "Repeat tone every (seconds)", "number", 'min="30" max="300" required')}</div>`,
    ].join("");
    const messageFields = messageMode === "off"
      ? '<p>The morning message is off.</p>'
      : [
        `<div class="grid">${this._select("assistant_id", "Assistant", (this._data.assistants || []).map((item) => [item.id, item.name]), false, "Choose an assistant", true)}${messageMode === "assistant" ? this._entity("weather", "Weather location", "weather") : ""}</div>`,
        '<p>Your selected assistant provides the voice. Preview plays on this device.</p>',
        messageMode === "assistant" ? [
          this._select("briefing_words", "Message length", [["100", "Short — up to 100 words"], ["200", "Medium — up to 200 words"], ["300", "Long — up to 300 words"]], false),
          `<label>Message instructions<textarea data-field="instructions" maxlength="10000">${esc(d.instructions)}</textarea></label><p>Up to 10,000 characters of instructions. The selected assistant writes the message.</p>`,
          '<p>Your assistant can include the time and weather. If it is unavailable, the alarm still rings.</p>',
          this._check("schedule_enabled", "Include today's schedule"),
          d.schedule_enabled ? [
            `<p>Choose the calendars to read. Only these calendars are shared with your assistant. Shared calendars may include other people's events.</p><div>${this._choices("calendar").map((state) => `<label class="check"><input type="checkbox" data-schedule-calendar="${esc(state.entity_id)}" ${(d.schedule_calendars || []).includes(state.entity_id) ? "checked" : ""}>${esc(state.attributes.friendly_name || state.entity_id)}</label>`).join("") || '<p>No calendars found. Add a calendar in Home Assistant first.</p>'}</div><p>Turn on the assistant-written message above to include your schedule. If a calendar cannot be read, the message will say so.</p>`,
            `<label>Only include events containing<textarea data-field="schedule_include" maxlength="2000">${esc(d.schedule_include || "")}</textarea></label><p>One word or phrase per line. Keep events matching any phrase. Leave blank to include everything.</p><label>Exclude events containing<textarea data-field="schedule_exclude" maxlength="2000">${esc(d.schedule_exclude || "")}</textarea></label><p>One word or phrase per line. Matching ignores capital letters. Exclusions always win.</p>`,
          ].join("") : "",
          `<details data-section="privacy" ${section("privacy")}><summary>About assistant messages</summary><p>During alarms and previews, your selected assistant receives your name, instructions, time, weather and filtered events from calendars you choose. Its voice provider receives the message text. The assistant keeps its usual permissions; asking it not to act does not remove them. For speech only, choose an assistant without smart-home controls. Preview plays on this device and does not change your alarm or sleep switch.</p></details>`,
          `<button type="button" data-action="preview" ${this._busy ? "disabled" : ""}>Preview message</button><span class="muted">Plays on this device</span>`,
        ].join("") : `<button type="button" data-action="preview" ${this._busy ? "disabled" : ""}>Preview message</button><span class="muted">Plays on this device</span>`,
      ].join("");
    const assistantAvailable = (this._data.assistants || []).some((item) => item.id === d.assistant_id);
    const assistantRepair = saved?.assistant_warning && !assistantAvailable && messageMode !== "off"
      ? `<p class="error" role="alert">${esc(saved.assistant_warning)} This saved alarm's spoken mode needs repair. Choose an available assistant below to keep the spoken message when saving edits. You can still use the alarm-list switch without repairing it.</p>`
      : "";
    editor.innerHTML = `<form><header class="editor-header"><h3>${this._editingId ? "Edit alarm" : "New alarm"}</h3></header>
      <p>${saved ? "Use the alarm list to turn it on or off. Save your other changes below." : "New alarms start off. Save the alarm before using its list controls."}</p>
      <fieldset><legend>When</legend><div class="grid">
        ${this._field("name", "Alarm name", "text", 'required maxlength="100"')}
        ${this._field("person", "Who is it for? (optional)", "text", 'list="people" maxlength="100"')}<datalist id="people">${people.map((person) => `<option>${esc(person)}</option>`).join("")}</datalist>
        ${this._field("time", "Alarm time", "time", "required")}
        ${this._select("mode", "Repeat", repeats, false)}
        ${d.mode === "once" ? this._field("date", "Date", "date", "required") : ""}
      </div>${d.mode === "weekdays" ? `<div class="days" role="group" aria-label="Choose days">${DAYS.map((day, i) => `<label class="day-option${d.weekdays.includes(i) ? " selected" : ""}"><input type="checkbox" data-day="${i}" ${d.weekdays.includes(i) ? "checked" : ""}>${day}</label>`).join("")}</div>
      <div class="grid">${this._entity("calendar", "Calendar rules (optional)", "calendar")}</div>
      ${d.calendar ? `<div class="grid">${this._select("calendar_rule", "When an event matches", [["block", "Skip matching days"], ["allow", "Only ring on matching days"]], false)}</div>
      ${d.calendar_rule === "allow" ? this._check("calendar_days_custom", "Choose which repeat days require a calendar match") : ""}
      ${d.calendar_rule === "allow" && d.calendar_days_custom ? calendarMatchDays : ""}
      <label>Event titles to match<textarea data-field="calendar_filters" maxlength="2000">${esc(d.calendar_filters || "")}</textarea></label><p>Write one word or phrase per line. Matching ignores capital letters. ${calendarHelp}</p>` : ""}
      <a href="https://my.home-assistant.io/redirect/config_flow_start/?domain=local_calendar" target="_blank" rel="noopener noreferrer">Add a calendar</a> · <a href="/calendar" target="_blank" rel="noopener noreferrer">Open your calendars</a>`
      : ["school", "non_school"].includes(d.mode) ? '<p>This alarm keeps its current repeat days. Choose another repeat option to change them.</p>' : ""}
      ${d.mode === "school" ? '<p>Set the latest wake-up time under Snooze and wake-up limits.</p>' : ""}</fieldset>
      <fieldset><legend>Sound</legend>${soundFields}</fieldset>
      <fieldset><legend>Morning message</legend>${this._modeButtons("message", messageMode, [["off", "Off"], ["greeting", "Simple greeting"], ["assistant", "Assistant-written"]])}${assistantRepair}${messageFields}</fieldset>
      <details class="settings-panel" data-section="wake-limits" ${section("wake-limits")}><summary>Snooze and wake-up limits<span class="settings-summary" data-summary="wake-limits">${wakeSummary}${d.deadline ? ` · Get up by ${esc(d.deadline)}` : ""}</span></summary>
        ${this._check("snooze_enabled", "Allow snooze")}
        ${d.snooze_enabled ? `<div class="grid">${this._field("snooze_minutes", "Snooze minutes", "number", 'min="1" max="30" required')}${this._field("max_snoozes", "How many times?", "number", 'min="0" max="10" required')}</div>` : '<p>Snooze length and count are hidden while snooze is off.</p>'}
        ${d.snooze_enabled && messageMode !== "off" ? this._check("repeat_message_after_snooze", "Repeat morning message after snooze") + '<p>Off by default. When enabled, the configured message is generated again on each snooze wake-up, never on ordinary song repeats.</p>' : ""}
        ${d.mode === "school" ? this._field("deadline", "Latest wake-up time", "time", "required") + '<p>Snoozes stop at this time. The alarm keeps ringing until you stop it.</p>' : this._field("deadline", "Latest wake-up time (optional)", "time")}
        ${d.mode !== "school" ? this._check("allow_sleep_in", "Allow sleeping in") : '<p>This saved alarm does not allow sleeping in.</p>'}
      </details>
      <details class="settings-panel" data-section="phone-controls" ${section("phone-controls")}><summary>Phone controls<span class="settings-summary" data-summary="phone-controls">${esc(phoneSummary)}</span></summary>${this._check("phone_enabled", "Show Dismiss and Snooze when this alarm rings")}
        ${d.phone_enabled ? `${this._select("phone_service", "Send alarm controls to", (this._data.phone_targets || []).map((item) => [item.service, item.service.replace(/^notify\.mobile_app_/, "").replace(/_/g, " ") + " — " + item.service]), false)}${this._check("phone_wake_screen", "Wake the phone screen (Android only)")}<p>Anyone holding the phone can use its lock-screen buttons. Snooze uses this alarm's limits and deadline. Your phone must allow Companion notifications and lock-screen content; screen wake needs an identified Android phone and enabled notification commands.</p>` : ""}
      </details>
      <details class="settings-panel" data-section="help-alerts" ${section("help-alerts")}><summary>Help alerts<span class="settings-summary" data-summary="help-alerts">${esc(alertSummary)}</span></summary>${this._check("notify_enabled", "Send a message if help is needed")}
        ${d.notify_enabled ? `<p>Let someone know when:</p><ul class="notification-help"><li>The alarm has not been stopped by the latest wake-up time.</li><li>You choose to sleep in.</li><li>The speaker cannot play the alarm.</li></ul>${this._select("notify_service", "Send to", this._data.notify_services.map((id) => [id, id.replace(/^notify\.(mobile_app_)?/, "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())]), true, "Home Assistant only")}<p>${d.notify_service ? "Messages will go to the person or group you choose." : "Choose a phone or group above to send a phone message. Otherwise, the message only appears in Home Assistant."}</p>` : ""}
      </details>
      <details class="settings-panel" data-section="sleep-switch" ${section("sleep-switch")}><summary>Sleep switch<span class="settings-summary" data-summary="sleep-switch">${esc(sleepSummary)}</span></summary>${this._entity("bedtime_entity", "Existing sleep switch (optional)", "input_boolean")}
        ${d.bedtime_entity ? this._check("clear_sleep_on_dismiss", "Turn off on dismissal") + '<p>Snooze and Sleep in leave the switch alone.</p>' : ""}
      </details>
      <p>Other alarms are not changed. Test the sound before relying on it. A spoken sentence may finish after you stop the alarm.</p>
      <div id="editor-message" class="notice" role="alert" aria-live="assertive" hidden></div>
      <div class="actions"><button class="primary" type="submit" ${this._busy ? "disabled" : ""}>${this._busy ? "Working…" : "Save alarm"}</button><button type="button" data-action="cancel" ${this._busy ? "disabled" : ""}>Cancel</button></div></form>`;
    this._showMessage();
    this._configureEntitySelectors();
    this._updateSectionSummaries();
    this._restoreEditorFocus(focus, editor);
  }

  _showMessage() {
    const globalMessage = this.shadowRoot.querySelector("#message");
    if (this._draft && globalMessage) { globalMessage.className = ""; globalMessage.textContent = ""; }
    const element = this._draft
      ? this.shadowRoot.querySelector("#editor-message")
      : this.shadowRoot.querySelector("#message");
    if (element) {
      element.className = this._message ? `notice${this._messageError ? " error" : ""}` : "";
      element.textContent = this._message;
      if (element.id === "editor-message") element.hidden = !this._message;
    }
  }

  _songPicker() {
    const d = this._draft;
    const selected = !!d.music_track;
    return `<div id="track-feedback" class="${this._trackStatus ? "notice" : ""} ${this._trackError ? "error" : ""}" role="status" aria-live="polite" aria-busy="${this._trackSearching}">${esc(this._trackStatus)}</div>
      ${selected ? `<div class="selected-track"><strong>✓ Selected song</strong><span>${esc(d.music_track_name || d.music_track)}</span><p>Save the alarm to keep any changes.</p><button type="button" data-action="change-track" ${this._busy ? "disabled" : ""}>Change song</button></div>` : '<p>No song selected yet.</p>'}
      ${!selected || this._choosingTrack ? `<label>Search your speaker's MA song library<input data-track-query maxlength="100" value="${esc(this._trackQuery)}" placeholder="Song or artist" aria-describedby="track-feedback"></label>
      <button type="button" data-action="search-tracks" ${this._busy || !d.speaker ? "disabled" : ""}>${this._trackSearching ? "Searching…" : "Search songs"}</button>
      <div class="actions">${this._tracks.map((track, index) => `<button type="button" data-action="choose-track" data-track-index="${index}" aria-pressed="${d.music_track === track.uri}">${esc(track.name)}</button>`).join("")}</div>` : ""}`;
  }

  _updateTrackStatus() {
    const status = this.shadowRoot.querySelector("#track-feedback");
    if (status) { status.textContent = this._trackStatus; status.className = `notice ${this._trackError ? "error" : ""}`; status.setAttribute("aria-busy", String(this._trackSearching)); }
    const button = this.shadowRoot.querySelector('[data-action="search-tracks"]');
    if (button) button.textContent = this._trackSearching ? "Searching…" : "Search songs";
  }

  _renderMusic(force = false) {
    const root = this.shadowRoot.querySelector("#music-test");
    if (!root || !this._data) return;
    const session = this._data.music_test;
    const active = session && !["dismissed", "sleeping_in", "finished", "failed", "interrupted"].includes(session.status);
    root.hidden = !session;
    if (!session) { root.innerHTML = ""; return; }
    root.innerHTML = `<details data-section="music-test" open><summary>Saved alarm music test</summary>
      <p>Saved alarms and sleep switches stay unchanged. Music repeats until stopped (30-minute test maximum). Test Snooze uses the saved alarm's minutes.</p>
      ${session ? `<div class="notice" role="status" aria-live="polite">${esc(session.status)}${session.track ? " · " + esc(session.track) : ""}<br>${esc(session.message)}</div>` : ""}
      <div class="actions">${active ? `<button data-action="music-snooze" ${session.status !== "playing" || this._busy ? "disabled" : ""}>Snooze test</button><button class="primary" data-action="music-dismiss" ${this._busy ? "disabled" : ""}>Dismiss test</button><button data-action="music-sleep_in" ${this._busy ? "disabled" : ""}>Sleep in (test)</button>` : ""}</div></details>`;
  }

  _musicOperation(action) {
    return this._operation(async () => {
      const session = this._data.music_test;
      if (["snooze", "dismiss", "sleep_in"].includes(action)) {
        await this._hass.callWS({ type: "household_alarms/music_action", session_id: session.id, action });
        this._message = "Music-test control requested. Check its status below.";
      }
      await this._refresh();
    });
  }

  _input(event) {
    const input = event.target;
    if (input.hasAttribute("data-track-query")) { this._trackQuery = input.value; return; }
    if (!this._draft || !input.dataset.field) return;
    if (input.tagName === "SELECT" || input.type === "checkbox") return;
    this._draft[input.dataset.field] = input.type === "number" ? Number(input.value) : input.value;
    if (["start_volume", "music_ramp_step", "music_ramp_seconds", "max_volume"].includes(input.dataset.field)) this._updateRampSummary();
    this._updateSectionSummaries();
  }

  _change(event) {
    const input = event.target;
    if (!this._draft) return;
    if (input.matches?.("ha-selector[data-entity-selector]")) return;
    if (input.dataset.scheduleCalendar) {
      const selected = this._draft.schedule_calendars || [];
      this._draft.schedule_calendars = input.checked ? [...new Set([...selected, input.dataset.scheduleCalendar])] : selected.filter((entity) => entity !== input.dataset.scheduleCalendar);
      return;
    }
    if (input.dataset.day !== undefined) {
      const day = Number(input.dataset.day);
      this._draft.weekdays = input.checked ? [...new Set([...this._draft.weekdays, day])].sort() : this._draft.weekdays.filter((d) => d !== day);
      if (this._draft.calendar_days_custom) {
        const matchDays = this._draft.calendar_match_days || [];
        this._draft.calendar_match_days = input.checked
          ? [...new Set([...matchDays, day])].sort()
          : matchDays.filter((d) => d !== day);
        const matchInput = this.shadowRoot.querySelector(`[data-calendar-match-day="${day}"]`);
        if (matchInput) {
          matchInput.disabled = !input.checked;
          matchInput.checked = this._draft.calendar_match_days.includes(day);
          matchInput.closest(".day-option")?.classList.toggle("selected", matchInput.checked);
        }
      }
      input.closest(".day-option")?.classList.toggle("selected", input.checked);
      return;
    }
    if (input.dataset.calendarMatchDay !== undefined) {
      const day = Number(input.dataset.calendarMatchDay);
      const matchDays = this._draft.calendar_match_days || [];
      this._draft.calendar_match_days = input.checked
        ? [...new Set([...matchDays, day])].sort()
        : matchDays.filter((d) => d !== day);
      input.closest(".day-option")?.classList.toggle("selected", input.checked);
      return;
    }
    const field = input.dataset.field;
    if (!field) return;
    this._draft[field] = input.type === "checkbox" ? input.checked : input.type === "number" || field === "briefing_words" ? Number(input.value) : input.value;
    if (field === "calendar_days_custom" && input.checked) this._draft.calendar_match_days = [...this._draft.weekdays];
    if (field === "tone" && input.value !== "none" && this._editorModeMemory) this._editorModeMemory.tone = input.value;
    if (field === "assistant_id" && this._editorModeMemory) this._editorModeMemory.assistantId = input.value;
    this._updateSectionSummaries();
    if (field === "speaker") { this._draft.music_track = ""; this._draft.music_track_name = ""; this._draft.music_server = ""; this._tracks = []; this._trackStatus = ""; this._trackError = false; this._choosingTrack = false; }
    if (field === "music_enabled" || field === "music_ramp_enabled" || field === "speaker") this._renderEditor();
    if (field === "assistant_id" || field === "phone_enabled" || field === "phone_service" || field === "snooze_enabled" || field === "notify_enabled") this._renderEditor();
    if (field === "mode") {
      if (input.value === "school") {
        this._draft.allow_sleep_in = false;
      }
      this._renderEditor();
    }
    if (field === "calendar" && !this._draft.calendar && this._draft.calendar_rule === "allow") this._draft.calendar_rule = "block";
    if (field === "bedtime_entity" && !this._draft.bedtime_entity) this._draft.clear_sleep_on_dismiss = false;
    if (field === "calendar" || field === "calendar_rule" || field === "calendar_days_custom" || field === "notify_service" || field === "schedule_enabled" || field === "bedtime_entity") this._renderEditor();
  }

  _configuration(alarm) {
    return Object.fromEntries(Object.keys(this._data.defaults).map((key) => [key, clone(alarm[key])]));
  }

  _edit(alarm = null) {
    if (this._draft && !window.confirm("Discard the current unsaved alarm edits?")) return;
    this._editingId = alarm?.id || null;
    this._message = "";
    this._messageError = false;
    this._editRevision = this._data.revision;
    this._draft = alarm ? this._configuration(alarm) : clone(this._data.defaults);
    this._editorModeMemory = {
      tone: this._draft.tone === "none" ? this._data.defaults.tone || "chime" : this._draft.tone,
      assistantId: this._draft.assistant_id,
      messageMode: this._draft.briefing_enabled ? "assistant" : this._draft.assistant_id ? "greeting" : "off",
    };
    this._tracks = []; this._trackQuery = "";
    this._trackStatus = ""; this._trackError = false; this._trackSearching = false; this._choosingTrack = false;
    this._openSections = new Set();
    this._renderEditor();
    this.shadowRoot.querySelector("#editor")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async _operation(work) {
    if (this._busy) return;
    this._busy = true;
    this.shadowRoot.querySelectorAll("button, form input, form select, form textarea, form ha-selector").forEach((element) => { element.disabled = true; });
    this._messageError = false;
    try { await work(); }
    catch (error) { this._message = error.message || "Operation failed. Check the alarm list before retrying."; this._messageError = true; }
    finally {
      this._busy = false;
      this._renderList();
      this._renderEditor();
      this._renderMusic(true);
      this._showMessage();
    }
  }

  async _refresh() { this._data = await this._hass.callWS({ type: "household_alarms/list" }); }

  _normalizeMessageConfig(config) {
    const messageMode = this._editorModeMemory?.messageMode
      ?? (config.briefing_enabled ? "assistant" : config.assistant_id ? "greeting" : "off");
    config.briefing_enabled = messageMode === "assistant";
    if (messageMode !== "assistant") config.schedule_enabled = false;
    if (messageMode === "off") config.assistant_id = "";
    return { config, messageMode };
  }

  _save() {
    return this._operation(async () => {
      const { config, messageMode } = this._normalizeMessageConfig(clone(this._draft));
      const availableAssistant = (this._data.assistants || []).some((item) => item.id === config.assistant_id);
      if (config.tone === "none" && messageMode === "off") {
        this._message = "Choose a morning message before saving Voice only.";
        this._messageError = true;
        this._editorModeMemory.messageMode = "greeting";
        this._focusAfterEditorRender = "assistant_id";
        return;
      }
      if (messageMode !== "off" && !availableAssistant) {
        this._message = "Choose an assistant for the selected morning message.";
        this._messageError = true;
        this._focusAfterEditorRender = "assistant_id";
        return;
      }
      if (this._editingId) config.enabled = this._data.alarms.find((alarm) => alarm.id === this._editingId)?.enabled ?? config.enabled;
      else if (config.enabled && !window.confirm("Save and turn on this alarm? Please check its sound first.")) return;
      await this._hass.callWS({ type: "household_alarms/save", config,
        expected_revision: this._editRevision, ...(this._editingId ? { alarm_id: this._editingId } : {}) });
      this._draft = null;
      this._editingId = null;
      this._editorModeMemory = null;
      await this._refresh();
      this._message = "Alarm saved. You can test its sound now.";
    });
  }

  _toggle(id, enabled) {
    const alarm = this._data.alarms.find((item) => item.id === id);
    return this._operation(async () => {
      const previousRevision = this._data.revision;
      await this._hass.callWS({ type: "household_alarms/save", alarm_id: id,
        expected_revision: this._data.revision, config: { ...this._configuration(alarm), enabled } });
      await this._refresh();
      if (this._editingId === id && this._draft) {
        this._draft.enabled = enabled;
        if (this._editRevision === previousRevision && this._data.revision === previousRevision + 1) this._editRevision = this._data.revision;
      }
      this._message = enabled ? "Alarm is on." : "Alarm is off.";
    });
  }

  async _click(event) {
    const button = event.target.closest("button[data-action]");
    if (!button || button.disabled || this._busy) return;
    const action = button.dataset.action;
    if (action === "search-tracks") {
      await this._operation(async () => {
        this._tracks = []; this._trackSearching = true; this._trackError = false;
        this._trackStatus = "Searching the selected speaker's Music Assistant library…"; this._updateTrackStatus();
        try {
          const result = await this._hass.callWS({ type: "household_alarms/tracks", speaker: this._draft.speaker, query: this._trackQuery });
          this._tracks = result.tracks; this._trackServer = result.server_id;
          this._trackStatus = this._tracks.length ? "Choose a song below. Save the alarm to keep it." : "No songs found. Add the song to this MA library, then search again.";
        } catch (error) {
          this._trackStatus = error.message || "Song search failed. Check the selected MA speaker."; this._trackError = true;
        } finally { this._trackSearching = false; }
      });
      return;
    }
    if (action === "editor-mode" && this._draft) {
      const group = button.dataset.modeGroup, mode = button.dataset.mode;
      this._changeEditorMode(group, mode);
      this._renderEditor();
      this.shadowRoot.querySelector(`[data-mode-group="${group}"][data-mode="${mode}"]`)?.focus();
      return;
    }
    if (action === "change-track") { this._choosingTrack = true; this._tracks = []; this._trackStatus = "Choose a replacement song. Your current selection stays until you pick another."; this._trackError = false; this._renderEditor(); this.shadowRoot.querySelector("[data-track-query]")?.focus(); return; }
    if (action === "choose-track") {
      const track = this._tracks[Number(button.dataset.trackIndex)];
      if (track && this._draft) { this._draft.music_track = track.uri; this._draft.music_track_name = track.name; this._draft.music_server = this._trackServer; this._tracks = []; this._choosingTrack = false; this._trackStatus = "Song selected. Save the alarm to keep it."; this._trackError = false; this._renderEditor(); this.shadowRoot.querySelector('[data-action="change-track"]')?.focus(); }
      return;
    }
    if (action.startsWith("music-")) { await this._musicOperation(action.slice(6)); return; }
    const id = button.closest("[data-id]")?.dataset.id;
    const alarm = this._data?.alarms.find((item) => item.id === id);
    if (action === "toggle") {
      const alarmId = button.dataset.toggleId;
      if (alarmId) {
        const item = this._data.alarms.find((item) => item.id === alarmId);
        await this._toggle(alarmId, !item.enabled);
      }
      return;
    }
    if (action === "retry") { this._connection = null; this._connect(); return; }
    if (action === "new") { this._edit(); return; }
    if (action === "edit") { this._edit(alarm); return; }
    if (action === "cancel") { this._draft = null; this._editingId = null; this._editorModeMemory = null; this._message = ""; this._messageError = false; this._renderEditor(); this._showMessage(); return; }
    if (action === "preview") { await this._openPreview(); return; }
    if (action === "close-preview") { this._closePreview(); return; }
    if (action === "play-preview") { await this._playPreview(); return; }
    await this._operation(async () => {
      if (action === "delete") {
        if (!window.confirm(`Delete ${alarm.name}?`)) return;
        await this._hass.callWS({ type: "household_alarms/delete", alarm_id: id, expected_revision: this._data.revision });
        await this._refresh();
        this._message = "Alarm deleted.";
      } else if (action === "test") {
        const speaker = this._hass.states[alarm.speaker]?.attributes.friendly_name || alarm.speaker;
        if (!window.confirm(alarm.music_enabled
          ? `Test ${alarm.music_track_name || alarm.music_track} on ${speaker} at ${alarm.start_volume}% speaker volume and ${alarm.music_gain}% music gain? Voice delay is ${alarm.speech_delay} seconds.${alarm.music_ramp_enabled ? ` Volume increases by ${alarm.music_ramp_step} percentage points every ${alarm.music_ramp_seconds} seconds, up to ${alarm.max_volume}%.` : ""} Music repeats until stopped, up to 30 minutes. Saved schedules and sleep switches stay unchanged.`
          : `Test this alarm on ${speaker} at ${alarm.start_volume}% volume? It will play the chosen sound${alarm.assistant_id || alarm.briefing_enabled ? " and morning message" : ""} once.`)) return;
        await this._hass.callWS({ type: "household_alarms/test", alarm_id: id, confirmation: "PLAY", briefing: false });
        this._message = "Listen at the speaker. Did you hear the test?";
      } else if (["snooze", "dismiss", "sleep_in"].includes(action)) {
        if (action === "sleep_in" && !window.confirm(`Allow ${alarm.person || alarm.name} to sleep in?`)) return;
        await this._hass.callWS({ type: "household_alarms/action", alarm_id: id, action });
        await this._refresh();
        this._message = action === "dismiss" ? "Alarm stopped. Check any warnings above." : "Alarm updated. Your sleep switch has not been changed.";
      }
    });
  }

  _closePreview() {
    this._previewGeneration++;
    const dialog = this.shadowRoot.querySelector("#preview-dialog");
    const audio = dialog?.querySelector("audio");
    if (audio) { audio.pause(); audio.removeAttribute("src"); audio.load(); }
    if (this._previewUrl) { URL.revokeObjectURL(this._previewUrl); this._previewUrl = null; }
    if (dialog) { dialog.close(); dialog.remove(); }
    if (this._previewFocus?.isConnected) this._previewFocus.focus();
    this._previewFocus = null;
  }

  async _openPreview() {
    if (!this._draft) return;
    const { config } = this._normalizeMessageConfig(clone(this._draft));
    this._closePreview();
    const generation = this._previewGeneration;
    this._previewFocus = this.shadowRoot.activeElement;
    const dialog = document.createElement("dialog");
    dialog.id = "preview-dialog";
    dialog.setAttribute("aria-labelledby", "preview-title");
    dialog.innerHTML = '<header><h3 id="preview-title">Morning message preview</h3><button type="button" data-action="close-preview" aria-label="Close preview">Close</button></header><p id="preview-status" role="status" aria-live="polite">Writing and preparing your message…</p><p class="preview-text"></p><audio controls hidden></audio><button type="button" data-action="play-preview" hidden>Play</button>';
    dialog.addEventListener("cancel", (event) => { event.preventDefault(); this._closePreview(); });
    this.shadowRoot.append(dialog);
    dialog.showModal();
    try {
      const result = await this._hass.callWS({ type: "household_alarms/preview", config });
      if (generation !== this._previewGeneration || !dialog.isConnected) return;
      dialog.querySelector(".preview-text").textContent = result.text || "";
      if (result.error) throw new Error(result.error);
      if (!["audio/mpeg", "audio/wav", "audio/ogg", "audio/flac"].includes(result.mime_type) || !result.audio) throw new Error("No playable audio was returned. Check the assistant's voice settings and try again.");
      const bytes = Uint8Array.from(atob(result.audio), (char) => char.charCodeAt(0));
      this._previewUrl = URL.createObjectURL(new Blob([bytes], { type: result.mime_type }));
      const audio = dialog.querySelector("audio");
      audio.src = this._previewUrl;
      audio.hidden = false;
      audio.addEventListener("error", () => {
        if (generation === this._previewGeneration) this._previewStatus("The audio could not play on this device. Check its audio settings or try another assistant voice.", true);
      });
      dialog.querySelector('[data-action="play-preview"]').hidden = false;
      await this._playPreview();
    } catch (error) {
      if (generation === this._previewGeneration) this._previewStatus(error.message || "Preview failed. Check the assistant's conversation and voice settings, then try again.", true);
    }
  }

  _previewStatus(text, error = false) {
    const status = this.shadowRoot.querySelector("#preview-status");
    if (status) { status.textContent = text; status.className = error ? "error" : ""; }
  }

  async _playPreview() {
    const audio = this.shadowRoot.querySelector("#preview-dialog audio");
    if (!audio?.src) return;
    const generation = this._previewGeneration;
    try {
      await audio.play();
      if (generation === this._previewGeneration) this._previewStatus("Playing on this device. Use the controls to pause or replay.");
    } catch (error) {
      if (generation === this._previewGeneration) this._previewStatus(error.name === "NotAllowedError" ? "Autoplay was blocked. Press Play to hear your message." : "The audio could not play. Check this device's audio settings or try another assistant voice.", error.name !== "NotAllowedError");
    }
  }
}

if (!customElements.get("household-alarms-card")) customElements.define("household-alarms-card", HouseholdAlarmsCard);
window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "household-alarms-card")) window.customCards.push({
  type: "household-alarms-card", name: "HA-AlarmClock", description: "Create and manage speaker alarms with snooze, deadlines and Assist voices.",
});
