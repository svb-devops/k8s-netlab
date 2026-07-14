/**
 * Regression tests for the LabGen session page layout fixes:
 *   1. The "实验步骤" drawer used to be a position:fixed overlay with a
 *      full-screen backdrop that covered the terminal (and dimmed it) whenever
 *      opened, instead of resizing the terminal area next to it.
 *   2. The terminal security notice ("use this terminal for the current lab
 *      only...") used to be printed as raw ANSI text into the xterm.js
 *      buffer, which wraps at the current column width and reads as
 *      unaligned/ragged instead of a real banner.
 *   3. openDrawer()/closeDrawer() used to call _terminal.fit() synchronously
 *      right when the drawer's CSS class was toggled — but #lab-drawer's width
 *      change on desktop is a 250ms CSS transition, not instant. fit() measured
 *      the container mid-transition (stale width), giving xterm.js a wrong
 *      column count that corrupted line-wrapping for the rest of the session
 *      (later output would overwrite characters instead of wrapping cleanly).
 *      Found via production dogfooding after fix #1 shipped: opening the
 *      drawer no longer overlays the terminal, but resizing it exposed this
 *      latent fit()-timing bug that never mattered when the drawer was an
 *      overlay (resizing nothing).
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

test('terminal is refit after the drawer transition ends, not synchronously on toggle', () => {
    const openDrawerStart = sessionInitJs.indexOf('function openDrawer()');
    const openDrawerBody = sessionInitJs.slice(
        openDrawerStart,
        sessionInitJs.indexOf('\n}', openDrawerStart)
    );
    const closeDrawerStart = sessionInitJs.indexOf('function closeDrawer()');
    const closeDrawerBody = sessionInitJs.slice(
        closeDrawerStart,
        sessionInitJs.indexOf('\n}', closeDrawerStart)
    );
    assert.doesNotMatch(
        openDrawerBody,
        /_terminal\.fit\(\)/,
        'openDrawer() must not call _terminal.fit() synchronously — the drawer\'s ' +
        'width change is a CSS transition, so fit() would measure a stale mid-transition width'
    );
    assert.doesNotMatch(
        closeDrawerBody,
        /_terminal\.fit\(\)/,
        'closeDrawer() must not call _terminal.fit() synchronously — same reasoning as openDrawer()'
    );
    assert.match(
        openDrawerBody,
        /_refitAfterDrawerTransition\(\)/,
        'openDrawer() must schedule a deferred refit'
    );
    assert.match(
        closeDrawerBody,
        /_refitAfterDrawerTransition\(\)/,
        'closeDrawer() must schedule a deferred refit'
    );
    // Regression (caught in safety review): a transitionend listener never fires
    // for prefers-reduced-motion / any 0-duration CSS transition, which would
    // leave fit() permanently stale for those users — worse than calling it too
    // early. setTimeout fires unconditionally regardless of whether the CSS
    // transition actually ran.
    assert.doesNotMatch(
        sessionInitJs,
        /addEventListener\(\s*['"]transitionend['"]/,
        'refit must not depend on the transitionend event — it does not fire for ' +
        '0-duration transitions (prefers-reduced-motion), which would silently break ' +
        'terminal refitting for those users'
    );
    assert.match(
        sessionInitJs,
        /setTimeout\(\s*\(\s*\)\s*=>\s*{\s*if\s*\(_terminal\)\s*_terminal\.fit\(\)/,
        'the deferred refit must use setTimeout so it fires regardless of whether a ' +
        'CSS transition actually occurred'
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

test('terminal fit() re-scrolls to bottom after resizing (regression: input line appeared to vanish)', () => {
    // Production bug found via owner dogfooding: after pressing Enter, the
    // command line the learner had just typed would appear to disappear.
    // Root cause: fitAddon.fit() reflows the xterm.js buffer to the new column
    // count but never re-scrolls the viewport to follow the cursor. Once the
    // drawer auto-opens on first terminal activation (see the other test in
    // this file), a resize fires shortly after page load — exactly the window
    // where a learner is likely to already be typing their first command. If
    // reflow needs more rows at the new (narrower) width, the current line can
    // end up above the visible viewport, reading as vanished even though it's
    // still in the buffer. scrollToBottom() after fit() is the standard fix
    // for this well-known xterm.js + fit-addon interaction.
    const fitStart = terminalJs.indexOf('fit() {');
    const fitBody = terminalJs.slice(fitStart, terminalJs.indexOf('\n    }', fitStart));
    assert.match(
        fitBody,
        /_fitAddon\.fit\(\)/,
        'fit() must still call fitAddon.fit()'
    );
    assert.match(
        fitBody,
        /_terminal\.scrollToBottom\(\)/,
        'fit() must call scrollToBottom() after fitAddon.fit() so the current line stays visible'
    );
    // Both call sites that used to call `this._fitAddon.fit()` directly (initial
    // connect() fit, and the window resize handler) must route through this.fit()
    // instead, so scrollToBottom() applies everywhere a resize can happen — not
    // just the one call site that happened to get the fix.
    assert.doesNotMatch(
        terminalJs,
        /window\.addEventListener\('resize'.*_fitAddon\.fit\(\)/,
        'the resize handler must call this.fit(), not this._fitAddon.fit() directly'
    );
});
