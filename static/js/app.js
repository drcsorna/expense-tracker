// ===== MAIN APPLICATION INITIALIZATION =====

// Global configuration
const API_BASE = '/proxy/8000/api';
let authToken = localStorage.getItem('auth_token');

// Global state
window.appState = {
    currentTab: 'staged',
    isAuthenticated: false,
    currentTheme: 'light'
};

// ===== INITIALIZATION =====
document.addEventListener('DOMContentLoaded', function() {
    console.log('🚀 Expense Tracker 3.0 - Starting...');
    
    initializeTheme();
    updateConnectionStatus('disconnected', 'Not connected');
    
    if (authToken) {
        checkAuth();
    } else {
        showLoginSection();
    }
    
    setupEventListeners();
});

// ===== EVENT LISTENERS =====
function setupEventListeners() {
    // Close dropdown when clicking outside
    document.addEventListener('click', function(event) {
        const dropdown = document.getElementById('user-dropdown');
        if (!dropdown.contains(event.target)) {
            closeUserDropdown();
        }
    });
    
    // Handle escape key to close dropdown
    document.addEventListener('keydown', function(event) {
        if (event.key === 'Escape') {
            closeUserDropdown();
        }
    });
}

// ===== USER DROPDOWN MANAGEMENT =====
function toggleUserDropdown() {
    const dropdown = document.getElementById('user-dropdown');
    const menu = document.getElementById('user-dropdown-menu');
    
    if (dropdown.classList.contains('open')) {
        closeUserDropdown();
    } else {
        openUserDropdown();
    }
}

function openUserDropdown() {
    const dropdown = document.getElementById('user-dropdown');
    const menu = document.getElementById('user-dropdown-menu');
    
    dropdown.classList.add('open');
    menu.classList.remove('hidden');
}

function closeUserDropdown() {
    const dropdown = document.getElementById('user-dropdown');
    const menu = document.getElementById('user-dropdown-menu');
    
    dropdown.classList.remove('open');
    menu.classList.add('hidden');
}

// ===== THEME MANAGEMENT =====
function initializeTheme() {
    const savedTheme = localStorage.getItem('theme') || 
                       (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    setTheme(savedTheme);
}

function setTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    
    // Update theme icon and text in dropdown
    const themeIcon = document.getElementById('theme-icon');
    const themeText = document.getElementById('theme-text');
    
    if (theme === 'dark') {
        themeIcon.textContent = '☀️';
        themeText.textContent = 'Light Mode';
    } else {
        themeIcon.textContent = '🌙';
        themeText.textContent = 'Dark Mode';
    }
    
    localStorage.setItem('theme', theme);
    window.appState.currentTheme = theme;
}

function toggleTheme() {
    const currentTheme = document.documentElement.getAttribute('data-theme');
    setTheme(currentTheme === 'dark' ? 'light' : 'dark');
    closeUserDropdown(); // Close dropdown after theme change
}

// ===== CONNECTION STATUS =====
function updateConnectionStatus(status, message = '') {
    const iconElement = document.getElementById('connection-icon');
    const textElement = document.getElementById('connection-text');
    const statusContainer = document.querySelector('.connection-status-inline');
    
    // Remove old status classes
    statusContainer.classList.remove('connected', 'disconnected', 'reconnecting');
    statusContainer.classList.add(status);
    
    switch(status) {
        case 'connected':
            iconElement.textContent = '🟢';
            textElement.textContent = message || 'Connected';
            break;
        case 'disconnected':
            iconElement.textContent = '🔴';
            textElement.textContent = message || 'Disconnected';
            break;
        case 'reconnecting':
            iconElement.textContent = '🟡';
            textElement.textContent = message || 'Reconnecting...';
            break;
    }
}

// ===== UI MANAGEMENT =====
function showLoginSection() {
    document.getElementById('login-section').classList.remove('hidden');
    document.getElementById('upload-section').classList.add('hidden');
    document.getElementById('main-section').classList.add('hidden');
    window.appState.isAuthenticated = false;
}

function showMainApplication() {
    document.getElementById('login-section').classList.add('hidden');
    document.getElementById('upload-section').classList.remove('hidden');
    document.getElementById('main-section').classList.remove('hidden');
    window.appState.isAuthenticated = true;
    loadInitialData();
}

// ===== TAB MANAGEMENT =====
function switchTab(tabName) {
    console.log(`Switching to tab: ${tabName}`);
    
    // Update active tab
    document.querySelectorAll('.tab').forEach(tab => {
        tab.classList.remove('active');
    });
    document.querySelector(`[onclick="switchTab('${tabName}')"]`).classList.add('active');
    
    // Update app state
    window.appState.currentTab = tabName;
    
    // Load content for the selected tab
    loadTabContent(tabName);
}

function loadTabContent(tabName) {
    const container = document.getElementById('tab-content-container');
    
    switch(tabName) {
        case 'staged':
            loadStagedTransactionsTab(container);
            break;
        case 'transactions':
            loadTransactionsTab(container);
            break;
        case 'duplicates':
            loadDuplicatesTab(container);
            break;
        case 'categories':
            loadCategoriesTab(container);
            break;
        case 'stats':
            loadStatsTab(container);
            break;
        default:
            container.innerHTML = `<p>Tab content for ${tabName} coming soon...</p>`;
    }
}

// ===== USER MENU FUNCTIONS =====
function openUserProfile() {
    closeUserDropdown();
    showToast('👤 User profile coming soon', 'warning');
    // TODO: Implement user profile modal/page
}

function openSettings() {
    closeUserDropdown();
    showToast('⚙️ Settings coming soon', 'warning');
    // TODO: Implement settings modal/page
}

function openUploadHistory() {
    closeUserDropdown();
    showToast('📜 Upload history coming soon', 'warning');
    // TODO: Implement upload history modal/page
}

function showAbout() {
    closeUserDropdown();
    showToast('ℹ️ Expense Tracker 3.0 - AI-powered expense tracking', 'success');
    // TODO: Implement about modal with version info, features, etc.
}

// ===== AUTHENTICATION =====
async function checkAuth() {
    try {
        updateConnectionStatus('reconnecting', 'Checking authentication...');
        
        const response = await fetch(`${API_BASE}/auth/me`, {
            headers: { 'Authorization': `Bearer ${authToken}` }
        });
        
        if (response.ok) {
            const userData = await response.json();
            updateConnectionStatus('connected', 'Authenticated');
            updateWelcomeMessage(userData);
            showMainApplication();
        } else {
            throw new Error('Authentication failed');
        }
    } catch (error) {
        console.error('Auth check failed:', error);
        updateConnectionStatus('disconnected', 'Authentication failed');
        localStorage.removeItem('auth_token');
        authToken = null;
        showLoginSection();
    }
}

function updateWelcomeMessage(userData) {
    const welcomeElement = document.getElementById('welcome-message');
    if (userData && userData.email) {
        welcomeElement.textContent = userData.email;
    } else {
        welcomeElement.textContent = 'User';
    }
}

async function login() {
    const email = document.getElementById('email').value;
    const password = document.getElementById('password').value;
    
    if (!email || !password) {
        showToast('❌ Please enter email and password', 'error');
        return;
    }
    
    try {
        updateConnectionStatus('reconnecting', 'Logging in...');
        
        const formData = new FormData();
        formData.append('username', email);
        formData.append('password', password);
        
        const response = await fetch(`${API_BASE}/auth/login`, {
            method: 'POST',
            body: formData
        });
        
        if (response.ok) {
            const data = await response.json();
            authToken = data.access_token;
            localStorage.setItem('auth_token', authToken);
            
            updateConnectionStatus('connected', 'Login successful');
            updateWelcomeMessage(data.user);
            showToast('✅ Login successful!', 'success');
            showMainApplication();
        } else {
            const error = await response.json();
            throw new Error(error.detail || 'Login failed');
        }
    } catch (error) {
        updateConnectionStatus('disconnected', 'Login failed');
        showToast(`❌ Login failed: ${error.message}`, 'error');
        console.error('Login error:', error);
    }
}

function logout() {
    localStorage.removeItem('auth_token');
    authToken = null;
    updateConnectionStatus('disconnected', 'Logged out');
    showToast('👋 Logged out successfully', 'success');
    showLoginSection();
    closeUserDropdown();
}

// ===== INITIAL DATA LOADING =====
function loadInitialData() {
    console.log('Loading initial data...');
    // Load the default tab content
    loadTabContent(window.appState.currentTab);
}

// ===== TAB CONTENT LOADERS =====
function loadStagedTransactionsTab(container) {
    container.innerHTML = `
        <div class="staged-transactions-content">
            <div class="flex justify-between align-items-center mb-lg">
                <h3>📋 Staged Transactions</h3>
                <div class="gap-md flex">
                    <button class="btn btn-success btn-sm" onclick="approveAllStaged()">✅ Approve All</button>
                    <button class="btn btn-danger btn-sm" onclick="deleteAllStaged()">🗑️ Delete All</button>
                </div>
            </div>
            <div id="staged-transactions-list">Loading staged transactions...</div>
        </div>
    `;
    
    // Load staged transactions if the loader exists
    if (typeof loadStagedTransactionsPaginated === 'function') {
        loadStagedTransactionsPaginated();
    }
}

function loadTransactionsTab(container) {
    container.innerHTML = `
        <div class="transactions-content">
            <h3>💰 All Transactions</h3>
            <div id="transactions-list">Loading transactions...</div>
        </div>
    `;
    
    // Load transactions if the loader exists
    if (typeof loadTransactionsPaginated === 'function') {
        loadTransactionsPaginated();
    }
}

function loadDuplicatesTab(container) {
    container.innerHTML = `
        <div class="duplicates-content">
            <div class="flex justify-between align-items-center mb-lg">
                <h3>🔍 Duplicate Manager</h3>
                <button class="btn btn-warning btn-sm" onclick="scanForDuplicates()">🔄 Scan for Duplicates</button>
            </div>
            <div id="duplicates-list">Loading duplicates...</div>
        </div>
    `;
    
    // Load duplicates if the loader exists
    if (typeof loadDuplicates === 'function') {
        loadDuplicates();
    }
}

function loadCategoriesTab(container) {
    container.innerHTML = `
        <div class="categories-content">
            <h3>🏷️ Categories</h3>
            <div id="categories-list">Loading categories...</div>
        </div>
    `;
    
    // TODO: Implement category management
}

function loadStatsTab(container) {
    container.innerHTML = `
        <div class="stats-content">
            <h3>📊 Analytics</h3>
            <div id="stats-content">Loading analytics...</div>
        </div>
    `;
    
    // TODO: Implement analytics dashboard
}

// ===== TOAST NOTIFICATIONS =====
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    
    container.appendChild(toast);
    
    // Trigger animation
    setTimeout(() => toast.classList.add('show'), 100);
    
    // Remove toast after 5 seconds
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => container.removeChild(toast), 300);
    }, 5000);
}

// ===== UTILITY FUNCTIONS =====
async function makeAuthenticatedRequest(url, options = {}) {
    const defaultOptions = {
        headers: {
            'Authorization': `Bearer ${authToken}`,
            'Content-Type': 'application/json',
            ...options.headers
        }
    };
    
    return fetch(url, { ...options, ...defaultOptions });
}

// Make functions globally available
window.toggleUserDropdown = toggleUserDropdown;
window.toggleTheme = toggleTheme;
window.openUserProfile = openUserProfile;
window.openSettings = openSettings;
window.openUploadHistory = openUploadHistory;
window.showAbout = showAbout;
window.login = login;
window.logout = logout;
window.swsoonitchTab = switchTab;
window.showToast = showToast;
window.makeAuthenticatedRequest = makeAuthenticatedRequest;
window.updateConnectionStatus = updateConnectionStatus;