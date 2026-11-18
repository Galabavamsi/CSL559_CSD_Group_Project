// Helpers shared by the demo pages (index.html and picker.html). Plain JavaScript, no build step.

const $ = (id) => document.getElementById(id);

// Staff logins (HLD 10). Each station logs in as a seeded demo user; the customer station needs no login.
const DEMO_PASSWORD = "demo"; // same as DEMO_PASSWORD in app/config.py; demo accounts only
const tokens = {}; // username -> promise of a bearer token, so calls made together share one login

function tokenFor(user) {
  tokens[user] ??= api("POST", "/v1/auth/login", { username: user, password: DEMO_PASSWORD })
    .then((session) => session.access_token)
    .catch((error) => {
      delete tokens[user]; // let the next call try to log in again
      throw error;
    });
  return tokens[user];
}

/** Call the API. Pass `user` to send that staff member's token; leave it out for the open customer endpoints. */
async function api(method, path, body, user, isRetry = false) {
  const headers = body ? { "Content-Type": "application/json" } : {};
  if (user) headers.Authorization = `Bearer ${await tokenFor(user)}`;
  const res = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  if (res.status === 401 && user && !isRetry) {
    delete tokens[user]; // the token expired: log in again and retry once
    return api(method, path, body, user, true);
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const error = new Error(data.error?.message || `Request failed (${res.status})`);
    error.code = data.error?.code;
    error.details = data.error?.details;
    throw error;
  }
  return data;
}

function el(tag, props = {}, ...children) {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children);
  return node;
}

function say(target, text, kind) {
  target.textContent = text;
  target.className = "message" + (kind ? ` is-${kind}` : "");
}

/** Run an action; show any failure in the station's message line. */
function guarded(messageEl, action) {
  return async (...args) => {
    try {
      await action(...args);
    } catch (error) {
      say(messageEl, error.message, "bad");
    }
  };
}

/** S-01 -> S-02, so each tote of a batch gets its own crate slot without typing. */
function nextSlot(slot) {
  const match = slot.match(/^(.*?)(\d+)$/);
  return match ? match[1] + String(Number(match[2]) + 1).padStart(match[2].length, "0") : slot;
}
