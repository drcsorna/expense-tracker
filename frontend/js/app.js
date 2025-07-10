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

// ===== THEME MANAGEMENT =====
function initializeTheme() {
    const savedTheme = localStorage.getItem('theme') || 
                       (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    setTheme(savedTheme);
}

function setTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    document.getElementById('theme-icon').textContent = theme === 'dark' ? '☀️' : '🌙';
    localStorage.setItem('theme', theme);
    window.appState.currentTheme = theme;
}

function toggleTheme() {
    const currentTheme = document.documentElement.getAttribute('data-theme');
    setTheme(currentTheme === 'dark' ? 'light' : 'dark');
}

// ===== CONNECTION STATUS =====
function updateConnectionStatus(status, message = '') {
    const statusElement = document.getElementById('connection-status');
    const iconElement = document.getElementById('connection-icon');
    const textElement = document.getElementById('connection-text');
    
    statusElement.className = `connection-status ${status}`;
    
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
    
    // Load tab content
    loadTabContent(tabName);
    window.appState.currentTab = tabName;
}

async function loadTabContent(tabName) {
    const container = document.getElementById('tab-content-container');
    
    try {
        // Show loading
        container.innerHTML = '<div class="text-center p-md">Loading...</div>';
        
        // Load the appropriate component
        const response = await fetch(`static/components/${tabName}-tab.html`);
        if (response.ok) {
            const html = await response.text();
            container.innerHTML = html;
            
            // Initialize tab-specific functionality
            switch(tabName) {
                case 'staged':
                    if (window.stagedTransactions) {
                        window.stagedTransactions.init();
                    }
                    break;
                case 'transactions':
                    if (window.transactionManager) {
                        window.transactionManager.init();
                    }
                    break;
                case 'duplicates':
                    if (window.duplicateManager) {
                        window.duplicateManager.init();
                    }
                    break;
            }
        } else {
            container.innerHTML = `<div class="text-center p-md">Error loading ${tabName} tab</div>`;
        }
    } catch (error) {
        console.error(`Error loading tab ${tabName}:`, error);
        container.innerHTML = `<div class="text-center p-md">Error loading ${tabName} tab</div>`;
    }
}

// ===== DATA LOADING =====
async function loadInitialData() {
    updateConnectionStatus('connected', 'Loading data...');
    
    try {
        // Load the default tab (staged)
        await loadTabContent('staged');
        updateConnectionStatus('connected', 'Ready');
    } catch (error) {
        console.error('Failed to load initial data:', error);
        updateConnectionStatus('disconnected', 'Failed to load data');
    }
}

// ===== EVENT LISTENERS =====
function setupEventListeners() {
    // Enter key for login
    document.getElementById('email').addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            login();
        }
    });
    
    document.getElementById('password').addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            login();
        }
    });
}

// ===== TOAST NOTIFICATIONS =====
function showToast(message, type = 'success', duration = 5000) {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <span>${message}</span>
            <button onclick="this.parentElement.parentElement.remove()" 
                    style="background: none; border: none; color: inherit; cursor: pointer; margin-left: var(--space-md);">×</button>
        </div>
    `;
    
    document.getElementById('toast-container').appendChild(toast);
    
    // Trigger animation
    setTimeout(() => toast.classList.add('show'), 100);
    
    // Auto remove
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

// ===== UTILITY FUNCTIONS =====
function formatDate(dateString) {
    return new Date(dateString).toLocaleDateString();
}

function formatAmount(amount) {
    return `€${Math.abs(amount).toFixed(2)}`;
}

function formatAmountColored(amount) {
    const color = amount < 0 ? 'var(--color-danger)' : 'var(--color-success)';
    return `<span style="color: ${color}; font-weight: var(--font-weight-bold);">${formatAmount(amount)}</span>`;
}

// Make functions globally available
window.toggleTheme = toggleTheme;
window.switchTab = switchTab;
window.showToast = showToast;
window.updateConnectionStatus = updateConnectionStatus;
window.formatDate = formatDate;
window.formatAmount = formatAmount;
window.formatAmountColored = formatAmountColored;