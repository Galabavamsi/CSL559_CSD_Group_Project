// The staff login every demo page shares. Plain JavaScript, no build step; load it before the page's own script.
//
// Each page logs in by itself as a seeded demo user. On a laptop the password is the built-in one. A hosted copy
// sets its own DEMO_PASSWORD, so that the staff screens of a site on the internet are not open to anyone: there the
// first refused login shows a sign-in box on the page, and this browser remembers what was typed.
//
// Any number of people may use the staff pages at the same time, each in their own browser; logging in on one does
// not end a session on another. The box is drawn by the page itself and not with window.prompt, which browsers
// opened from inside other apps (a link tapped in WhatsApp or Gmail) often suppress. A password that is refused is
// forgotten and asked for again at once, instead of being sent again with every refresh.

const BUILT_IN_PASSWORD = "demo"; // the default DEMO_PASSWORD in app/config.py; demo accounts only
const PASSWORD_KEY = "staffPassword";
let typedPassword = null; // what was typed in this page load, for a browser that will not keep it
let asking = null; // the sign-in box on screen, shared by every login that is refused while it is up
let declined = false; // the box was closed without a password: stop asking until the page is reloaded

function staffPassword() {
  if (typedPassword) return typedPassword;
  try {
    return localStorage.getItem(PASSWORD_KEY) || BUILT_IN_PASSWORD;
  } catch {
    return BUILT_IN_PASSWORD; // storage is blocked (some private windows): the built-in password still works locally
  }
}

function rememberPassword(password) {
  typedPassword = password;
  try {
    localStorage.setItem(PASSWORD_KEY, password);
  } catch {
    // nowhere to keep it: it lasts until this page is closed
  }
}

function forgetPassword() {
  typedPassword = null;
  try {
    localStorage.removeItem(PASSWORD_KEY);
  } catch {
    // nothing was kept
  }
}

/** Draw the sign-in box and resolve with what was typed, or null if it was closed. One box at a time. */
function askForPassword(refused) {
  asking ??= new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-labelledby", "staff-sign-in-title");
    overlay.style.cssText =
      "position:fixed;inset:0;z-index:2147483647;display:flex;align-items:center;justify-content:center;" +
      "padding:16px;background:rgba(20,24,20,0.55);font:16px/1.4 system-ui,-apple-system,'Segoe UI',sans-serif;";
    overlay.innerHTML = `
      <form style="width:100%;max-width:360px;background:#fff;color:#1f2a1f;border-radius:14px;padding:20px;
                   box-shadow:0 12px 40px rgba(0,0,0,0.3);">
        <h2 id="staff-sign-in-title" style="margin:0 0 6px;font-size:20px;">Staff sign-in</h2>
        <p style="margin:0 0 14px;color:#555;font-size:14px;">This site has its own password for the staff screens.
          Type it once; this browser remembers it. Other people can sign in on their own devices at the same time.</p>
        <label style="display:block;font-size:14px;margin-bottom:4px;" for="staff-sign-in-password">Staff password</label>
        <input id="staff-sign-in-password" type="password" autocomplete="current-password" autocapitalize="off"
               autocorrect="off" spellcheck="false" required
               style="box-sizing:border-box;width:100%;padding:10px 12px;font-size:16px;border:1px solid #888;
                      border-radius:8px;">
        <label style="display:flex;align-items:center;gap:6px;margin:8px 0 0;font-size:14px;color:#555;">
          <input type="checkbox" data-show> Show the password</label>
        <p data-error role="alert" style="min-height:20px;margin:8px 0;font-size:14px;color:#b3261e;"></p>
        <div style="display:flex;gap:8px;justify-content:flex-end;">
          <button type="button" data-cancel style="padding:10px 14px;font-size:15px;border:1px solid #888;
                  border-radius:8px;background:#fff;color:#1f2a1f;">Cancel</button>
          <button type="submit" style="padding:10px 18px;font-size:15px;border:0;border-radius:8px;
                  background:#2e7d32;color:#fff;font-weight:600;">Sign in</button>
        </div>
      </form>`;
    const form = overlay.querySelector("form");
    const input = overlay.querySelector("input[type=password]");
    overlay.querySelector("[data-error]").textContent = refused
      ? "That password was not accepted. Check it and try again: capitals count."
      : "";
    overlay.querySelector("[data-show]").addEventListener("change", (event) => {
      input.type = event.target.checked ? "text" : "password";
    });
    const close = (password) => {
      overlay.remove();
      asking = null;
      resolve(password);
    };
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const password = input.value.trim();
      if (password) close(password);
    });
    overlay.querySelector("[data-cancel]").addEventListener("click", () => close(null));
    overlay.addEventListener("keydown", (event) => {
      if (event.key === "Escape") close(null);
    });
    const show = () => {
      document.body.appendChild(overlay);
      input.focus();
    };
    if (document.body) show();
    else document.addEventListener("DOMContentLoaded", show, { once: true });
  });
  return asking;
}

/** Log in as a seeded staff user (picker1, manager1, ops, ...) and return the bearer token. */
async function staffLogin(username) {
  for (;;) {
    const password = staffPassword();
    const res = await fetch("/v1/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok) return data.access_token;
    const error = new Error(data.error?.message || `Could not log in as ${username} (${res.status})`);
    error.code = data.error?.code;
    if (error.code !== "bad_credentials") throw error;
    if (password !== staffPassword()) continue; // someone typed a new password while this one was on its way
    if (declined) throw error;
    const refused = password !== BUILT_IN_PASSWORD; // a password that was typed, and is wrong
    if (refused) forgetPassword();
    const typed = await askForPassword(refused);
    if (!typed) {
      declined = true;
      error.message = "Staff sign-in was cancelled. Reload the page to sign in.";
      throw error;
    }
    if (typed !== staffPassword()) rememberPassword(typed);
  }
}
