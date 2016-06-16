"""
Utility functions and classes for receiver function calculation.
"""
import collections
import itertools
import numpy as np


DEG2KM = 111.2  #: Conversion factor from degrees epicentral distance to km


def iter_event_data(catalog, inventory, get_waveforms, phase='P',
                    request_window=None, pad=10, pbar=None, **kwargs):
    """
    Return iterator yielding three component streams per station and event.

    :param catalog: `~obspy.core.event.Catalog` instance with events
    :param inventory: `~obspy.core.inventory.inventory.Inventory` instance
        with station and channel information
    :param get_waveforms: Function returning the data. It has to take the
        arguments network, station, location, channel, starttime, endtime.
    :param phase: Considered phase, e.g. 'P', 'S', 'PP'
    :type request_window: tuple (start, end)
    :param request_window: requested time window around the onset of the phase
    :param float pad: add specified time in seconds to request window and
       trim afterwards again
    :param pbar: tqdm_ instance for displaying a progressbar

    Example usage with progressbar::

        from tqdm import tqdm
        from rf.util import iter_event_data
        with tqdm() as t:
            for stream3c in iter_event_data(*args, pbar=t):
                do_something(stream3c)

    .. _tqdm: https://pypi.python.org/pypi/tqdm
    """
    from rf.rfstream import rfstats, RFStream
    method = phase[-1].upper()
    if request_window is None:
        request_window = (-50, 150) if method == 'P' else (-100, 50)
    channels = inventory.get_contents()['channels']
    stations = {ch[:-1] + '?': ch[-1] for ch in channels}
    if pbar is not None:
        pbar.total = len(catalog) * len(stations)
    for event, seedid in itertools.product(catalog, stations):
        if pbar is not None:
            pbar.update(1)
        origin_time = (event.preferred_origin() or event.origins[0])['time']
        try:
            args = (seedid[:-1] + stations[seedid], origin_time)
            coords = inventory.get_coordinates(*args)
        except:  # station not available at that time
            continue
        stats = rfstats(station=coords, event=event, phase=phase, **kwargs)
        if not stats:
            continue
        net, sta, loc, cha = seedid.split('.')
        starttime = stats.onset + request_window[0]
        endtime = stats.onset + request_window[1]
        kws = {'network': net, 'station': sta, 'location': loc,
               'channel': cha, 'starttime': starttime - pad,
               'endtime': endtime + pad}
        try:
            stream = get_waveforms(**kws)
        except:  # no data available
            continue
        stream.trim(starttime, endtime)
        stream.merge()
        if len(stream) != 3:
            from warnings import warn
            warn('Need 3 component seismograms. %d components '
                 'detected for event %s, station %s.'
                 % (len(stream), event.resource_id, seedid))
            continue
        if any(isinstance(tr.data, np.ma.masked_array) for tr in stream):
            from warnings import warn
            warn('Gaps or overlaps detected for event %s, station %s.'
                 % (event.resource_id, seedid))
            continue
        for tr in stream:
            tr.stats.update(stats)
        yield RFStream(stream, warn=False)


class IterMultipleComponents(object):

    """
    Return iterable to iterate over associated components of a stream.

    :param stream: Stream with different, possibly many traces. It is
        split into substreams with the same seed id (only last character
        i.e. component may vary)
    :type key: str or None
    :param key: Additionally, the stream is grouped by the values of
         the given stats entry to differentiate between e.g. different events
         (for example key='starttime', key='onset')
    :type number_components: int, tuple of ints or None
    :param number_components: Only iterate through substreams with
         matching number of components.
    """

    def __init__(self, stream, key=None, number_components=None):
        substreams = collections.defaultdict(stream.__class__)
        for tr in stream:
            k = (tr.id[:-1], str(tr.stats[key]) if key is not None else None)
            substreams[k].append(tr)
        n = number_components
        self.substreams = [s for _, s in sorted(substreams.items())
                           if n is None or len(s) == n or len(s) in n]

    def __len__(self):
        return len(self.substreams)

    def __iter__(self):
        for s in self.substreams:
            yield s


def direct_geodetic(latlon, azi, dist):
    """
    Solve direct geodetic problem with geographiclib.

    :param tuple latlon: coordinates of first point
    :param azi: azimuth of direction
    :param dist: distance in km

    :return: coordinates (lat, lon) of second point on a WGS84 globe
    """
    from geographiclib.geodesic import Geodesic
    coords = Geodesic.WGS84.Direct(latlon[0], latlon[1], azi, dist * 1000)
    return coords['lat2'], coords['lon2']