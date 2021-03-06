 # coding: utf8
from datetime import timedelta as timed
import datetime
import time
from gluon.storage import Storage
from gluon import current
from gluon.serializers import json as dumps
from gluon.tools import prettydate
from plugin_cs_monitor.html_helpers import nice_worker_status, graph_colors_task_status
from plugin_cs_monitor.html_helpers import nice_worker_stats, nice_task_status, mybootstrap
from plugin_cs_monitor.html_helpers import fixup_bs3_widgets
from plugin_cs_monitor.scheduler_helpers import requeue_task
from gluon.scheduler import JobGraph
from collections import defaultdict

response.files.append(URL('static', 'plugin_cs_monitor/js/stupidtable/stupidtable.min.js'))

response.files.append(URL('static', 'plugin_cs_monitor/js/underscore/underscore.min.js'))

response.files.append(URL('static', 'plugin_cs_monitor/js/moment/moment.min.js'))
response.files.append(URL('static', 'plugin_cs_monitor/js/datetimepicker/bootstrap-datetimepicker.min.js'))
response.files.append(URL('static', 'plugin_cs_monitor/js/datetimepicker/bootstrap-datetimepicker.min.css'))

response.files.append(URL('static', 'plugin_cs_monitor/js/c3/d3.v3.min.js'))
response.files.append(URL('static', 'plugin_cs_monitor/js/c3/c3.css'))
response.files.append(URL('static', 'plugin_cs_monitor/js/c3/c3.min.js'))

response.files.append(URL('static', 'plugin_cs_monitor/js/dagre/dagre-d3.min.js'))

response.files.append(URL('static', 'plugin_cs_monitor/js/select2/select2.min.js'))
response.files.append(URL('static', 'plugin_cs_monitor/js/select2/select2-bootstrap.css'))

response.files.append(URL('static', 'plugin_cs_monitor/js/app.js'))

##Configure start
sc_cache = cache.ram
GROUPING_MODE = 'database'  # or 'python'
ANALYZE_CACHE_TIME = 60
TASKS_SUMMARY_CACHE_TIME = 10
PAGINATE = 10
##Configure end

s = current._scheduler
dbs = s.db
st = dbs.scheduler_task
sw = dbs.scheduler_worker
sr = dbs.scheduler_run
sd = dbs.scheduler_task_deps


ANALYZE_CACHE_KWARGS = {
    'cache': (cache.with_prefix(sc_cache, "plugin_cs_monitor"), ANALYZE_CACHE_TIME),
    'cacheable': True}

TASKS_SUMMARY_KWARGS = {
    'cache': (cache.with_prefix(sc_cache, "plugin_cs_monitor"), TASKS_SUMMARY_CACHE_TIME),
    'cacheable' : True}

response.meta.author = 'Niphlod <niphlod@gmail.com>'
response.title = 'ComfortScheduler Monitor'
response.subtitle = '2.0.0'
response.static_version = '2.0.0'

try:
    response.menu.append(
        ('Comfy Scheduler Monitor', False, URL('plugin_cs_monitor', 'index'), []),
    )
except:
    pass


@auth.requires_login()
def index():
    return dict()

@auth.requires_signature()
def workers():
    session.forget(response)
    now = s.utc_time and request.utcnow or request.now
    limit = now - timed(seconds=s.heartbeat * 3 * 10)
    w = s.get_workers()
    for worker, props in w.iteritems():
        if props.last_heartbeat < limit:
            props.status_ = nice_worker_status('Probably Dead')
        else:
            props.status_ = nice_worker_status(props.status)
        props.worker_stats_ = nice_worker_stats(props.worker_stats)

    BASEURL = URL("plugin_cs_monitor", "wactions", user_signature=True)

    return dict(w=w, BASEURL=BASEURL, limit=limit)


@auth.requires_signature()
def wactions():
    session.forget(response)
    default = URL('workers', user_signature=True)
    if not request.vars.action or request.vars.action == 'none':
        session.flash = "No action selected"
        redirect(default)
    if not request.vars.w_records:
        session.flash = "No worker selected"
        redirect(default)
    if isinstance(request.vars.w_records, str):
        r = [request.vars.w_records]
    else:
        r = request.vars.w_records
    for w in r:
        s.set_worker_status(action=request.vars.action, worker_name=w)
    rtn = dbs(sw.worker_name.belongs(r)).validate_and_update(status=request.vars.action)
    session.flash = "%s workers updated correctly" % len(r)
    redirect(default)


@auth.requires_signature()
def tactions():
    session.forget(response)
    default = request.vars.current_page or URL('task_group', user_signature=True)
    action = request.vars.action
    if not action or action == 'none':
        session.flash = "No action selected"
        redirect(default)
    if not request.vars.t_records:
        session.flash = "No tasks selected"
        redirect(default)
    if isinstance(request.vars.t_records, str):
        t = [request.vars.t_records]
    else:
        t = request.vars.t_records
    if action == 'disable':
        rtn = dbs(st.id.belongs(t)).update(enabled=False)
        if rtn:
            session.flash = "%s tasks disabled correctly" % rtn
        else:
            session.flash = "No tasks disabled"
        redirect(default)
    elif action == 'enable':
        rtn = dbs(st.id.belongs(t)).update(enabled=True)
        if rtn:
            session.flash = "%s tasks enabled correctly" % rtn
        else:
            session.flash = "No tasks enabled"
        redirect(default)
    elif action == 'delete':
        rtn = dbs(st.id.belongs(t)).delete()
        if rtn:
            session.flash = "%s tasks deleted" % rtn
        else:
            session.flash = "No tasks deleted"
        redirect(default)
    elif action == 'clone':
        requeued = []
        tasks = dbs(st.id.belongs(t)).select()
        for row in tasks:
            res = requeue_task(st, row)
            if res:
                requeued.append(requeued)
        if requeued:
            session.flash = "%s tasks successfully requeued" % (len(requeued))
        else:
            session.flash = "Cloning failed"
    elif action == 'stop':
        stopped = []
        tasks = dbs(st.id.belongs(t)).select()
        for row in tasks:
            res = s.stop_task(row.id)
            if res == 1:
                stopped.append(res)
        if stopped:
            session.flash = "%s tasks successfully stopped" % (len(stopped))
        else:
            session.flash = "Stopping failed"

    redirect(default)


@auth.requires_signature()
def tasks():
    session.forget(response)
    c = cache_tasks_counts(st)

    return dict(c=c)


def cache_tasks_counts(t):

    if GROUPING_MODE == 'python':
        res = dbs(t.id > 0).select(t.group_name, t.status, orderby=t.group_name|t.status, **TASKS_SUMMARY_KWARGS)
        rtn = {}
        for row in res:
            k = row.group_name
            s = row.status
            if k not in rtn:
                rtn[k] = defaultdict(lambda : { 'count' : 0, 'pretty' : nice_task_status(s)})
                rtn[k][s]['count'] += 1
            else:
                rtn[k][s]['count'] += 1
    else:
        c = t.id.count()
        res = dbs(t.id > 0).select(c, t.group_name, t.status, groupby=t.group_name|t.status, **TASKS_SUMMARY_KWARGS)
        rtn = Storage()
        for row in res:
            k = row.scheduler_task.group_name
            s = row.scheduler_task.status
            if k not in rtn:
                rtn[k] = {s : { 'count' : row[c], 'pretty' : nice_task_status(s)}}
            else:
                rtn[k][s] = { 'count' : row[c], 'pretty' : nice_task_status(s)}

    return rtn


@auth.requires_signature()
def task_group():
    session.forget(response)
    group_name, status = request.args(0), request.args(1)
    if not group_name:
        return ''
    c = cache_tasks_counts(st)
    paginate = PAGINATE
    try:
        page = int(request.vars.page or 1) - 1
    except ValueError:
        page = 0
    limitby = (paginate * page, paginate * (page + 1))
    q = (st.group_name == group_name)
    if status:
        q = q & (st.status == status)
        if group_name in c and status in c[group_name]:
            total = c[group_name][status]['count']
        else:
            total = 0
    else:
        if group_name in c:
            total = sum([a['count'] for a in c[group_name].values()])
        else:
            total = 0
    qfilter = request.vars.qfilter
    if qfilter:
        parts = []
        fields = [st.task_name, st.group_name, st.function_name, st.uuid, st.args, st.vars, st.assigned_worker_name]
        for a in fields:
            parts.append(a.contains(qfilter))
            qf = reduce(lambda a, b: a | b, parts)
        q = q & qf
        total = dbs(q).count()
    tasks = dbs(q).select(limitby=limitby, orderby=~st.next_run_time)
    for row in tasks:
        row.status_ = nice_task_status(row.status)

    BASEURL = URL("plugin_cs_monitor", "tactions", user_signature=True)
    return dict(tasks=tasks, paginate=paginate, total=total, page=page, BASEURL=BASEURL)


@auth.requires_signature()
def task_details():
    session.forget(response)
    id = request.args(0)
    task = dbs(st.id == id).select().first()
    if not task:
        return ''
    task.status_ = nice_task_status(task.status)
    deps = dbs((sd.task_parent == id) | (sd.task_child == id)).select(sd.job_name, groupby=sd.job_name)
    deps = [row.job_name for row in deps]
    return dict(task=task, st=st, deps=deps)


@auth.requires_signature()
def run_details():
    session.forget(response)
    task_id = request.args(0)
    if not task_id:
        return ''
    paginate = 10
    try:
        page = int(request.vars.page or 1)-1
    except ValueError:
        page = 0
    limitby = (paginate*page,paginate*(page+1))
    total = dbs(sr.task_id == task_id).count()
    q = sr.task_id == task_id
    qfilter = request.vars.qfilter
    if qfilter:
        parts = []
        fields = [sr.status, sr.run_result, sr.run_output, sr.traceback, sr.worker_name]
        for a in fields:
            parts.append(a.contains(qfilter))
            qf = reduce(lambda a, b: a | b, parts)
        q = q & qf
    runs = dbs(q).select(orderby=~sr.stop_time|~sr.id, limitby=limitby)
    for row in runs:
        row.status_ = nice_task_status(row.status)
        if row.start_time and row.stop_time:
            td = row.stop_time - row.start_time
            td = (td.seconds + td.days * 24 * 3600)
        else:
            td = 0
        row.elapsed_seconds_ = td
    return dict(runs=runs, paginate=paginate, total=total, page=page)


@auth.requires_signature()
def run_traceback():
    session.forget(response)
    run_id = request.args(0)
    if not run_id:
        return ''
    rtn = dbs(sr.id == run_id).select(sr.traceback).first()
    if not rtn:
        return ''
    return dict(traceback=rtn.traceback)


@auth.requires_signature()
def edit_task():
    task_id = request.args(0)
    if task_id is None:
        return ''
    try:
        task_id = int(task_id)
    except:
        return ''
    task = dbs(st.id == task_id).select().first()

    if not task and task_id != 0:
        return ''
    if request.args(1) == 'delete':
        task.delete_record()
        session.flash = 'Task deleted correctly'
        redirect(URL('index'))
    elif request.args(1) == 'stop':
        rtn = s.stop_task(task_id)
        if rtn == 1:
            session.flash = 'Task stopped'
        else:
            session.flash = 'Nothing to do...'
        redirect(URL('task_details', args=task.id, user_signature=True))
    elif request.args(1) == 'clone':
        result = requeue_task(st, task)
        if result:
            session.flash = 'Task requeued correctly'
            redirect(URL('task_details', args=result, user_signature=True))
        else:
            session.flash = 'Task clone failed'
            redirect(URL('edit_task', args=task_id, user_signature=True))
    elif request.args(1) == 'new':
        if task_id != 0:
            st.function_name.default = task.function_name
            st.task_name.default = task.task_name
            st.group_name.default = task.group_name
    elif request.args(1) == 'requeue':
        result = requeue_task(st, task, clone=False)
        if result:
            session.flash = 'Task requeued correctly'
            redirect(URL('task_details', args=result, user_signature=True))
        else:
            session.flash = 'Task requeue failed'
            redirect(URL('edit_task', args=task_id, user_signature=True))
        task = None

    fixup_bs3_widgets(SQLFORM)

    st.function_name.requires = IS_NOT_EMPTY()
    form = SQLFORM(st, task, formstyle=mybootstrap)
    if form.process().accepted:
        if request.args(1) == 'new':
            response.flash = 'Task created correctly'
        else:
            response.flash = 'Updated correctly'
    elif form.errors:
        response.flash = 'Errors detected'
    return dict(form=form, task=task)


def gb_duration(q):
    #byduration
    count_ = sr.id.count()
    status_ = sr.status
    duration_g = sr.stop_time.epoch() - sr.start_time.epoch()

    if GROUPING_MODE == 'python':
        gb_duration_rows = dbs(q).select(status_, sr.start_time, sr.stop_time, orderby=status_|duration_g)
        gb_duration_series = {}
        for row in gb_duration_rows:
            status = row.status
            duration_ = row.stop_time - row.start_time
            duration = (duration_.seconds + duration_.days * 24 * 3600)
            if status not in gb_duration_series:
                gb_duration_series[status] = defaultdict(int, {duration : 1})
            else:
                gb_duration_series[status][duration] += 1
    else:
        gb_duration_rows = dbs(q).select(count_, status_, duration_g, groupby=status_|duration_g, orderby=status_|duration_g)
        #convert to duration series
        gb_duration_series = {}
        for row in gb_duration_rows:
            status = row.scheduler_run.status
            duration = row[duration_g]
            howmany = row[count_]
            if status not in gb_duration_series:
                gb_duration_series[status] = {duration : howmany}
            else:
                if duration not in gb_duration_series[status]:
                    gb_duration_series[status][duration] = howmany

    jgb_duration_series = []
    for k,v in gb_duration_series.items():
        jgb_duration_series.append(
                {'label': k, 'data' : [[kk,vv] for kk,vv in v.items()], 'color' : graph_colors_task_status(k)}
            )

    return gb_duration_rows, jgb_duration_series


def gb_status(q, mode='runs'):
    #bystatus
    if GROUPING_MODE == 'python':
        if mode == 'runs':
            gb_status_rows = dbs(q).select(sr.status, orderby=sr.status, **ANALYZE_CACHE_KWARGS)
            gb_status_series = defaultdict(int)
            for row in gb_status_rows:
                status = row.status
                gb_status_series[status] += 1
        else:
            gb_status_series = defaultdict(int)
            gb_status_rows = dbs(q).select(st.status, st.times_run, **ANALYZE_CACHE_KWARGS)
            for row in gb_status_rows:
                gb_status_series[row.status] += row.times_run
    else:
        if mode == 'runs':
            status_ = sr.status
            count_ = sr.id.count()
            gb_status_rows = dbs(q).select(count_, status_, groupby=status_, orderby=status_, **ANALYZE_CACHE_KWARGS)
            gb_status_series = defaultdict(int)
            for row in gb_status_rows:
                status = row.scheduler_run.status
                howmany = row[count_]
                gb_status_series[status] += howmany
        else:
            status_ = st.status
            count_ = st.times_run.sum()
            gb_status_rows = dbs(q).select(count_, status_, groupby=status_, orderby=status_, **ANALYZE_CACHE_KWARGS)
            gb_status_series = defaultdict(int)
            for row in gb_status_rows:
                status = row.scheduler_task.status
                howmany = row[count_]
                gb_status_series[status] += howmany


    jgb_status_series = []
    for k,v in gb_status_series.items():
        jgb_status_series.append(
            {'label' : k, 'color' : graph_colors_task_status(k), 'data' : [v]}
        )

    return gb_status_rows, jgb_status_series


def bydate(q, mode):
    #by period

    if GROUPING_MODE == 'python':
        if mode == 'runs':
            gb_when_rows = dbs(q).select(sr.status, sr.start_time, orderby=sr.status|sr.start_time, **ANALYZE_CACHE_KWARGS)
            gb_when_series = {}
            for row in gb_when_rows:
                refdate = row.start_time.strftime('%Y-%m-%d')
                if row.status not in gb_when_series:
                    gb_when_series[row.status] = defaultdict(int, {refdate : 1})
                else:
                    gb_when_series[row.status][refdate] += 1
        else:
            gb_when_rows = dbs(q).select(st.status, st.times_run, st.last_run_time, orderby=st.status|st.last_run_time, **ANALYZE_CACHE_KWARGS)
            gb_when_series = {}
            for row in gb_when_rows:
                refdate = row.last_run_time.strftime('%Y-%m-%d')
                if row.status not in gb_when_series:
                    gb_when_series[row.status] = defaultdict(int, {refdate : 1})
                else:
                    gb_when_series[row.status][refdate] += row.times_run
    else:
        if mode == 'runs':
            count_ = sr.id.count()
            status_ = sr.status
            d = sr.start_time.year()|sr.start_time.month()|sr.start_time.day()
            gb_when_rows = dbs(q).select(count_, status_, sr.start_time.year(), sr.start_time.month(), sr.start_time.day(), groupby=status_|d, orderby=status_|d, **ANALYZE_CACHE_KWARGS)
            gb_when_series = {}
            for row in gb_when_rows:
                status = row.scheduler_run.status
                howmany = row[count_]
                refdate = row[sr.start_time.year()], row[sr.start_time.month()], row[sr.start_time.day()]
                refdate = datetime.date(*refdate).strftime('%Y-%m-%d')
                if status not in gb_when_series:
                    gb_when_series[status] = {refdate : howmany}
                else:
                    gb_when_series[status][refdate] = howmany
        else:
            count_ = st.times_run.sum()
            status_ = st.status
            d = st.last_run_time.year()|st.last_run_time.month()|st.last_run_time.day()
            gb_when_rows = dbs(q).select(count_, status_, st.last_run_time.year(), st.last_run_time.month(), st.last_run_time.day(), groupby=status_|d, orderby=status_|d, **ANALYZE_CACHE_KWARGS)
            gb_when_series = {}
            for row in gb_when_rows:
                status = row.scheduler_task.status
                howmany = row[count_]
                refdate = row[st.last_run_time.year()], row[st.last_run_time.month()], row[st.last_run_time.day()]
                refdate = datetime.date(*refdate).strftime('%Y-%m-%d')
                if status not in gb_when_series:
                    gb_when_series[status] = {refdate : howmany}
                else:
                    gb_when_series[status][refdate] = howmany

    jgb_when_series = []
    for k, v in gb_when_series.items():
        jgb_when_series.append(
            {'label': k, 'data' : [[kk,vv] for kk,vv in v.items()], 'color' : graph_colors_task_status(k)}
        )

    return gb_when_rows, jgb_when_series


def byday(q, day, mode):
    #by period
    if GROUPING_MODE == 'python':
        if mode == 'runs':
            gb_whend_rows = dbs(q).select(sr.status, sr.start_time, orderby=sr.status|sr.start_time, **ANALYZE_CACHE_KWARGS)
            gb_whend_series = {}
            for row in gb_whend_rows:
                status = row.status
                refdate = row.start_time.strftime('%Y-%m-%d %H:%M')
                if status not in gb_whend_series:
                    gb_whend_series[status] = defaultdict(int, {refdate : 1})
                else:
                    gb_whend_series[status][refdate] += 1
        else:
            gb_whend_rows = dbs(q).select(st.times_run, st.status, st.last_run_time, orderby=st.status|st.last_run_time, **ANALYZE_CACHE_KWARGS)
            gb_whend_series = {}
            for row in gb_whend_rows:
                status = row.status
                refdate = row.last_run_time.strftime('%Y-%m-%d %H:%M')
                if status not in gb_whend_series:
                    gb_whend_series[status] = defaultdict(int, {refdate : row.times_run})
                else:
                    gb_whend_series[status][refdate] += row.times_run
    else:
        if mode == 'runs':
            count_ = sr.id.count()
            status_ = sr.status
            d = sr.start_time.hour()|sr.start_time.minutes()
            gb_whend_rows = dbs(q).select(count_, status_, sr.start_time.hour(), sr.start_time.minutes(), groupby=status_|d, orderby=status_|d, **ANALYZE_CACHE_KWARGS)
            gb_whend_series = {}
            for row in gb_whend_rows:
                status = row.scheduler_run.status
                howmany = row[count_]
                refdate = day.year, day.month, day.day, row[sr.start_time.hour()], row[sr.start_time.minutes()], 0
                refdate = datetime.datetime(*refdate).strftime('%Y-%m-%d %H:%M')
                if status not in gb_whend_series:
                    gb_whend_series[status] = {refdate : howmany}
                else:
                    gb_whend_series[status][refdate] = howmany
        else:
            count_ = st.times_run.sum()
            status_ = st.status
            d = st.last_run_time.hour()|st.last_run_time.minutes()
            gb_whend_rows = dbs(q).select(count_, status_, st.last_run_time.hour(), st.last_run_time.minutes(), groupby=status_|d, orderby=status_|d, **ANALYZE_CACHE_KWARGS)
            gb_whend_series = {}
            for row in gb_whend_rows:
                status = row.scheduler_task.status
                howmany = row[count_]
                refdate = day.year, day.month, day.day, row[st.last_run_time.hour()], row[st.last_run_time.minutes()], 0
                refdate = datetime.datetime(*refdate).strftime('%Y-%m-%d %H:%M')
                if status not in gb_whend_series:
                    gb_whend_series[status] = {refdate : howmany}
                else:
                    gb_whend_series[status][refdate] = howmany

    jgb_whend_series = []
    for k, v in gb_whend_series.items():
        jgb_whend_series.append(
            {'label': k, 'data' : [[kk,vv] for kk,vv in v.items()], 'color' : graph_colors_task_status(k)}
        )

    return gb_whend_rows, jgb_whend_series


@auth.requires_signature()
def analyze_task():
    session.forget(response)
    task_id = request.args(0)
    if not task_id:
        return ''
    task = dbs(st.id == task_id).select().first()

    if not task:
        return ''

    q = sr.task_id == task_id

    first_run = dbs(q).select(sr.start_time, orderby=sr.start_time, limitby=(0,1)).first()

    last_run = dbs(q).select(sr.start_time, orderby=~sr.start_time, limitby=(0,1)).first()

    first_run_pretty = first_run and prettydate(first_run.start_time) or 'Never'
    last_run_pretty = last_run and prettydate(last_run.start_time) or 'Never'

    if not first_run:
        mode = 'no_runs'
        #we can rely on the data on the scheduler_task table because no scheduler_run were found
        q = st.id == task_id
        first_run_pretty = 'Never'
    else:
        mode = 'runs'
    if len(request.args) >= 2:
        if request.args(1) == 'byfunction':
            if mode == 'runs':
                q = sr.task_id.belongs(dbs(st.function_name == task.function_name)._select(st.id))
            else:
                q = st.function_name == task.function_name
        elif request.args(1) == 'bytaskname':
            if mode == 'runs':
                q = sr.task_id.belongs(dbs(st.task_name == task.task_name)._select(st.id))
            else:
                q = st.task_name == task.task_name
        elif request.args(1) == 'this':
            if mode == 'runs':
                q = sr.task_id == task_id
            else:
                q = st.id == task_id

    if len(request.args) == 4 and request.args(2) == 'byday':
            daysback = int(request.args(3))
            now = s.utc_time and request.utcnow or request.now
            day = now.date() - timed(days=daysback)
            if mode == 'runs':
                q = q & ((sr.start_time >= day) & (sr.start_time < day + timed(days=1)))
            else:
                q = q & ((st.last_run_time >= day) & (st.last_run_time < day + timed(days=1)))

    if mode == 'runs':
        gb_duration_rows, jgb_duration_series = gb_duration(q)
        jgb_duration_series = dumps(jgb_duration_series)
    else:
        #no duration can be calculated using the scheduler_task table only
        jgb_duration_series = dumps([])

    gb_status_rows, jgb_status_series = gb_status(q, mode)
    jgb_status_series = dumps(jgb_status_series)

    gb_when_rows, jgb_when_series = bydate(q, mode)
    jgb_when_series = dumps(jgb_when_series)

    if len(request.args) == 4 and request.args(2) == 'byday':
        gb_whend_rows, jgb_whend_series = byday(q, day, mode)
        jgb_whend_series = dumps(jgb_whend_series)
    else:
        jgb_whend_series = dumps([[]])

    return locals()


@auth.requires_signature()
def clear_cache():
    sc_cache.clear("plugin_cs_monitor.*")
    session.flash = 'Cache Cleared'
    redirect(URL("index"), client_side=True)


@auth.requires_signature()
def delete_tasks():
    session.forget(response)
    period = request.args(0)
    if not period in ['1d', '3d', '1w', '1m', '3m']:
        return ''
    now = s.utc_time and request.utcnow or request.now
    if period == '1d':
        limit = timed(days=1)
    elif period == '3d':
        limit = timed(days=3)
    elif period == '1w':
        limit = timed(days=7)
    elif period == '1m':
        limit = timed(days=30)
    elif period == '3m':
        limit = timed(days=90)
    limit = now - limit
    if request.vars.confirm == '1':
        statuses = ['COMPLETED', 'FAILED', 'EXPIRED', 'STOPPED']
        dbs(
            (st.status.belongs(statuses)) &
            (st.start_time < limit)
             ).delete()
        sc_cache.clear("plugin_cs_monitor.*")
        redirect(URL('index'))
    limit = limit.strftime('%Y-%m-%d %H:%M:%S')
    return dict(limit=limit)


@auth.requires_signature(hash_vars=False)
def jobs():
    return dict()


@auth.requires_signature(hash_vars=False)
def jobs_render():
    session.forget(response)
    if request.vars.job_name:
        q = sd.job_name == request.vars.job_name
        all_jobs = {request.vars.job_name : 'a_0'}
        newjob = None
    else:
        q = sd.id > 0
        all_jobs = dbs(q).select(sd.job_name, groupby=sd.job_name)
        all_jobs = dict([(row.job_name, "a_%s" % k) for k, row in enumerate(all_jobs)])
        newjob = str(int(time.mktime(datetime.datetime.utcnow().timetuple())))

    all_deps = dbs(q).select()
    all_nodes = {}
    all_edges = {}
    for row in all_deps:
        jname_slug = all_jobs[row.job_name]
        if jname_slug not in all_nodes:
            all_nodes[jname_slug] = {}
        all_nodes[jname_slug][row.task_parent] = None
        all_nodes[jname_slug][row.task_child] = None
        if jname_slug not in all_edges:
            all_edges[jname_slug] = []
        all_edges[jname_slug].append((row.task_child, row.task_parent,
            dict(style="stroke: %s" % (row.can_visit and '#5CB85C' or '#D9534F'))))

    all_tasks_ids = {}
    for k, v in all_nodes.iteritems():
        for id in v.keys():
            all_tasks_ids[id] = None

    all_tasks_labels = dbs(st.id.belongs(all_tasks_ids.keys())).select(
        st.id, st.function_name, st.task_name, st.status
        ).as_dict()

    for k, v in all_nodes.iteritems():
        for id in v.keys():
            all_nodes[k][id] = dict(label=all_tasks_labels[id]['task_name'],
                style="fill: %s;" % graph_colors_task_status(all_tasks_labels[id]['status']),
                title="%(id)s (%(function_name)s): %(status)s" % all_tasks_labels[id],
                linkto=URL('task_details', args=id, user_signature=True))

    return dict(all_jobs=all_jobs, all_edges=dumps(all_edges), all_nodes=dumps(all_nodes), newjob=newjob)

@auth.requires_signature(hash_vars=False)
def edit_job():
    posted = request.post_vars
    if posted:
        if ',' in posted.task_child and ',' in posted.task_parent:
            session.flash = 'Only one multiple value allowed'
            return dict()
        if ',' in posted.task_child:
            posted.task_child = posted.task_child.split(',')
        else:
            posted.task_child = [posted.task_child]
        if ',' in posted.task_parent:
            posted.task_parent = posted.task_parent.split(',')
        else:
            posted.task_parent = [posted.task_parent]
        myjob = JobGraph(dbs, posted.job_name)
        for child in posted.task_child:
            for parent in posted.task_parent:
                myjob.add_deps(parent, child)
        rtn = myjob.validate(posted.job_name)
        if rtn is None:
            session.flash = "No task added, validation failed"
        else:
            session.flash = "Dependency correctly added"
    return dict()

@auth.requires_signature(hash_vars=False)
def tasks_dropdown_helper():
    session.forget(response)
    if not request.get_vars.q:
        raise HTTP(404)
    q = request.get_vars.q
    all_tasks = dbs(
        (st.task_name.ilike('%' + q + '%')) |
        (st.id.ilike('%' + q + '%'))
            ).select(
        st.id, st.task_name
        )
    rtn = []
    for row in all_tasks:
        rtn.append(dict(id=row.id, text='%(id)s - %(task_name)s' % row))

    return dumps(dict(results=rtn))