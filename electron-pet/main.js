const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');
const fs = require('fs');

let mainWindow = null;

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

// Get the GIF path for the pet
ipcMain.handle('get-gif-path', () => {
  return path.join(__dirname, 'assets', 'Fluffball', 'animations', 'idle.gif');
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

// App lifecycle

app.whenReady().then(() => {
  createWindow();

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
