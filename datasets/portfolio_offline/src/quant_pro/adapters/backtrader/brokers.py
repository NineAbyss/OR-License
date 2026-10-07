
from __future__ import annotations

import collections
import datetime as _dt
import itertools
import logging
from copy import copy

from backtrader.brokers.bbroker import BackBroker as BT_BackBroker
from backtrader.metabase import MetaParams
from backtrader.utils import AutoOrderedDict
from backtrader.utils.py3 import iteritems, with_metaclass
from backtrader.utils.py3 import range as bt_range

logger = logging.getLogger(__name__)




class Position:

    def __str__(self) -> str:
        items = [
            "--- Position Begin",
            f"- Size: {self.size}",
            f"- Price: {self.price}",
            f"- Price orig: {self.price_orig}",
            f"- Closed: {self.upclosed}",
            f"- Opened: {self.upopened}",
            f"- Adjbase: {self.adjbase}",
            "--- Position End",
        ]
        return "\n".join(items)

    def __init__(self, size: float = 0, price: float = 0.0) -> None:
        self.size = size
        if size:
            self.price = self.price_orig = price
        else:
            self.price = 0.0

        self.adjbase = None

        self.upopened = size
        self.upclosed = 0
        self.set(size, price)

        self.updt = None

    def fix(self, size, price):
        oldsize = self.size
        self.size = size
        self.price = price
        return self.size == oldsize

    def set(self, size, price):
        if self.size > 0:
            if size > self.size:
                self.upopened = size - self.size
                self.upclosed = 0
            else:
                self.upopened = min(0, size)
                self.upclosed = min(self.size, self.size - size)
        elif self.size < 0:
            if size < self.size:
                self.upopened = size - self.size
                self.upclosed = 0
            else:
                self.upopened = max(0, size)
                self.upclosed = max(self.size, self.size - size)
        else:
            self.upopened = self.size
            self.upclosed = 0

        self.size = size
        self.price_orig = self.price
        if size:
            self.price = price
        else:
            self.price = 0.0

        return self.size, self.price, self.upopened, self.upclosed

    def __len__(self):
        return abs(self.size)

    def __bool__(self):
        return bool(self.size != 0)

    __nonzero__ = __bool__

    def clone(self):
        return Position(size=self.size, price=self.price)

    def pseudoupdate(self, size, price):
        return Position(self.size, self.price).update(size, price)

    def update(self, size, price, dt=None):
        self.datetime = dt

        self.price_orig = self.price
        oldsize = self.size
        self.size += size

        if not self.size:
            opened, closed = 0, size
            self.price = 0.0
        elif not oldsize:
            opened, closed = size, 0
            self.price = price
        elif oldsize > 0:
            if size > 0:
                opened, closed = size, 0
                self.price = (self.price * oldsize + size * price) / self.size
            elif self.size > 0:
                opened, closed = 0, size
            else:
                opened, closed = self.size, -oldsize
                self.price = price
        else:
            if size < 0:
                opened, closed = size, 0
                self.price = (self.price * oldsize + size * price) / self.size
            elif self.size < 0:
                opened, closed = 0, size
            else:
                opened, closed = self.size, -oldsize
                self.price = price

        self.upopened = opened
        self.upclosed = closed

        if -1e-9 < opened < 1e-9:
            opened = 0
        if -1e-9 < closed < 1e-9:
            closed = 0
        if -1e-10 < self.size < 1e-10:
            self.size = 0

        return self.size, self.price, opened, closed




class OrderExecutionBit:

    def __init__(
        self,
        dt=None,
        size=0,
        price=0.0,
        closed=0,
        closedvalue=0.0,
        closedcomm=0.0,
        opened=0,
        openedvalue=0.0,
        openedcomm=0.0,
        pnl=0.0,
        psize=0,
        pprice=0.0,
    ):
        self.dt = dt
        self.size = size
        self.price = price

        self.closed = closed
        self.opened = opened
        self.closedvalue = closedvalue
        self.openedvalue = openedvalue
        self.closedcomm = closedcomm
        self.openedcomm = openedcomm

        self.value = closedvalue + openedvalue
        self.comm = closedcomm + openedcomm
        self.pnl = pnl

        self.psize = psize
        self.pprice = pprice


class OrderData:

    def __init__(
        self,
        dt=None,
        size=0,
        price=0.0,
        pricelimit=0.0,
        remsize=0,
        pclose=0.0,
        trailamount=0.0,
        trailpercent=0.0,
    ):
        self.pclose = pclose
        self.exbits = collections.deque()
        self.p1, self.p2 = 0, 0

        self.dt = dt
        self.size = size
        self.remsize = remsize
        self.price = price
        self.pricelimit = pricelimit
        self.trailamount = trailamount
        self.trailpercent = trailpercent

        if not pricelimit:
            self.pricelimit = self.price
        if pricelimit and not price:
            self.price = pricelimit

        self.plimit = pricelimit

        self.value = 0.0
        self.comm = 0.0
        self.margin = None
        self.pnl = 0.0

        self.psize = 0
        self.pprice = 0

    def _getplimit(self):
        return self._plimit

    def _setplimit(self, val):
        self._plimit = val

    plimit = property(_getplimit, _setplimit)

    def __len__(self):
        return len(self.exbits)

    def __getitem__(self, key):
        return self.exbits[key]

    def add(
        self,
        dt,
        size,
        price,
        closed=0,
        closedvalue=0.0,
        closedcomm=0.0,
        opened=0,
        openedvalue=0.0,
        openedcomm=0.0,
        pnl=0.0,
        psize=0,
        pprice=0.0,
    ):
        self.addbit(
            OrderExecutionBit(
                dt,
                size,
                price,
                closed,
                closedvalue,
                closedcomm,
                opened,
                openedvalue,
                openedcomm,
                pnl,
                psize,
                pprice,
            )
        )

    def addbit(self, exbit):
        self.exbits.append(exbit)

        self.remsize -= exbit.size

        self.dt = exbit.dt
        oldvalue = self.size * self.price
        newvalue = exbit.size * exbit.price
        self.size += exbit.size
        self.price = (oldvalue + newvalue) / self.size
        self.value += exbit.value
        self.comm += exbit.comm
        self.pnl += exbit.pnl
        self.psize = exbit.psize
        self.pprice = exbit.pprice

    def getpending(self):
        return list(self.iterpending())

    def iterpending(self):
        return itertools.islice(self.exbits, self.p1, self.p2)

    def markpending(self):
        self.p1, self.p2 = self.p2, len(self.exbits)

    def clone(self):
        self.markpending()
        obj = copy(self)
        return obj


class OrderBase(with_metaclass(MetaParams, object)):

    params = (
        ("owner", None),
        ("data", None),
        ("size", None),
        ("price", None),
        ("pricelimit", None),
        ("exectype", None),
        ("valid", None),
        ("tradeid", 0),
        ("oco", None),
        ("trailamount", None),
        ("trailpercent", None),
        ("parent", None),
        ("transmit", True),
        ("simulated", False),
        ("histnotify", False),
    )

    DAY = _dt.timedelta()

    T_Close, T_Day, T_Date, T_None = bt_range(4)
    V_None = bt_range(1)

    (
        Market,
        Close,
        Limit,
        Stop,
        StopLimit,
        StopTrail,
        StopTrailLimit,
        Historical,
    ) = bt_range(8)
    ExecTypes = [
        "Market",
        "Close",
        "Limit",
        "Stop",
        "StopLimit",
        "StopTrail",
        "StopTrailLimit",
        "Historical",
    ]

    OrdTypes = ["Buy", "Sell"]
    Buy, Sell = bt_range(2)

    (
        Created,
        Submitted,
        Accepted,
        Partial,
        Completed,
        Canceled,
        Expired,
        Margin,
        Rejected,
    ) = bt_range(9)

    Cancelled = Canceled

    Status = [
        "Created",
        "Submitted",
        "Accepted",
        "Partial",
        "Completed",
        "Canceled",
        "Expired",
        "Margin",
        "Rejected",
    ]

    refbasis = itertools.count(1)

    def _getplimit(self):
        return self._plimit

    def _setplimit(self, val):
        self._plimit = val

    plimit = property(_getplimit, _setplimit)

    def __getattr__(self, name):
        return getattr(self.params, name)

    def __setattribute__(self, name, value):
        if hasattr(self.params, name):
            setattr(self.params, name, value)
        else:
            super(Order, self).__setattribute__(name, value)

    def __str__(self):
        tojoin = []
        tojoin.append(f"Ref: {self.ref}")
        tojoin.append(f"OrdType: {self.ordtype}")
        tojoin.append(f"OrdType: {self.ordtypename()}")
        tojoin.append(f"Status: {self.status}")
        tojoin.append(f"Status: {self.getstatusname()}")
        tojoin.append(f"Size: {self.size}")
        tojoin.append(f"Price: {self.price}")
        tojoin.append(f"Price Limit: {self.pricelimit}")
        tojoin.append(f"TrailAmount: {self.trailamount}")
        tojoin.append(f"TrailPercent: {self.trailpercent}")
        tojoin.append(f"ExecType: {self.exectype}")
        tojoin.append(f"ExecType: {self.getordername()}")
        tojoin.append(f"CommInfo: {self.comminfo}")
        tojoin.append(f"End of Session: {self.dteos}")
        tojoin.append(f"Info: {self.info}")
        tojoin.append(f"Broker: {self.broker}")
        tojoin.append(f"Alive: {self.alive()}")
        return "\n".join(tojoin)

    def __init__(self):
        self.ref = next(self.refbasis)
        self.broker = None
        self.info = AutoOrderedDict()
        self.comminfo = None
        self.triggered = False

        self._active = self.parent is None
        self.status = Order.Created

        self.plimit = self.p.pricelimit

        if self.exectype is None:
            self.exectype = Order.Market

        if not self.isbuy():
            self.size = -self.size

        pclose = self.data.close[0] if not self.p.simulated else self.price
        price = pclose if not self.price and not self.pricelimit else self.price

        dcreated = self.data.datetime[0] if not self.p.simulated else 0.0
        self.created = OrderData(
            dt=dcreated,
            size=self.size,
            price=price,
            pricelimit=self.pricelimit,
            pclose=pclose,
            trailamount=self.trailamount,
            trailpercent=self.trailpercent,
        )

        if self.exectype in [Order.StopTrail, Order.StopTrailLimit]:
            self._limitoffset = self.created.price - self.created.pricelimit
            price = self.created.price
            self.created.price = float("inf" * self.isbuy() or "-inf")
            self.trailadjust(price)
        else:
            self._limitoffset = 0.0

        self.executed = OrderData(remsize=self.size)
        self.position = 0

        if isinstance(self.valid, _dt.date):
            self.valid = self.data.date2num(self.valid)
        elif isinstance(self.valid, _dt.timedelta):
            if self.valid == self.DAY:
                valid = _dt.datetime.combine(self.data.datetime.date(), _dt.time(23, 59, 59, 9999))
            else:
                valid = self.data.datetime.datetime() + self.valid
            self.valid = self.data.date2num(valid)
        elif self.valid is not None:
            if not self.valid:
                valid = _dt.datetime.combine(self.data.datetime.date(), _dt.time(23, 59, 59, 9999))
            else:
                valid = self.data.datetime[0] + self.valid

        if not self.p.simulated:
            dtime = self.data.datetime.datetime(0)
            session = self.data.p.sessionend
            dteos = dtime.replace(
                hour=session.hour,
                minute=session.minute,
                second=session.second,
                microsecond=session.microsecond,
            )
            if dteos < dtime:
                dteos += _dt.timedelta(days=1)
            self.dteos = self.data.date2num(dteos)
        else:
            self.dteos = 0.0

    def clone(self):
        obj = copy(self)
        obj.executed = self.executed.clone()
        return obj

    def getstatusname(self, status=None):
        return self.Status[self.status if status is None else status]

    def getordername(self, exectype=None):
        return self.ExecTypes[self.exectype if exectype is None else exectype]

    @classmethod
    def ExecType(cls, exectype):
        return getattr(cls, exectype)

    def ordtypename(self, ordtype=None):
        return self.OrdTypes[self.ordtype if ordtype is None else ordtype]

    def active(self):
        return self._active

    def activate(self):
        self._active = True

    def alive(self):
        return self.status in [
            Order.Created,
            Order.Submitted,
            Order.Partial,
            Order.Accepted,
        ]

    def addcomminfo(self, comminfo):
        self.comminfo = comminfo

    def addinfo(self, **kwargs):
        for key, val in iteritems(kwargs):
            self.info[key] = val

    def __eq__(self, other):
        return other is not None and self.ref == other.ref

    def __ne__(self, other):
        return self.ref != other.ref

    def isbuy(self):
        return self.ordtype == self.Buy

    def issell(self):
        return self.ordtype == self.Sell

    def setposition(self, position):
        self.position = position

    def submit(self, broker=None):
        self.status = Order.Submitted
        self.broker = broker
        self.plen = len(self.data)

    def accept(self, broker=None):
        self.status = Order.Accepted
        self.broker = broker

    def brokerstatus(self):
        if self.broker:
            return self.broker.orderstatus(self)
        return self.status

    def reject(self, broker=None):
        if self.status == Order.Rejected:
            return False
        self.status = Order.Rejected
        self.broker = broker
        if not self.p.simulated:
            self.executed.dt = self.data.datetime[0]
        return True

    def cancel(self):
        self.status = Order.Canceled
        if not self.p.simulated:
            self.executed.dt = self.data.datetime[0]

    def margin(self):
        self.status = Order.Margin
        if not self.p.simulated:
            self.executed.dt = self.data.datetime[0]

    def completed(self):
        self.status = self.Completed

    def partial(self):
        self.status = self.Partial

    def execute(
        self,
        dt,
        size,
        price,
        closed,
        closedvalue,
        closedcomm,
        opened,
        openedvalue,
        openedcomm,
        margin,
        pnl,
        psize,
        pprice,
    ):
        if not size:
            return

        self.executed.add(
            dt,
            size,
            price,
            closed,
            closedvalue,
            closedcomm,
            opened,
            openedvalue,
            openedcomm,
            pnl,
            psize,
            pprice,
        )

        self.executed.margin = margin

    def expire(self):
        self.status = self.Expired
        return True

    def trailadjust(self, price):
        pass


class Order(OrderBase):

    def execute(
        self,
        dt,
        size,
        price,
        closed,
        closedvalue,
        closedcomm,
        opened,
        openedvalue,
        openedcomm,
        margin,
        pnl,
        psize,
        pprice,
    ):
        super().execute(
            dt,
            size,
            price,
            closed,
            closedvalue,
            closedcomm,
            opened,
            openedvalue,
            openedcomm,
            margin,
            pnl,
            psize,
            pprice,
        )

        if abs(self.executed.remsize) > 1e-10:
            self.status = Order.Partial
        else:
            self.status = Order.Completed

    def expire(self):
        if self.exectype == Order.Market:
            return False

        if self.valid and self.data.datetime[0] > self.valid:
            self.status = Order.Expired
            self.executed.dt = self.data.datetime[0]
            return True

        return False

    def trailadjust(self, price):
        if self.trailamount:
            pamount = self.trailamount
        elif self.trailpercent:
            pamount = price * self.trailpercent
        else:
            pamount = 0.0

        if self.isbuy():
            price += pamount
            if price < self.created.price:
                self.created.price = price
                if self.exectype == Order.StopTrailLimit:
                    self.created.pricelimit = price - self._limitoffset
        else:
            price -= pamount
            if price > self.created.price:
                self.created.price = price
                if self.exectype == Order.StopTrailLimit:
                    self.created.pricelimit = price - self._limitoffset


class BuyOrder(Order):
    ordtype = Order.Buy


class SellOrder(Order):
    ordtype = Order.Sell




class EnhancedIndexBackBroker(BT_BackBroker):

    def init(self):
        super().init()
        self.positions = collections.defaultdict(Position)


    def buy(
        self,
        owner,
        data,
        size,
        price=None,
        plimit=None,
        exectype=None,
        valid=None,
        tradeid=0,
        oco=None,
        trailamount=None,
        trailpercent=None,
        parent=None,
        transmit=True,
        histnotify=False,
        _checksubmit=True,
        **kwargs,
    ):
        order = BuyOrder(
            owner=owner,
            data=data,
            size=size,
            price=price,
            pricelimit=plimit,
            exectype=exectype,
            valid=valid,
            tradeid=tradeid,
            trailamount=trailamount,
            trailpercent=trailpercent,
            parent=parent,
            transmit=transmit,
            histnotify=histnotify,
        )
        order.addinfo(**kwargs)
        self._ocoize(order, oco)
        return self.submit(order, check=_checksubmit)

    def sell(
        self,
        owner,
        data,
        size,
        price=None,
        plimit=None,
        exectype=None,
        valid=None,
        tradeid=0,
        oco=None,
        trailamount=None,
        trailpercent=None,
        parent=None,
        transmit=True,
        histnotify=False,
        _checksubmit=True,
        **kwargs,
    ):
        order = SellOrder(
            owner=owner,
            data=data,
            size=size,
            price=price,
            pricelimit=plimit,
            exectype=exectype,
            valid=valid,
            tradeid=tradeid,
            trailamount=trailamount,
            trailpercent=trailpercent,
            parent=parent,
            transmit=transmit,
            histnotify=histnotify,
        )
        order.addinfo(**kwargs)
        self._ocoize(order, oco)
        return self.submit(order, check=_checksubmit)

    def _execute(self, order, ago=None, price=None, cash=None, position=None, dtcoc=None):
        if ago is not None and price is None:
            return

        if self.p.filler is None or ago is None:
            size = order.executed.remsize
        else:
            size = self.p.filler(order, price, ago)
            if not order.isbuy():
                size = -size

        comminfo = self.getcommissioninfo(order.data)

        if order.data._compensate is not None:
            data = order.data._compensate
            cinfocomp = self.getcommissioninfo(data)
        else:
            data = order.data
            cinfocomp = comminfo

        if ago is not None:
            position = self.positions[data]
            pprice_orig = position.price

            psize, pprice, opened, closed = position.pseudoupdate(size, price)

            pnl = comminfo.profitandloss(-closed, pprice_orig, price)
            cash = self.cash

        else:
            pnl = 0
            if not self.p.coo:
                price = pprice_orig = order.created.price
            else:
                if order.exectype == Order.Market:
                    price = pprice_orig = order.data.open[0]
                else:
                    price = pprice_orig = order.created.price

            psize, pprice, opened, closed = position.update(size, price)


        if closed:
            if self.p.shortcash:
                closedvalue = comminfo.getvaluesize(-closed, pprice_orig)
            else:
                closedvalue = comminfo.getoperationcost(closed, pprice_orig)

            closecash = closedvalue
            if closedvalue > 0:
                closecash /= comminfo.get_leverage()

            if "future" in order.info.sr:
                cash += closecash + pnl
            elif "o_ss_id" in order.info:
                cash += pnl * comminfo.stocklike
            else:
                cash += closecash + pnl * comminfo.stocklike

            closedcomm = comminfo.getcommission(closed, price)
            cash -= closedcomm

            if ago is not None:
                cash += comminfo.cashadjust(-closed, position.adjbase, price)

                self.cash = cash
        else:
            closedvalue = closedcomm = 0.0

        popened = opened
        if opened:
            if self.p.shortcash:
                openedvalue = comminfo.getvaluesize(opened, price)
            else:
                openedvalue = comminfo.getoperationcost(opened, price)

            opencash = openedvalue
            if openedvalue > 0:
                opencash /= comminfo.get_leverage()

            cash -= opencash

            openedcomm = cinfocomp.getcommission(opened, price)
            cash -= openedcomm

            if cash < 0.0:
                opened = 0
                openedvalue = openedcomm = 0.0

            elif ago is not None:
                if abs(psize) > abs(opened):
                    adjsize = psize - opened
                    cash += comminfo.cashadjust(adjsize, position.adjbase, price)

                position.adjbase = price

                self.cash = cash
        else:
            openedvalue = openedcomm = 0.0

        if ago is None:
            return cash

        execsize = closed + opened

        if execsize:
            comminfo.confirmexec(execsize, price)

            position.update(execsize, price, data.datetime.datetime())

            if closed and self.p.int2pnl:
                closedcomm += self.d_credit.pop(data, 0.0)

            order.execute(
                dtcoc or data.datetime[ago],
                execsize,
                price,
                closed,
                closedvalue,
                closedcomm,
                opened,
                openedvalue,
                openedcomm,
                comminfo.margin,
                pnl,
                psize,
                pprice,
            )

            order.addcomminfo(comminfo)

            self.notify(order)
            self._ococheck(order)

        if popened and not opened:
            order.margin()
            self.notify(order)
            self._ococheck(order)
            self._bracketize(order, cancel=True)

    def _try_exec_limit(self, order, popen, phigh, plow, plimit):
        if order.isbuy():
            if plimit >= popen:
                pmax = min(phigh, plimit)
                p = self._slip_up(pmax, popen, doslip=self.p.slip_open, lim=True)
                self._execute(order, ago=0, price=p)
            elif plimit >= plow:
                self._execute(order, ago=0, price=plimit)

        else:
            if "o_ss_id" in order.info:
                self._execute(order, ago=0, price=plimit)
            elif plimit <= popen:
                p = self._slip_down(plimit, popen, doslip=self.p.slip_open, lim=True)
                self._execute(order, ago=0, price=p)
            elif plimit <= phigh:
                self._execute(order, ago=0, price=plimit)


class LongShortBackBroker(EnhancedIndexBackBroker):

    def init(self):
        super().init()
        self.lvrg_long_cash = 0
        self.lvrg_short_cash = 0

        self.prev_long_value = 0
        self.prev_short_value = 0
        self.long_value = 0
        self.short_value = 0

        self.is_incremental = False


    def _get_value(self, datas=None, lever=False):
        pos_value = 0.0
        pos_value_unlever = 0.0
        unrealized = 0.0

        while self._cash_addition:
            c = self._cash_addition.popleft()
            self._fundshares += c / self._fundval
            self.cash += c

        for data in datas or self.positions:
            comminfo = self.getcommissioninfo(data)
            position = self.positions[data]
            if not self.p.shortcash:
                dvalue = comminfo.getvalue(position, data.close[0])
            else:
                dvalue = comminfo.getvaluesize(position.size, data.close[0])

            dunrealized = comminfo.profitandloss(position.size, position.price, data.close[0])
            if datas and len(datas) == 1:
                if lever and dvalue > 0:
                    dvalue -= dunrealized
                    return (dvalue / comminfo.get_leverage()) + dunrealized
                return dvalue

            pos_value += dvalue
            unrealized += dunrealized

            if dvalue > 0:
                pos_value_unlever += dunrealized
            else:
                pos_value_unlever += dunrealized

        if not self._fundhist:
            self._value = self.cash + pos_value_unlever
            self._fundval = self._value / self._fundshares
        else:
            fval, fvalue = self._process_fund_history()

            self._value = fvalue
            self.cash = fvalue - pos_value_unlever
            self._fundval = fval
            self._fundshares = fvalue / fval
            lev = pos_value / (pos_value_unlever or 1.0)

            pos_value_unlever = fvalue
            pos_value = fvalue * lev

        self._valuemkt = pos_value_unlever

        self._valuelever = self.cash + pos_value
        self._valuemktlever = pos_value

        self._leverage = pos_value / (pos_value_unlever or 1.0)
        self._unrealized = unrealized

        return self._value if not lever else self._valuelever

    def get_unrealized(self):
        return self._unrealized

    def get_real_value(self):
        return self._value


    def check_submitted(self):
        cash = self.cash
        positions = {}

        while self.submitted:
            order = self.submitted.popleft()
            if self._take_children(order) is None:
                continue

            position = positions.setdefault(order.data, self.positions[order.data].clone())

            if order.isbuy():
                p = self._slip_up(order.data.high[0], order.data.open[0], doslip=self.p.slip_open)
            else:
                p = self._slip_down(order.data.low[0], order.data.open[0], doslip=self.p.slip_open)
            cash = self._execute(order, price=p, cash=cash, position=position)

            if cash >= 0.0:
                self.submit_accept(order)
                continue

            order.margin()
            self.notify(order)
            self._ococheck(order)
            self._bracketize(order, cancel=True)


    def _execute(self, order, ago=None, price=None, cash=None, position=None, dtcoc=None):
        if ago is not None and price is None:
            return

        if self.p.filler is None or ago is None:
            size = order.executed.remsize
        else:
            size = self.p.filler(order, price, ago)
            if not order.isbuy():
                size = -size

        comminfo = self.getcommissioninfo(order.data)

        if order.data._compensate is not None:
            data = order.data._compensate
            cinfocomp = self.getcommissioninfo(data)
        else:
            data = order.data
            cinfocomp = comminfo

        if ago is not None:
            position = self.positions[data]
            pprice_orig = position.price

            psize, pprice, opened, closed = position.pseudoupdate(size, price)

            pnl = comminfo.profitandloss(-closed, pprice_orig, price)
            cash = self.cash

        else:
            pnl = 0
            if not self.p.coo:
                pprice_orig = price
            else:
                if order.exectype == Order.Market:
                    price = pprice_orig = order.data.open[0]
                else:
                    price = pprice_orig = order.created.price

            psize, pprice, opened, closed = position.update(size, price)

        if closed:
            if self.p.shortcash:
                closedvalue = comminfo.getvaluesize(-closed, pprice_orig)
            else:
                closedvalue = comminfo.getoperationcost(closed, pprice_orig)

            closecash = closedvalue

            if closedvalue > 0:
                closecash /= comminfo.get_leverage()

            if "id" in order.info["sr"]:
                cash += pnl * comminfo.stocklike
                if ago is not None:
                    self.lvrg_short_cash -= closecash
            else:
                cash += pnl * comminfo.stocklike
                if ago is not None:
                    self.lvrg_long_cash -= closecash

            closedcomm = comminfo.getcommission(closed, price)
            cash -= closedcomm

            if ago is not None:
                cash += comminfo.cashadjust(-closed, position.adjbase, price)
                self.cash = cash
        else:
            closedvalue = closedcomm = 0.0

        popened = opened
        if opened:
            if self.p.shortcash:
                openedvalue = comminfo.getvaluesize(opened, price)
            else:
                openedvalue = comminfo.getoperationcost(opened, price)

            opencash = openedvalue
            if openedvalue > 0:
                if psize < 0:
                    opencash = 0
                else:
                    opencash /= comminfo.get_leverage()

            if ago is not None:
                if "id" in order.info["sr"]:
                    self.lvrg_short_cash += openedvalue
                else:
                    self.lvrg_long_cash += opencash

            openedcomm = cinfocomp.getcommission(opened, price)
            cash -= openedcomm

            if cash < 0.0:
                opened = 0
                openedvalue = openedcomm = 0.0

            elif ago is not None:
                if abs(psize) > abs(opened):
                    adjsize = psize - opened
                    cash += comminfo.cashadjust(adjsize, position.adjbase, price)

                position.adjbase = price

                self.cash = cash
        else:
            openedvalue = openedcomm = 0.0

        if ago is None:
            return cash

        execsize = closed + opened

        if execsize:
            comminfo.confirmexec(execsize, price)

            position.update(execsize, price, data.datetime.datetime())

            if closed and self.p.int2pnl:
                closedcomm += self.d_credit.pop(data, 0.0)

            order.execute(
                dtcoc or data.datetime[ago],
                execsize,
                price,
                closed,
                closedvalue,
                closedcomm,
                opened,
                openedvalue,
                openedcomm,
                comminfo.margin,
                pnl,
                psize,
                pprice,
            )

            order.addcomminfo(comminfo)

            self.notify(order)
            self._ococheck(order)

        if popened and not opened:
            order.margin()
            self.notify(order)
            self._ococheck(order)
            self._bracketize(order, cancel=True)


    def next(self):
        while self._toactivate:
            self._toactivate.popleft().activate()

        if self.p.checksubmit:
            self.check_submitted()

        credit = 0.0
        for data, pos in self.positions.items():
            if pos:
                comminfo = self.getcommissioninfo(data)
                dt0 = data.datetime.datetime()
                dcredit = comminfo.get_credit_interest(data, pos, dt0)
                self.d_credit[data] += dcredit
                credit += dcredit
                pos.datetime = dt0

        self.cash -= credit

        self._process_order_history()

        self.pending.append(None)
        while True:
            order = self.pending.popleft()
            if order is None:
                break

            if order.expire():
                self.notify(order)
                self._ococheck(order)
                self._bracketize(order, cancel=True)

            elif not order.active():
                self.pending.append(order)

            else:
                self._try_exec(order)
                if order.alive():
                    self.pending.append(order)

                elif order.status == Order.Completed:
                    self._bracketize(order)


        if self.is_incremental:
            self.is_incremental = False

        for data, pos in self.positions.items():
            if pos:
                comminfo = self.getcommissioninfo(data)
                self.cash += comminfo.cashadjust(pos.size, pos.adjbase, data.close[0])
                pos.adjbase = data.close[0]

        self._get_value()


__all__ = ["EnhancedIndexBackBroker", "LongShortBackBroker"]
