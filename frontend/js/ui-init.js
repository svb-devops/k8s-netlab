// ── Admin badge + password change modal ──────────────────────────────────
(function () {
    const modal    = document.getElementById('change-password-modal');
    const form     = document.getElementById('change-password-form');
    const errDiv   = document.getElementById('cp-error');
    const okDiv    = document.getElementById('cp-success');
    const btnOpen  = document.getElementById('btn-change-password');
    const btnClose = document.getElementById('cp-cancel');

    function openModal() {
        form.reset();
        errDiv.classList.add('hidden');
        okDiv.classList.add('hidden');
        modal.classList.remove('hidden');
        modal.classList.add('flex');
    }
    function closeModal() {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }

    btnOpen.addEventListener('click', openModal);
    btnClose.addEventListener('click', closeModal);
    modal.addEventListener('click', e => { if (e.target === modal) closeModal(); });

    form.addEventListener('submit', async e => {
        e.preventDefault();
        errDiv.classList.add('hidden');
        okDiv.classList.add('hidden');
        const oldPw  = document.getElementById('cp-old').value;
        const newPw  = document.getElementById('cp-new').value;
        const confPw = document.getElementById('cp-confirm').value;
        if (newPw !== confPw) {
            errDiv.textContent = '两次输入的新密码不一致';
            errDiv.classList.remove('hidden');
            return;
        }
        try {
            const resp = await fetch('/api/auth/change-password', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ old_password: oldPw, new_password: newPw }),
            });
            const data = await resp.json();
            if (resp.ok) {
                okDiv.textContent = '密码已修改成功';
                okDiv.classList.remove('hidden');
                form.reset();
                setTimeout(closeModal, 1500);
            } else {
                errDiv.textContent = data.detail || '修改失败';
                errDiv.classList.remove('hidden');
            }
        } catch {
            errDiv.textContent = '网络错误，请重试';
            errDiv.classList.remove('hidden');
        }
    });

    // Show admin badge + console link if user is admin
    fetch('/api/auth/me').then(r => r.json()).then(data => {
        if (data.is_admin) {
            document.getElementById('admin-badge').classList.remove('hidden');
            document.getElementById('admin-panel-link').classList.remove('hidden');
        }
    }).catch(() => {});
})();
