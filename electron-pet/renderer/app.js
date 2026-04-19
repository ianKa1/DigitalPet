/**
 * Desktop Pet Renderer
 * Handles GIF loading and drag functionality
 */

// Drag state
let isDragging = false;
let mouseOffsetX = 0;
let mouseOffsetY = 0;

// DOM Elements
const petContainer = document.getElementById('pet-container');
const petGif = document.getElementById('pet-gif');

/**
 * Load the pet GIF on startup
 */
async function loadGif() {
  try {
    const gifPath = await window.electronAPI.getGifPath();
    petGif.src = gifPath;
  } catch (error) {
    console.error('Failed to load GIF:', error);
  }
}

/**
 * Handle mouse down - start drag operation
 * @param {MouseEvent} event
 */
function handleMouseDown(event) {
  isDragging = true;

  // Record mouse position relative to window top-left
  // This prevents the pet from "jumping" when drag starts
  mouseOffsetX = event.clientX;
  mouseOffsetY = event.clientY;

  // Update cursor
  petContainer.classList.add('dragging');
}

/**
 * Handle mouse move - move window during drag
 * @param {MouseEvent} event
 */
function handleMouseMove(event) {
  if (!isDragging) return;

  // Calculate new window position
  // screenX/Y gives absolute screen coordinates
  // Subtract offset to maintain relative mouse position
  const newX = event.screenX - mouseOffsetX;
  const newY = event.screenY - mouseOffsetY;

  // Move the window
  window.electronAPI.moveWindow(newX, newY);
}

/**
 * Handle mouse up - end drag operation
 * @param {MouseEvent} event
 */
function handleMouseUp(event) {
  if (!isDragging) return;

  isDragging = false;

  // Update cursor
  petContainer.classList.remove('dragging');

  // Save final position
  const finalX = event.screenX - mouseOffsetX;
  const finalY = event.screenY - mouseOffsetY;
  window.electronAPI.savePosition(finalX, finalY);
}

// Event Listeners

// Load GIF when page loads
document.addEventListener('DOMContentLoaded', loadGif);

// Drag events on container
petContainer.addEventListener('mousedown', handleMouseDown);

// Use document-level listeners for move/up
// This ensures smooth dragging even if mouse moves quickly
document.addEventListener('mousemove', handleMouseMove);
document.addEventListener('mouseup', handleMouseUp);

// Prevent context menu (right-click) for cleaner UX
document.addEventListener('contextmenu', (event) => {
  event.preventDefault();
});
