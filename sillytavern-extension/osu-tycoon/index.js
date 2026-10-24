// osu! Tycoon Bridge for SillyTavern.
//
// SillyTavern has no inbound webhook, so this extension pulls: it polls the Tycoon engine for
// new events, runs the prompts the engine bundles with each event through your current LLM,
// and posts the results back (forum comments, IRC lines). Optionally it narrates events into the
// open chat and exposes a {{tycoon}} macro with the career's current state.

const MODULE = 'osu_tycoon';
const MAX_FAILURES = 3;

const defaults = {
    engineUrl: 'http://127.0.0.1:8642',
    careerId: null,
    enabled: false,
    pollSeconds: 20,
    forum: true,
    irc: true,
    narrate: false,
    structured: true,
};

let timer = null;
let busy = false;
let contextText = '';
const failures = new Map();

const ctx = () => SillyTavern.getContext();

function settings() {
    const { extensionSettings } = ctx();
    extensionSettings[MODULE] ??= structuredClone(defaults);
    for (const [key, value] of Object.entries(defaults)) {
        if (extensionSettings[MODULE][key] === undefined) extensionSettings[MODULE][key] = value;
    }
    return extensionSettings[MODULE];
}

function save() {
    ctx().saveSettingsDebounced();
}

function setStatus(text) {
    $('#osu_tycoon_status').text(text);
}

async function api(path, options = {}) {
    const url = settings().engineUrl.replace(/\/$/, '') + path;
    const response = await fetch(url, {
        ...options,
        headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    });
    if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
    return response.status === 204 ? null : response.json();
}

/** Pull the first JSON object out of an LLM reply (handles ```json fences and chatter). */
function extractJson(text) {
    if (!text) return null;
    const cleaned = String(text).replace(/```(?:json)?/gi, '').trim();
    try {
        return JSON.parse(cleaned);
    } catch {
        const start = cleaned.indexOf('{');
        const end = cleaned.lastIndexOf('}');
        if (start < 0 || end <= start) return null;
        try {
            return JSON.parse(cleaned.slice(start, end + 1));
        } catch {
            return null;
        }
    }
}

/** Ask the LLM for JSON: structured outputs first (Chat Completion only), plain prompt as fallback. */
async function generateJson(prompt, schema, key) {
    const { generateQuietPrompt } = ctx();
    if (settings().structured && schema) {
        try {
            const raw = await generateQuietPrompt({
                quietPrompt: prompt,
                jsonSchema: { name: `osu_tycoon_${key}`, strict: false, value: schema },
            });
            const parsed = extractJson(raw);
            if (parsed && Array.isArray(parsed[key]) && parsed[key].length) return parsed;
        } catch (error) {
            if (error?.name === 'AbortError') throw error;
            console.warn('[osu! Tycoon] structured output failed; retrying without a response schema', error);
        }
    }
    return extractJson(await generateQuietPrompt({ quietPrompt: prompt }));
}

async function narrate(text) {
    const c = ctx();
    const command = `/sys ${text.replace(/\|/g, '\\|')}`;
    if (typeof c.executeSlashCommandsWithOptions === 'function') {
        await c.executeSlashCommandsWithOptions(command);
    } else if (typeof c.executeSlashCommands === 'function') {
        await c.executeSlashCommands(command);
    } else {
        toastr.info(text, 'osu! Tycoon');
    }
}

async function handleEvent(event) {
    const s = settings();
    const id = s.careerId;
    if (s.forum && event.prompts.forum && event.thread) {
        const result = await generateJson(event.prompts.forum, event.schemas.forum, 'comments');
        if (result?.comments?.length) {
            await api(`/api/st/careers/${id}/threads/${event.thread.id}/comments`, {
                method: 'POST',
                body: JSON.stringify({ comments: result.comments.slice(0, 30) }),
            });
        }
    }
    if (s.irc && event.prompts.irc) {
        const result = await generateJson(event.prompts.irc, event.schemas.irc, 'lines');
        if (result?.lines?.length) {
            await api(`/api/st/careers/${id}/irc`, {
                method: 'POST',
                body: JSON.stringify({ channel: event.channel, lines: result.lines.slice(0, 30) }),
            });
        }
    }
    if (event.prompts.dm) {
        const result = await generateJson(event.prompts.dm, event.schemas.dm, 'lines');
        if (result?.lines?.length) {
            await api(`/api/st/careers/${id}/irc`, {
                method: 'POST',
                body: JSON.stringify({ channel: event.channel, lines: result.lines.slice(0, 5) }),
            });
        }
    }
    if (s.narrate && event.prompts.narration) {
        const text = await ctx().generateQuietPrompt({ quietPrompt: event.prompts.narration });
        if (text?.trim()) await narrate(text.trim());
    }
    await api(`/api/st/careers/${id}/events/${event.id}/ack`, { method: 'POST' });
}

async function refreshContext() {
    const s = settings();
    if (!s.careerId) return;
    try {
        contextText = (await api(`/api/st/careers/${s.careerId}/context`)).text;
    } catch {
        // keep the last known context
    }
}

async function poll() {
    const s = settings();
    if (busy || !s.enabled || !s.careerId) return;
    busy = true;
    try {
        await refreshContext();
        const events = await api(`/api/st/careers/${s.careerId}/events?limit=3`);
        for (const event of events) {
            setStatus(`Writing reactions to ${event.type} (${event.date})…`);
            try {
                await handleEvent(event);
                failures.delete(event.id);
            } catch (error) {
                const count = (failures.get(event.id) || 0) + 1;
                failures.set(event.id, count);
                console.warn('[osu! Tycoon] event failed', event.id, error);
                if (count >= MAX_FAILURES) {
                    // Don't let one bad event block the queue forever.
                    await api(`/api/st/careers/${s.careerId}/events/${event.id}/ack`, { method: 'POST' }).catch(() => {});
                    failures.delete(event.id);
                }
            }
        }
        setStatus(`Connected · last check ${new Date().toLocaleTimeString()} · ${events.length} event(s) handled`);
    } catch (error) {
        setStatus(`Can't reach the engine at ${s.engineUrl}: ${error.message}`);
    } finally {
        busy = false;
    }
}

function restartTimer() {
    clearInterval(timer);
    const s = settings();
    if (s.enabled) {
        timer = setInterval(poll, Math.max(5, Number(s.pollSeconds) || 20) * 1000);
        void poll();
    }
}

async function loadCareers() {
    const s = settings();
    const select = $('#osu_tycoon_career').empty();
    try {
        const careers = await api('/api/st/careers');
        select.append($('<option>').val('').text('— choose a career —'));
        for (const c of careers) {
            select.append($('<option>').val(c.id).text(`${c.name} [${c.country}] · ${c.in_game_date}`));
        }
        select.val(s.careerId ?? '');
        setStatus(`Found ${careers.length} career(s).`);
    } catch (error) {
        setStatus(`Can't reach the engine at ${s.engineUrl}: ${error.message}`);
    }
}

function settingsHtml() {
    const checkbox = (key, label) =>
        `<label class="checkbox_label"><input type="checkbox" id="osu_tycoon_${key}"> ${label}</label>`;
    return `
<div class="osu-tycoon-settings">
  <div class="inline-drawer">
    <div class="inline-drawer-toggle inline-drawer-header">
      <b>osu! Tycoon Bridge</b>
      <div class="inline-drawer-icon fa-solid fa-circle-chevron-down down"></div>
    </div>
    <div class="inline-drawer-content">
      <div class="row"><label for="osu_tycoon_url">Engine URL</label><input type="text" id="osu_tycoon_url" class="text_pole"></div>
      <div class="row"><label for="osu_tycoon_career">Career</label><select id="osu_tycoon_career" class="text_pole"></select>
        <div id="osu_tycoon_reload" class="menu_button fa-solid fa-rotate" title="Reload careers"></div></div>
      <div class="row"><label for="osu_tycoon_poll">Check every (seconds)</label><input type="number" min="5" id="osu_tycoon_poll" class="text_pole"></div>
      ${checkbox('enabled', 'Enabled')}
      ${checkbox('forum', 'Write forum comments')}
      ${checkbox('irc', 'Write IRC chatter')}
      ${checkbox('narrate', 'Narrate events into the current chat')}
      ${checkbox('structured', 'Use structured outputs (Chat Completion APIs)')}
      <div class="row"><div id="osu_tycoon_now" class="menu_button">Process events now</div></div>
      <small>Put <code>{{tycoon}}</code> in an Author's Note or World Info entry to give the model the career's current state.
        Play from the chat with <code>/tycoon status | train | play | rest | week | dm</code>.</small>
      <div id="osu_tycoon_status" class="status"></div>
    </div>
  </div>
</div>`;
}

function bindSettings() {
    const s = settings();
    $('#osu_tycoon_url').val(s.engineUrl).on('change', function () {
        s.engineUrl = String($(this).val()).trim();
        save();
        void loadCareers();
    });
    $('#osu_tycoon_career').on('change', function () {
        const value = $(this).val();
        s.careerId = value ? Number(value) : null;
        save();
        void refreshContext();
    });
    $('#osu_tycoon_reload').on('click', () => void loadCareers());
    $('#osu_tycoon_poll').val(s.pollSeconds).on('change', function () {
        s.pollSeconds = Number($(this).val()) || 20;
        save();
        restartTimer();
    });
    for (const key of ['enabled', 'forum', 'irc', 'narrate', 'structured']) {
        $(`#osu_tycoon_${key}`).prop('checked', !!s[key]).on('change', function () {
            s[key] = $(this).prop('checked');
            save();
            if (key === 'enabled') restartTimer();
        });
    }
    $('#osu_tycoon_now').on('click', () => void poll());
}


// --- /tycoon: play the game from the chat ---------------------------------------------------

const WEEK_DEFAULT = [
    { type: 'train', drill: 'ranked_pack_grind', hours: 2 },
    { type: 'train', drill: 'tech_maps', hours: 2 },
    { type: 'session', preset: 'farm', hours: 2 },
    { type: 'train', drill: 'watch_replays', hours: 2 },
    { type: 'rest' },
    { type: 'session', preset: 'push', hours: 3 },
    { type: 'rest' },
];

function summarizeAction(result) {
    const lines = (result.events || [])
        .filter((e) => !e.type.startsWith('WORLD_') || ['WORLD_TOURNAMENT_WIN', 'WORLD_NEW_NUMBER_ONE'].includes(e.type))
        .slice(0, 6)
        .map((e) => `- ${e.message}`);
    const p = result.player || {};
    const head = `[osu! Tycoon] ${result.start_date || result.date} → ${p.in_game_date}: rank ${p.global_rank ? '#' + p.global_rank.toLocaleString() : 'unranked'}, ${Math.round(p.total_pp || 0)}pp, OVR ${Math.round(p.overall || 0)}`;
    return [head, ...lines].join('\n');
}

async function tycoonCommand(text) {
    const s = settings();
    if (!s.careerId) return 'osu! Tycoon: choose a career in the extension settings first.';
    const [verb = 'status', ...args] = String(text || '').trim().split(/\s+/);
    const id = s.careerId;
    const post = (path, body) => api(path, { method: 'POST', body: JSON.stringify(body) });
    try {
        switch (verb) {
            case 'status':
                await refreshContext();
                return contextText;
            case 'train': {
                const [drill, hours = '2', days = '1'] = args;
                if (!drill) return 'Usage: /tycoon train <drill> [hours/day] [days]';
                return summarizeAction(await post(`/api/players/${id}/train`, { drill, hours_per_day: Number(hours), days: Number(days) }));
            }
            case 'play': {
                const [preset = 'farm', hours = '2', stream] = args;
                return summarizeAction(await post(`/api/players/${id}/sessions/auto`, { preset, hours: Number(hours), stream: stream === 'stream' }));
            }
            case 'rest': {
                const [days = '1', physio] = args;
                return summarizeAction(await post(`/api/players/${id}/rest`, { days: Number(days), physio: physio === 'physio' }));
            }
            case 'week': {
                const r = await post(`/api/players/${id}/week`, { days: WEEK_DEFAULT });
                const days = r.days.map((d) => `- ${d.date}: ${d.summary}`).join('\n');
                return `[osu! Tycoon] week ${r.start_date} → ${r.end_date}${r.stopped_early ? ` (stopped: ${r.stopped_early})` : ''}\n${days}`;
            }
            case 'dm': {
                const [to, ...words] = args;
                if (!to || !words.length) return 'Usage: /tycoon dm <player> <message>';
                await post(`/api/players/${id}/dm`, { to, text: words.join(' ') });
                void poll(); // the reply is generated from the DM event right away
                return `[osu! Tycoon] message sent to ${to}; their reply appears in DM:${to}.`;
            }
            default:
                return 'Commands: /tycoon status | train <drill> [h] [days] | play <preset> [h] [stream] | rest [days] [physio] | week | dm <player> <text>';
        }
    } catch (error) {
        return `osu! Tycoon: ${error.message}`;
    }
}

function registerCommand() {
    const c = ctx();
    if (!c.SlashCommandParser || !c.SlashCommand) return;
    c.SlashCommandParser.addCommandObject(c.SlashCommand.fromProps({
        name: 'tycoon',
        helpString: 'osu! Tycoon: status, train, play, rest, week or dm. Example: /tycoon train jump_farm 4 3',
        callback: async (_named, unnamed) => {
            const result = await tycoonCommand(unnamed);
            await narrate(result);
            return result;
        },
    }));
}

function registerMacro() {
    const c = ctx();
    if (typeof c.registerMacro === 'function') {
        c.registerMacro('tycoon', () => contextText || '[osu! Tycoon: no career selected]');
    }
}

jQuery(async () => {
    $('#extensions_settings2').append(settingsHtml());
    bindSettings();
    registerMacro();
    registerCommand();
    await loadCareers();
    await refreshContext();
    restartTimer();
});
