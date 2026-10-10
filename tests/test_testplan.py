import datetime as dt

from openrec.testplan import is_steering_day, pair_of

START = dt.date(2027, 1, 4)


def test_each_pair_has_exactly_one_steering_day():
    for pair in range(60):
        a = START + dt.timedelta(days=2 * pair)
        b = a + dt.timedelta(days=1)
        assert is_steering_day(a, START, "seed") != is_steering_day(b, START, "seed")
        assert pair_of(a, START) == pair_of(b, START) == pair


def test_plan_is_deterministic_and_not_simply_alternating():
    plan = [is_steering_day(START + dt.timedelta(days=i), START, "seed") for i in range(40)]
    again = [is_steering_day(START + dt.timedelta(days=i), START, "seed") for i in range(40)]
    assert plan == again
    first_of_pair = plan[::2]
    assert 0 < sum(first_of_pair) < len(first_of_pair)  # order randomised within pairs


def test_before_start_or_no_plan_always_steers():
    assert is_steering_day(START - dt.timedelta(days=1), START, "seed")
    assert is_steering_day(START, None, "seed")
