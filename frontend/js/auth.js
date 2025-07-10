// ===== AUTHENTICATION MANAGEMENT =====

// ===== LOGIN FUNCTION =====
async function login() {
    const email = document.getElementById('email').value;
    const password = document.getElementById('password').value;

    if (!email || !password) {
        showToast('❌ Please enter email and password', 'error');
        return;
    }

    try {
        updateConnectionStatus('reconnecting', 'Signing in...');
        
        const response = await fetch(`${API_BASE}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: `username=${encodeURIComponent(email)}&password=${encodeURIComponent(password)}`
        });

        if (response.ok) {
            const data = await response.json();
            authToken = data.access_token;
            localStorage.setItem('auth_token', authToken);
            
            showToast('✅ Login successful!', 'success');
            updateConnectionStatus('connected', 'Authenticated');
            
            // Clear form
            document.getElementById('email').value = '';
            document.getElementById('password').value = '';
            
            // Check auth and show main app
            await checkAuth();
        } else {
            const error = await response.json();
            showToast(`❌ Login failed: ${error.detail}`, 'error');
            updateConnectionStatus('disconnected', 'Authentication failed');
        }
    } catch (error) {
        showToast(`❌ Login error: ${error.message}`, 'error');
        updateConnectionStatus('disconnected', 'Connection failed');
        console.error('Login error:', error);
    }
}

// ===== AUTHENTICATION CHECK =====
async function checkAuth() {
    try {
        updateConnectionStatus('reconnecting', 'Verifying authentication...');
        
        const response = await fetch(`${API_BASE}/auth/me`, {
            headers: { 'Authorization': `Bearer ${authToken}` }
        });

        if (response.ok) {
            const user = await response.json();
            
            // Update UI with user info
            document.getElementById('welcome-message').textContent = `Welcome, ${user.email}!`;
            
            updateConnectionStatus('connected', 'Authenticated');
            showMainApplication();
            
            return true;
        } else {
            console.warn('Authentication check failed:', response.status);
            logout();
            return false;
        }
    } catch (error) {
        console.error('Auth check error:', error);
        updateConnectionStatus('disconnected', 'Authentication check failed');
        logout();
        return false;
    }
}

// ===== LOGOUT FUNCTION =====
function logout() {
    localStorage.removeItem('auth_token');
    authToken = null;
    
    // Reset pagination state
    if (window.stagedPagination) {
        window.stagedPagination.reset();
    }
    if (window.transactionsPagination) {
        window.transactionsPagination.reset();
    }
    
    // Clear user info
    document.getElementById('welcome-message').textContent = 'Loading...';
    
    // Show login section
    showLoginSection();
    updateConnectionStatus('disconnected', 'Logged out');
    
    showToast('👋 Logged out successfully', 'success');
}

// ===== REGISTER FUNCTION (Optional) =====
async function register() {
    const email = document.getElementById('email').value;
    const password = document.getElementById('password').value;
    
    if (!email || !password) {
        showToast('Please enter both email and password', 'error');
        return;
    }
    
    if (password.length < 6) {
        showToast('Password must be at least 6 characters', 'error');
        return;
    }
    
    try {
        updateConnectionStatus('reconnecting', 'Creating account...');
        
        const response = await fetch(`${API_BASE}/auth/register`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password })
        });
        
        if (response.ok) {
            showToast('✅ Account created successfully! Please sign in.', 'success');
            updateConnectionStatus('disconnected', 'Account created');
        } else {
            const error = await response.json();
            showToast(`❌ Registration failed: ${error.detail}`, 'error');
            updateConnectionStatus('disconnected', 'Registration failed');
        }
    } catch (error) {
        showToast('❌ Network error. Please try again.', 'error');
        updateConnectionStatus('disconnected', 'Connection failed');
        console.error('Registration error:', error);
    }
}

// ===== API REQUEST HELPER =====
async function makeAuthenticatedRequest(url, options = {}) {
    const defaultOptions = {
        headers: {
            'Authorization': `Bearer ${authToken}`,
            'Content-Type': 'application/json',
            ...options.headers
        }
    };
    
    const response = await fetch(url, { ...options, headers: defaultOptions.headers });
    
    // Check for authentication errors
    if (response.status === 401) {
        console.warn('Authentication expired, logging out');
        logout();
        throw new Error('Authentication expired');
    }
    
    return response;
}

// ===== TOKEN REFRESH (Future enhancement) =====
async function refreshToken() {
    // This would be implemented if your backend supports token refresh
    // For now, we just logout on token expiry
    console.log('Token refresh not implemented, logging out');
    logout();
}

// Make functions globally available
window.login = login;
window.logout = logout;
window.register = register;
window.checkAuth = checkAuth;
window.makeAuthenticatedRequest = makeAuthenticatedRequest;