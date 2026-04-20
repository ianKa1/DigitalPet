const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');
const fs = require('fs');
const StateManager = require('./stateManager');
const WanderManager = require('./wanderManager');

let mainWindow = null;
let stateManager = null;
let wanderManager = null;

/**
 * Get the path to the position config file
 * @returns {string} Path to position.json in user data directory
 */
function getConfigPath() {
  return path.join(app.getPath('userData'), 'position.json');
}

/**
 * Load saved window position from config file
 * @returns {{x: number, y: number} | null} Saved position or null if not found
 */
function loadPosition() {
  const configPath = getConfigPath();

  try {
    if (fs.existsSync(configPath)) {
      const data = fs.readFileSync(configPath, 'utf8');
      return JSON.parse(data);
    }
  } catch (error) {
    console.error('Failed to load position:', error);
  }

  return null;
}

/**
 * Save window position to config file
 * @param {number} x - X coordinate
 * @param {number} y - Y coordinate
 */
function savePosition(x, y) {
  const configPath = getConfigPath();
  const data = JSON.stringify({ x, y });

  try {
    fs.writeFileSync(configPath, data, 'utf8');
  } catch (error) {
    console.error('Failed to save position:', error);
  }
}

/**
 * Create the main pet window
 */
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 200,
    height: 200,
    transparent: true,
    frame: false,
    alwaysOnTop: true,
    resizable: false,
    skipTaskbar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  // Load the renderer HTML
  mainWindow.loadFile('renderer/index.html');

  // Restore saved position if available
  const savedPosition = loadPosition();
  if (savedPosition) {
    mainWindow.setPosition(savedPosition.x, savedPosition.y);
  }

  // Handle window close
  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// IPC Handlers

// Get the GIF path for the pet (state-aware)
ipcMain.handle('get-gif-path', () => {
  const gifFileName = stateManager ? stateManager.getCurrentGif() : 'idle.gif';
  return path.join(__dirname, 'assets', 'Fluffball', 'animations', gifFileName);
});

// Move window to new position
ipcMain.on('move-window', (event, { x, y }) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  if (win) {
    win.setPosition(Math.round(x), Math.round(y));
  }
});

// Save window position
ipcMain.on('save-position', (event, { x, y }) => {
  savePosition(Math.round(x), Math.round(y));
});

// Handle state change request from renderer
ipcMain.on('change-state', (event, newState) => {
  try {
    const gifFileName = stateManager.setState(newState);
    const fullPath = path.join(__dirname, 'assets', 'Fluffball', 'animations', gifFileName);

    // Send new GIF path back to renderer
    event.reply('state-changed', {
      state: newState,
      gifPath: fullPath
    });
  } catch (error) {
    console.error('State change error:', error);
    // Don't crash - just log the error
  }
});

// Get current state (for initialization or debugging)
ipcMain.handle('get-current-state', () => {
  return {
    state: stateManager.getCurrentState(),
    gif: stateManager.getCurrentGif()
  };
});

// Start wander behavior
ipcMain.on('start-wander', () => {
  if (wanderManager) {
    wanderManager.start();
  }
});

// Stop wander behavior
ipcMain.on('stop-wander', () => {
  if (wanderManager) {
    wanderManager.stop();
  }
});

// Pause wander behavior (e.g., during drag)
ipcMain.on('pause-wander', () => {
  if (wanderManager) {
    wanderManager.pause();
  }
});

// Resume wander behavior
ipcMain.on('resume-wander', () => {
  if (wanderManager) {
    wanderManager.resume();
  }
});

// App lifecycle

app.whenReady().then(() => {
  // Initialize state manager
  stateManager = new StateManager('idle');

  createWindow();

  // Initialize wander manager with state change callback
  wanderManager = new WanderManager(mainWindow, (newState) => {
    if (stateManager) {
      const gifFileName = stateManager.setState(newState);
      const fullPath = path.join(__dirname, 'assets', 'Fluffball', 'animations', gifFileName);

      // Notify renderer of state change
      if (mainWindow) {
        mainWindow.webContents.send('state-changed', {
          state: newState,
          gifPath: fullPath
        });
      }
    }
  });

  // macOS: Re-create window when dock icon clicked
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

// Quit when all windows are closed (except on macOS)
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});
