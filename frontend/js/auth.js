/**
 * K8S NetLab - Authentication Logic
 *
 * Handles user login, registration, and session management.
 */

// Tab switching
const tabLogin = document.getElementById('tab-login');
const tabRegister = document.getElementById('tab-register');
const loginForm = document.getElementById('login-form');
const registerForm = document.getElementById('register-form');

tabLogin.addEventListener('click', () => {
    tabLogin.classList.add('border-k8s-blue', 'text-k8s-blue');
    tabLogin.classList.remove('border-transparent', 'text-gray-500');
    tabRegister.classList.add('border-transparent', 'text-gray-500');
    tabRegister.classList.remove('border-k8s-blue', 'text-k8s-blue');

    loginForm.classList.remove('hidden');
    registerForm.classList.add('hidden');
});

tabRegister.addEventListener('click', () => {
    tabRegister.classList.add('border-k8s-blue', 'text-k8s-blue');
    tabRegister.classList.remove('border-transparent', 'text-gray-500');
    tabLogin.classList.add('border-transparent', 'text-gray-500');
    tabLogin.classList.remove('border-k8s-blue', 'text-k8s-blue');

    registerForm.classList.remove('hidden');
    loginForm.classList.add('hidden');
});

// Message display
function showMessage(message, isError = false) {
    const messageDiv = document.getElementById('message');
    const messageContent = document.getElementById('message-content');

    messageContent.textContent = message;
    messageContent.className = isError
        ? 'p-3 rounded-lg bg-red-100 text-red-700'
        : 'p-3 rounded-lg bg-green-100 text-green-700';

    messageDiv.classList.remove('hidden');

    // Auto-hide after 5 seconds
    setTimeout(() => {
        messageDiv.classList.add('hidden');
    }, 5000);
}

// Login handler
loginForm.addEventListener('submit', async (e) => {
    e.preventDefault();

    const username = document.getElementById('login-username').value;
    const password = document.getElementById('login-password').value;

    try {
        const response = await fetch('/api/auth/login', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ username, password }),
            credentials: 'include',
        });

        const result = await response.json();

        if (response.ok) {
            showMessage('登录成功！正在跳转...', false);
            // Redirect to main page after 1 second
            setTimeout(() => {
                window.location.href = '/';
            }, 1000);
        } else {
            showMessage(result.detail || '登录失败', true);
        }
    } catch (error) {
        console.error('Login error:', error);
        showMessage('网络错误，请稍后重试', true);
    }
});

// Register handler
registerForm.addEventListener('submit', async (e) => {
    e.preventDefault();

    const username = document.getElementById('register-username').value;
    const password = document.getElementById('register-password').value;
    const passwordConfirm = document.getElementById('register-password-confirm').value;

    // Validate password match
    if (password !== passwordConfirm) {
        showMessage('两次输入的密码不一致', true);
        return;
    }

    try {
        const response = await fetch('/api/auth/register', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ username, password }),
        });

        const result = await response.json();

        if (response.ok) {
            showMessage('注册成功！请登录', false);
            // Switch to login tab after 2 seconds
            setTimeout(() => {
                tabLogin.click();
                document.getElementById('login-username').value = username;
            }, 2000);
        } else {
            showMessage(result.detail || '注册失败', true);
        }
    } catch (error) {
        console.error('Register error:', error);
        showMessage('网络错误，请稍后重试', true);
    }
});
