"""Delivery: packed orders leave the hub in trips, and each is handed over against the customer's code
(docs/DESIGN.md, section 4).

    packed            the bag waits at the hub in a crate slot
    pooled            the order is on a trip with an agent; the customer sees the door code
    out_for_delivery  the agent has checked every bag of the trip out of the hub
    delivered         the code the customer read out was right
    delivery_failed   the agent could not hand it over; the bag comes back to the hub

A trip is formed when an agent is free and either enough orders wait or the oldest has waited long enough (4.1).
When more wait than one trip takes, the longest-waiting order goes with its nearest neighbours by compass direction
(4.2). The stops are made in
the order with the least travel, found by trying every order (4.3). The agent free longest takes it (4.4), checks
each bag out (4.5), and at the door types the four digits the customer reads out (4.6).

Not built yet, and said so where it matters: road times (distances are straight lines times ROAD_FACTOR), the
agent's position on a map (4.8), what the hub does with a bag that comes back (4.7), and releasing a locked code.
"""
import hmac
import itertools
import math
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ... import config, events
from ...errors import DomainError, not_found
from ...models import AgentProfile, FulfilmentJob, Order, OrderEvent, Store, Trip, TripStop, User, utcnow
from ..fulfilment import riders
from ..orders import service as orders
from ..serviceability import service as serviceability

OPEN = ("assigned", "out")                          # a trip the agent is still on
ENDED = ("delivered", "failed")                     # a stop that is over
FAIL_REASONS = ("nobody_home", "refused", "not_found")
LOCK = 0x46324854                                   # "F2HT" plus the hub's id: one trip-forming at a time per hub


# --------------------------------------------------------------------------- forming trips

def waiting(db: Session, store_id: int) -> list[tuple[Order, datetime]]:
    """Packed orders at this hub that are on no trip, with when each was packed, the longest wait first."""
    packed_at = func.max(OrderEvent.at)
    rows = db.execute(
        select(Order, packed_at)
        .join(OrderEvent, OrderEvent.order_id == Order.id)
        .where(Order.store_id == store_id, Order.status == "packed", OrderEvent.status == "packed",
               Order.id.not_in(select(TripStop.order_id)))
        .group_by(Order.id).order_by(packed_at, Order.id)).all()
    return [(order, at) for order, at in rows]


def due(queue: list[tuple[Order, datetime]], now: datetime) -> bool:
    """Should a trip leave now (section 4.1)? Yes when enough orders wait, or the oldest has waited long enough."""
    if not queue:
        return False
    return (len(queue) >= config.POOL_MIN_ORDERS
            or now - queue[0][1] >= timedelta(minutes=config.POOL_MAX_WAIT_MINUTES))


def bearing(store: Store, order: Order) -> float:
    """The compass direction of the order's address from the hub, in degrees: 0 north, 90 east."""
    lat1, lat2 = math.radians(store.lat), math.radians(order.lat)
    d_lng = math.radians(order.lng - store.lng)
    x = math.sin(d_lng) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(d_lng)
    return math.degrees(math.atan2(x, y)) % 360


def one_load(store: Store, queue: list[Order]) -> list[Order]:
    """Which of the waiting orders travel together when more wait than one trip takes (section 4.2): the one that
    has waited longest (the first of `queue`), and the ones nearest to it in compass direction from the hub, up to
    TRIP_MAX_ORDERS. Of two equally near, the longer wait goes."""
    size = config.TRIP_MAX_ORDERS
    if len(queue) <= size:
        return list(queue)
    turn = bearing(store, queue[0])

    def apart(order: Order) -> float:
        degrees = abs(bearing(store, order) - turn) % 360
        return min(degrees, 360 - degrees)

    others = sorted(enumerate(queue[1:]), key=lambda placed: (apart(placed[1]), placed[0]))
    return [queue[0], *(order for _place, order in others[:size - 1])]


def route(store: Store, load: list[Order]) -> tuple[list[Order], float]:
    """The order of the stops with the least travel from the hub and back (section 4.3), found by trying every
    one, and that round's length in road kilometres. Until road times are wired in, a leg is the straight line
    times ROAD_FACTOR, which changes the length and not which order is shortest."""
    def leg(a, b) -> float:
        return serviceability.distance_km(a.lat, a.lng, b.lat, b.lng)

    best, best_km = list(load), math.inf
    for stops in itertools.permutations(load):
        km = leg(store, stops[0]) + sum(leg(a, b) for a, b in zip(stops, stops[1:])) + leg(stops[-1], store)
        if km < best_km - 1e-9:                     # the first of two equal rounds is kept, so the answer is steady
            best, best_km = list(stops), km
    return best, round(best_km * config.ROAD_FACTOR, 2)


def _claim_free_agent(db: Session, store_id: int) -> AgentProfile | None:
    """The on-duty agent at this hub who has been free longest, made busy (section 4.4). The claim is one guarded
    update, so two trips formed at the same moment cannot take the same agent. Does not commit."""
    candidates = db.scalars(select(AgentProfile.user_id)
                            .where(AgentProfile.store_id == store_id, AgentProfile.on_duty.is_(True),
                                   AgentProfile.free_since.is_not(None))
                            .order_by(AgentProfile.free_since, AgentProfile.user_id)).all()
    for user_id in candidates:
        claimed = db.execute(update(AgentProfile)
                             .where(AgentProfile.user_id == user_id, AgentProfile.on_duty.is_(True),
                                    AgentProfile.free_since.is_not(None))
                             .values(free_since=None).execution_options(synchronize_session=False)).rowcount == 1
        if claimed:
            profile = db.get(AgentProfile, user_id)
            db.refresh(profile)
            return profile
    return None


def form_trips(db: Session, store_id: int, commit: bool = True) -> list[Trip]:
    """Form every trip that is due at this hub and has an agent to take it. Each order on a new trip becomes
    `pooled`. Called when an order is packed, when an agent comes on duty or finishes a trip, and on a timer.
    Returns the trips formed."""
    db.execute(select(func.pg_advisory_xact_lock(LOCK + store_id)))        # until this transaction ends
    store = db.get(Store, store_id)
    formed = []
    while store is not None:
        queue = waiting(db, store_id)
        if not due(queue, utcnow()):
            break
        agent = _claim_free_agent(db, store_id)
        if agent is None:
            break
        stops, km = route(store, one_load(store, [order for order, _at in queue]))
        trip = Trip(store_id=store_id, agent_id=agent.user_id, status="assigned", km=km,
                    stops=[TripStop(order_id=order.id, seq=n) for n, order in enumerate(stops, start=1)])
        db.add(trip)
        db.flush()
        for order in stops:
            orders.move(db, order.order_id, "pooled", only_from=("packed",))
        events.publish(db, "trip.formed", store_id, {"trip_id": trip.id, "agent_id": agent.user_id, "km": km,
                                                     "orders": [order.order_id for order in stops]})
        formed.append(trip)
    if commit:
        db.commit()
    return formed


def form_all(db: Session) -> int:
    """The timer's pass: form what is due at every hub that has a free agent. Returns how many trips. Commits."""
    hubs = db.scalars(select(AgentProfile.store_id)
                      .where(AgentProfile.on_duty.is_(True), AgentProfile.free_since.is_not(None),
                             AgentProfile.store_id.is_not(None)).distinct()).all()
    return sum(len(form_trips(db, store_id)) for store_id in hubs)


@events.subscribe("fulfilment.state_changed")
def on_job_state(db: Session, store_id: int | None, payload: dict) -> None:
    """An order was packed: a trip may be due at once. Runs in the packing transaction, after the handler in
    orders (imported above, so registered first) has marked the order packed."""
    if payload["state"] == "packed" and store_id is not None:
        form_trips(db, store_id, commit=False)


# --------------------------------------------------------------------------- the agent

def _profile(db: Session, user_id: int) -> AgentProfile:
    profile = db.get(AgentProfile, user_id)
    if profile is None:
        profile = AgentProfile(user_id=user_id)
        db.add(profile)
        db.flush()
    return profile


def _open_trip(db: Session, agent_id: int) -> Trip | None:
    return db.scalar(select(Trip).where(Trip.agent_id == agent_id, Trip.status.in_(OPEN)))


def stop_view(db: Session, stop: TripStop) -> dict:
    order = stop.order
    job = db.scalar(select(FulfilmentJob).where(FulfilmentJob.order_id == order.order_id))
    customer = db.get(User, order.user_id)
    return {"order_id": order.order_id, "seq": stop.seq, "status": stop.status,
            "crate_slot": job.crate_slot if job else None, "units": sum(line.qty for line in order.lines),
            "address": {"label": order.address_label, "line": order.address_line, "landmark": order.landmark,
                        "lat": order.lat, "lng": order.lng},
            "customer": {"name": customer.name, "phone": customer.phone},
            "failed_reason": stop.failed_reason,
            "tries_left": max(config.DOOR_CODE_TRIES - stop.code_tries, 0)}


def trip_view(db: Session, trip: Trip) -> dict:
    hub = db.get(Store, trip.store_id)
    return {"trip_id": trip.id, "status": trip.status, "km": trip.km,
            "created_at": trip.created_at.isoformat() + "Z",
            "left_at": trip.left_at.isoformat() + "Z" if trip.left_at else None,
            "done_at": trip.done_at.isoformat() + "Z" if trip.done_at else None,
            "hub": {"store_id": hub.id, "name": hub.name, "lat": hub.lat, "lng": hub.lng},
            "stops": [stop_view(db, stop) for stop in trip.stops]}


def me(db: Session, user_id: int) -> dict:
    """The agent's own state: their hub, whether they are on duty, and the trip they are on, if any."""
    profile = _profile(db, user_id)
    user = db.get(User, user_id)
    hub = db.get(Store, profile.store_id) if profile.store_id else None
    trip = _open_trip(db, user_id)
    answer = {"user_id": user_id, "name": user.name,
              "hub": {"store_id": hub.id, "name": hub.name, "lat": hub.lat, "lng": hub.lng} if hub else None,
              "on_duty": profile.on_duty, "trip": trip_view(db, trip) if trip else None,
              "waiting_at_hub": len(waiting(db, hub.id)) if hub else 0}
    db.commit()                                     # keeps a profile made on the first look
    return answer


def choose_hub(db: Session, user_id: int, store_id: int) -> dict:
    """The agent says which hub they work from. Only while off duty: an agent on duty is counted on by that hub.
    Commits. 409 on_duty."""
    profile = _profile(db, user_id)
    store = db.get(Store, store_id)
    if store is None or store.status == "closed":
        raise not_found("Hub", store_id)
    if profile.on_duty or _open_trip(db, user_id) is not None:
        raise DomainError(409, "on_duty", "Go off duty before changing your hub")
    profile.store_id = store_id
    db.commit()
    return me(db, user_id)


def set_duty(db: Session, user_id: int, on_duty: bool) -> dict:
    """Go on or off duty. Coming on duty may form a trip at once, if orders have waited long enough. Commits.
    409 no_hub before a hub is chosen; 409 on_a_trip when going off duty with bags still out."""
    profile = _profile(db, user_id)
    trip = _open_trip(db, user_id)
    if on_duty:
        if profile.store_id is None:
            raise DomainError(409, "no_hub", "Choose the hub you work from first")
        if not profile.on_duty:
            profile.on_duty = True
            profile.free_since = None if trip else utcnow()
            db.flush()
            form_trips(db, profile.store_id, commit=False)
    else:
        if trip is not None:
            raise DomainError(409, "on_a_trip", "Finish your trip before going off duty")
        profile.on_duty, profile.free_since = False, None
    db.commit()
    return me(db, user_id)


def _my_trip(db: Session, agent_id: int) -> Trip:
    trip = _open_trip(db, agent_id)
    if trip is None:
        raise DomainError(409, "no_trip", "You have no trip at the moment")
    return trip


def _my_stop(trip: Trip, order_id: str) -> TripStop:
    stop = next((stop for stop in trip.stops if stop.order.order_id == order_id), None)
    if stop is None:
        raise not_found("Order on your trip", order_id)     # someone else's order does not exist, as far as you know
    return stop


def load_bag(db: Session, agent_id: int, order_id: str) -> dict:
    """The agent confirms one bag at the hub (section 4.5): the order leaves the hub's hands for theirs. When every
    bag of the trip is confirmed the trip is out and its orders are out for delivery. Safe to repeat. Commits."""
    trip = _my_trip(db, agent_id)
    stop = _my_stop(trip, order_id)
    if stop.status == "waiting":
        job = db.scalar(select(FulfilmentJob).where(FulfilmentJob.order_id == order_id))
        riders.give_to_agent(db, job, f"agent-{agent_id}")
        stop.status, stop.loaded_at = "loaded", utcnow()
        db.flush()
    if trip.status == "assigned" and all(other.status != "waiting" for other in trip.stops):
        trip.status, trip.left_at = "out", utcnow()
        for other in trip.stops:
            orders.move(db, other.order.order_id, "out_for_delivery", only_from=("pooled",))
        events.publish(db, "trip.left", trip.store_id, {"trip_id": trip.id, "agent_id": agent_id,
                                                        "orders": [s.order.order_id for s in trip.stops]})
    db.commit()
    return trip_view(db, trip)


def _end_stop(db: Session, trip: Trip, stop: TripStop, status: str, order_status: str) -> None:
    """A stop is over. When it was the trip's last, the trip is done and the agent is free again, which may form
    the next trip at once. Does not commit."""
    stop.status, stop.ended_at = status, utcnow()
    orders.move(db, stop.order.order_id, order_status, only_from=("out_for_delivery",))
    db.flush()
    if all(other.status in ENDED for other in trip.stops):
        trip.status, trip.done_at = "done", utcnow()
        profile = _profile(db, trip.agent_id)
        if profile.on_duty:
            profile.free_since = utcnow()
        db.flush()
        events.publish(db, "trip.done", trip.store_id, {
            "trip_id": trip.id, "agent_id": trip.agent_id,
            "delivered": sum(1 for s in trip.stops if s.status == "delivered"),
            "failed": sum(1 for s in trip.stops if s.status == "failed")})
        form_trips(db, trip.store_id, commit=False)


def _stop_out(db: Session, agent_id: int, order_id: str) -> tuple[Trip, TripStop]:
    trip = _my_trip(db, agent_id)
    stop = _my_stop(trip, order_id)
    if trip.status != "out":
        raise DomainError(409, "not_left", "Check every bag out of the hub before making a delivery")
    return trip, stop


def deliver(db: Session, agent_id: int, order_id: str, code: str) -> dict:
    """Hand an order over at the door: the agent types the four digits the customer reads out (section 4.6).
    Commits. A wrong code is counted (422 wrong_code, with the tries left); after DOOR_CODE_TRIES the hand-over is
    locked (409 code_locked) and the agent reports the stop as failed. Repeating a delivery that went through is
    safe."""
    trip, stop = _stop_out(db, agent_id, order_id)
    if stop.status == "delivered":
        return trip_view(db, trip)
    if stop.status != "loaded":
        raise DomainError(409, "stop_over", f"Order {order_id} is already marked {stop.status}")
    if stop.code_tries >= config.DOOR_CODE_TRIES:
        raise DomainError(409, "code_locked", "Too many wrong codes. Report this stop as not delivered; the hub "
                                              "will call the customer.")
    if not hmac.compare_digest(code.encode(), orders.door_code(order_id).encode()):
        stop.code_tries += 1
        db.commit()
        left = config.DOOR_CODE_TRIES - stop.code_tries
        raise DomainError(422, "wrong_code", "That is not this order's code. Ask the customer to read it again."
                          if left else "That is not this order's code, and there are no tries left.",
                          {"tries_left": left})
    _end_stop(db, trip, stop, "delivered", "delivered")
    db.commit()
    return trip_view(db, trip)


def fail(db: Session, agent_id: int, order_id: str, reason: str) -> dict:
    """The order could not be handed over (section 4.7): nobody home, refused, or the address not found. The bag
    comes back with the agent. Commits. Repeating it is safe."""
    trip, stop = _stop_out(db, agent_id, order_id)
    if stop.status == "failed":
        return trip_view(db, trip)
    if stop.status != "loaded":
        raise DomainError(409, "stop_over", f"Order {order_id} is already marked {stop.status}")
    stop.failed_reason = reason
    _end_stop(db, trip, stop, "failed", "delivery_failed")
    db.commit()
    return trip_view(db, trip)


# --------------------------------------------------------------------------- the platform team and the hub

def add_agent(db: Session, email: str, name: str, store_id: int) -> dict:
    """Make a delivery agent's account, attached to a hub. They then sign in with a code sent to that address.
    Commits. 409 email_taken for an address that already has an account."""
    if db.get(Store, store_id) is None:
        raise not_found("Hub", store_id)
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise DomainError(409, "email_taken", "That address already has an account")
    user = User(role="agent", email=email, name=name.strip())
    db.add(user)
    db.flush()
    db.add(AgentProfile(user_id=user.id, store_id=store_id))
    db.commit()
    return {"user_id": user.id, "email": user.email, "name": user.name, "store_id": store_id}


def dispatch(db: Session, store_id: int) -> dict:
    """What the hub sees of delivery (section 4.9): bags waiting and for how long, trips forming and out, and the
    agents on duty. Read-only."""
    if db.get(Store, store_id) is None:
        raise not_found("Hub", store_id)
    now = utcnow()
    trips = db.scalars(select(Trip).where(Trip.store_id == store_id, Trip.status.in_(OPEN)).order_by(Trip.id)).all()
    busy = {trip.agent_id: trip.id for trip in trips}
    agents = db.execute(select(AgentProfile, User).join(User, User.id == AgentProfile.user_id)
                        .where(AgentProfile.store_id == store_id, AgentProfile.on_duty.is_(True))
                        .order_by(AgentProfile.free_since, User.id)).all()
    return {
        "store_id": store_id,
        "rule": {"min_orders": config.POOL_MIN_ORDERS, "max_wait_minutes": config.POOL_MAX_WAIT_MINUTES,
                 "max_orders": config.TRIP_MAX_ORDERS},
        "waiting": [{"order_id": order.order_id, "area": order.address_label,
                     "minutes_waiting": round((now - at).total_seconds() / 60, 1)}
                    for order, at in waiting(db, store_id)],
        "trips": [{"trip_id": trip.id, "status": trip.status, "agent": trip.agent.name, "km": trip.km,
                   "stops": [{"order_id": stop.order.order_id, "area": stop.order.address_label,
                              "status": stop.status} for stop in trip.stops]} for trip in trips],
        "agents": [{"user_id": user.id, "name": user.name, "trip_id": busy.get(user.id),
                    "free_minutes": round((now - profile.free_since).total_seconds() / 60, 1)
                    if profile.free_since else None} for profile, user in agents],
    }
