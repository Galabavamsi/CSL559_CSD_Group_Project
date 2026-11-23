"""Record the demo: drive the real backend through the phone app and the hub's pages, saving screenshots and video.

What it shows, in order, is one lot of tomatoes going from a farm to a customer's order:

    farmer   signs in with an emailed code, registers a farm, lists 40 kg of tomatoes, gets a hub and a drop slot
    hub      weighs and grades the lot, packs it into units and puts them away (through the API: there is no
             intake screen yet), and the stock appears on the hub's desk
    customer signs in, picks a delivery area, finds the tomatoes in the shop, holds a cart and pays
    hub      a picker claims the order, scans it and packs it
    customer sees the order move to Packed

Everything above runs on the real API. Delivery is not built yet, so nothing is recorded for it beyond the delivery
agent's placeholder screen. A second, short pass shows the app on its built-in demo data, which is what the screens
for orders, tracking and rescue deals look like before the backend has them.

It needs, already running (scripts/record_demo.sh starts them on the dev server):
    the API at API_URL, on an empty database, with EMAIL_BACKEND=log and its log in API_LOG
    the phone app's web build made with EXPO_PUBLIC_API_URL=API_URL at APP_URL, and the mock build at MOCK_URL
and Playwright with Chromium. The browser runs with web security off, because the web build and the API are on
different ports here; a phone has no such rule.

Usage:  python scripts/record_demo.py <output directory>
"""
import json
import os
import pathlib
import re
import sys
import time
import urllib.request

from playwright.sync_api import Page, sync_playwright

API_URL = os.getenv("API_URL", "http://127.0.0.1:8000")
APP_URL = os.getenv("APP_URL", "http://127.0.0.1:8090")
MOCK_URL = os.getenv("MOCK_URL", "http://127.0.0.1:8091")
API_LOG = os.getenv("API_LOG", "/tmp/f2h-api.log")
OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/f2h-demo")
SHOTS, VIDEO = OUT / "shots", OUT / "video"
PHONE = {"viewport": {"width": 390, "height": 844}, "device_scale_factor": 2, "color_scheme": "light",
         "locale": "en-IN", "timezone_id": "Asia/Kolkata"}
DESK = {"viewport": {"width": 1280, "height": 800}, "device_scale_factor": 1.5, "color_scheme": "light",
        "locale": "en-IN", "timezone_id": "Asia/Kolkata"}
FARM = {"latitude": 12.80, "longitude": 77.59, "accuracy": 18}       # 19 km south of the Central hub
FARMER, CUSTOMER = "ravi.farmer@example.com", "asha.customer@example.com"
PAUSE = 1.2                                                          # seconds a viewer gets to read a screen

captions: dict[str, list[tuple[float, str]]] = {}                    # clip -> [(seconds into the clip, caption)]
started: dict[str, float] = {}


def say(clip: str, text: str) -> None:
    """Note what is happening now, for the caption beside the video."""
    captions.setdefault(clip, []).append((round(time.monotonic() - started[clip], 2), text))
    print(f"  [{clip}] {text}", flush=True)


def shot(page: Page, name: str) -> None:
    page.wait_for_timeout(500)
    page.screenshot(path=str(SHOTS / f"{name}.png"))


def api(method: str, path: str, body: dict | None = None, token: str | None = None) -> dict | list:
    request = urllib.request.Request(API_URL + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json",
                                              **({"Authorization": f"Bearer {token}"} if token else {})})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read() or b"{}")


def code_for(email: str, after: int) -> str:
    """The newest sign-in code the API "sent" to this address: with EMAIL_BACKEND=log it is in the API's log."""
    for _ in range(60):
        text = pathlib.Path(API_LOG).read_text(errors="ignore")[after:]
        found = re.findall(rf"To: {re.escape(email)} \| (\d{{6}}) is your", text)
        if found:
            return found[-1]
        time.sleep(0.25)
    raise RuntimeError(f"no sign-in code for {email} in {API_LOG}")


def sign_in(page: Page, clip: str, base: str, email: str, role: str, real: bool = True) -> None:
    page.goto(base + "/")
    page.get_by_text("Send sign-in code").wait_for()
    page.wait_for_timeout(1000)
    if role != "Customer":
        page.get_by_role("radio", name=role).click()
    say(clip, f"Sign in as a {role.lower()}: an email address, no password")
    page.locator("input").first.fill(email)
    page.wait_for_timeout(PAUSE * 1000)
    mark = len(pathlib.Path(API_LOG).read_text(errors="ignore")) if real else 0
    page.get_by_text("Send sign-in code").click()
    page.get_by_text("Enter your code").wait_for()
    code = code_for(email, mark) if real else "123456"
    say(clip, "A six-digit code arrives by email and is typed in" if real else "On demo data the code is 123456")
    page.wait_for_timeout(PAUSE * 1000)
    page.get_by_label("6-digit sign-in code").fill(code)
    page.wait_for_timeout(600)
    verify = page.get_by_text("Verify and continue")
    if verify.count() and verify.first.is_enabled():
        verify.first.click()


def new_phone(browser, clip: str, **extra):
    context = browser.new_context(**PHONE, record_video_dir=str(VIDEO / clip), record_video_size=PHONE["viewport"],
                                  **extra)
    started[clip] = time.monotonic()
    return context, context.new_page()


def finish(context, clip: str) -> None:
    page = context.pages[0]
    path = page.video.path()
    context.close()
    pathlib.Path(path).rename(VIDEO / f"{clip}.webm")
    (VIDEO / clip).rmdir()


# --------------------------------------------------------------------------- the farmer

def farmer_lists(browser) -> int:
    clip = "1-farmer"
    context, page = new_phone(browser, clip, geolocation=FARM, permissions=["geolocation"])
    sign_in(page, clip, APP_URL, FARMER, "Farmer")
    page.get_by_text("Add your farm first").wait_for()
    shot(page, "farmer-home-empty")
    say(clip, "A new farmer has no farm yet")
    page.wait_for_timeout(PAUSE * 1000)

    page.get_by_text("Add farm").first.click()
    page.get_by_text("Farm name").wait_for()
    page.locator("input").first.fill("Green Acres")
    say(clip, "The farm is registered where the farmer stands; a rough GPS fix is refused")
    page.get_by_text("Read my location").click()
    page.get_by_text("Read my location again").wait_for()
    shot(page, "farmer-add-farm")
    page.wait_for_timeout(PAUSE * 1000)
    page.get_by_text("Save farm").click()
    page.get_by_text("Green Acres").first.wait_for()
    page.wait_for_timeout(PAUSE * 1000)
    shot(page, "farmer-home-farm")

    say(clip, "Listing produce: 40 kg of tomatoes, harvested today")
    page.get_by_role("button", name="List produce").first.click()
    page.get_by_text("What are you listing?").wait_for()
    page.get_by_text("Tomato", exact=True).first.click()
    inputs = page.locator("input")
    inputs.nth(0).fill("40")
    inputs.nth(1).fill("18")
    page.wait_for_timeout(PAUSE * 1000)
    shot(page, "farmer-list-produce")
    page.get_by_role("button", name="List produce").last.click()
    page.get_by_text("Where and when to drop it").wait_for()
    say(clip, "The nearest hub with room is chosen (PostGIS), with a morning drop slot")
    shot(page, "farmer-listing-made")
    page.wait_for_timeout(PAUSE * 2500)
    page.get_by_text("Back to my listings").click()
    page.get_by_text("My listings").wait_for()
    page.wait_for_timeout(PAUSE * 1500)
    shot(page, "farmer-listings")
    finish(context, clip)
    staff = api("POST", "/v1/auth/login", {"username": "receiver1", "password": "demo"})["access_token"]
    return api("GET", "/v1/stores/1/expected-drops", token=staff)[0]["listing_id"]


def farmer_sees_result(browser) -> None:
    clip = "5-farmer-result"
    context, page = new_phone(browser, clip)
    sign_in(page, clip, APP_URL, FARMER, "Farmer")
    page.get_by_text("My listings").wait_for()
    say(clip, "Back on the farmer's phone: the hub's grade, and the kilograms accepted and rejected")
    page.get_by_text("Accepted").first.wait_for()
    page.get_by_text("Accepted").first.scroll_into_view_if_needed()
    page.wait_for_timeout(PAUSE * 2500)
    shot(page, "farmer-listing-graded")
    finish(context, clip)


# --------------------------------------------------------------------------- the hub

def hub_takes_in(browser, listing_id: int) -> None:
    clip = "2-hub-intake"
    context = browser.new_context(**DESK, record_video_dir=str(VIDEO / clip), record_video_size=DESK["viewport"])
    started[clip] = time.monotonic()
    page = context.new_page()
    page.goto(API_URL + "/")
    page.get_by_text("Check delivery").first.wait_for()
    page.wait_for_timeout(1500)
    say(clip, "The hub's desk before the lot arrives: no tomatoes in stock")
    shot(page, "hub-desk-before")
    page.wait_for_timeout(PAUSE * 1500)

    staff = api("POST", "/v1/auth/login", {"username": "receiver1", "password": "demo"})["access_token"]
    say(clip, "The receiver weighs and grades the lot: 39.5 kg arrived, 1.5 kg rejected, grade A (no screen yet: API)")
    intake = api("POST", f"/v1/listings/{listing_id}/intake", {"received_kg": 39.5, "rejected_kg": 1.5, "grade": "A",
                                                             "remarks": "firm, even colour"}, staff)
    receipt = intake["receipt"]["receipt_id"]
    (OUT / "intake.json").write_text(json.dumps(intake, indent=1))
    page.wait_for_timeout(PAUSE * 1500)
    say(clip, f"38 kg accepted becomes {intake['packed'][0]['units']} packs of 500 g, put away bin by bin")
    for task in api("GET", f"/v1/goods-receipts/{receipt}/putaway-tasks", token=staff):
        api("POST", f"/v1/goods-receipts/{receipt}/putaway",
            {"sku_id": task["sku_id"], "batch_no": task["batch_no"], "bin_code": task["bin_code"], "qty": task["qty"]}, staff)
    api("POST", f"/v1/goods-receipts/{receipt}/close", token=staff)
    page.reload()
    page.get_by_text("Tomato, 500 g").first.wait_for()
    page.get_by_text("Tomato, 500 g").first.scroll_into_view_if_needed()
    page.wait_for_timeout(800)
    say(clip, "The packs are on the shelf and on sale the moment they are put away")
    shot(page, "hub-desk-after")
    page.wait_for_timeout(PAUSE * 2500)
    path = page.video.path()
    context.close()
    pathlib.Path(path).rename(VIDEO / f"{clip}.webm")
    (VIDEO / clip).rmdir()


def hub_picks(browser) -> None:
    clip = "4-hub-picking"
    context, page = new_phone(browser, clip)
    page.goto(API_URL + "/picker.html?store=1")
    page.locator("#next").wait_for()
    page.wait_for_timeout(1200)
    say(clip, "At the hub, a picker's phone: claim the next paid order")
    shot(page, "hub-picker-idle")
    page.locator("#next").click()
    page.locator("#what").wait_for()
    page.wait_for_timeout(PAUSE * 1500)
    say(clip, "Each line names the bin; the oldest batch is picked first, and every unit is scanned")
    shot(page, "hub-picker-line")
    for _ in range(12):
        if page.locator("#pack-btn").is_visible():
            break
        button = page.locator("#scan-all") if page.locator("#scan-all").is_visible() else page.locator("#scan-one")
        button.click()
        page.wait_for_timeout(900)
    page.locator("#pack-btn").wait_for()
    say(clip, "Packed into a crate slot: only now does the stock on hand go down")
    shot(page, "hub-picker-pack")
    page.wait_for_timeout(PAUSE * 1000)
    page.locator("#pack-btn").click()
    page.wait_for_timeout(PAUSE * 2000)
    shot(page, "hub-picker-packed")
    finish(context, clip)


def hub_screens(browser) -> None:
    """Stills of the hub's other screens, for the handbook."""
    context = browser.new_context(**DESK)
    page = context.new_page()
    for name, path, wait in (("hub-ops-dashboard", "/ops.html", 3500), ("hub-network-map", "/network.html", 6000),
                             ("hub-desk", "/", 2500), ("api-docs", "/docs", 3000)):
        page.goto(API_URL + path)
        page.wait_for_timeout(wait)
        page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=name != "hub-network-map")
    context.close()


# --------------------------------------------------------------------------- the customer

def customer_orders(browser) -> None:
    clip = "3-customer"
    context, page = new_phone(browser, clip)
    sign_in(page, clip, APP_URL, CUSTOMER, "Customer")
    page.get_by_text("Delivery location").first.wait_for()
    shot(page, "customer-verify-done")
    say(clip, "Where to deliver: the hub whose zone covers the address serves it")
    page.get_by_role("radio", name="Bangalore").click()
    page.get_by_text("MG Road").first.click()
    page.get_by_text("Deliver here").wait_for()
    page.wait_for_timeout(PAUSE * 1500)
    shot(page, "customer-location")
    page.get_by_text("Deliver here").click()

    page.get_by_label(re.compile(r"^Add Tomato")).first.wait_for()
    page.wait_for_timeout(1500)
    shot(page, "customer-home-real")
    say(clip, "The shop shows only what that hub can deliver now, including the farmer's tomatoes")
    add = page.get_by_label(re.compile(r"^Add Tomato")).first
    add.scroll_into_view_if_needed()
    page.wait_for_timeout(PAUSE * 1500)
    shot(page, "customer-home-tomato")
    add.click()
    page.wait_for_timeout(700)
    more = page.get_by_label(re.compile(r"(one more|Add one|Increase|more Tomato)", re.I))
    if more.count():
        more.first.click()
    page.wait_for_timeout(PAUSE * 1000)
    shot(page, "customer-home-added")
    page.get_by_label(re.compile(r"^View cart")).click()
    page.get_by_text(re.compile(r"^Hold my items")).wait_for()
    say(clip, "Holding the cart sets the items aside at the hub for 10 minutes: whole cart or nothing")
    shot(page, "customer-cart")
    page.wait_for_timeout(PAUSE * 1500)
    page.get_by_text(re.compile(r"^Hold my items")).click()
    page.get_by_text("Your items are held").wait_for()
    page.locator("input").first.fill("12 Lake Road, MG Road")
    page.wait_for_timeout(PAUSE * 1500)
    shot(page, "customer-checkout")
    say(clip, "Paying confirms the order; an unpaid hold expires and gives the stock back")
    page.get_by_text(re.compile(r"^Pay ")).click()
    page.get_by_text("Progress").wait_for()
    page.wait_for_timeout(PAUSE * 2000)
    shot(page, "customer-order-confirmed")
    say(clip, "The order is confirmed and waits for a picker at the hub")
    page.wait_for_timeout(PAUSE * 1500)
    context.storage_state(path=str(OUT / "customer-state.json"))
    finish(context, clip)


def customer_sees_packed(browser) -> None:
    clip = "6-customer-packed"
    context, page = new_phone(browser, clip, storage_state=str(OUT / "customer-state.json"))
    page.goto(APP_URL + "/")
    page.get_by_text("Orders").first.wait_for()
    page.get_by_text("Orders").first.click()
    page.wait_for_timeout(1500)
    say(clip, "Back on the customer's phone, the order now reads Packed")
    shot(page, "customer-orders")
    page.get_by_text(re.compile(r"^Order ")).first.click()
    page.get_by_text("Progress").wait_for()
    page.wait_for_timeout(PAUSE * 2500)
    shot(page, "customer-order-packed")
    say(clip, "Pooling, the delivery agent and the door-step code come next: not built yet")
    page.wait_for_timeout(PAUSE * 2000)
    finish(context, clip)


# --------------------------------------------------------------------------- demo data: what is still to come

def on_demo_data(browser) -> None:
    clip = "7-demo-data"
    context, page = new_phone(browser, clip)
    sign_in(page, clip, MOCK_URL, "demo@example.com", "Customer", real=False)
    page.get_by_text("Delivery location").first.wait_for()
    page.get_by_text("Supela").first.click()
    page.get_by_text("Deliver here").click()
    page.get_by_text("Rescue deals").wait_for()
    page.wait_for_timeout(1500)
    say(clip, "DEMO DATA from here: the screens for what the backend does not have yet")
    shot(page, "mock-home")
    page.wait_for_timeout(PAUSE * 1500)
    page.get_by_label(re.compile(r"^Add Brinjal")).first.click()
    page.get_by_label(re.compile(r"^Add Sweet corn")).first.click()
    page.wait_for_timeout(PAUSE * 800)
    page.get_by_text("Tomato", exact=True).first.click()
    page.wait_for_timeout(PAUSE * 1500)
    shot(page, "mock-product")
    page.go_back()
    page.get_by_label(re.compile(r"^View cart")).click()
    page.get_by_text(re.compile(r"^Hold my items")).click()
    page.get_by_text("Your items are held").wait_for()
    page.locator("input").first.fill("12 Lake Road")
    shot(page, "mock-checkout")
    page.get_by_text(re.compile(r"^Pay ")).click()
    page.get_by_text("Delivery code").wait_for()
    say(clip, "Order tracking, with the code the customer reads to the delivery agent at the door")
    page.wait_for_timeout(PAUSE * 2000)
    shot(page, "mock-order-placed")
    page.get_by_text("Out for delivery").first.wait_for()
    page.wait_for_timeout(28_000)                                       # the mock moves an order on every few seconds
    shot(page, "mock-order-moving")
    page.wait_for_timeout(PAUSE * 1500)
    finish(context, clip)

    context = browser.new_context(**PHONE)                              # stills only: the agent's placeholder
    page = context.new_page()
    sign_in(page, "x", MOCK_URL, "kiran@example.com", "Delivery", real=False)
    page.wait_for_timeout(2500)
    page.screenshot(path=str(SHOTS / "agent-placeholder.png"))
    context.close()


def main() -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    VIDEO.mkdir(parents=True, exist_ok=True)
    started["x"] = time.monotonic()
    only = set(sys.argv[2:])
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=["--disable-web-security", "--use-fake-ui-for-media-stream"])
        if not only or "real" in only:
            listing_id = farmer_lists(browser)
            hub_takes_in(browser, listing_id)
            customer_orders(browser)
            hub_picks(browser)
            farmer_sees_result(browser)
            customer_sees_packed(browser)
            hub_screens(browser)
        if not only or "mock" in only:
            on_demo_data(browser)
        browser.close()
    (OUT / "captions.json").write_text(json.dumps(captions, indent=1))
    print("clips:", sorted(p.name for p in VIDEO.glob("*.webm")))
    print("shots:", len(list(SHOTS.glob("*.png"))))


if __name__ == "__main__":
    main()
