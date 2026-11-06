"""HTTP routes. Views stay thin: parse input, call a logic module, render."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from flask import (
    Blueprint,
    Response,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.wrappers import Response as BaseResponse

from . import analytics, calendar_view, followups, ics, participation, rsvp, scheduling
from .forms import (
    FormError,
    parse_date,
    parse_datetime,
    parse_exdates,
    parse_id_list,
    parse_optional_int,
)
from .models import (
    CONTACT_ROLES,
    EVENT_TYPE_LABELS,
    EVENT_TYPES,
    RSVP,
    Cohort,
    Contact,
    Event,
    FollowUp,
    Room,
    Student,
    db,
)
from .recurrence import RecurrenceError, describe
from .security import authenticate, is_safe_next, login_required

bp = Blueprint("main", __name__)


def _now() -> datetime:
    from . import current_time

    return current_time()


def _get_or_404(model, ident: int):  # type: ignore[no-untyped-def]
    obj = db.session.get(model, ident)
    if obj is None:
        abort(404)
    return obj


@bp.app_context_processor
def inject_globals() -> dict:
    return {"admin": g.get("admin"), "type_labels": EVENT_TYPE_LABELS, "now": _now()}


@bp.app_template_global("month_label")
@bp.app_template_filter("month_label")
def month_label(value: str) -> str:
    return datetime.strptime(value, "%Y-%m").strftime("%b %Y")


# ---------------------------------------------------------------- auth

@bp.route("/login", methods=["GET", "POST"])
def login() -> str | BaseResponse:
    if request.method == "POST":
        admin = authenticate(request.form.get("username", ""), request.form.get("password", ""))
        if admin:
            session.clear()
            session["admin_id"] = admin.id
            target = request.args.get("next")
            return redirect(target if is_safe_next(target) else url_for("main.dashboard"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")


@bp.post("/logout")
def logout() -> BaseResponse:
    session.clear()
    return redirect(url_for("main.login"))


# ---------------------------------------------------------------- dashboard

@bp.route("/")
@login_required
def dashboard() -> str:
    now = _now()
    upcoming = (Event.query.filter(Event.start >= now).order_by(Event.start).limit(8).all())
    students = Student.query.all()
    risk = participation.at_risk(students, now)
    return render_template(
        "dashboard.html",
        upcoming=upcoming,
        at_risk=risk[:8],
        at_risk_count=len(risk),
        student_count=len(students),
        cohorts=Cohort.query.order_by(Cohort.name).all(),
        overdue=followups.overdue(now.date()),
        overall=analytics.overall_rate(),
        event_count=Event.query.count(),
    )


# ---------------------------------------------------------------- cohorts & students

@bp.route("/cohorts")
@login_required
def cohorts() -> str:
    now = _now()
    rows = []
    for cohort in Cohort.query.order_by(Cohort.name).all():
        parts = participation.roster_participation(cohort.students, now)
        rated = [p.rate for p in parts if p.rate is not None]
        rows.append({
            "cohort": cohort,
            "size": len(cohort.students),
            "avg": round(100 * sum(rated) / len(rated), 1) if rated else None,
            "at_risk": sum(p.at_risk for p in parts),
        })
    return render_template("cohorts.html", rows=rows)


@bp.route("/cohorts/<int:cohort_id>")
@login_required
def cohort_detail(cohort_id: int) -> str:
    cohort = _get_or_404(Cohort, cohort_id)
    now = _now()
    upcoming = (Event.query.filter(Event.cohorts.any(id=cohort.id), Event.start >= now)
                .order_by(Event.start).limit(6).all())
    return render_template("cohort_detail.html", cohort=cohort, upcoming=upcoming,
                           rows=participation.roster_participation(cohort.students, now))


@bp.route("/students/<int:student_id>")
@login_required
def student_detail(student_id: int) -> str:
    student = _get_or_404(Student, student_id)
    now = _now()
    events = (Event.query.filter(Event.cohorts.any(id=student.cohort_id), Event.end <= now)
              .order_by(Event.start.desc()).all())
    marks = {a.event_id: a.present for e in events for a in e.attendance
             if a.student_id == student.id}
    rsvps = (RSVP.query.join(Event).filter(RSVP.student_id == student.id,
                                           Event.start >= now)
             .order_by(Event.start).all())
    return render_template("student_detail.html", student=student, events=events, marks=marks,
                           rsvps=rsvps, p=participation.participation_for(student, now))


@bp.route("/participation")
@login_required
def participation_report() -> str:
    cohort_id = request.args.get("cohort", type=int)
    only_risk = request.args.get("at_risk") == "1"
    q = Student.query
    if cohort_id:
        q = q.filter_by(cohort_id=cohort_id)
    rows = participation.roster_participation(q.all(), _now())
    if only_risk:
        rows = [r for r in rows if r.at_risk]
    return render_template("participation.html", rows=rows, cohort_id=cohort_id,
                           only_risk=only_risk, threshold=participation.AT_RISK_THRESHOLD,
                           cohorts=Cohort.query.order_by(Cohort.name).all())


# ---------------------------------------------------------------- events

@bp.route("/events")
@login_required
def events() -> str:
    now = _now()
    when = request.args.get("when", "upcoming")
    event_type = request.args.get("type", "")
    cohort_id = request.args.get("cohort", type=int)
    q = Event.query
    if when == "past":
        q = q.filter(Event.start < now).order_by(Event.start.desc())
    else:
        q = q.filter(Event.start >= now).order_by(Event.start)
    if event_type in EVENT_TYPES:
        q = q.filter(Event.event_type == event_type)
    if cohort_id:
        q = q.filter(Event.cohorts.any(id=cohort_id))
    return render_template("events.html", events=q.all(), when=when, event_type=event_type,
                           cohort_id=cohort_id, cohorts=Cohort.query.order_by(Cohort.name).all())


def _form_context(form: dict | None = None) -> dict:
    return {
        "form": form or {},
        "cohorts": Cohort.query.order_by(Cohort.name).all(),
        "rooms": Room.query.order_by(Room.name).all(),
        "contacts": Contact.query.order_by(Contact.name).all(),
        "event_types": EVENT_TYPES,
    }


@bp.route("/events/new", methods=["GET", "POST"])
@login_required
def event_new() -> str | BaseResponse:
    if request.method == "GET":
        return render_template("event_form.html", **_form_context())
    form = request.form
    try:
        start = parse_datetime(form.get("date", ""), form.get("start_time", ""), "Start")
        end = parse_datetime(form.get("date", ""), form.get("end_time", ""), "End")
        created = scheduling.create_events(
            title=form.get("title", ""),
            event_type=form.get("event_type", ""),
            start=start,
            end=end,
            cohort_ids=parse_id_list(form.getlist("cohort_ids")),
            room_id=parse_optional_int(form.get("room_id"), "Room"),
            capacity=parse_optional_int(form.get("capacity"), "Capacity"),
            required=form.get("required") == "on",
            description=form.get("description", ""),
            rrule=form.get("rrule", ""),
            exdates=parse_exdates(form.get("exdates", "")),
            contact_ids=parse_id_list(form.getlist("contact_ids")),
            allow_conflicts=form.get("allow_conflicts") == "on",
        )
    except (FormError, scheduling.ValidationError) as exc:
        flash(str(exc), "error")
        return render_template("event_form.html", **_form_context(form.to_dict(flat=False))), 422
    flash(f"Created {len(created)} event(s).", "success")
    return redirect(url_for("main.event_detail", event_id=created[0].id))


@bp.route("/events/<int:event_id>")
@login_required
def event_detail(event_id: int) -> str:
    event = _get_or_404(Event, event_id)
    statuses = {r.student_id: r.status for r in event.rsvps}
    going = sorted((r for r in event.rsvps if r.status == "going"),
                   key=lambda r: r.student.last_name)
    eligible = [s for s in event.invited_students if statuses.get(s.id) in (None, "cancelled")]
    rule_text = None
    if event.recurrence_rule:
        try:
            rule_text = describe(event.recurrence_rule)
        except RecurrenceError:
            rule_text = event.recurrence_rule
    series_count = (Event.query.filter_by(series_id=event.series_id).count()
                    if event.series_id else 1)
    return render_template("event_detail.html", event=event, going=going,
                           waitlist=rsvp.waitlist(event), eligible=eligible,
                           seats_left=rsvp.seats_left(event), rule_text=rule_text,
                           series_count=series_count, started=event.start <= _now(),
                           rooms=Room.query.order_by(Room.name).all())


@bp.post("/events/<int:event_id>/rsvp")
@login_required
def event_rsvp(event_id: int) -> BaseResponse:
    event = _get_or_404(Event, event_id)
    student = db.session.get(Student, request.form.get("student_id", type=int) or 0)
    if student is None:
        flash("Choose a student.", "error")
    else:
        try:
            record = rsvp.rsvp(event, student, _now())
            msg = "is going" if record.status == "going" else "joined the waitlist"
            flash(f"{student.full_name} {msg}.", "success")
        except rsvp.RSVPError as exc:
            flash(str(exc), "error")
    return redirect(url_for("main.event_detail", event_id=event.id))


@bp.post("/events/<int:event_id>/rsvp/<int:student_id>/cancel")
@login_required
def event_cancel(event_id: int, student_id: int) -> BaseResponse:
    event = _get_or_404(Event, event_id)
    student = _get_or_404(Student, student_id)
    try:
        promoted = rsvp.cancel(event, student)
        msg = f"Cancelled {student.full_name}."
        if promoted:
            msg += f" {promoted.student.full_name} was promoted from the waitlist."
        flash(msg, "success")
    except rsvp.RSVPError as exc:
        flash(str(exc), "error")
    return redirect(url_for("main.event_detail", event_id=event.id))


@bp.post("/events/<int:event_id>/capacity")
@login_required
def event_capacity(event_id: int) -> BaseResponse:
    event = _get_or_404(Event, event_id)
    try:
        promoted = rsvp.set_capacity(event, parse_optional_int(request.form.get("capacity"),
                                                               "Capacity"))
        flash(f"Capacity updated. {len(promoted)} promoted from the waitlist.", "success")
    except (FormError, rsvp.RSVPError) as exc:
        flash(str(exc), "error")
    return redirect(url_for("main.event_detail", event_id=event.id))


@bp.post("/events/<int:event_id>/reschedule")
@login_required
def event_reschedule(event_id: int) -> BaseResponse:
    event = _get_or_404(Event, event_id)
    form = request.form
    try:
        start = parse_datetime(form.get("date", ""), form.get("start_time", ""), "Start")
        end = parse_datetime(form.get("date", ""), form.get("end_time", ""), "End")
        scheduling.reschedule(event, start, end,
                              parse_optional_int(form.get("room_id"), "Room"),
                              allow_conflicts=form.get("allow_conflicts") == "on")
        flash("Event rescheduled.", "success")
    except (FormError, scheduling.ValidationError) as exc:
        flash(str(exc), "error")
    return redirect(url_for("main.event_detail", event_id=event.id))


@bp.post("/events/<int:event_id>/delete")
@login_required
def event_delete(event_id: int) -> BaseResponse:
    event = _get_or_404(Event, event_id)
    try:
        n = scheduling.delete_event(event, request.form.get("scope", "single"))
    except scheduling.ValidationError as exc:
        flash(str(exc), "error")
        return redirect(url_for("main.event_detail", event_id=event_id))
    flash(f"Deleted {n} event(s).", "success")
    return redirect(url_for("main.events"))


@bp.route("/events/<int:event_id>/attendance", methods=["GET", "POST"])
@login_required
def event_attendance(event_id: int) -> str | BaseResponse:
    event = _get_or_404(Event, event_id)
    if request.method == "POST":
        try:
            present = set(parse_id_list(request.form.getlist("present")))
            n = participation.mark_attendance(event, present, _now())
            followups.ensure_thank_yous(event)
            flash(f"Attendance saved: {n} of {len(event.invited_students)} present.", "success")
            return redirect(url_for("main.event_detail", event_id=event.id))
        except (FormError, participation.AttendanceError) as exc:
            flash(str(exc), "error")
    marks = {a.student_id: a.present for a in event.attendance}
    going_ids = {r.student_id for r in event.rsvps if r.status == "going"}
    return render_template("attendance.html", event=event, marks=marks, going_ids=going_ids,
                           started=event.start <= _now())


# ---------------------------------------------------------------- calendar & ics

@bp.route("/calendar")
@login_required
def calendar_page() -> str:
    now = _now()
    year = request.args.get("year", type=int) or now.year
    month = request.args.get("month", type=int) or now.month
    if not 1 <= month <= 12 or not 2000 <= year <= 2100:
        abort(404)
    cohort_id = request.args.get("cohort", type=int)
    start, end = calendar_view.month_bounds(year, month)
    q = Event.query.filter(Event.start >= start - timedelta(days=7),
                           Event.start < end + timedelta(days=7))
    if cohort_id:
        q = q.filter(Event.cohorts.any(id=cohort_id))
    weeks = calendar_view.month_grid(year, month, q.all())
    return render_template(
        "calendar.html", weeks=weeks, year=year, month=month, cohort_id=cohort_id,
        title=date(year, month, 1).strftime("%B %Y"),
        prev=calendar_view.shift_month(year, month, -1),
        next=calendar_view.shift_month(year, month, 1),
        cohorts=Cohort.query.order_by(Cohort.name).all(), today=now.date(),
    )


def _ics_response(events: list[Event], name: str, filename: str) -> Response:
    body = ics.to_ics(events, name)
    return Response(body, mimetype="text/calendar",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@bp.route("/cohorts/<int:cohort_id>/calendar.ics")
def cohort_ics(cohort_id: int) -> Response:
    """Public subscription feed: event titles, times and rooms only, no student data."""
    cohort = _get_or_404(Cohort, cohort_id)
    events = Event.query.filter(Event.cohorts.any(id=cohort.id)).order_by(Event.start).all()
    slug = cohort.name.lower().replace(" ", "-")
    return _ics_response(events, f"ACE {cohort.name}", f"ace-{slug}.ics")


# ---------------------------------------------------------------- contacts & follow-ups

@bp.route("/contacts", methods=["GET", "POST"])
@login_required
def contacts() -> str | BaseResponse:
    if request.method == "POST":
        fields = {k: request.form.get(k, "").strip()
                  for k in ("name", "company", "title", "email", "role")}
        if not all(fields.values()):
            flash("All contact fields are required.", "error")
        elif "@" not in fields["email"]:
            flash("Enter a valid email.", "error")
        elif fields["role"] not in CONTACT_ROLES:
            flash("Unknown role.", "error")
        else:
            db.session.add(Contact(**fields))
            db.session.commit()
            flash(f"Added {fields['name']}.", "success")
            return redirect(url_for("main.contacts"))
    role = request.args.get("role", "")
    q = Contact.query.order_by(Contact.name)
    if role in CONTACT_ROLES:
        q = q.filter_by(role=role)
    return render_template("contacts.html", contacts=q.all(), roles=CONTACT_ROLES, role=role)


@bp.route("/contacts/<int:contact_id>")
@login_required
def contact_detail(contact_id: int) -> str:
    contact = _get_or_404(Contact, contact_id)
    events = (Event.query.filter(Event.contacts.any(id=contact.id))
              .order_by(Event.start.desc()).all())
    return render_template("contact_detail.html", contact=contact, events=events,
                           today=_now().date(), status=followups.status)


@bp.route("/followups")
@login_required
def followup_list() -> str:
    today = _now().date()
    return render_template("followups.html", groups=followups.grouped(today), today=today,
                           contacts=Contact.query.order_by(Contact.name).all(),
                           events=Event.query.filter(Event.contacts.any())
                           .order_by(Event.start.desc()).all())


@bp.post("/followups/new")
@login_required
def followup_new() -> BaseResponse:
    contact = db.session.get(Contact, request.form.get("contact_id", type=int) or 0)
    event = db.session.get(Event, request.form.get("event_id", type=int) or 0)
    try:
        if contact is None or event is None:
            raise FormError("Choose a contact and an event")
        followups.add_followup(contact, event, parse_date(request.form.get("due", ""), "Due"),
                               request.form.get("notes", ""))
        flash("Follow-up added.", "success")
    except (FormError, followups.FollowUpError) as exc:
        flash(str(exc), "error")
    return redirect(url_for("main.followup_list"))


@bp.post("/followups/<int:fu_id>/complete")
@login_required
def followup_complete(fu_id: int) -> BaseResponse:
    fu = _get_or_404(FollowUp, fu_id)
    try:
        followups.complete(fu, _now().date(), request.form.get("notes", ""))
        flash(f"Marked follow-up with {fu.contact.name} done.", "success")
    except followups.FollowUpError as exc:
        flash(str(exc), "error")
    return redirect(request.form.get("back") if is_safe_next(request.form.get("back"))
                    else url_for("main.followup_list"))


@bp.post("/followups/<int:fu_id>/reopen")
@login_required
def followup_reopen(fu_id: int) -> BaseResponse:
    followups.reopen(_get_or_404(FollowUp, fu_id))
    flash("Follow-up reopened.", "success")
    return redirect(url_for("main.followup_list"))


# ---------------------------------------------------------------- analytics

@bp.route("/analytics")
@login_required
def analytics_page() -> str:
    return render_template("analytics.html", rates=analytics.attendance_rates(),
                           overall=analytics.overall_rate())
