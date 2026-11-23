# Design of what is left

*Written 24 November 2026, nine days before the demo. There is no earlier design document to follow for these
parts, so this one makes the decisions and gives the reason for each. What is already built is described in
`docs/handbook/` and `docs/journal/`; this document covers what is not.*

Every decision below has the same four parts: **what** we will do, **why**, what was **considered and not taken**,
and what it **costs or risks**. A fact from outside the project has a link under Sources at the end. Where a fact
could not be confirmed, the text says so.

## 0. What the design has to respect

| Constraint | Consequence |
| --- | --- |
| Nine days, one developer | Prefer rules that fit in a page and can be tested, over rules that are optimal |
| The demo is live, in Bhilai, on a phone | Nothing in the demo path may depend on a service that can fail on the day without a fallback |
| The app runs in Expo Go until there is an installable build | No library that needs its own native code |
| One copy of the API runs | Timed work stays in the process; anything that must not run twice is guarded in the database |
| The showcase is the AWS architecture, paid from credits | When two services are equal, the one on AWS is chosen |
| Stock is whole units, held per hub and item | Nothing here may weaken the hold: no design that prices or promises below that level without the same guard |

## 1. Maps and location

### 1.1 What is used today

- **The phone app has no map.** A customer's location is the phone's GPS fix or an area picked from a list. A
  farm's location is a GPS fix good to 50 m.
- **The hub's network map** is a web page drawn with Leaflet on OpenStreetMap's public tiles.
- **Every distance is computed by us:** PostGIS for "nearest hub" and "hubs within reach", H3 cells for "which hub
  serves this address". Distances are straight lines. A delivery time is a packing time plus minutes per
  straight-line kilometre.
- **No maps service is called and no key exists.** Google Maps was mentioned at the start of the project and never
  wired in.

### 1.2 Decision: Amazon Location Service, drawn with MapLibre

**What.** One provider for the three things we need: map tiles, place search (an address typed by a customer
becomes a point, and a point becomes an address), and road routing (travel times between a hub and its stops). The
maps are drawn with MapLibre GL JS, the open-source renderer Amazon Location documents for its tiles. On the phone
the map lives in a web view (an Expo "DOM component"), so the same map code serves the phone and the web pages.

**Why.**

1. **It is in the region we run in.** Amazon Location has Maps, Places and Routes endpoints in Mumbai
   (`ap-south-1`), beside the rest of the system.
2. **It is on the account and the credits we already have.** No second billing relationship, no second place where
   a key can leak, and access is granted the way everything else here is: by IAM, or by an API key scoped to named
   actions.
3. **It can be used in Expo Go.** This is what rules out the obvious alternative for now. A native Google map in
   React Native (`react-native-maps`) no longer works inside Expo Go: users report a blank map, and a maintainer's
   reply says Expo Go stopped supporting it, so it needs our own development build with our own key. A MapLibre map
   in a web view needs no native code, and Expo's DOM components are documented as supported in Expo Go.
4. **Google's routing and places may not be mixed with someone else's map.** Google's terms say its core services
   are not to be used with or near a non-Google map, and repeat that for Routes and Places. So "Google for
   addresses, something else for the map" is not open to us: choosing Google means Google for all three, which
   brings back point 3.
5. **The routing API has what pooling needs.** A route matrix (travel time between every pair of points) and a
   waypoint optimiser for up to 50 stops.

**Considered and not taken.**

- **Google Maps Platform.** Probably the best address data in India, and at our volume it would cost nothing:
  India pricing gives each basic service 70,000 free requests a month. Not taken because of points 3 and 4, and
  because it needs a billing account in India that is the owner's to set up. It stays the fallback if Amazon's
  data proves poor (see the risk below).
- **OpenStreetMap's public tiles with our own routing server (OSRM).** Free, and it is what the network map does
  today. Not taken for the app: OpenStreetMap's tile policy asks applications that make heavy use to run their own
  tile servers or use a third party, and an app distributed to phones is exactly that case. Running tile and
  routing servers ourselves is a week we do not have.
- **An Indian provider (Mappls).** Not evaluated: no time to compare a fourth option.

**Tested on 24 November, with real places in and around Bhilai.** The owner agreed to Amazon Location that day,
and the open question was whether its data for a tier-2 Indian city is good enough. Calls were made from the AWS
CLI with the project's own login; no key was created for the test.

| Asked | Answer | Verdict |
| --- | --- | --- |
| Find "Supela, Bhilai" and "Risali, Bhilai" | Both found as districts of Bhilai, each within about 1 km of the point we had chosen by hand | Good |
| Find a village: "Patan, Durg" | Found as a locality | Good |
| Find a street: "Street 12, Sector 6, Bhilai" | An intersection in Sector 4 | Not to be trusted to the street |
| What is at the Civic Centre hub's point? | A named building 8 m away | Good |
| Complete "Nehru Nag" near Bhilai | Four suggestions; Bhilai's Nehru Nagar was the fourth, after Raipur's | Usable once limited to the city |
| Drive from the hub to Supela | 2.6 km, 6.6 minutes | Plausible |
| Ride a scooter from a farm 14.6 km away to the hub | 19.5 km, 32 minutes | Plausible |
| Travel times between the hub and four areas (5 by 5) | All 25 answered, none failed | Good |
| Best order for four stops from the hub and back | Risali, Smriti Nagar, Nehru Nagar, Supela: 21.9 km, 47 minutes | Plausible |

Two things follow for the design.

- **An address search finds the area, not the door.** The customer searches or picks an area, the map opens there,
  and the customer moves the pin to the door. The typed house and street stay as text for the agent.
- **Roads in Bhilai are far longer than straight lines.** From the hub to Nehru Nagar is 3.1 km as the crow flies
  and 5.8 km by road; across the five points the road was 1.6 to 1.9 times the straight line. A railway line and
  the steel plant's layout sit between the areas. The straight-line fallback in section 1.3 therefore multiplies by
  1.7 before applying a town speed, and the grouping of orders by direction (section 4.2) is to be checked against
  the road matrix, because two areas in the same direction can be on opposite sides of the line.

**The key for map tiles (created 24 November, at the owner's request).** A map in a browser or a web view cannot
sign its requests the way the server does, so Amazon Location gives it an API key instead. One exists now, named
`farm2home-map-tiles`, in Mumbai, tagged for this project.

- **It can read map tiles and nothing else** (`geo-maps:GetTile`). The key travels to every phone and browser that
  draws the map, so anyone can copy it out; what a copied key can do should be as little as possible. Tiles are
  the one thing the device has to fetch itself: the map asks for dozens as it is moved, and passing them through
  our server would add a hop for nothing.
- **Place search is not on the key**, which changes the earlier plan of one key for tiles and search. Search goes
  through our server with the server's own role, where it can be limited to the city (the test above showed it
  needs that), capped per person, and its answers remembered.
- **It ends on 31 March 2027.** A copied key then stops by itself. Moving the date is one command
  (`aws location update-key`), and AWS recommends an end date as the way to force a replacement.
- **It is not limited to a web address.** AWS recommends limiting a key to the pages allowed to use it, but the
  same map also runs inside the app's web view, which has no fixed address to name. To revisit with the
  installable build: AWS can also limit a key to one Android or iOS app.
- **Its value is not in this repository**, which is public. The server will hand the map's style address, key
  included, to the app and the web pages from its own settings, so the key can be replaced without a new build of
  the app.
- **We ask for India's view of its borders** (`political-view=IND` in the style address). Amazon Location draws
  disputed borders differently by country; a map shown in India should use India's.

Tested the same day, from this laptop. With the key: the Standard style, its drawings and letters, and tiles over
Bhilai at two zoom levels all arrived. Without the key, or with a wrong one: refused. A place search and a static
picture asked for with this key: refused. Then drawn with MapLibre GL JS in a browser: Bhilai with the three hubs
as pins, and at street level around the Civic Centre hub the map names the streets, the canal, the park and the
market. So the map is detailed enough for a customer to move a pin to their door.

**Costs and risks.**

- **Price.** Charged per request, with no minimum. Driving by car and the matrix are in the lowest price group;
  scooter routes and the stop-ordering call are in the next one up. We have not found the current rates per
  thousand; at demo volume (hundreds of requests) it is cents either way, and the cost guard on the account
  already watches the total.
- **A web view map is less smooth than a native one.** Acceptable for a pin on a map and a route line.
- **The network map keeps OpenStreetMap's tiles until this is done**, with their attribution, at a handful of
  views a day.

### 1.3 Decision: a map is never required

**What.** Every flow keeps working with no map service at all: a GPS fix or an area from the list for the customer,
a GPS fix for the farm, straight-line distances for pooling and for the order of stops. The map and road times
improve what is there; nothing waits for them.

**Why.** The demo runs on a network we do not control, which has already blocked our own domain once. A design in
which "the map did not load" means "the order cannot be placed" would put the whole demo behind one more external
call. And it lets delivery be built and tested before any maps work is done.

**Costs.** Two code paths for distance. They are kept honest by one function that returns travel minutes between
two points and says which method it used. The straight-line path multiplies by 1.7, from the test in section 1.2.

### 1.4 Decision: what location we keep

| Whose | When it is read | What is kept | Why |
| --- | --- | --- | --- |
| Customer | When they choose where to deliver | The point of the address, with the order | The stop's position; the hub's zone |
| Farm | Once, at registration | One point, refused if rougher than 50 m | It decides the hub |
| Delivery agent | Every 15 seconds, only while on a trip, only with the app open | The latest point per trip, and one point a minute as a trail | The customer's "where is my order"; the hub's view |

An agent's position is not read when they are off a trip, and a customer sees it only for their own order while
it is out for delivery. Reading location in the background needs a native build and a stronger permission; the
agent keeps the app open instead, and the screen says so.

### 1.5 Decision: where nobody delivers, the customer can ask, and the asking is counted

**What.** An address no hub serves used to end the conversation: "not in our delivery area yet". Now the same
screen offers "Request delivery here". The request (`POST /v1/service-requests`) is kept as the customer and the
H3 cell, never the exact point, and one customer asking twice from the same cell is one request. The answer says
how many neighbours within about a kilometre have asked too.

**Why.** Planning already counts every lookup that was turned away, and suggests new hubs where those pile up. A
lookup is weak evidence: someone was curious. A person who then taps a button is saying they would order. So a
request counts as five turned-away lookups (`SERVICE_REQUEST_WEIGHT`) in the same calculation, and the planning
map shows requests beside lookups. The owner asked for this on 24 November: a customer outside every zone should
be able to say so.

**Why the cell and not the address.** The same rule as for a turned-away lookup (section 1.4): planning needs to
know which neighbourhood, and nothing here needs the door.

**Considered and not taken.** Promising a date, or telling the customer when a hub opens. Nothing in the system
knows that, and a notification system does not exist. The screen says only what is true: the request is counted.

**Costs.** The weight of five is a guess; nothing measures how many requesters go on to order. The count of
neighbours leaks a little: someone who asks from many places learns where others asked. It is a count within a
kilometre, with no names, and asking needs a sign-in.

## 2. Orders as records on the server

### 2.1 What exists

A cart is **held** (`POST /v1/reservations`), which sets stock aside for ten minutes. **Paying** confirms the hold
and creates a pick job. The job is picked and **packed**. None of this knows who the customer is: the hold
endpoints are open, and the phone app remembers its own orders in the phone's storage and works out their progress
from the hold and the job.

### 2.2 Decision: an order is created at payment, around the hold

**What.** A new `orders` table and four endpoints, for signed-in customers only:

| Call | Does |
| --- | --- |
| `POST /v1/orders` with a hold's id and a delivery address | Confirms the hold (the existing step), and writes the order: who, which hub, the address, each line with the price charged, the totals |
| `GET /v1/reservations/{id}/bill` | What the held cart costs if paid now (section 3.3) |
| `GET /v1/orders` | The customer's own orders, newest first |
| `GET /v1/orders/{id}` | One order with its history, for the tracking screen |
| `POST /v1/orders/{id}/cancel` | Cancels until the order is packed (the existing rule) |

The hold stays exactly as it is, including its open endpoint, so the hub's demo desk still works.

**Why at payment and not at the hold.** A hold is a cart that may never be paid; most are released or expire. An
order is a promise to deliver. Writing an order row for every hold would fill the customer's history with
abandoned carts and would need a clean-up job to remove them.

**Why around the hold and not instead of it.** The hold is the part of the system with the strongest guarantee
(no overselling, proven under races), and most of the test suite leans on it. An order adds identity, address, prices and
history on top; it does not touch how stock is promised.

**Considered and not taken.** Making the hold endpoints require a customer login. It would be right in
production, but the hub's desk page and many tests place anonymous holds, and nothing in the demo is made
safer by it.

**Costs.** Two ids for one purchase (the hold's and the order's). The order carries the hold's id and that is the
only link the app needs.

### 2.3 Decision: an order's state is written when it changes, not worked out when read

**What.** The order has a `status` and a history table of `(status, at)`. The order module subscribes to the events
the hub already publishes (order paid, job packed, job cancelled) and to the new delivery events (trip formed, trip
left, delivered, delivery failed), and moves the order forward when one arrives, in the same transaction as the
event.

| Status | Set when |
| --- | --- |
| `confirmed` | The order is placed (payment is a stand-in, so placed and confirmed are one moment) |
| `packed` | The hub packs the job |
| `pooled` | The order is put on a trip |
| `out_for_delivery` | The agent leaves the hub with it |
| `delivered` | The agent enters the customer's code |
| `cancelled` | The customer cancels before packing, or nothing could be picked |
| `delivery_failed` | The agent could not hand it over |

**Why.** The app shows a timeline with times, which a status worked out on the fly cannot give. Delivery adds
states that no existing table has. And an event handler in the publisher's transaction cannot leave an order
disagreeing with its job: either both change or neither does.

**Costs.** A status can only be as right as the events. Each transition is a guarded update (`WHERE status = the
one before`), so an event arriving twice changes nothing.

### 2.4 Decision: payment stays a stand-in

**What.** `POST /v1/orders` takes no payment details and records `payment: "stand_in"`. **Why.** A gateway needs a
merchant account, webhooks and refunds, and proves nothing about micro-warehousing. The seam is one function, so a
gateway replaces it without changing the order. **Cost.** The demo must say that no money moves, and does.

## 3. What a customer is told about a pack

### 3.1 Decision: the shop describes the batch a customer would get next

**What.** For each item, the shop's list adds the facts of the batch that would be picked first: its grade, harvest
date, use-by date and farm. These already exist (a batch is `L<listing>`, the listing has the farm and harvest
date, the quality check has the grade); they are joined in, not stored again.

**Why one batch per item and not a row per batch.** Stock is promised per hub and item, and picked oldest batch
first. A customer cannot choose a batch, so showing several would offer a choice the hub does not honour. The
oldest batch is what the next order receives.

**Costs.** An order larger than what is left of the oldest batch receives some units from a newer one. They are
never older than shown, but their grade may differ. The order's lines record the batch of every unit, so the
receipt is exact even when the shop's summary was not.

### 3.2 Decision: a rescue price on a batch in its last day, for that batch's units only

**What.** When the batch to be picked first has one day of shelf life left or less, its units are offered at a
lower price (a setting, 30% off to begin with), and the shop says how many units are left at that price. An
order's lines are priced by walking the batches oldest first, the same walk that later chooses the bins: units
from the expiring batch at the rescue price, the rest at the full price.

**Why.** Wastage is a number this system is judged on, and produce a day from its date is still good to eat today.
A price that follows the batch is the smallest honest version of that. Pricing by the same walk as picking is what
keeps it honest: without it a customer could order ten at the rescue price when only three such packs exist.

**Considered and not taken.** A price that falls gradually with age, or that reacts to demand. Both are more
interesting and neither can be explained in one sentence to a customer or checked in one test.

**Costs.** The price a customer is shown can change between looking and paying, if someone else buys the last
rescue units first.

### 3.3 Decision: the checkout shows the hub's bill, and a price that rose is asked about, not charged

**What.** Two things, added on 24 November when the app moved onto the server's orders.

- `GET /v1/reservations/{id}/bill` answers what the held cart would cost if paid this moment. The checkout shows
  that, not a sum made on the phone, and asks again every 20 seconds.
- `POST /v1/orders` takes `expected_total`, the total the customer was looking at. If the order would cost more,
  nothing is paid, the hold stays held, and the answer is `409 price_changed` with the new bill. The app shows the
  new total and the customer taps Pay again, or leaves. An order that costs less than shown is placed as it is.

**Why.** A hold sets units aside, not batches. Two customers can each hold six packs while six remain at the
rescue price, and both are rightly told the lower price, because either may be the one who pays first. Whoever
paid second was charged the full price, on a screen that had said otherwise. Found while reading the app's
checkout: its total was the phone's own sum, and nothing compared it with the order.

**Why the bill comes from the hub's allocation.** The bill asks the same function that later chooses the bins
which units it would pick, and prices those. A second copy of that walk, on the phone or in a separate price
calculator, would be right until the day the two drifted apart. The phone still sums the cart before the hold,
from the shop's list; that is an estimate and the cart says nothing more than the list does.

**Why refuse instead of holding the price.** Keeping the shown price would mean either holding batches for ten
minutes for carts that are often abandoned, which takes the rescue units off sale exactly when they most need to
sell, or selling at a price the batch no longer supports. Refusing costs the customer one more tap, in a case
that needs two people buying the same last-day item in the same ten minutes.

**Considered and not taken.** Refusing any difference, lower as well. Nobody needs to be asked before paying less.

**Costs.** Units the hub would fail to find are counted at the full price in the bill, and leave the order at
payment, so in that rare case the order costs less than the bill said. The refusal is made inside the payment's
own transaction, after the pick job is built and priced, and undone as a whole; that is one wasted build of a pick
job per refusal.

### 3.4 Decision: a calendar date is India's date

**What.** Everything that asks "what is the date today" asks `app/clock.py`, which answers with the date in India
(UTC plus the offset in `LOCAL_UTC_OFFSET_MINUTES`, 330). That covers which batches may be sold and picked, the
rescue price, the write-off of expired stock, the use-by date given to stock that arrives without one, and the
demo data. Timestamps are untouched: they stay UTC, as every stored time is.

**Why.** The server's clock is UTC, and the code took today's date from it. India is five and a half hours ahead,
so for the first five and a half hours of every day the server was still on yesterday. Seen on staging on 24
November at one in the morning: a batch with a use-by date of the 23rd was still on sale, and at the rescue
price. A use-by date printed on a pack ends at midnight where the pack is.

**Why an offset and not a time zone name.** India has one time zone and no daylight saving, so a fixed offset is
exact, and the farm-supply code already used this setting for drop slots. A time zone database in the container
would be one more thing to keep up to date, for no gain here.

**Considered and not taken.** Setting the container's time zone to India. It would have fixed the date with no
code change, and silently moved every log line and every place that formats a time; and the tests, which run on
machines set to UTC, would then not be testing what runs.

**Costs.** Sales statistics (forecasting, assortment, the day's sales) still count a day from midnight UTC. They
bucket timestamps already stored, and moving the boundary would shift the history the forecasts were fitted on.
A day of sales there runs from 05:30 to 05:30 in India, which splits the night, when almost nothing sells.

## 4. Delivery

A packed order waits at the hub in a crate slot. Delivery has to answer five questions: when does a trip leave,
which orders are on it, in what order are they dropped, who takes it, and how is the hand-over proved.

### 4.1 Decision: a trip leaves when there are enough orders or when the oldest has waited long enough

**What.** At each hub, packed orders wait in a pool. A trip is formed when a delivery agent is free and either
`POOL_MIN_ORDERS` orders are waiting (4 to begin with) or the oldest has waited `POOL_MAX_WAIT_MINUTES` (10 to begin
with). A trip takes at most `TRIP_MAX_ORDERS` (6). A timed job checks every 30 seconds; packing an order checks at
once.

**Why.** This is the whole idea of pooling in one rule: waiting buys fuller trips, and the deadline caps what
waiting costs the customer. Both numbers are settings, and can be set per city later: a tier-2 city with fewer orders
would wait longer for the same fill. It is also the rule the hub already uses for picking (three orders in one walk once four are waiting),
so the people running a hub meet one idea twice.

**Considered and not taken.**

- **Fixed slots** (a trip every hour, or morning and evening). The fullest trips, and usual for milk and groceries
  on subscription. Not taken because the app promises a time in minutes from the order, and a slot would make that
  promise "by 6 pm".
- **Deciding trip by trip with an optimiser** that weighs every waiting order against every agent. Not taken: at a
  few orders an hour per hub it would choose what the rule chooses, and it could not be explained on a slide.

**Costs.** With one order an hour, every trip carries one order and pooling saves nothing. The simulator
(section 8) will say at what order rate pooling starts to pay; the handbook should report that number and not
only the happy case.

### 4.2 Decision: the order that has waited longest goes, with its nearest neighbours by direction

**What.** When more orders wait than one trip takes, the trip is the order that has waited longest and the
waiting orders nearest to it in compass direction from the hub, up to the trip's limit. Of two equally near, the
longer wait goes.

**Why.** A trip that goes north and then south drives past the hub in between. Grouping by direction is the
simplest rule that avoids it and needs nothing but the points. Starting from the longest wait keeps the promise in
4.1: the order that made the trip due is always on it.

**Changed in the building (24 November).** The first version of this section cut the whole circle of waiting
orders into fixed wedges, the textbook sweep, and sent the wedge holding the oldest order. The first test of it
showed the flaw: with three orders waiting and room for two, the oldest could land alone in a leftover wedge, and
an agent left with one bag while two that could have gone stayed behind. A trip is formed one at a time here, as
agents come free, so there is no need to divide everything at once. The sweep remains the right tool for planning
many trips together, which the simulated day (section 8) may want.

**Costs.** It ignores rivers, railway lines and one-way roads, which a road-time matrix would see. In Bhilai the
railway makes that matter (section 1.2). With road times the neighbours would be chosen by minutes, not degrees;
the rule's shape does not change.

### 4.3 Decision: the order of stops is the best one, found by trying them all

**What.** For a trip of up to 8 stops, every order of the stops is tried and the one with the least travel time
from the hub and back is kept. Travel time comes from the road matrix when the maps service answers, and from
straight-line distance at a town speed when it does not.

**Why.** Eight stops have 40,320 orders, which a laptop tries in well under a second. For trips this small there
is no reason to accept an approximate answer or to add a solver, and the result is the same every time, so it can
be tested exactly.

**Considered and not taken.** Amazon Location's waypoint optimiser, which takes 50 stops and knows traffic. It
would make the order of stops depend on a network call at the moment a trip is formed; we will use it to check
our answers, not to produce them.

**Costs.** It stops scaling at about ten stops. A trip is capped at six orders, so this limit is not reached.

### 4.4 Decision: the free agent who has waited longest takes the trip

**What.** Delivery agents are app accounts created by the platform team and attached to one hub. An agent goes on
duty in the app. A formed trip is given to the on-duty agent at that hub who has been free the longest. The claim
is one guarded update, as for a picker and a pick job, so a trip cannot have two agents.

**Why.** First come, first served is fair, obvious to the agents and needs no tuning. **Not taken:** letting
agents bid for or decline trips; it needs rules for what happens when everyone declines.

**Costs.** No account of where the agent is: an agent just back from the north gets a trip to the south. With all
trips starting and ending at the hub this costs nothing.

### 4.5 Decision: the bag is checked out of the hub, order by order

**What.** At the hub the agent's screen lists the trip's bags with their crate slots. The agent confirms each bag
(its order number is on the label; the app can take it typed or scanned later). When every bag is confirmed, the
trip leaves and its orders become `out_for_delivery`. This replaces the made-up rider the prototype assigns to
each packed order.

**Why.** The moment a bag leaves the hub is the moment responsibility for it changes hands, and the prototype's
hand-over rule ("only this order's rider, only with this order's bag") already encodes that. The trip keeps the
rule and applies it to several bags.

### 4.6 Decision: a four-digit code, worked out from a secret and never stored

**What.** Each order has a four-digit code, shown to the customer once the order is on a trip. At the door the
customer reads it out and the agent types it in. The server works the code out as a keyed hash (HMAC) of the order
id and the server's secret, reduced to four digits; it is not kept in the database. Five wrong tries lock the
hand-over for that order until the hub releases it.

**Why a code at all.** It proves the agent and the customer were together, with no signature pad and no
photograph, and a customer can pass it to a neighbour or a guard by phone. **Why worked out and not stored.** The
customer's app has to be able to show the code at any time, so a one-way hash in the database would not do, and
the alternative is to store it readable. Working it out on request means a copy of the database does not contain
any codes. **Why four digits.** It is read aloud on a doorstep; the limit of five tries, by an agent whose name is
on the trip, is what protects it.

**Costs.** Changing the server's secret changes every outstanding code. The secret is not changed while orders are
out.

### 4.7 Decision: an order that cannot be handed over comes back, and the hub decides

**What.** The agent marks the stop as failed with a reason (nobody home, refused, could not find it). The order
becomes `delivery_failed`, the customer is told, and the bag returns with the agent. At the hub, each unit is
either put back on the shelf (if its batch still has more than half its shelf life, the same rule as at the dock)
or written off, through the existing stock adjustments.

**Why.** Produce that has been out for an hour is usually still good; throwing it away by rule would add to the
wastage the system exists to reduce, and putting it back by rule would shelve what a customer just refused. A
person at the hub looks at it.

**Costs.** One more task for the hub. Refunds are a stand-in, like payment.

### 4.8 Decision: positions are sent and fetched by ordinary requests, not over a socket

**What.** The agent's app posts its position every 15 seconds while on a trip. The customer's app asks for its
order every 15 seconds while it is out for delivery and gets the last position and a time of arrival.

**Why.** The system already has a live socket, for the hub's staff, relayed inside the one API process. Phones on
mobile data lose sockets as they move between cells and when the app goes to the background; a request every 15
seconds does not care. "Where is my order" does not need better than 15 seconds.

**Costs.** At a thousand orders out at once this is about 80 requests a second (67 from customers, the rest from
agents), which is real load; it would then move to a socket or to push notifications. At demo scale it is nothing.

### 4.9 What the hub sees

A dispatch panel on the ops dashboard: bags waiting and for how long, trips forming and out, agents on duty. It is
the hub's answer to "why has this order not left", and the demo's proof that pooling happened.

### 4.10 What is built, and what is not (24 November)

Built, so that an order reaches a door: forming trips (4.1, 4.2), the order of stops (4.3), the agent who takes it
(4.4), checking bags out (4.5), the door code (4.6), a failed hand-over (the first half of 4.7), and what the hub
sees as an API (`GET /v1/stores/{id}/dispatch`, 4.9). The agent has screens in the app for all of it.

Different from what the sections above say, each for a reason:

- **Distances are straight lines times 1.7**, not road times. The road matrix is one more network call in the
  path of forming a trip, and the straight line gives the same order of stops for a handful of addresses in one
  direction. It gives the wrong length; the trip's kilometres are an estimate until the matrix is wired in.
- **A bag is confirmed by a tap**, not by scanning its label. The agent's screen shows the crate slot and the
  order number to match by eye. Scanning needs the camera permission and a printed label, neither of which a demo
  on one phone has.
- **An agent chooses their hub in the app**, while off duty. Section 4.4 has the platform team attach them, and
  `POST /v1/admin/agents` does that. Choosing in the app is for a demo run by one person, as is the setting
  `AGENT_SELF_SIGNUP`, which lets anyone sign up as an agent. Both are on for staging and off by default.
- **A locked code can only end in "not delivered".** The hub cannot release it yet.

Not built: what the hub does with a bag that comes back (4.7), the agent's position and the customer's map
(4.8), a time of arrival, and the dispatch panel as a page (4.9 is an API only).

On staging a trip leaves when the oldest order has waited two minutes, not ten, so that one person can show a
delivery without three more orders or a long pause.

## 5. Asking farms for what the hub expects to sell

### 5.1 Decision: a hub posts requests; a farmer answers one with a listing

**What.** Each evening, per hub and item: expected sales tomorrow (the forecast the hub already makes), plus a
margin, minus what is on the shelf and what is already on its way, converted from units to kilograms with the pack
size. If the result is above a floor, the hub posts a request ("up to 60 kg of tomatoes, tomorrow morning"). Farmers
within 60 km see the open requests in the app and answer with a listing; the request's remaining quantity goes
down by what is listed.

**Why.** Today a farmer lists what they have and hopes the hub wants it. The hub knows what it expects to sell.
Telling farmers closes the loop the name "just in time" promises, and it reuses three things that exist: the
forecast, the hub's count of what is coming, and the listing.

**Considered and not taken.** Setting the quantity by the newsvendor rule (order more when running out costs more
than throwing away). It is the right next step and needs a cost of running out and a cost of wastage that we would
be inventing. A fixed margin is honest about being a guess.

**Costs.** It is the piece most likely to be cut if delivery takes longer than planned. Nothing else depends on it.

## 6. Decisions not to do something before the demo

| Not doing | Why |
| --- | --- |
| **Removing the dark store's groceries from Bangalore's hubs** | About six hundred tests are written against that data, and staging already holds it; removing it there means deleting data on a hosted database. Bhilai's hubs hold only produce, and the demo is in Bhilai |
| **A production environment** | Staging is production-shaped and is what the demo uses. A second environment doubles the daily cost and the things that can drift, and nobody would look at it |
| **A second copy of the API** | The timed jobs and the staff's live feed run inside the process; two copies would run jobs twice. Moving them out is a week. The load balancer, the standby database and the rollback are already in place for it |
| **Real staff accounts** | The hub's logins are shared demo accounts behind one password per environment. Replacing them touches every staff screen |
| **Location in the background, native maps, push notifications** | Each needs our own build of the app and its own permissions. They follow the installable build |

## 7. An installable build

**What.** After delivery works, one Android build made by Expo's build service (EAS), installed from a file.
**Why not now.** Expo Go is enough to demo and to develop in, and this laptop cannot build Android itself. The
build service needs an Expo account, which is the owner's to create. **Why at all.** A build of our own is what
lifts the limits in section 6's last row, and "install this" is a stronger ending to a demo than "open Expo Go".

## 8. A simulated day

**What.** A script that plays one day through the real API with a compressed clock: farmers list in the morning,
the hub takes lots in, customers order through the day in clusters around real areas, pickers pick, trips form
and agents deliver. It reports what the design is judged on: minutes from order to door, orders per trip,
kilometres per order with and without pooling, units wasted, and how often a customer was refused.

**Why.** Every number in the handbook so far comes from one order or from a load test of reads. Pooling is a claim
about many orders, and only a day of them can support or deny it. **Why through the API.** A model of the system
would test the model. The scripted pickers that exist already do it this way.

**Costs.** Compressed time hides real picking and driving speeds, so those are inputs to the run, stated beside
the results.

### 8.1 Decision: demo farms keep a hosted demo's shelves stocked, through the ordinary intake

**What.** With `DEMO_SUPPLY` on, a job looks every half hour at each hub in a city that has demo farms. For each
produce item the hub has fewer than six units of, one lot arrives from a demo farm: a listing, the hub's weighing
and grading, packing into units, and putaway bin by bin, by the same functions a receiver's phone calls. An admin
can ask for it at once (`POST /v1/admin/demo-supply`). It is off for the tests and for the recorded demo.

**Why.** A hub sells only what a farm has brought, so the hubs opened for Bhilai showed an empty shop to the first
person who looked, which was the owner, on a phone, on 24 November. Asking every visitor to play farmer and
receiver before they may see a product is not a demo.

**Why through the intake and not written onto the shelf.** Stock written straight into the tables would have no
listing, no quality check and no farm, so the shop could not say where a pack came from, and that sentence is the
product. It would also be a second way for stock to appear, which is a second thing to keep honest. Going through
the intake costs nothing extra and the audit of stock treats these lots like any other.

**Why spinach comes a day old.** It keeps two days, so a day-old lot is in its last day tomorrow and the shop
always has one item at the rescue price to show.

**The farms are not real** and say so: one account, `demo-farms@farm2home.invalid`, owns them. `.invalid` can
never receive mail, and the sign-in now refuses to make a code for such an address, so nobody can become that
farmer.

**Costs.** A real farmer's lot now arrives at a hub that already has that item, so the story "the shop was empty
until the farmer listed" is no longer what staging shows; the recorded demo still shows it. Two app instances
could both top up, so one runs at a time, by a database lock.

### 8.2 Decision: a hub at IIT Bhilai

**What.** A fourth demo hub, BH-04 IIT Bhilai, about half a kilometre from the permanent campus at Kutelabhata
(found with Amazon Location: 21.2444 N, 81.3176 E). "IIT Bhilai" is the first area offered in the app for the
city.

**Why.** The campus is 4 km from the nearest hub, Nehru Nagar, and a hub serves 3 km, so the place the demo will
be given from was outside every zone. **Why a new hub and not a wider radius.** The radius is the promise of a
short ride; widening one hub's to reach one more address would quietly break it for everyone at the edge.

**How it reaches a copy that is already running.** The demo hubs used to be opened only when the city had none.
Each is now opened if it is missing, so staging, which has three, gets the fourth when it next starts, and the
other three keep every place that is nearer to them.

## 9. Order of work

| Day | Piece | If it runs late |
| --- | --- | --- |
| 1 | Orders on the server; the app reads them | Nothing below works without it |
| 2 | Batch facts and the rescue price in the shop | The rescue price can wait; the facts are cheap |
| 3 to 5 | Delivery: pool, trips, agent's screens, the code, the hub's dispatch panel | Failed deliveries and the position trail are cut first |
| 6 | Maps: the address test, then the map in the app and on the network page | Section 1.3 means the demo does not need it |
| 7 | Requests to farms | Cut whole |
| 8 | The simulated day and its numbers | A shorter run |
| 9 | Rehearsal on the phone, on the venue's kind of network; fixes only | Not cut |

## Sources

- AWS, "Amazon Location Service endpoints and quotas" (Maps, Places and Routes endpoints in `ap-south-1`; request
  quotas): https://docs.aws.amazon.com/general/latest/gr/location.html
- AWS, "Amazon Location Service Routes V2" (route matrix; waypoint optimisation, 50 waypoints):
  https://docs.aws.amazon.com/location/latest/APIReference/API_Operations_Amazon_Location_Service_Routes_V2.html
  and https://aws.amazon.com/location/routes/
- AWS, "How to display a map" (Amazon Location's tiles drawn with MapLibre GL JS, with an API key in the style
  address): https://docs.aws.amazon.com/location/latest/developerguide/how-to-display-a-map.html
- AWS, "Pricing model" for Amazon Location (per request, no minimum; the same price whatever the authentication):
  https://docs.aws.amazon.com/location/latest/developerguide/pricing.html
- AWS, "Best practices" for Amazon Location, API key optimization (only the actions needed; limit by web address
  or by app; an end date to force replacement):
  https://docs.aws.amazon.com/location/latest/developerguide/auth-best-practices.html
- AWS CLI reference, `location create-key` (the actions a key may allow, `geo-maps:GetTile` among them):
  https://docs.aws.amazon.com/cli/latest/reference/location/create-key.html
- AWS, "How to set the political view of a map" (`political-view` in the style address):
  https://docs.aws.amazon.com/location/latest/developerguide/how-to-set-political-view-map.html
- Google, "Google Maps Platform core services pricing list: India" (70,000 free requests a month for each basic
  service; the rates): https://developers.google.com/maps/billing-and-pricing/pricing-india
- Google, "Google Maps Platform Terms of Service" and "Service Specific Terms" (no use with or near a non-Google
  map; repeated for Routes and Places): https://cloud.google.com/maps-platform/terms and
  https://cloud.google.com/maps-platform/terms/maps-service-terms
- `react-native-maps`, issue 5888, "Google Maps blank in Expo Go" (a maintainer's reply that Expo Go no longer
  supports it; works in development builds): https://github.com/react-native-maps/react-native-maps/issues/5888
- Expo, "react-native-maps" (the key is set through a config plugin and needs a rebuild):
  https://docs.expo.dev/versions/latest/sdk/map-view/
- Expo, "Using React DOM in Expo native apps" (DOM components; supported in Expo Go):
  https://docs.expo.dev/guides/dom-components/
- OpenStreetMap Foundation, "Tile Usage Policy" (heavy users should run their own tile servers or use a third
  party; attribution; no bulk downloading): https://operations.osmfoundation.org/policies/tiles/
- B. E. Gillett and L. R. Miller, "A Heuristic Algorithm for the Vehicle-Dispatch Problem", *Operations Research*
  22(2), 1974 (the sweep method): https://pubsonline.informs.org/doi/fpi/10.1287/opre.22.2.340
- Not found: a page stating Amazon Location's map and address coverage for India (tested by us instead, in
  section 1.2), and its current price per thousand requests.
- Measured by us on 24 November 2026: every row of the table in section 1.2, from the service's own answers.
- Our own, not from a source: every number given as a setting (4 orders, 10 minutes, 6 per trip, 30% off, 15
  seconds). They are starting values to be changed by what the simulated day shows.
