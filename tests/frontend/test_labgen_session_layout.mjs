/**
 * Regression tests for the LabGen session page layout fixes:
 *   1. The "实验步骤" drawer used to be a position:fixed overlay with a
 *      full-screen backdrop that covered the terminal (and dimmed it) whenever
 *      opened, instead of resizing the terminal area next to it.
 *   2. The terminal security notice ("use this terminal for the current lab
 *      only...") used to be printed as raw ANSI text into the xterm.js
 *      buffer, which wraps at the current column width and reads as
 *      unaligned/ragged instead of a real banner.
 *
 * No jsdom is set up in this project (frontend tests only exercise pure
 * functions — see test_views.mjs's docstring), so these assert on the static
 * HTML/CSS/JS source rather than rendered DOM.
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_DIR = path.join(__dirname, '..', '..', 'frontend');

const sessionHtml = readFileSync(path.join(FRONTEND_DIR, 'labgen-session.html'), 'utf8');
const terminalJs = readFileSync(path.join(FRONTEND_DIR, 'js', 'labgen-kubectl-terminal.js'), 'utf8');
const sessionInitJs = readFileSync(path.join(FRONTEND_DIR, 'js', 'labgen-session-init.js'), 'utf8');

test('lab-drawer and terminal are wrapped in a shared flex row (sidebar, not overlay)', () => {
    const rowStart = sessionHtml.indexOf('id="session-body-row"');
    const drawerIdx = sessionHtml.indexOf('id="lab-drawer"');
    const mainIdx = sessionHtml.indexOf('id="session-terminal-wrap"');
    const rowEnd = sessionHtml.indexOf('<!-- end session-body-row -->');

    assert.ok(rowStart !== -1, '#session-body-row wrapper must exist');
    assert.ok(rowEnd !== -1, '#session-body-row must have a closing marker');
    assert.ok(
        drawerIdx > rowStart && drawerIdx < rowEnd,
        '#lab-drawer must be nested inside #session-body-row'
    );
    assert.ok(
        mainIdx > rowStart && mainIdx < rowEnd,
        '#session-terminal-wrap must be nested inside #session-body-row (same flex row as the drawer)'
    );
});

test('desktop #lab-drawer overrides the shared fixed-overlay positioning', () => {
    const styleBlock = sessionHtml.slice(
        sessionHtml.indexOf('<style>'),
        sessionHtml.indexOf('</style>')
    );
    assert.match(
        styleBlock,
        /#lab-drawer\s*\{[^}]*position:\s*static/,
        'desktop #lab-drawer must override .doc-drawer\'s position:fixed with position:static ' +
        'so opening it resizes the terminal instead of overlaying it'
    );
    assert.match(
        styleBlock,
        /#lab-drawer-backdrop\s*\{[^}]*display:\s*none/,
        'the full-screen backdrop must be disabled on desktop — the sidebar no longer covers ' +
        'the terminal, so dimming it has no purpose'
    );
    assert.match(
        styleBlock,
        /max-width:\s*768px\)\s*\{[^]*#lab-drawer\s*\{[^}]*position:\s*fixed/,
        'mobile viewports must keep the original fixed-overlay behavior (no room for two columns)'
    );
});

test('security notice is a real HTML banner, not text printed into the terminal', () => {
    assert.match(
        sessionHtml,
        /请仅在本实验范围内使用该终端/,
        'labgen-session.html must render the security notice as static HTML'
    );
    assert.doesNotMatch(
        terminalJs,
        /_showSecurityNotice/,
        'the ANSI-escape security notice writer must be removed from the terminal client — ' +
        'it wrapped at the terminal\'s current column width and looked misaligned'
    );
});

test('drawer auto-opens once on desktop when the terminal first becomes active', () => {
    assert.match(
        sessionInitJs,
        /_hasAutoOpenedDrawer/,
        'a one-shot guard must exist so the drawer only auto-opens on the first activation, ' +
        'not every snapshot refresh (which would re-open a drawer the learner just closed)'
    );
    assert.match(
        sessionInitJs,
        /DESKTOP_DRAWER_BREAKPOINT_PX/,
        'auto-open must be gated on viewport width — auto-opening a full-screen mobile overlay ' +
        'the moment the terminal connects would hide the very thing the learner just waited for'
    );
});
