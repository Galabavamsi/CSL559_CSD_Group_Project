# Showing the app on a phone

A run sheet for showing JustInTimeFarm2Home from phones alone, against the staging copy on AWS: what to install,
what to tap, what to say, and what is not built. It takes about eight minutes. `docs/DEMO_SCRIPT.md` is the older
script for the hub's desk screens on a laptop.

## Before you start

- **Install the app.** `scripts/build_apk.sh` builds an Android app (an APK) with the staging address built in.
  Open the download link on the phone, allow the browser to install apps when Android asks, and open **Farm2Home**.
  It needs no laptop and no Expo Go.
- **Use mobile data.** The campus Wi-Fi blocks the staging address (a new domain its filter has not classified);
  the app then says "No connection". Mobile data works.
- **Two email addresses**, one for the customer and one for the delivery agent. Sign-in is a six-digit code sent
  to the address. A Gmail address with `+agent` before the `@` is a second address that arrives in the same inbox.
- **Two phones if you can**: the customer on one, the agent on the other. With one phone you sign out and in
  between the two, and each sign-in is one more code.
- Staging keeps what earlier runs did. Nothing needs resetting.

## What staging does for you

A hub sells what farms bring it, pickers pick, and agents deliver. A demo by one person has no farmer, no picker
and no time to wait, so staging has four settings on that production would not:

| Setting | What it does | What you would otherwise need |
| --- | --- | --- |
| Demo farms | Every half hour, any hub nearly out of an item gets a lot from a demo farm, through the hub's ordinary intake | A farmer listing and a receiver weighing |
| Demo hub | An order no picker starts within 45 seconds is picked and packed by the app, as a picker would | Someone at the picker's screen |
| Short wait | A lone packed order leaves after half a minute, not ten | Three more orders, or ten minutes |
| Agents sign up | Anyone may sign in as a delivery agent and choose a hub | The platform team making the account |

Say so when you show it: the lots, the picking and the trip are real records made by the real code paths; what
is simulated is the people.

## The run

**1. The agent goes on duty** (agent's phone, or first on a single phone).
Sign in, choosing **Delivery**. Pick the city **Bhilai** and the hub **BH-04 IIT Bhilai**, then **Go on duty**.
*Say:* agents belong to a hub; the one free longest gets the next trip.
On one phone: open the account screen and sign out. The agent stays on duty.

**2. The customer chooses where to deliver** (customer's phone).
Sign in as a customer. On **Delivery location** choose **Bhilai**, then **Kumhari**: "Not in our delivery area
yet", and **Request delivery here**. Then choose **IIT Bhilai**: "We deliver", from BH-04.
*Say:* each hub serves the H3 cells nearer to it than to any other, within 3 km. A request from outside every
zone is counted when the next hub is chosen.

**3. The shop.**
Every card has a photograph, a grade, when it was picked, a use-by date and, on the product's page, the farm.
Spinach is marked down: its batch is in its last day.
*Say:* the shop shows the batch the next order would be picked from, oldest first; a batch in its last day is
sold 30% cheaper so it is eaten and not thrown away.

**4. Hold and pay.**
Add three or four items, including spinach. **View cart**, **Hold my items**: a ten-minute clock starts.
Type a room and hostel, **Pay**.
*Say:* the hold takes the units off sale for everyone else, whole cart or nothing; payment is a stand-in and no
money moves. The total on the button is the hub's own bill, and a price that rose in between is refused, not
charged.

**5. The order moves by itself.**
Stay on the order's screen. Within about a minute and a half it goes **Confirmed, Packed, Pooled**, and four
digits appear under **Delivery code**.
*Say:* the hub picked oldest batch first and packed the bag into a crate slot; with an agent free and no
neighbour ordering in the same half minute, the bag got a trip to itself.

**6. The agent collects and delivers** (agent's phone, or sign in again as the agent).
The trip is there: **Collect 1 bag**, the crate slot in large type. Tap **Bag checked**: the customer's order
turns **Out for delivery**. On the stop, type the customer's four digits and **Hand over**.
Try a wrong code first if you like: it is counted, and five lock the hand-over.
*Say:* the code proves the two met; it is worked out from the order's number and a secret, and is stored nowhere.

**7. Delivered** (customer's phone).
The order reads **Delivered**, with the time of every step.

**If you have a second order:** place two from different areas of one hub before the agent goes on duty, and the
agent's trip has two stops, in the shorter order.

## What to say is not built

- A map, the agent's position, and a time of arrival. Distances are straight lines times 1.7 for now.
- Real payment.
- What the hub does with a bag that comes back.
- Hubs asking farms for what they expect to sell.

## If something goes wrong

| You see | Likely cause | Do |
| --- | --- | --- |
| "No connection" | The phone is on Wi-Fi | Switch to mobile data |
| No code arrives | More than one a minute, or too many in an hour, for that address | Wait a minute; check spam |
| The shop is empty | The hub's stock ran out between two rounds of the demo farms | Wait for the half hour, or choose another area |
| The order stays at Packed | No agent is on duty at that hub | Go on duty as the agent, at the hub the order came from |
| The agent sees no trip | The order is from another hub | The customer's location screen names the hub; the agent must choose the same one |
