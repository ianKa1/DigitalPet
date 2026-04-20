const { contextBridge, ipcRenderer } = require('electron');

/**
 * Expose protected methods to the renderer process via contextBridge.
 * This ensures security by not exposing the full ipcRenderer or Node.js APIs.
 */
contextBridge.exposeInMainWorld('electronAPI', {
  /**
   * Get the file path to the pet GIF
   * @returns {Promise<string>} Path to the GIF file
   */
  getGifPath: () => ipcRenderer.invoke('get-gif-path'),

  /**
   * Move the window to a new position
   * @param {number} x - X coordinate
   * @param {number} y - Y coordinate
   */
  moveWindow: (x, y) => ipcRenderer.send('move-window', { x, y }),

  /**
   * Save the current window position for persistence
   * @param {number} x - X coordinate
   * @param {number} y - Y coordinate
   */
  savePosition: (x, y) => ipcRenderer.send('save-position', { x, y }),

  /**
   * Change pet state
   * @param {string} state - New state name ('idle', 'dragged', etc.)
   */
  changeState: (state) => ipcRenderer.send('change-state', state),

  /**
   * Listen for state changes from main process
   * @param {function} callback - Called with {state, gifPath} when state changes
   */
  onStateChanged: (callback) => ipcRenderer.on('state-changed', (event, data) => callback(data)),

  /**
   * Get current state
   * @returns {Promise<{state: string, gif: string}>} Current state and GIF filename
   */
  getCurrentState: () => ipcRenderer.invoke('get-current-state'),

  /**
   * Start autonomous wander behavior
   */
  startWander: () => ipcRenderer.send('start-wander'),

  /**
   * Stop autonomous wander behavior
   */
  stopWander: () => ipcRenderer.send('stop-wander'),

  /**
   * Pause wander behavior temporarily
   */
  pauseWander: () => ipcRenderer.send('pause-wander'),

  /**
   * Resume wander behavior after pause
   */
  resumeWander: () => ipcRenderer.send('resume-wander')
});
