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

// ===== INITIAL DATA LOADING =====
function loadInitialData() {
    console.log('Loading initial data...');
    // Load the default tab content
    loadTabContent(window.appState.currentTab);
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

async function loadTabContent(tabName) {
    const container = document.getElementById('tab-content-container');
    
    switch(tabName) {
        case 'staged':
            await loadStagedTransactionsTab(container);
            break;
        case 'transactions':
            await loadTransactionsTab(container);
            break;
        case 'duplicates':
            await loadDuplicatesTab(container);
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

// ===== TAB CONTENT LOADERS - USE YOUR EXISTING STATIC COMPONENTS =====
async function loadStagedTransactionsTab(container) {
    try {
        console.log('Loading staged transactions tab from static component...');
        
        // Try different paths to find your static component
        const possiblePaths = [
            './static/components/staged-tab.html',
            '/static/components/staged-tab.html',
            'static/components/staged-tab.html',
            './components/staged-tab.html'
        ];
        
        let componentHtml = null;
        
        for (const path of possiblePaths) {
            try {
                const response = await fetch(path);
                if (response.ok) {
                    componentHtml = await response.text();
                    console.log(`✅ Successfully loaded from: ${path}`);
                    break;
                }
            } catch (e) {
                console.log(`❌ Failed to load from: ${path}`);
            }
        }
        
        if (componentHtml) {
            container.innerHTML = componentHtml;
        } else {
            throw new Error('Could not load static component from any path');
        }
        
        // Initialize staged transactions functionality
        if (typeof loadStagedTransactionsPaginated === 'function') {
            loadStagedTransactionsPaginated();
        }
        
    } catch (error) {
        console.error('Error loading staged transactions tab:', error);
        // Fallback to ensure it works
        container.innerHTML = `
            <div class="staged-transactions-content">
                <div class="flex justify-between align-items-center mb-lg">
                    <h3>📋 Staged Transactions</h3>
                    <div class="gap-md flex">
                        <button class="btn btn-success btn-sm" onclick="approveAllStaged()">✅ Approve All</button>
                        <button class="btn btn-danger btn-sm" onclick="deleteAllStaged()">🗑️ Delete All</button>
                    </div>
                </div>
                <div id="staged-list">Loading staged transactions...</div>
            </div>
        `;
        
        if (typeof loadStagedTransactionsPaginated === 'function') {
            loadStagedTransactionsPaginated();
        }
    }
}

async function loadTransactionsTab(container) {
    try {
        console.log('Loading transactions tab from static component...');
        
        // Try different paths to find your static component
        const possiblePaths = [
            './static/components/transactions-tab.html',
            '/static/components/transactions-tab.html',
            'static/components/transactions-tab.html',
            './components/transactions-tab.html'
        ];
        
        let componentHtml = null;
        
        for (const path of possiblePaths) {
            try {
                const response = await fetch(path);
                if (response.ok) {
                    componentHtml = await response.text();
                    console.log(`✅ Successfully loaded from: ${path}`);
                    break;
                }
            } catch (e) {
                console.log(`❌ Failed to load from: ${path}`);
            }
        }
        
        if (componentHtml) {
            container.innerHTML = componentHtml;
        } else {
            throw new Error('Could not load static component from any path');
        }
        
        // Initialize transactions functionality
        if (typeof loadTransactionsPaginated === 'function') {
            loadTransactionsPaginated();
        }
        
    } catch (error) {
        console.error('Error loading transactions tab:', error);
        // Fallback to ensure it works
        container.innerHTML = `
            <div class="transactions-content">
                <h3>💰 All Transactions</h3>
                <div id="transactions-list">Loading transactions...</div>
            </div>
        `;
        
        if (typeof loadTransactionsPaginated === 'function') {
            loadTransactionsPaginated();
        }
    }
}

async function loadDuplicatesTab(container) {
    try {
        console.log('Loading duplicates tab from static component...');
        
        // Try different paths to find your static component
        const possiblePaths = [
            './static/components/duplicates-tab.html',
            '/static/components/duplicates-tab.html',
            'static/components/duplicates-tab.html',
            './components/duplicates-tab.html'
        ];
        
        let componentHtml = null;
        
        for (const path of possiblePaths) {
            try {
                const response = await fetch(path);
                if (response.ok) {
                    componentHtml = await response.text();
                    console.log(`✅ Successfully loaded from: ${path}`);
                    break;
                }
            } catch (e) {
                console.log(`❌ Failed to load from: ${path}`);
            }
        }
        
        if (componentHtml) {
            container.innerHTML = componentHtml;
        } else {
            throw new Error('Could not load static component from any path');
        }
        
        // Load duplicates if the loader exists
        if (typeof loadDuplicates === 'function') {
            loadDuplicates();
        }
        
    } catch (error) {
        console.error('Error loading duplicates tab:', error);
        // Fallback to ensure it works
        container.innerHTML = `
            <div class="duplicates-content">
                <div class="flex justify-between align-items-center mb-lg">
                    <h3>🔍 Duplicate Manager</h3>
                    <button class="btn btn-warning btn-sm" onclick="scanForDuplicates()">🔄 Scan for Duplicates</button>
                </div>
                <div id="duplicates-list">Loading duplicates...</div>
            </div>
        `;
        
        if (typeof loadDuplicates === 'function') {
            loadDuplicates();
        }
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