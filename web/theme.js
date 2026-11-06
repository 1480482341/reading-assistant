const THEMES = ["eye-green", "dark", "light", "eye-warm"];
const THEME_LABELS = { "eye-green": "护眼绿", "dark": "暗黑", "light": "浅色", "eye-warm": "暖黄" };

// Return the active theme, falling back to eye-green for a missing/invalid value.
function currentTheme() {
  const stored = localStorage.getItem("ra-theme");
  return THEMES.indexOf(stored) < 0 ? "eye-green" : stored;
}

// Apply a theme to the document and sync the toggle button label with it.
function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const toggle = document.getElementById("theme-toggle");
  if (toggle) toggle.textContent = THEME_LABELS[theme];
}

// On toggle click, cycle to the next theme and persist it in localStorage['ra-theme'].
const toggle = document.getElementById("theme-toggle");
if (toggle) {
  toggle.addEventListener("click", function () {
    const next = THEMES[(THEMES.indexOf(currentTheme()) + 1) % THEMES.length];
    localStorage.setItem("ra-theme", next);
    applyTheme(next);
  });
}

// Keep the label in sync with the theme set by the inline head script.
applyTheme(currentTheme());
