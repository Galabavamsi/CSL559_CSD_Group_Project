// The staff login every demo page shares. Plain JavaScript, no build step; load it before the page's own script.
//
// Each page logs in by itself as a seeded demo user. On a laptop the password is the built-in one. A hosted copy
// sets its own DEMO_PASSWORD, so that the staff screens of a site on the internet are not open to anyone: there the
// first refused login asks for the password once, and this browser remembers it.

const BUILT_IN_PASSWORD = "demo"; // the default DEMO_PASSWORD in app/config.py; demo accounts only
const PASSWORD_KEY = "staffPassword";
let asked = null; // the one question per page load, shared by every login that is refused

function staffPassword() {
  try {
    return localStorage.getItem(PASSWORD_KEY) || BUILT_IN_PASSWORD;
  } catch {
    return BUILT_IN_PASSWORD; // storage is blocked (a private window): the built-in password still works locally
  }
}

/** Ask for this site's staff password, once however many logins need it. Resolves to false if nothing was typed. */
function askForPassword() {
  asked ??= Promise.resolve().then(() => {
    const typed = window.prompt("This site has its own staff password. Enter it to use the staff screens:");
    if (!typed) return false;
    try {
      localStorage.setItem(PASSWORD_KEY, typed);
    } catch {
      return false; // nowhere to keep it, so a retry would only send the built-in one again
    }
    return true;
  });
  return asked;
}

/** Log in as a seeded staff user (picker1, manager1, ops, ...) and return the bearer token. */
async function staffLogin(username) {
  const attempt = async () => {
    const res = await fetch("/v1/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password: staffPassword() }),
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok) return data.access_token;
    const error = new Error(data.error?.message || `Could not log in as ${username} (${res.status})`);
    error.code = data.error?.code;
    throw error;
  };
  try {
    return await attempt();
  } catch (error) {
    if (error.code !== "bad_credentials" || !(await askForPassword())) throw error;
    return attempt(); // a wrong password typed here is asked for again after a reload
  }
}
