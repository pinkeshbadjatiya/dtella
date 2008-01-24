"""
Dtella - Dynamic Config Pusher Module
Copyright (C) 2008  Dtella Labs (http://www.dtella.org/)
Copyright (C) 2008  Paul Marks (http://www.pmarks.net/)

$Id$

This program is free software; you can redistribute it and/or
modify it under the terms of the GNU General Public License
as published by the Free Software Foundation; either version 2
of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
"""

import binascii
import md5
import random
import time

from twisted.internet import reactor

from Crypto.Util.number import long_to_bytes
from Crypto.PublicKey import RSA

import dtella.bridge_config as cfg
from dtella.common.log import LOG

from dtella.common.util import Ad

# TODO: Implement a stand-alone config pusher (./dtella.py --configpusher)


class DNSUpdateManager(object):

    # Calls the 'dnsup_update_func' function in dtella_bridge_config,
    # which accepts a dictionary of key=value pairs, and returns a twisted
    # Deferred object.  We currently have a module which writes to a text
    # file, and another which performs a Dynamic DNS update.  Other modules
    # could potentially be written for free DNS hosting services.
    
    def __init__(self, main):
        self.main = main
        self.update_dcall = None
        self.busy = False

        self.scheduleUpdate(30.0)


    def scheduleUpdate(self, when):

        if self.update_dcall or self.busy:
            return

        def cb():
            self.update_dcall = None
            entries = self.getEntries()

            self.busy = True
            
            d = cfg.dnsup_update_func(entries)
            d.addCallback(self.updateSuccess)
            d.addErrback(self.updateFailed)

        self.update_dcall = reactor.callLater(when, cb)


    def updateSuccess(self, result):
        self.busy = False

        LOG.debug("DNS Update Successful: %s" % result)
        
        self.scheduleUpdate(cfg.dnsup_interval)


    def updateFailed(self, why):
        self.busy = False

        LOG.warning("DNS Update Failed: %s" % why)
        
        self.scheduleUpdate(cfg.dnsup_interval)


    def getEntries(self):
        # Build and return a dict of entries which should be sent to DNS

        def b64(arg):
            return binascii.b2a_base64(arg).rstrip()
        
        # Dictionary of key=value pairs to return.
        # Start out with the static entries provided in the config.
        entries = cfg.dnsup_fixed_entries.copy()

        osm = self.main.osm

        # Generate public key hash
        if cfg.private_key:
            pubkey = long_to_bytes(RSA.construct(cfg.private_key).n)
            entries['pkhash'] = b64(md5.new(pubkey).digest())

        # Collect IPPs for the ipcache string
        GOAL = 10
        ipps = set()

        # Initially add all the exempt IPs, without a port
        for ip in self.main.state.exempt_ips:
            ad = Ad()
            ad.ip = ip
            ad.port = 0
            ipps.add(ad.getRawIPPort())

        # Helper function to add an IPP, overriding any portless entries.
        def add_ipp(ipp):
            ipps.discard(ipp[:4] + '\0\0')
            ipps.add(ipp)

        # Add my own IP
        if osm:
            add_ipp(osm.me.ipp)
        else:
            try:
                add_ipp(self.main.selectMyIP())
            except ValueError:
                pass

        # Add the IPPs of online nodes
        if (osm and osm.syncd):

            now = time.time()

            def n_uptime(n):
                uptime = max(0, now - n.uptime)
                if n.persist:
                    uptime *= 1.5
                return -uptime
            
            nodes = osm.nodes[:]
            nodes.sort(key=n_uptime)

            for n in nodes:
                add_ipp(n.ipp)
                if len(ipps) >= GOAL:
                    break

        # Add the IPPs of offline nodes (if necessary)
        if len(ipps) < GOAL:
            for when,ipp in self.main.state.getYoungestPeers(GOAL):
                add_ipp(ipp)

                if len(ipps) >= GOAL:
                    break

        ipcache = list(ipps)
        random.shuffle(ipcache)

        ipcache = '\xFF\xFF\xFF\xFF' + ''.join(ipcache)
        ipcache = b64(self.main.pk_enc.encrypt(ipcache))

        entries['ipcache'] = ipcache

        return entries
