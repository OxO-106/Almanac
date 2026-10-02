"""How the assistant words its questions: every question text is made here."""


def who_teaches(label):
    return f"Who teaches {label}? The document doesn't name the instructor."


def when_is(title, kind):
    return f"When is “{title}”{'' if kind == 'events' else ' due'}? The document doesn't say."


def which_day(week, monday, friday, title):
    return f"Which day in Week {week} ({monday:%b} {monday.day} – {friday:%b} {friday.day}) is “{title}”? The document only gives the week."


DAY_NAMES = {"MO": "Mondays", "TU": "Tuesdays", "WE": "Wednesdays", "TH": "Thursdays", "FR": "Fridays", "SA": "Saturdays", "SU": "Sundays"}


def _days(days):
    names = [DAY_NAMES.get(d, d) for d in days]
    return " and ".join(names) if len(names) < 3 else ", ".join(names[:-1]) + " and " + names[-1]


def meeting_time(short, days):
    return f"What time does {short} meet on {_days(days)}? The document doesn't say."


def meeting_time_again(days):
    return f"What time does it meet on {_days(days) or 'those days'}? For example: 10am to 11:50am, or the same as another class."


def same_course(existing, name):
    return f"You already have {existing}. Is {name} a different course?"


def which_section(code, title, names):
    return f"Which of your courses is {code} ({title}) on Bruin Learn: {names}?"


def paper_pages(title):
    return f"How many pages is the paper for “{title}”?"


def read_each(course, n):
    return (f"The {course} schedule lists {n} reading{'s' if n != 1 else ''} by class date. "
            f"Should I add a task to read each one the day before its class?")


def left_out(items):
    """items: (title, reason) the reader couldn't place even on a second look."""
    why = {"no date or lecture stated": "the document doesn't say when",
           "quote not found in the document": "I couldn't find where the document says it"}
    if len(items) == 1:
        title, reason = items[0]
        return (f"I couldn't place “{title}”: {why.get(reason, reason)}. "
                f"Is it something you need to do? If so, when?")
    listed = "; ".join(f"“{t}”" for t, _ in items)
    return (f"I couldn't place {len(items)} things, even on a second look: {listed}. "
            f"Do you need to do any of them? If so, tell me which and when.")


def which_slot(title, labels):
    return f"Which day is your “{title}”: {' or '.join(labels)}?"
