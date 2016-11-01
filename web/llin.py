#!/usr/bin/python
# Author: Samuel Sekiwere <sekiskylink@gmail.com>

import os
import sys
import web
import logging

import requests
import json
from web.contrib.template import render_jinja
from pagination import doquery, getPaginationString, countquery
from settings import config

filedir = os.path.dirname(__file__)
sys.path.append(os.path.join(filedir))

PAGE_LIMIT = 25
logging.basicConfig(
    format='%(asctime)s:%(levelname)s:%(message)s', filename='/tmp/llin-web.log',
    datefmt='%Y-%m-%d %I:%M:%S', level=logging.DEBUG
)

# DB confs
db_host = config['db_host']
db_name = config['db_name']
db_user = config['db_user']
db_passwd = config['db_passwd']
db_port = config['db_port']

urls = (
    r'^/', "Index",
    r'^/dashboard', "Dashboard",
    r'/warehousedata', "WarehouseData",
    r'/dispatch', "Dispatch",
    r'/distributionpoints', "DistPoints",
    r'/api/v1/loc_children/(\d+)/?', "LocationChildren",
    r'/api/v1/location/(\d+)/?', "Location",
    r'/api/v1/distribution_points/(\d+)/?', "DistributionPoints",
    r'/api/v1/subcountylocations/(\d+)/?', "SubcountyLocations",
    r'/reporters', "Reporters",
    # "/search", "Search",
    r'/settings', "Settings",
    r'/users', "Users",
    r'/groups', "Groups",
    "/logout", "Logout",
)

# web.config.smtp_server = 'mail.mydomain.com'
web.config.debug = False

app = web.application(urls, globals())
db = web.database(
    dbn='postgres',
    user=db_user,
    pw=db_passwd,
    db=db_name,
    host=db_host,
    port=db_port
)

store = web.session.DBStore(db, 'sessions')
session = web.session.Session(app, store, initializer={'loggedin': False})

render = render_jinja(
    'templates',
    encoding='utf-8'
)
render._lookup.globals.update(
    ses=session
)

app.notfound = lambda: web.notfound(render.missing())


def lit(**keywords):
    return keywords


def default(*args):
    p = [i for i in args if i or i == 0]
    if p.__len__():
        return p[0]
    if args.__len__():
        return args[args.__len__() - 1]
    return None


def post_request(data, url=config['default_api_uri']):
    response = requests.post(url, data=data, headers={
        'Content-type': 'application/json',
        'Authorization': 'Token %s' % config['api_token']})
    return response


def auth_user(db, username, password):
    sql = (
        "SELECT a.id, a.firstname, a.lastname, b.name as role "
        "FROM users a, user_roles b "
        "WHERE username = $username AND password = crypt($passwd, password) "
        "AND a.user_role = b.id AND is_active = 't'")
    res = db.query(sql, {'username': username, 'passwd': password})
    if not res:
        return False, "Wrong username or password"
    else:
        return True, res[0]


def require_login(f):
    """usage
    @require_login
    def GET(self):
        ..."""
    def decorated(*args, **kwargs):
        if not session.loggedin:
            session.logon_err = "Please Logon"
            return web.seeother("/")
        else:
            session.logon_err = ""
        return f(*args, **kwargs)

    return decorated


def csrf_token():
    if 'csrf_token' not in session:
        from uuid import uuid4
        session.csrf_token = uuid4().hex
    return session.csrf_token


def csrf_protected(f):
    def decorated(*args, **kwargs):
        inp = web.input()
        if not ('csrf_token' in inp and inp.csrf_token == session.pop('csrf_token', None)):
            raise web.HTTPError(
                "400 Bad request",
                {'content-type': 'text/html'},
                """Cross-site request forgery (CSRF) attempt (or stale browser form).
<a href="/"></a>.""")  # Provide a link back to the form
        return f(*args, **kwargs)
    return decorated

render._lookup.globals.update(csrf_token=csrf_token)


class Index:
    def GET(self):
        l = locals()
        del l['self']
        return render.start(**l)

    def POST(self):
        params = web.input(username="", password="")
        username = params.username
        password = params.password
        r = auth_user(db, username, password)
        if r[0]:
            session.loggedin = True
            info = r[1]
            session.username = info.firstname + " " + info.lastname
            session.sesid = info.id
            session.role = info.role

            l = locals()
            del l['self']
            if info.role == 'Warehouse Manager':
                return web.seeother("/warehousedata")
            else:
                return web.seeother("/dashboard")
        else:
            session.loggedin = False
            session.logon_err = r[1]
        l = locals()
        del l['self']
        return render.logon(**l)


class Logout:
    def GET(self):
        session.kill()
        return web.seeother("/")


class Dashboard:
    @require_login
    def GET(self):
        params = web.input(page=1, ed="", d_id="")
        edit_val = params.ed
        l = locals()
        del l['self']
        return render.dashboard(**l)

    @require_login
    def POST(self):
        params = web.input(page="1", ed="", d_id="")
        try:
            page = int(params.page)
        except:
            page = 1

        with db.transaction():
            if params.ed:
                return web.seeother("/dashboard")
            else:
                return web.seeother("/dashboard")

        l = locals()
        del l['self']
        return render.dashboard(**l)


class Users:
    @require_login
    def GET(self):
        params = web.input(page=1, ed="", d_id="")
        edit_val = params.ed

        if params.ed:
            r = db.query(
                "SELECT a.id, a.firstname, a.lastname, a.username, a.email, a.telephone, "
                "a.is_active, b.id as role "
                "FROM users a, user_roles b "
                "WHERE a.id = $id AND a.user_role = b.id", {'id': params.ed})
            if r and (session.role == 'Administrator' or '%s' % session.sesid == edit_val):
                u = r[0]
                firstname = u.firstname
                lastname = u.lastname
                telephone = u.telephone
                email = u.email
                username = u.username
                role = u.role
                is_active = u.is_active
                is_super = True if u.role == 'Administrator' else False

        if params.d_id:
            if session.role == 'Administrator':
                db.query("DELETE FROM users WHERE id=$id", {'id': params.d_id})

        roles = db.query("SELECT id, name FROM user_roles ORDER by name")
        if session.role == 'Administrator':
            users = db.query(
                "SELECT a.id, a.firstname, a.lastname, a.username, a.email, a.telephone, b.name as role "
                "FROM users a, user_roles b WHERE a.user_role = b.id")
        else:
            users = db.query(
                "SELECT a.id, a.firstname, a.lastname, a.username, a.email, a.telephone, b.name as role "
                "FROM users a, user_roles b WHERE a.user_role = b.id "
                "AND a.id=$id", {'id': session.sesid})
        l = locals()
        del l['self']
        return render.users(**l)

    @require_login
    @csrf_protected
    def POST(self):
        params = web.input(
            firstname="", lastname="", telephone="", username="", email="", passwd="",
            cpasswd="", is_active="", is_super="", page="1", ed="", d_id="")
        try:
            page = int(params.page)
        except:
            page = 1
        is_active = 't' if params.is_active == "on" else 'f'
        role = 'Administrator' if params.is_super == "on" else 'Basic'
        with db.transaction():
            if params.ed:
                db.query(
                    "UPDATE users SET firstname=$firstname, lastname=$lastname, "
                    "telephone=$telephone, email=$email, username=$username, "
                    "password = crypt($cpasswd, gen_salt('bf')), "
                    "is_active=$is_active, "
                    "user_role=(SELECT id FROM user_roles WHERE name=$role) "
                    "WHERE id = $id", {
                        'firstname': params.firstname, 'lastname': params.lastname,
                        'telephone': params.telephone, 'email': params.email,
                        'username': params.username, 'cpasswd': params.cpasswd,
                        'role': role, 'is_active': is_active, 'id': params.ed
                    }
                )
                return web.seeother("/users")
            else:
                db.query(
                    "INSERT INTO users (firstname, lastname, telephone, email, "
                    "username, password, is_active, user_role) "
                    "VALUES($firstname, $lastname, $telephone, $email, $username, "
                    "crypt($cpasswd, gen_salt('bf')), $is_active, "
                    "(SELECT id FROM user_roles WHERE name=$role))", {
                        'firstname': params.firstname, 'lastname': params.lastname,
                        'telephone': params.telephone, 'email': params.email,
                        'username': params.username, 'cpasswd': params.cpasswd,
                        'role': role, 'is_active': is_active, 'id': params.ed
                    }
                )
                return web.seeother("/users")
        l = locals()
        del l['self']
        return render.users(**l)


class Reporters:
    @require_login
    def GET(self):
        params = web.input(page=1, ed="", d_id="")
        edit_val = params.ed
        districts = db.query(
            "SELECT id, name FROM locations WHERE type_id = "
            "(SELECT id FROM locationtype WHERE name = 'district') ORDER by name")
        roles = db.query("SELECT id, name from reporter_groups order by name")
        if params.ed:
            res = db.query(
                "SELECT id, firstname, lastname, telephone, email, national_id, "
                "reporting_location, distribution_point, role, dpoint FROM reporters_view "
                " WHERE id = $id", {'id': edit_val})
            if res:
                r = res[0]
                firstname = r.firstname
                lastname = r.lastname
                telephone = r.telephone
                email = r.email
                role = r.role
                national_id = r.national_id
                dpoint_id = r.distribution_point
                dpoint = r.dpoint
        if params.d_id:
            if session.role in ('Micro Planning', 'Administrator'):
                db.query("DELETE FROM reporter_groups_reporters WHERE reporter_id=$id", {'id': params.d_id})
                db.query("DELETE FROM reporters WHERE id=$id", {'id': params.d_id})

        reporters = db.query("SELECT * FROM reporters_view")
        l = locals()
        del l['self']
        return render.reporters(**l)

    @require_login
    @csrf_protected
    def POST(self):
        params = web.input(
            firstname="", lastname="", telephone="", email="", location_id="", dpoint="",
            national_id="", role="", page="1", ed="", d_id="")
        try:
            page = int(params.page)
        except:
            page = 1

        with db.transaction():
            if params.ed:
                location = params.location if params.location else None
                dpoint = params.dpoint if params.dpoint else None
                r = db.query(
                    "UPDATE reporters SET firstname=$firstname, lastname=$lastname, "
                    "telephone=$telephone, email=$email, reporting_location=$location, "
                    "distribution_point=$dpoint, national_id=$nid "
                    "WHERE id=$id", {
                        'firstname': params.firstname, 'lastname': params.lastname,
                        'telephone': params.telephone, 'email': params.email,
                        'location': location, 'dpoint': dpoint, 'nid': params.national_id,
                        'id': params.ed
                    })
                db.query(
                    "UPDATE reporter_groups_reporters SET group_id = $gid "
                    " WHERE reporter_id = $id ", {'gid': params.role, 'id': params.ed})
                return web.seeother("/reporters")
            else:
                location = params.location if params.location else None
                dpoint = params.dpoint if params.dpoint else None
                r = db.query(
                    "INSERT INTO reporters (firstname, lastname, telephone, email, "
                    " reporting_location, distribution_point, national_id, uuid) VALUES "
                    " ($firstname, $lastname, $telephone, $email, $location, $dpoint,"
                    " $nid, uuid_generate_v4()) RETURNING id", {
                        'firstname': params.firstname, 'lastname': params.lastname,
                        'telephone': params.telephone, 'email': params.email,
                        'location': location, 'dpoint': dpoint, 'nid': params.national_id
                    })
                if r:
                    reporter_id = r[0]['id']
                    db.query(
                        "INSERT INTO reporter_groups_reporters (group_id, reporter_id) "
                        " VALUES ($role, $reporter_id)",
                        {'role': params.role, 'reporter_id': reporter_id})
                return web.seeother("/reporters")

        l = locals()
        del l['self']
        return render.reporters(**l)


class DistPoints:
    @require_login
    def GET(self):
        params = web.input(page=1, ed="", d_id="")
        edit_val = params.ed
        districts = db.query(
            "SELECT id, name FROM locations WHERE type_id = "
            "(SELECT id FROM locationtype WHERE name = 'district') ORDER by name")
        if params.ed:
            res = db.query(
                "SELECT id, name, subcounty, get_location_name(subcounty) subcounty_name , "
                " get_district(subcounty) district FROM distribution_points "
                " WHERE id = $id", {'id': edit_val})
            if res:
                r = res[0]
                district = r.district
                subcounty = r.subcounty
                subcounty_name = r.subcounty_name
                name = r.name
                villages = db.query(
                    "SELECT id, name FROM locations WHERE id IN "
                    "(SELECT village_id FROM distribution_point_villages "
                    " WHERE distribution_point = $id)", {'id': params.ed})

        if params.d_id:
            if session.role in ('Micro Planning', 'Administrator'):
                db.query(
                    "DELETE FROM distribution_point_villages WHERE distribution_point=$id",
                    {'id': params.d_id})
                db.query("DELETE FROM distribution_points WHERE id=$id", {'id': params.d_id})

        dpoints = db.query(
            "SELECT id, name, get_location_name(subcounty) as subcounty, "
            " get_distribution_point_locations(id) villages FROM distribution_points")
        l = locals()
        del l['self']
        return render.dpoints(**l)

    @require_login
    @csrf_protected
    def POST(self):
        params = web.input(
            name="", subcounty="", villages=[], page="1", ed="", d_id="")
        try:
            page = int(params.page)
        except:
            page = 1

        with db.transaction():
            if params.ed:
                db.query(
                    "DELETE FROM distribution_point_villages WHERE distribution_point=$id",
                    {'id': params.ed})
                db.query(
                    "UPDATE distribution_points SET "
                    " subcounty = $subcounty, name = $name "
                    " WHERE id = $id",
                    {'subcounty': params.subcounty, 'name': params.name, 'id': params.ed})
                for val in params.villages:
                    db.query(
                        "INSERT INTO distribution_point_villages (distribution_point, village_id) "
                        " VALUES($dpoint, $village)", {'dpoint': params.ed, 'village': val})
                return web.seeother("/distributionpoints")
            else:
                r = db.query(
                    "INSERT INTO  distribution_points (name, subcounty, uuid, code) "
                    " VALUES ($name, $subcounty, uuid_generate_v4(), gen_code())"
                    " RETURNING id",
                    {'name': params.name, 'subcounty': params.subcounty})
                if r:
                    dpoint_id = r[0]['id']
                    for val in params.villages:
                        db.query(
                            "INSERT INTO distribution_point_villages (distribution_point, village_id) "
                            " VALUES($dpoint, $village)", {'dpoint': dpoint_id, 'village': val})
                return web.seeother("/distributionpoints")

        l = locals()
        del l['self']
        return render.reporters(**l)


class WarehouseData:
    @require_login
    def GET(self):
        params = web.input(page=1)
        try:
            page = int(params.page)
        except:
            page = 1

        limit = PAGE_LIMIT
        start = (page - 1) * limit if page > 0 else 0

        dic = lit(relations='national_deliery_log', fields="*", criteria="", order="id desc", limit=limit, offset=start)
        res = doquery(db, dic)
        count = countquery(db, dic)
        pagination_str = getPaginationString(default(page, 0), count, limit, 2, "warehousedata", "?page=")
        countries = db.query("SELECT id, name FROM countries ORDER BY name")

        l = locals()
        del l['self']
        return render.warehousedata(**l)

    @require_login
    def POST(self):
        pass


class Groups:
    @require_login
    def GET(self):
        params = web.input(page=1, ed="", d_id="")
        edit_val = params.ed
        groups = db.query("SELECT id, name, descr FROM user_roles order by id desc")
        l = locals()
        del l['self']
        return render.groups(**l)

    @require_login
    @csrf_protected
    def POST(self):
        params = web.input(
            name="", descr="", page="1", ed="", d_id="")
        try:
            page = int(params.page)
        except:
            page = 1

        with db.transaction():
            if params.ed:
                pass
                return web.seeother("/groups")
            else:
                r = db.query(
                    "INSERT INTO user_roles (name, descr) "
                    " VALUES ($name, $descr)",
                    {'name': params.name, 'descr': params.descr})
                return web.seeother("/groups")

        l = locals()
        del l['self']
        return render.reporters(**l)


class Settings:
    @require_login
    def GET(self):
        params = web.input(page=1, ed="", d_id="")
        edit_val = params.ed
        l = locals()
        del l['self']
        return render.settings(**l)

    @require_login
    @csrf_protected
    def POST(self):
        params = web.input(
            name="", descr="", page="1", ed="", d_id="")
        try:
            page = int(params.page)
        except:
            page = 1

        with db.transaction():
            if params.ed:
                return web.seeother("/settings")
            else:
                return web.seeother("/settings")

        l = locals()
        del l['self']
        return render.settings(**l)


class Dispatch:
    @require_login
    def GET(self):
        params = web.input(page=1, ed="", d_id="")
        edit_val = params.ed
        l = locals()
        del l['self']
        return render.dispatch(**l)

    @csrf_protected
    @require_login
    def POST(self):
        params = web.input(
            name="", descr="", page="1", ed="", d_id="")
        try:
            page = int(params.page)
        except:
            page = 1

        with db.transaction():
            if params.ed:
                return web.seeother("/dispatch")
            else:
                return web.seeother("/dispatch")

        l = locals()
        del l['self']
        return render.dispatch(**l)


class LocationChildren:
    """Returns Children for a node """
    def GET(self, id):
        ret = []
        rs = db.query(
            "SELECT id, name, tree_parent_id FROM get_children($id);", {'id': id})
        if rs:
            for r in rs:
                parent = r['tree_parent_id']
                ret.append(
                    {
                        "name": r['name'],
                        "id": r['id'],
                        "attr": {'id': r['id']},
                        "parent": parent if parent else "#",
                        "state": "closed"
                    })
        return json.dumps(ret)


class Location:
    def GET(self, id):
        ret = []
        rs = db.query(
            "SELECT id, name, tree_parent_id FROM locations WHERE id = $id;", {'id': id})
        if rs:
            for r in rs:
                parent = r['tree_parent_id']
                ret.append(
                    {
                        "text": r['name'],
                        "attr": {'id': r['id']},
                        "id": parent if parent else "#",
                        "state": "closed"
                    })
        return json.dumps(ret)


class DistributionPoints:
    """Returns Distribution Points in Sub County"""
    def GET(self, id):
        ret = []
        rs = db.query(
            "SELECT id, name, code, uuid FROM distribution_points "
            "WHERE subcounty = $id;", {'id': id})
        if rs:
            for r in rs:
                ret.append(
                    {
                        "id": r['id'],
                        "name": r['name'],
                        "uuid": r['uuid'],
                        "code": r['code'],
                    })
        return json.dumps(ret)


class SubcountyLocations:
    def GET(self, id):
        """ returs the form bellow
        ret = {
            "Parish X": [{'name': "Villa 1"}, {"name": "Villa 2"}, {"name": "Villa 3"}],
            "Parish Y": [{'name': "Villa 4"}, {"name": "Villa 5"}],
            "Parish Z": [{'name': "Villa 6"}, {"name": "Villa 7"}],
        }
        """
        web.header("Content-Type", "application/json; charset=utf-8")
        ret = {}
        res = db.query("SELECT id, name FROM get_children($id)", {'id': id})
        for r in res:
            parish_name = r['name']
            parish_id = r['id']
            ret[parish_name] = []
            x = db.query("SELECT id, name FROM get_children($id)", {'id': parish_id})
            for i in x:
                ret[parish_name].append({'id': i['id'], 'name': i['name']})
        return json.dumps(ret)

if __name__ == "__main__":
    app.run()

# makes sure apache wsgi sees our app
application = web.application(urls, globals()).wsgifunc()
