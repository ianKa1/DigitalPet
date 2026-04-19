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
  savePosition: (x, y) => ipcRenderer.send('save-position', { x, y })
});
