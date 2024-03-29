##############################################################################
#
# Copyright (c) 2002 Zope Foundation and Contributors.
# All Rights Reserved.
#
# This software is subject to the provisions of the Zope Public License,
# Version 2.1 (ZPL).  A copy of the ZPL should accompany this distribution.
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE.
#
##############################################################################
"""Code to initialize the application server."""

__docformat__ = 'restructuredtext'

import base64
import sys
import time
import urllib.parse
from io import BytesIO
from pdb import Pdb

from zope.app.appsetup import config
from zope.app.appsetup import database
from zope.app.publication.browser import BrowserPublication
from zope.publisher.browser import TestRequest
from zope.publisher.browser import setDefaultSkin
from zope.publisher.publish import debug_call
from zope.publisher.publish import publish as _publish


class Debugger:

    pdb = Pdb

    def __init__(self, db=None, config_file=None, stdout=None):
        if db is None and config_file is None:
            db = 'Data.fs'
            config_file = 'site.zcml'

        if config_file is not None:
            config(config_file)
        self.db = database(db)
        self.stdout = stdout

    @classmethod
    def fromDatabase(cls, db):
        inst = cls.__new__(cls)
        inst.db = db
        return inst

    def root(self):
        """Get the top-level application object

        The object returned is connected to an open database connection.
        """

        from zope.app.publication.zopepublication import ZopePublication
        return self.db.open().root()[ZopePublication.root_name]

    def _request(self,
                 path='/', stdin='', basic=None,
                 environment=None, form=None,
                 request=None, publication=BrowserPublication):
        """Create a request
        """

        env = {}

        if isinstance(stdin, str):
            stdin = stdin.encode("utf-8")

        if isinstance(stdin, bytes):
            stdin = BytesIO(stdin)

        p = path.split('?')
        if len(p) == 1:
            env['PATH_INFO'] = p[0]
        elif len(p) == 2:
            env['PATH_INFO'], env['QUERY_STRING'] = p
        else:
            raise ValueError("Too many ?s in path", path)

        env['PATH_INFO'] = urllib.parse.unquote(env['PATH_INFO'])

        if environment is not None:
            env.update(environment)

        if basic:
            basic_bytes = basic.encode('ascii') if not isinstance(
                basic, bytes) else basic
            basic64_bytes = base64.b64encode(basic_bytes)
            basic64 = basic64_bytes.decode('ascii').strip()
            env['HTTP_AUTHORIZATION'] = "Basic %s" % basic64

        pub = publication(self.db)

        if request is not None:
            request = request(stdin, env)
        else:
            request = TestRequest(stdin, env)
            setDefaultSkin(request)
        request.setPublication(pub)
        if form:
            request.form.update(form)

        return request

    def publish(self, path='/', stdin='', *args, **kw):
        t, pt = time.time(), time.process_time()

        request = self._request(path, stdin, *args, **kw)

        # agroszer: 2008.feb.1.: if a retry occurs in the publisher,
        # the response will be LOST, so we must accept the returned request
        request = _publish(request)
        getStatus = getattr(request.response, 'getStatus', lambda: None)

        headers = sorted(request.response.getHeaders())

        print(
            'Status {}\r\n{}\r\n\r\n{}'.format(
                request.response.getStatusString(),
                '\r\n'.join([("%s: %s" % h) for h in headers]),
                request.response.consumeBody(),
            ), file=self.stdout or sys.stdout)
        return time.time() - t, time.process_time() - pt, getStatus()

    def run(self, *args, **kw):
        t, pt = time.time(), time.process_time()
        request = self._request(*args, **kw)
        # agroszer: 2008.feb.1.: if a retry occurs in the publisher,
        # the response will be LOST, so we must accept the returned request
        request = _publish(request, handle_errors=False)
        getStatus = getattr(request.response, 'getStatus', lambda: None)

        return time.time() - t, time.process_time() - pt, getStatus()

    def debug(self, *args, **kw):
        out = self.stdout or sys.stdout

        class ZopePdb(self.Pdb):
            done_pub = False
            done_ob = False

            def do_pub(self, arg):
                if self.done_pub:
                    print('pub already done.', file=out)
                    return

                self.do_s('')
                self.do_s('')
                self.do_c('')
                self.done_pub = True

            def do_ob(self, arg):
                if self.done_ob:
                    print('ob already done.', file=out)
                    return

                self.do_pub('')
                self.do_c('')
                self.done_ob = True

        dbg = ZopePdb()

        request = self._request(*args, **kw)
        fbreak(dbg, _publish)
        fbreak(dbg, debug_call)

        print('* Type c<cr> to jump to published object call.',
              file=out)
        dbg.runcall(_publish, request)
        return dbg


def getlineno(code):
    return code.co_firstlineno


def fbreak(db, meth):
    try:
        meth = meth.__func__
    except AttributeError:
        pass
    code = meth.__code__
    lineno = getlineno(code)
    filename = code.co_filename
    db.set_break(filename, lineno)
