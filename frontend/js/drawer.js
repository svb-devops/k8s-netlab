/**
 * K8S NetLab - Doc Drawer
 *
 * Controls the experiment doc drawer overlay.
 * The drawer slides in from the left over the terminal (terminal never resizes).
 * After open/close transition, calls terminalManager.fit() to correct xterm layout.
 */

(function () {
    const TRANSITION_MS = 260; // slightly longer than CSS 250ms to ensure transition is done

    const drawer    = document.getElementById('doc-drawer');
    const backdrop  = document.getElementById('doc-drawer-backdrop');
    const btnToggle = document.getElementById('btn-toggle-drawer');
    const btnClose  = document.getElementById('btn-close-drawer');

    if (!drawer || !backdrop) return;

    let isOpen = false;

    function openDrawer() {
        if (isOpen) return;
        isOpen = true;
        drawer.classList.add('drawer-open');
        backdrop.classList.add('backdrop-visible');
        // Update toggle button appearance
        if (btnToggle) {
            btnToggle.classList.add('bg-gray-600', 'text-white');
            btnToggle.classList.remove('bg-gray-700', 'text-gray-300');
        }
        // fit() after transition so xterm measures the correct width
        setTimeout(() => {
            if (typeof terminalManager !== 'undefined') terminalManager.fit();
        }, TRANSITION_MS);
    }

    function closeDrawer() {
        if (!isOpen) return;
        isOpen = false;
        drawer.classList.remove('drawer-open');
        backdrop.classList.remove('backdrop-visible');
        // Restore toggle button appearance
        if (btnToggle) {
            btnToggle.classList.remove('bg-gray-600', 'text-white');
            btnToggle.classList.add('bg-gray-700', 'text-gray-300');
        }
        // fit() after transition
        setTimeout(() => {
            if (typeof terminalManager !== 'undefined') terminalManager.fit();
        }, TRANSITION_MS);
    }

    function toggleDrawer() {
        if (isOpen) closeDrawer(); else openDrawer();
    }

    btnToggle?.addEventListener('click', toggleDrawer);
    btnClose?.addEventListener('click', closeDrawer);
    backdrop.addEventListener('click', closeDrawer);

    // Close on Escape key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && isOpen) closeDrawer();
    });
})();
