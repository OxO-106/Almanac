# 02: Plan by hand

**What to build:** The user can create, edit and delete Goals, Projects, Tasks, Events, Deadlines and Courses in the UI. Tasks have a due date and a do date. Today lists today's do dates, Events and Deadlines, and Tasks can be ticked off anywhere.

**Blocked by:** 01 (Walking skeleton)

**Status:** done

- [x] CRUD over HTTP for every plan entity, with Goal → Project → Task links
- [x] Task has due date, do date, Work kind, size, status; Course has number + instructor
- [x] Today shows today's do-date Tasks, Events and Deadlines in LA time
- [x] Ticking a Task done persists and removes it from Today's open list
- [x] API tests cover create/edit/delete/tick and Today's contents at a set clock time
