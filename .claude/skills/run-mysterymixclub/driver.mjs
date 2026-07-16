// REPL driver for the MysteryMixClub web app (React/Vite frontend + FastAPI
// backend). Drives a real headless Chromium via Playwright against the
// running dev server. Designed for agents: wrap in tmux, send-keys commands,
// capture-pane output. No chromium-cli in this environment, so this REPL
// fills the same role (see .claude/skills/run-mysterymixclub/SKILL.md).
import { chromium } from 'playwright';
import * as readline from 'node:readline';
import * as fs from 'node:fs';
import * as path from 'node:path';

const BASE_URL = process.env.APP_URL || 'http://127.0.0.1:5173';
const SHOT_DIR = process.env.SCREENSHOT_DIR || '/tmp/shots';
fs.mkdirSync(SHOT_DIR, { recursive: true });

let browser = null;
let page = null;
const consoleLog = [];

const COMMANDS = {
  async launch() {
    if (browser) return console.log('already launched');
    browser = await chromium.launch({ args: ['--no-sandbox'] });
    page = await (await browser.newContext()).newPage();
    page.on('console', (msg) => consoleLog.push({ type: msg.type(), text: msg.text() }));
    page.on('pageerror', (err) => consoleLog.push({ type: 'pageerror', text: err.message }));
    console.log('launched.');
  },

  async nav(url) {
    if (!page) return console.log('ERROR: launch first');
    const target = /^https?:\/\//.test(url) ? url : BASE_URL + (url || '/');
    await page.goto(target, { waitUntil: 'domcontentloaded' });
    console.log('nav ->', target);
  },

  async ss(name) {
    if (!page) return console.log('ERROR: launch first');
    const f = path.join(SHOT_DIR, (name || `ss-${Date.now()}`) + '.png');
    await page.screenshot({ path: f });
    console.log('screenshot:', f);
  },

  async click(sel) {
    if (!page) return console.log('ERROR: launch first');
    try { await page.click(sel, { timeout: 10_000 }); console.log('click', sel, '-> OK'); }
    catch (e) { console.log('click', sel, '-> ERROR:', e.message); }
  },

  async 'click-text'(text) {
    if (!page) return console.log('ERROR: launch first');
    try {
      await page.getByText(text, { exact: false }).first().click({ timeout: 10_000 });
      console.log('click-text', JSON.stringify(text), '-> OK');
    } catch (e) { console.log('click-text', JSON.stringify(text), '-> ERROR:', e.message); }
  },

  // Playwright's fill() goes through the real input pipeline (fires React's
  // onChange) — unlike `eval el.value = …`, which controlled inputs ignore.
  async fill(rest) {
    if (!page) return console.log('ERROR: launch first');
    const sp = rest.indexOf(' ');
    const sel = sp === -1 ? rest : rest.slice(0, sp);
    const value = sp === -1 ? '' : rest.slice(sp + 1);
    try { await page.fill(sel, value, { timeout: 10_000 }); console.log('fill', sel, '->', value); }
    catch (e) { console.log('fill', sel, '-> ERROR:', e.message); }
  },

  async press(key) { if (page) await page.keyboard.press(key); },

  async 'wait-for'(sel) {
    if (!page) return console.log('ERROR: launch first');
    try {
      if (sel.startsWith('text=')) {
        await page.getByText(sel.slice(5), { exact: false }).first().waitFor({ timeout: 15_000 });
      } else {
        await page.waitForSelector(sel, { timeout: 15_000 });
      }
      console.log('found:', sel);
    } catch { console.log('TIMEOUT:', sel); }
  },

  async eval(expr) {
    if (!page) return console.log('ERROR: launch first');
    try { console.log(JSON.stringify(await page.evaluate(expr))); }
    catch (e) { console.log('ERROR:', e.message); }
  },

  async text(sel) {
    if (!page) return console.log('ERROR: launch first');
    console.log(await page.evaluate(
      (s) => (s ? document.querySelector(s) : document.body)?.innerText ?? '(null)',
      sel || null,
    ));
  },

  async url() { if (page) console.log(page.url()); },

  async console(flag) {
    const entries = flag === '--errors'
      ? consoleLog.filter((e) => e.type === 'error' || e.type === 'pageerror')
      : consoleLog;
    if (entries.length === 0) return console.log('(none)');
    for (const e of entries) console.log(`[${e.type}] ${e.text}`);
  },

  async quit() { if (browser) await browser.close().catch(() => {}); browser = null; page = null; },
  help() { console.log('commands:', Object.keys(COMMANDS).join(', ')); },
};

const rl = readline.createInterface({ input: process.stdin, output: process.stdout, prompt: 'driver> ' });

console.log('mysterymixclub driver - "help" for commands, "launch" to start');
rl.prompt();

// `for await…of rl` pulls one line at a time, awaiting each command before
// requesting the next — unlike the `rl.on('line', async …)` pattern, which
// fires every buffered line in the same tick regardless of async work still
// pending (fatal for piped/heredoc input: every command race-starts before
// `launch` finishes). This is the fix, not a style preference.
for await (const line of rl) {
  const [cmd, ...rest] = line.trim().split(/\s+/);
  if (!cmd) { rl.prompt(); continue; }
  const fn = COMMANDS[cmd];
  if (!fn) { console.log('unknown:', cmd, '- try: help'); rl.prompt(); continue; }
  try { await fn(rest.join(' ')); } catch (e) { console.log('ERROR:', e.message); }
  if (cmd === 'quit') break;
  rl.prompt();
}
await COMMANDS.quit();
process.exit(0);
