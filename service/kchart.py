#!/usr/bin/env python
# -*- coding: utf-8 -*-

# filename   : kchart.py
# created at : 2012年07月14日 星期六 10时44分51秒
# author     : Jianing Yang <jianingy.yang AT gmail DOT com>

__author__ = 'Jianing Yang <jianingy.yang AT gmail DOT com>'

from twisted.internet import reactor, defer
from twisted.internet.threads import deferToThread
from twisted.python import log
from txpostgres import txpostgres
from base import BaseResource
import matplotlib.pyplot as plt
from cStringIO import StringIO
import time
import re
import logging

TIME_RE = re.compile('(?P<oper>[-+])?(?P<amount>\d+)(?P<unit>[smhdw])|(?P<now>now)')
DSN = 'host=localhost port=5432 user=jianingy dbname=jianingy'
TIME_UNIT = dict(s=1, m=60, h=3600, d=86400, w=86400 * 7)


def to_timestamp(matched):
    c = matched.groupdict()
    if c['now'] == 'now':
        return time.time()
    ts = float(c['amount']) * TIME_UNIT[c['unit']]
    if c['oper'] == '-':
        return time.time() - ts
    else:
        return time.time() + ts


def candlestick(ax, quotes, width=0.6, colorup='#00ff00', colordown='#ff0000'):
    stick_width = 0.05
    i = 0
    for quote in quotes:
        highest, lowest = None, None
        i = i + 1
        ts, opening, closing, high, low = quote[:5]
        if closing < opening:
            height = opening - closing
            bottom = closing
            color = colordown
        else:
            height = closing - opening
            bottom = opening
            color = colorup

        ax.bar(i + (width - stick_width) / 2,
               high - low, stick_width, low,
               color='#555555', linewidth=0, aa=False)

        ax.bar(i, height, width, bottom,
               color=color, edgecolor='#555555', aa=False)

        if not highest or highest < high:
            highest = high

        if not lowest or lowest > low:
            lowest = low

        ax.set_ylim(highest, lowest)


class KChartService(BaseResource):

    def __init__(self, *args, **kwargs):
        self._database_connected = False
        self.db = txpostgres.ConnectionPool(None, DSN)
        d = self.db.start()
        d.addBoth(self._connect_database)

        BaseResource.__init__(self, *args, **kwargs)

    def _connect_database(self, ignore):
        from twisted.python.failure import Failure

        if isinstance(ignore, Failure):
            log.msg("cannot connect database", level=logging.ERROR)
            log.msg(ignore.getTraceback(), level=logging.ERROR)
            reactor.stop()
        else:
            self._database_connected = True

    @defer.inlineCallbacks
    def _fetch(self, cursor, option):
        tbl = "kchart_%s_%sm" % (option['symbol'].lower(), option['period'])
        sql = "SELECT extract(EPOCH FROM ts), open, close, high, low FROM %s " % tbl
        sql += "WHERE ts >= to_timestamp(%(start)s) "
        sql += "AND ts <= to_timestamp(%(end)s)"
        iterator = yield cursor.execute(sql, option)
        quotes = list(iterator.fetchall())
        defer.returnValue(quotes)

    def _draw(self, quotes):
        fig = plt.figure(figsize=(10, 5))
        ax = fig.add_axes([0.1, 0.2, 0.85, 0.7])
        ax.xaxis.set_ticks_position('bottom')
        ax.yaxis.set_ticks_position('right')
        ax.tick_params(axis='both', direction='out', width=1, length=10,
                       labelsize=9, pad=8)
        candlestick(ax, quotes)
        output = StringIO()
        plt.savefig(output, format='png')
        return output.getvalue()

    @defer.inlineCallbacks
    def async_GET(self, request):

        option = dict()
        option['start'] = request.args.get('start', ['-8h'])[0]
        option['end'] = request.args.get('end', ['now'])[0]
        option['period'] = request.args.get('peroid', ['1'])[0]
        option['symbol'] = request.args.get('symbol', ['eurusd'])[0]

        matched = TIME_RE.match(option['start'])
        if not matched:
            raise InvalidChartData('start time is invalid')
        else:
            option['start'] = to_timestamp(matched)

        matched = TIME_RE.match(option['end'])
        if not matched:
            raise InvalidChartData('end time is invalid')
        else:
            option['end'] = to_timestamp(matched)

        quotes = yield self.db.runInteraction(self._fetch, option)
        result = yield deferToThread(self._draw, quotes)
        request.setHeader('Content-Type', 'image/png')
        defer.returnValue(result)