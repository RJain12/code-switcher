# Orbit Courier: benchmark brief

Create a polished, playable single-page browser game using only `index.html`, `style.css`, and `game.js`. No frameworks, remote assets, fonts, or dependencies. The game must work by opening `index.html` directly in a browser.

Premise: You pilot a courier ship through a compact orbital field. Collect glowing energy cells while avoiding moving hazards. Use original vector or CSS artwork. Make it look like a finished arcade game, with a strong visual hierarchy and coherent art direction.

Requirements:

1. Responsive layout that works at desktop and phone widths. Provide a clear title, instructions, score, lives or health, timer, and a prominent start/restart control.
2. Playable movement by arrow keys and WASD. Add visible on-screen controls for touch users. Pause/resume via a visible control and keyboard shortcut.
3. At least three energy cells and two moving hazards. Collecting a cell increases score and respawns it; colliding with a hazard visibly reduces health or lives. Include a win or game-over state and restart.
4. Create a distinct visual game board using SVG or Canvas with animated effects. Add a small sound toggle, with sound optional and off by default. Respect `prefers-reduced-motion`.
5. Save the best score locally and show it on the page. Make buttons keyboard accessible and give controls useful labels.
6. Keep all game logic local. Avoid timers or event handlers that duplicate after restart. The game should continue to work after multiple restarts.

You may choose the detailed rules and visual style. Spend the effort on playability and polish. Test the game in a browser if one is available, and report what you tested. Do not edit this spec.
