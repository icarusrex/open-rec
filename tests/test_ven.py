import datetime as dt

from openrec.logic import build_event, quarter_starts
from openrec.ven import Bridge

DAY = dt.date(2026, 10, 12)
Q = quarter_starts(DAY)


class FakeVtn:
    def __init__(self, events):
        self.events_list = events
        self.fail = False

    def find_program_id(self, name):
        return "p1"

    def events(self, program_id):
        if self.fail:
            raise ConnectionError("down")
        return self.events_list


class FakeHA:
    def __init__(self):
        self.calls = []
        self.leases = []

    def set_on(self, entity, on):
        self.calls.append((entity, on))

    def set_lease(self, entity, active):
        self.leases.append((entity, active))


def make_bridge(flags):
    ev = build_event("p1", DAY, Q, {}, flags, steering=True)
    vtn, ha = FakeVtn([ev]), FakeHA()
    return Bridge(vtn, ha, "input_boolean.w", "open-rec-surplus"), vtn, ha


def test_bridge_follows_event_and_only_writes_on_change():
    flags = [1 if 40 <= i < 44 else 0 for i in range(96)]
    bridge, _, ha = make_bridge(flags)
    assert bridge.tick(Q[39]) == 0
    assert bridge.tick(Q[40]) == 1
    assert bridge.tick(Q[40] + dt.timedelta(minutes=5)) == 1
    assert bridge.tick(Q[44]) == 0
    assert ha.calls == [("input_boolean.w", False), ("input_boolean.w", True), ("input_boolean.w", False)]


def test_bridge_holds_through_brief_outage_then_fails_safe():
    bridge, vtn, ha = make_bridge([1] * 96)
    t = Q[10]
    assert bridge.tick(t) == 1
    vtn.fail = True
    assert bridge.tick(t + dt.timedelta(minutes=1)) == 1  # 1st failure: hold
    assert bridge.tick(t + dt.timedelta(minutes=2)) == 1  # 2nd failure: hold
    assert bridge.tick(t + dt.timedelta(minutes=3)) == 0  # 3rd failure: off
    assert ha.calls[-1] == ("input_boolean.w", False)


def test_bridge_reasserts_periodically():
    bridge, _, ha = make_bridge([0] * 96)
    bridge.tick(Q[0])
    bridge.tick(Q[0] + dt.timedelta(minutes=5))
    bridge.tick(Q[0] + dt.timedelta(minutes=16))
    assert len(ha.calls) == 2


def test_invalid_event_cannot_reset_the_failure_counter():
    bridge, vtn, ha = make_bridge([1] * 96)
    assert bridge.tick(Q[0]) == 1
    vtn.events_list[0]['intervalPeriod']['duration'] = 'P1M'
    for i in range(1, 4):
        bridge.tick(Q[0] + dt.timedelta(seconds=30 * i))
    assert bridge._failures >= 3
    assert ha.calls[-1] == ('input_boolean.w', False)


def test_registration_failure_clears_existing_permission_and_retries():
    bridge, vtn, ha = make_bridge([1] * 96)
    bridge.ven_name = 'home-1'
    attempts = []

    def register(name):
        attempts.append(name)
        raise ConnectionError('registration down')

    vtn.ensure_ven = register
    assert bridge.tick(Q[0]) == 0
    assert bridge.tick(Q[0] + dt.timedelta(seconds=30)) == 0
    assert attempts == ['home-1', 'home-1']
    assert ha.calls[0] == ('input_boolean.w', False)
    assert not any(active for _, active in ha.leases)


def test_only_valid_polls_renew_the_ha_lease():
    bridge, vtn, ha = make_bridge([1] * 96)
    bridge.tick(Q[0])
    assert ha.leases[-1] == ('timer.open_rec_bridge_lease', True)
    count = len(ha.leases)
    vtn.fail = True
    bridge.tick(Q[0] + dt.timedelta(seconds=30))
    assert len(ha.leases) == count
