def make(client, kind, **fields):
    r = client.post(f"/api/{kind}", json=fields)
    assert r.status_code == 201, r.text
    return r.json()


def test_calendar_returns_everything_in_range(client):
    make(client, "tasks", title="Read P10", do_date="2026-10-13", due="2026-11-05T09:00")
    make(client, "tasks", title="Outside", do_date="2026-10-20")
    make(client, "tasks", title="Undated", due="2026-10-14")
    make(client, "events", title="Kim lecture", start="2026-09-29T14:00", repeat="TU,TH")
    make(client, "deadlines", title="Team list", due="2026-10-09")

    cal = client.get("/api/calendar", params={"start": "2026-10-12", "end": "2026-10-18"}).json()
    assert [t["title"] for t in cal["tasks"]] == ["Read P10"]
    assert [e["start"] for e in cal["events"]] == ["2026-10-13T14:00", "2026-10-15T14:00"]
    assert cal["deadlines"] == []
    # Tasks with a due date in range but no do date still show, on their due day.
    assert [t["title"] for t in cal["unscheduled"]] == ["Undated"]


def test_moving_a_task_changes_its_do_date(client):
    task = make(client, "tasks", title="Outline", do_date="2026-10-13")
    client.patch(f"/api/tasks/{task['id']}", json={"do_date": "2026-10-15"})
    cal = client.get("/api/calendar", params={"start": "2026-10-15", "end": "2026-10-15"}).json()
    assert [t["title"] for t in cal["tasks"]] == ["Outline"]


def test_courses_with_the_same_number_get_different_colors(client):
    ding = make(client, "courses", number="CS 239", instructor="Robin Ding")
    kim = make(client, "courses", number="CS 239", instructor="Miryung Kim")
    assert ding["color"] and kim["color"] and ding["color"] != kim["color"]
