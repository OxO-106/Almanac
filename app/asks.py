"""How the assistant words its questions: every question text is made here."""


def who_teaches(label):
    return f"Who teaches {label}? The document doesn't name the instructor."


def when_is(title, kind):
    return f"When is “{title}”{'' if kind == 'events' else ' due'}? The document doesn't say."


def which_day(week, monday, friday, title):
    return f"Which day in Week {week} ({monday:%b} {monday.day} – {friday:%b} {friday.day}) is “{title}”? The document only gives the week."


def meeting_time(short, days):
    return f"What time does {short} meet on {'/'.join(days)}? The document doesn't say."


def same_course(existing, name):
    return f"You already have {existing}. Is {name} a different course?"


def which_section(code, title, names):
    return f"Which of your courses is {code} ({title}) on Bruin Learn: {names}?"


def paper_pages(title):
    return f"How many pages is the paper for “{title}”?"
