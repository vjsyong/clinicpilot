/*! Triage boot.js — inline this in <head> before first paint. Restores the
 *  docked chat panel state so there is no flicker. */
try{var v=localStorage.getItem('dock_open');if(v===null||v==='1')document.documentElement.classList.add('dock-open');
var w=parseInt(localStorage.getItem('dock_w')||'',10);if(w>=280)document.documentElement.style.setProperty('--dock-w',Math.min(720,w)+'px');}catch(e){}
