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
    this._openSections = new Set();
    this._tracks = [];
    this._trackQuery = "";
    this.shadowRoot.addEventListener("click", (event) => this._click(event));
    this.shadowRoot.addEventListener("input", (event) => this._input(event));
    this.shadowRoot.addEventListener("change", (event) => this._change(event));
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
    this._render();
    if (this._hass) this._connect();
  }

  disconnectedCallback() {
    this._closePreview();
    this._generation++;
    this._unsubscribe?.();
    this._unsubscribe = null;
    this._connection = null;
  }

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

  _select(field, label, options, optional = true, emptyLabel = "None") {
    const current = String(this._draft[field] ?? "");
    const values = options.map((item) => typeof item === "string" ? [item, item] : item);
    if (current && !values.some(([id]) => id === current)) values.push([current, current + " (not currently available)"]);
    return `<label>${esc(label)}<select data-field="${esc(field)}">${optional ? `<option value="">${esc(emptyLabel)}</option>` : '<option value="" disabled>Choose…</option>'}${values.map(([id, text]) => `<option value="${esc(id)}" ${current === id ? "selected" : ""}>${esc(text)}</option>`).join("")}</select></label>`;
  }

  _entity(field, label, domain, optional = true) {
    return this._select(field, label, this._choices(domain).map((state) => [state.entity_id,
      (state.attributes.friendly_name || state.entity_id) + (["unavailable", "unknown"].includes(state.state) ? " (unavailable)" : "")]), optional);
  }

  _field(field, label, type = "text", extra = "") {
    return `<label>${esc(label)}<input data-field="${esc(field)}" type="${type}" value="${esc(this._draft[field])}" ${extra}></label>`;
  }

  _check(field, label) {
    return `<label class="check"><input data-field="${esc(field)}" type="checkbox" ${this._draft[field] ? "checked" : ""}>${esc(label)}</label>`;
  }

  _power(enabled, id = "", disabled = false) {
    return `<button type="button" class="power ${enabled ? "is-on" : ""}" role="switch" aria-checked="${enabled}" aria-label="Alarm on or off" data-action="toggle" data-toggle-id="${esc(id)}" ${disabled ? "disabled" : ""}><span class="track" aria-hidden="true"><span></span></span><strong>${enabled ? "On" : "Off"}</strong></button>`;
  }

  _syncPower() {
    if (!this._draft || !this._editingId) return;
    const alarm = this._data?.alarms.find((item) => item.id === this._editingId);
    if (!alarm) return;
    this._draft.enabled = alarm.enabled;
    const power = this.shadowRoot.querySelector("#editor .power");
    if (power) power.outerHTML = this._power(alarm.enabled, alarm.id, this._busy || ACTIVE.has(alarm.run?.status));
  }

  _render() {
    this._closePreview();
    this.shadowRoot.innerHTML = `<style>
      :host{display:block;color:var(--primary-text-color);font-family:var(--paper-font-body1_-_font-family,system-ui)}
      ha-card{display:block;padding:18px;border-radius:var(--ha-card-border-radius,16px);background:var(--ha-card-background,var(--card-background-color));border:1px solid var(--divider-color)}
      header,.row,.actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap}header{justify-content:space-between}h2{font-size:21px;margin:0}h3{font-size:17px;margin:0 0 8px}
      p,.muted{color:var(--secondary-text-color);font-size:15px;line-height:1.5}button{font:inherit;font-size:16px;min-height:48px;padding:10px 16px;border:1px solid var(--divider-color);border-radius:10px;color:var(--primary-text-color);background:transparent;cursor:pointer}button.primary{background:var(--primary-color);color:var(--text-primary-color,#fff);border-color:transparent}button:disabled{opacity:.45;cursor:default}
      button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{outline:2px solid var(--primary-color);outline-offset:2px}.alarm{border-top:1px solid var(--divider-color);padding:16px 0}.alarm .row{justify-content:space-between}.time{font-size:28px;font-weight:600}.name{font-size:16px}.pill{padding:4px 8px;background:var(--secondary-background-color);border-radius:8px;font-size:12px}.actions{margin-top:10px}.actions button{font-size:13px}
      .notice{white-space:pre-wrap;background:var(--secondary-background-color);padding:10px;border-radius:10px;font-size:13px;line-height:1.5;margin:12px 0}.error{color:var(--error-color,#db4437)}[hidden]{display:none!important}form{margin-top:18px;border-top:1px solid var(--divider-color);padding-top:18px}fieldset{border:1px solid var(--divider-color);border-radius:12px;margin:12px 0;padding:14px}legend{font-weight:600;padding:0 6px}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}label{display:flex;flex-direction:column;gap:6px;font-size:13px;min-width:0}input,select,textarea{box-sizing:border-box;width:100%;min-height:44px;font:inherit;color:var(--primary-text-color);background:var(--secondary-background-color);border:1px solid var(--divider-color);border-radius:8px;padding:10px}input[type=checkbox]{width:22px;min-height:22px;accent-color:var(--primary-color)}.check{flex-direction:row;align-items:center;gap:10px;padding:6px 0;min-height:32px}.days{display:flex;flex-wrap:wrap;gap:12px}.days label{flex-direction:row;align-items:center}textarea{min-height:110px;resize:vertical}.full{grid-column:1/-1}.preview{white-space:pre-wrap}.right{margin-left:auto}
      :host{font-size:16px}label,.actions button{font-size:16px}input,select,textarea{font-size:16px;min-height:48px}input[type=checkbox]{min-height:24px;width:24px}.check{min-height:44px}.power{display:inline-flex;align-items:center;gap:10px;min-width:104px;border:none}.track{display:inline-flex;align-items:center;width:46px;height:28px;border-radius:18px;background:var(--disabled-color,#777);padding:3px;box-sizing:border-box}.track span{display:block;width:22px;height:22px;border-radius:50%;background:#fff}.is-on .track{background:var(--primary-color)}.is-on .track span{transform:translateX(18px)}details{margin:18px 0;border-top:1px solid var(--divider-color);padding-top:14px}summary{font-weight:600;cursor:pointer;min-height:44px;line-height:44px}.editor-header{justify-content:space-between}.section-help{margin-bottom:0}a{color:var(--primary-color);display:inline-block;min-height:32px;line-height:32px}.notification-help{font-size:15px;line-height:1.6;padding-left:22px}
      .alarm-actions{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:12px;align-items:stretch}.alarm-actions button{width:100%;box-sizing:border-box;white-space:nowrap}.alarm-actions [data-action=delete]{grid-column:1/-1}
      dialog{box-sizing:border-box;width:min(560px,calc(100vw - 24px));max-height:85vh;overflow:auto;border:1px solid var(--divider-color);border-radius:16px;padding:20px;background:var(--card-background-color,#191919);color:var(--primary-text-color)}dialog::backdrop{background:#0009}dialog audio{width:100%;margin:12px 0}dialog .preview-text{white-space:pre-wrap;overflow-wrap:anywhere}
      @media(max-width:480px){.grid{grid-template-columns:1fr}.full{grid-column:auto}ha-card{padding:14px}.actions button{flex:1}.time{font-size:28px}}
    </style><ha-card><header><h2>Alarms</h2><button class="primary" data-action="new" ${!this._data ? "disabled" : ""}>＋ Add alarm</button></header>
      <p>Choose when and where your alarms ring.</p>
      <div id="message" role="status" aria-live="polite"></div>
      ${this._loadError ? `<div class="notice error">${esc(this._loadError)}</div><button data-action="retry">Retry connection</button>` : ""}
      <div id="list"></div><div id="editor"></div><div id="music-test"></div></ha-card>`;
    this._renderList();
    this._renderEditor();
    this._renderMusic();
    this._showMessage();
  }

  _renderList() {
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
        const schedule = { school: "Current school schedule", non_school: "Current saved schedule", once: alarm.date, weekdays: alarm.weekdays.map((d) => DAYS[d]).join(", ") }[alarm.mode];
        const next = alarm.next ? new Date(alarm.next).toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" }) : "Not scheduled";
        return `<section class="alarm" data-id="${esc(alarm.id)}"><div class="row"><div><span class="time">${esc(alarm.time)}</span>${active ? ` <span class="pill">${run.status === "snoozed" ? "Snoozing" : "Ringing"}</span>` : ""}<div class="name">${esc(alarm.name)}${alarm.person ? " · " + esc(alarm.person) : ""}</div></div>
          ${this._power(alarm.enabled, alarm.id, active || this._busy)}</div>
          <p>${esc(schedule)} · ${esc(speaker)}${alarm.deadline ? " · Get up by " + esc(alarm.deadline) : ""}<br>Next alarm: ${esc(next)}</p>
          ${run?.error ? `<div class="notice error">${esc(run.error)}</div>` : ""}
          ${alarm.assistant_warning ? `<div class="notice">${esc(alarm.assistant_warning)}</div>` : ""}
          ${this._data.test_results?.[alarm.id] ? `<div class="notice">${esc(this._data.test_results[alarm.id])}</div>` : ""}
          <div class="actions ${active ? "" : "alarm-actions"}">${active ? `<button data-action="snooze" ${!alarm.snooze_enabled || run.snoozes >= alarm.max_snoozes || run.escalated ? "disabled" : ""}>Snooze</button><button class="primary" data-action="dismiss">Stop alarm</button>${alarm.allow_sleep_in && alarm.mode !== "school" ? '<button data-action="sleep_in">Sleep in</button>' : ""}` : '<button data-action="edit">Edit</button><button data-action="test">Test</button><button data-action="delete">Delete</button>'}</div></section>`;
      }).join("") : '<p>No alarms yet. Add an alarm, save it, then test the sound before turning it on.</p>');
  }

  _renderEditor() {
    const editor = this.shadowRoot.querySelector("#editor");
    if (!editor) return;
    this._renderList();
    if (!this._draft) { editor.innerHTML = ""; return; }
    const d = this._draft;
    const saved = this._data.alarms.find((alarm) => alarm.id === this._editingId);
    const people = [...new Set(this._data.alarms.map((alarm) => alarm.person).filter(Boolean))];
    const section = (id) => this._openSections.has(id) ? "open" : "";
    const repeats = [["weekdays", "Choose days"], ["once", "Just once"]];
    if (["school", "non_school"].includes(d.mode)) repeats.push([d.mode, "Keep current schedule"]);
    const calendarHelp = d.calendar_rule === "allow"
      ? "The alarm will ring only on selected days when an event title includes one of these phrases. Add at least one phrase."
      : "Selected days with an event title that includes one of these phrases will be skipped. Leave blank to skip no days.";
    editor.innerHTML = `<form><header class="editor-header"><h3>${this._editingId ? "Edit alarm" : "New alarm"}</h3>${this._power(saved ? saved.enabled : d.enabled, saved?.id || "", this._busy || ACTIVE.has(saved?.run?.status))}</header>
      <p>${saved ? "On or off changes straight away. Save your other changes below." : "New alarms start off. Save and test the sound before turning on."}</p>
      <fieldset><legend>When</legend><div class="grid">
        ${this._field("name", "Alarm name", "text", 'required maxlength="100"')}
        ${this._field("person", "Who is it for? (optional)", "text", 'list="people" maxlength="100"')}<datalist id="people">${people.map((person) => `<option>${esc(person)}</option>`).join("")}</datalist>
        ${this._field("time", "Alarm time", "time", "required")}
        ${this._select("mode", "Repeat", repeats, false)}
        ${d.mode === "once" ? this._field("date", "Date", "date", "required") : ""}
      </div>${d.mode === "weekdays" ? `<div class="days">${DAYS.map((day, i) => `<label><input type="checkbox" data-day="${i}" ${d.weekdays.includes(i) ? "checked" : ""}>${day}</label>`).join("")}</div>
      <div class="grid">${this._entity("calendar", "Calendar (optional)", "calendar")}</div>
      ${d.calendar ? `<div class="grid">${this._select("calendar_rule", "When an event matches", [["block", "Skip matching days"], ["allow", "Only ring on matching days"]], false)}</div>
      <label>Event titles to match<textarea data-field="calendar_filters" maxlength="2000" ${d.calendar_rule === "allow" ? "required" : ""}>${esc(d.calendar_filters || "")}</textarea></label><p>Write one word or phrase per line. Matching ignores capital letters. ${calendarHelp}</p>` : ""}
      <a href="https://my.home-assistant.io/redirect/config_flow_start/?domain=local_calendar" target="_blank" rel="noopener noreferrer">Add a calendar</a> · <a href="/calendar" target="_blank" rel="noopener noreferrer">Open your calendars</a>`
      : ["school", "non_school"].includes(d.mode) ? '<p>This alarm keeps its current repeat days. Choose another repeat option to change them.</p>' : ""}
      ${d.mode === "school" ? this._field("deadline", "Latest wake-up time", "time", "required") + '<p>Snoozes stop at this time. The alarm keeps ringing until you stop it.</p>' : ""}</fieldset>
      <fieldset><legend>Sound</legend><div class="grid">
        ${this._entity("speaker", "Play on", "media_player", false)}
        ${this._select("tone", "Alarm sound", [["chime", "Chime"], ["bell", "Bell"], ["digital", "Digital"], ["none", "Voice only"]], false)}
        ${this._field("start_volume", "Starting volume (%)", "number", 'min="1" max="100" required')}
      </div></fieldset>
      <fieldset><legend>Music</legend>${this._check("music_enabled", "Play a Music Assistant song instead of a tone")}
      ${d.music_enabled ? `<p>Requires the pinned HA-AlarmClock MA companion and an idle, empty, ungrouped queue. Add songs to that server's library first. Music repeats until you stop the alarm; Snooze restarts the same song without the message.</p>
      <label>Search your speaker's MA song library<input data-track-query maxlength="100" value="${esc(this._trackQuery)}" placeholder="Song or artist"></label>
      <button type="button" data-action="search-tracks" ${this._busy || !d.speaker ? "disabled" : ""}>Search songs</button>
      <p role="status">Selected song: ${esc(d.music_track_name || d.music_track || "None")}</p>
      <div class="actions">${this._tracks.map((track, index) => `<button type="button" data-action="choose-track" data-track-index="${index}">${esc(track.name)}</button>`).join("")}</div>
      <div class="grid">${this._field("music_gain", "Background music gain (%)", "number", 'min="1" max="30" required')}${this._field("speech_delay", "Music before voice (seconds)", "number", 'min="0" max="120" required')}</div>
      <p>The delay starts with the music, after message preparation. Choose an assistant under More settings for speech. Short songs can end before a long delay or message finishes. Music alarms do not interrupt someone else's queue.</p>` : ""}</fieldset>
      <details data-section="more" ${section("more")}><summary>More settings</summary>
      <fieldset><legend>Snooze</legend>${this._check("snooze_enabled", "Allow snooze")}<div class="grid">
        ${this._field("snooze_minutes", "Snooze minutes", "number", 'min="1" max="30" required')}
        ${this._field("max_snoozes", "How many times?", "number", 'min="0" max="10" required')}
        ${d.mode !== "school" ? this._field("deadline", "Latest wake-up time (optional)", "time") : ""}
      </div>${d.mode !== "school" ? this._check("allow_sleep_in", "Allow sleeping in") : '<p>This saved alarm does not allow sleeping in.</p>'}
      </fieldset><fieldset><legend>Let someone know</legend>${this._check("notify_enabled", "Send a message if help is needed")}
      <p>Let someone know when:</p><ul class="notification-help"><li>The alarm has not been stopped by the latest wake-up time.</li><li>You choose to sleep in.</li><li>The speaker cannot play the alarm.</li></ul>
      ${this._select("notify_service", "Send to", this._data.notify_services.map((id) => [id, id.replace(/^notify\.(mobile_app_)?/, "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())]), true, "Home Assistant only")}
      <p>${d.notify_service ? "Messages will go to the person or group you choose." : "Choose a phone or group above to send a phone message. Otherwise, the message only appears in Home Assistant."}</p></fieldset>
      <fieldset><legend>Morning message</legend>${this._check("briefing_enabled", "Let my assistant write a good morning message")}
      <div class="grid">${this._select("assistant_id", "Choose an assistant", (this._data.assistants || []).map((item) => [item.id, item.name]), true, "No spoken message")}${this._entity("weather", "Weather location", "weather")}</div>
      <p>Your assistant uses its configured voice and language. Change these in Settings → Voice assistants. Without an available voice, the alarm uses a tone.</p>
      ${this._select("briefing_words", "Message length", [["100", "Short — up to 100 words"], ["200", "Medium — up to 200 words"], ["300", "Long — up to 300 words"]], false)}
      <label>What would you like it to say?<textarea data-field="instructions" maxlength="10000">${esc(d.instructions)}</textarea></label><p>Up to 10,000 characters of instructions. Choose the spoken message length separately above.</p>
      <p>Your assistant can include the time and weather. If it is unavailable, the alarm still rings.</p>
      ${this._check("schedule_enabled", "Include today's schedule")}
      ${d.schedule_enabled ? `<p>Choose the calendars to read. Only these calendars are shared with your assistant. Shared calendars may include other people's events.</p><div>${this._choices("calendar").map((state) => `<label class="check"><input type="checkbox" data-schedule-calendar="${esc(state.entity_id)}" ${(d.schedule_calendars || []).includes(state.entity_id) ? "checked" : ""}>${esc(state.attributes.friendly_name || state.entity_id)}</label>`).join("") || '<p>No calendars found. Add a calendar in Home Assistant first.</p>'}</div><p>Turn on the assistant's morning message above to hear your schedule. If a calendar cannot be read, the message will say so.</p>` : ""}
      ${d.schedule_enabled ? `<label>Only include events containing<textarea data-field="schedule_include" maxlength="2000">${esc(d.schedule_include || "")}</textarea></label><p>One word or phrase per line. Keep events matching any phrase. Leave blank to include everything.</p><label>Exclude events containing<textarea data-field="schedule_exclude" maxlength="2000">${esc(d.schedule_exclude || "")}</textarea></label><p>One word or phrase per line. Matching ignores capital letters. Exclusions always win. These filters check event titles before sharing them with your assistant.</p>` : ""}
      <button type="button" data-action="preview" ${this._busy ? "disabled" : ""}>Preview message</button>
      <details data-section="privacy" ${section("privacy")}><summary>About assistant messages</summary><p>During alarms and previews, your selected assistant receives your name, instructions, time, weather and filtered events from calendars you choose. Its voice provider receives the message text. The assistant keeps its usual permissions; asking it not to act does not remove them. For speech only, choose an assistant without smart-home controls. Preview plays on this device, not your alarm speaker, and does not change your alarm or sleep switch.</p></details></fieldset>
      <fieldset><legend>Sound options</legend><div class="grid">${this._field("max_volume", "Loudest volume (%)", "number", 'min="1" max="100" required')}
      ${this._field("volume_step", "Get louder each time by (%)", "number", 'min="0" max="25" required')}${this._field("repeat_seconds", "Repeat sound every (seconds)", "number", 'min="30" max="300" required')}</div></fieldset>
      <fieldset><legend>Link to a sleep switch</legend>${this._entity("bedtime_entity", "Existing sleep switch (optional)", "input_boolean")}<p>Leave this blank unless you use a switch to show someone is asleep. If it is off when the alarm is due, that day's alarm is skipped. Future days stay enabled.</p>
      ${d.bedtime_entity ? this._check("clear_sleep_on_dismiss", "Turn off the sleep switch when I dismiss the alarm") + '<p>Snooze and Sleep in leave the switch alone.</p>' : ""}</fieldset>
      <p>Other alarms are not changed. Test the sound before relying on it. A spoken sentence may finish after you stop the alarm.</p></details>
      <div class="actions"><button class="primary" type="submit" ${this._busy ? "disabled" : ""}>${this._busy ? "Working…" : "Save alarm"}</button><button type="button" data-action="cancel" ${this._busy ? "disabled" : ""}>Cancel</button></div></form>`;
  }

  _showMessage() {
    const element = this.shadowRoot.querySelector("#message");
    if (element) { element.className = this._message ? "notice" : ""; element.textContent = this._message; }
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
  }

  _change(event) {
    const input = event.target;
    if (!this._draft) return;
    if (input.dataset.scheduleCalendar) {
      const selected = this._draft.schedule_calendars || [];
      this._draft.schedule_calendars = input.checked ? [...new Set([...selected, input.dataset.scheduleCalendar])] : selected.filter((entity) => entity !== input.dataset.scheduleCalendar);
      return;
    }
    if (input.dataset.day !== undefined) {
      const day = Number(input.dataset.day);
      this._draft.weekdays = input.checked ? [...new Set([...this._draft.weekdays, day])].sort() : this._draft.weekdays.filter((d) => d !== day);
      return;
    }
    const field = input.dataset.field;
    if (!field) return;
    this._draft[field] = input.type === "checkbox" ? input.checked : input.type === "number" || field === "briefing_words" ? Number(input.value) : input.value;
    if (field === "speaker") { this._draft.music_track = ""; this._draft.music_track_name = ""; this._draft.music_server = ""; this._tracks = []; }
    if (field === "music_enabled" || field === "speaker") this._renderEditor();
    if (field === "mode") {
      if (input.value === "school") {
        this._draft.allow_sleep_in = false;
      }
      this._renderEditor();
    }
    if (field === "calendar" && !this._draft.calendar && this._draft.calendar_rule === "allow") this._draft.calendar_rule = "block";
    if (field === "bedtime_entity" && !this._draft.bedtime_entity) this._draft.clear_sleep_on_dismiss = false;
    if (field === "calendar" || field === "calendar_rule" || field === "notify_service" || field === "schedule_enabled" || field === "bedtime_entity") this._renderEditor();
  }

  _configuration(alarm) {
    return Object.fromEntries(Object.keys(this._data.defaults).map((key) => [key, clone(alarm[key])]));
  }

  _edit(alarm = null) {
    if (this._draft && !window.confirm("Discard the current unsaved alarm edits?")) return;
    this._editingId = alarm?.id || null;
    this._editRevision = this._data.revision;
    this._draft = alarm ? this._configuration(alarm) : clone(this._data.defaults);
    this._tracks = []; this._trackQuery = "";
    this._openSections = new Set();
    this._renderEditor();
    this.shadowRoot.querySelector("#editor")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async _operation(work) {
    if (this._busy) return;
    this._busy = true;
    this.shadowRoot.querySelectorAll("button, form input, form select, form textarea").forEach((element) => { element.disabled = true; });
    try { await work(); }
    catch (error) { this._message = error.message || "Operation failed. Check the alarm list before retrying."; }
    finally {
      this._busy = false;
      this._renderList();
      this._renderEditor();
      this._renderMusic(true);
      this._showMessage();
    }
  }

  async _refresh() { this._data = await this._hass.callWS({ type: "household_alarms/list" }); }

  _save() {
    return this._operation(async () => {
      const config = clone(this._draft);
      if (this._editingId) config.enabled = this._data.alarms.find((alarm) => alarm.id === this._editingId)?.enabled ?? config.enabled;
      else if (config.enabled && !window.confirm("Save and turn on this alarm? Please check its sound first.")) return;
      await this._hass.callWS({ type: "household_alarms/save", config,
        expected_revision: this._editRevision, ...(this._editingId ? { alarm_id: this._editingId } : {}) });
      this._draft = null;
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
        const result = await this._hass.callWS({ type: "household_alarms/tracks", speaker: this._draft.speaker, query: this._trackQuery });
        this._tracks = result.tracks;
        this._trackServer = result.server_id;
        this._message = this._tracks.length ? "Choose a song below. Save the alarm to keep it." : "No songs found. Add the song to this MA library, then search again.";
      });
      return;
    }
    if (action === "choose-track") {
      const track = this._tracks[Number(button.dataset.trackIndex)];
      if (track && this._draft) { this._draft.music_track = track.uri; this._draft.music_track_name = track.name; this._draft.music_server = this._trackServer; this._renderEditor(); }
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
      } else if (this._draft) {
        this._draft.enabled = !this._draft.enabled;
        button.outerHTML = this._power(this._draft.enabled);
      }
      return;
    }
    if (action === "retry") { this._connection = null; this._connect(); return; }
    if (action === "new") { this._edit(); return; }
    if (action === "edit") { this._edit(alarm); return; }
    if (action === "cancel") { this._draft = null; this._renderEditor(); return; }
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
          ? `Test ${alarm.music_track_name || alarm.music_track} on ${speaker} at ${alarm.start_volume}% speaker volume and ${alarm.music_gain}% music gain? Voice delay is ${alarm.speech_delay} seconds. Music repeats until stopped, up to 30 minutes. Saved schedules and sleep switches stay unchanged.`
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
    const config = clone(this._draft);
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
