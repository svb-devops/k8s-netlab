/**
 * K8S NetLab - Authentication Logic
 *
 * Handles user login (local + Directus), registration, and session management.
 */

// Tab elements
const tabLogin = document.getElementById('tab-login');
const tabDirectus = document.getElementById('tab-directus');
const tabRegister = document.getElementById('tab-register');
const loginForm = document.getElementById('login-form');
const directusForm = document.getElementById('directus-form');
const registerForm = document.getElementById('register-form');
const verifyForm = document.getElementById('verify-form');

const ALL_TABS = [tabLogin, tabDirectus, tabRegister];
const ALL_FORMS = [loginForm, directusForm, registerForm, verifyForm];

// Username pending email verification (set on register success, consumed by verify/resend)
let pendingVerificationUsername = null;

function showVerifyForm(username, email) {
    pendingVerificationUsername = username;
    document.getElementById('verify-email-display').textContent = email;
    ALL_FORMS.forEach(f => f.classList.add('hidden'));
    verifyForm.classList.remove('hidden');
}

function activateTab(activeTab, activeForm) {
    ALL_TABS.forEach(t => {
        t.classList.add('border-transparent', 'text-gray-500');
        t.classList.remove('border-k8s-blue', 'text-k8s-blue');
    });
    activeTab.classList.remove('border-transparent', 'text-gray-500');
    activeTab.classList.add('border-k8s-blue', 'text-k8s-blue');

    ALL_FORMS.forEach(f => f.classList.add('hidden'));
    activeForm.classList.remove('hidden');
}

tabLogin.addEventListener('click', () => activateTab(tabLogin, loginForm));
tabDirectus.addEventListener('click', () => activateTab(tabDirectus, directusForm));
tabRegister.addEventListener('click', () => activateTab(tabRegister, registerForm));

// Message display
function showMessage(message, isError = false) {
    const messageDiv = document.getElementById('message');
    const messageContent = document.getElementById('message-content');

    messageContent.textContent = message;
    messageContent.className = isError
        ? 'p-3 rounded-lg bg-red-100 text-red-700'
        : 'p-3 rounded-lg bg-green-100 text-green-700';

    messageDiv.classList.remove('hidden');

    setTimeout(() => {
        messageDiv.classList.add('hidden');
    }, 5000);
}

async function submitLogin(endpoint, username, password) {
    const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
        credentials: 'include',
    });
    const result = await response.json();
    if (response.ok) {
        showMessage('登录成功！正在跳转...', false);
        const next = new URLSearchParams(window.location.search).get('next');
        setTimeout(() => { window.location.href = next || '/app'; }, 1000);
    } else {
        showMessage(result.detail || '登录失败', true);
    }
}

// Local login handler
loginForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const username = document.getElementById('login-username').value;
    const password = document.getElementById('login-password').value;
    try {
        await submitLogin('/api/auth/login', username, password);
    } catch (error) {
        console.error('Login error:', error);
        showMessage('网络错误，请稍后重试', true);
    }
});

// Directus login handler
directusForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const username = document.getElementById('directus-username').value;
    const password = document.getElementById('directus-password').value;
    try {
        await submitLogin('/api/auth/directus-login', username, password);
    } catch (error) {
        console.error('Directus login error:', error);
        showMessage('网络错误，请稍后重试', true);
    }
});

// Register handler
registerForm.addEventListener('submit', async (e) => {
    e.preventDefault();

    const username = document.getElementById('register-username').value;
    const email = document.getElementById('register-email').value.trim().toLowerCase();
    const password = document.getElementById('register-password').value;
    const passwordConfirm = document.getElementById('register-password-confirm').value;

    if (password !== passwordConfirm) {
        showMessage('两次输入的密码不一致', true);
        return;
    }

    if (!email) {
        showMessage('请填写邮箱', true);
        return;
    }

    try {
        const response = await fetch('/api/auth/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, email, password }),
        });

        const result = await response.json();

        if (response.ok) {
            if (result.verification_required) {
                showMessage('注册成功！请查收邮箱验证码', false);
                showVerifyForm(username, email);
            } else {
                showMessage('注册成功！请登录', false);
                setTimeout(() => {
                    tabLogin.click();
                    document.getElementById('login-username').value = username;
                }, 2000);
            }
        } else {
            showMessage(result.detail || '注册失败', true);
        }
    } catch (error) {
        console.error('Register error:', error);
        showMessage('网络错误，请稍后重试', true);
    }
});

// Email verification handler
verifyForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const code = document.getElementById('verify-code').value.trim();

    try {
        const response = await fetch('/api/auth/verify-email', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: pendingVerificationUsername, code }),
        });
        const result = await response.json();

        if (response.ok) {
            showMessage('验证成功！请登录', false);
            const verifiedUsername = pendingVerificationUsername;
            pendingVerificationUsername = null;
            setTimeout(() => {
                tabLogin.click();
                document.getElementById('login-username').value = verifiedUsername;
            }, 1500);
        } else {
            showMessage(result.detail || '验证失败', true);
        }
    } catch (error) {
        console.error('Verify email error:', error);
        showMessage('网络错误，请稍后重试', true);
    }
});

// Resend verification code handler
document.getElementById('verify-resend').addEventListener('click', async () => {
    try {
        const response = await fetch('/api/auth/resend-verification', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: pendingVerificationUsername }),
        });
        const result = await response.json();
        showMessage(response.ok ? '验证码已重新发送' : (result.detail || '发送失败'), !response.ok);
    } catch (error) {
        console.error('Resend verification error:', error);
        showMessage('网络错误，请稍后重试', true);
    }
});
