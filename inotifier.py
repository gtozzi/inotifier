#!/usr/bin/env python

# -*- coding: utf-8 -*-

'''
iNotifier

@author Gabriele Tozzi <gabriele@tozzi.eu>

Watches a series of directories for changes, and notify them by email

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

'''

import pyinotify
import argparse, ConfigParser
import smtplib
from email.mime.text import MIMEText
from string import Template
import re

NAME = 'iNotifier'
VERSION = '1.1'

class EventHandler(pyinotify.ProcessEvent):
    ''' Handles events '''
    
    def __init__(self, watchlist, verbose=False):
        self.watchlist = watchlist
        self.verbose = verbose
        super(EventHandler,self).__init__()
    
    def process_default(self, event):

        # Find the watch item
        w = None
        for k in self.watchlist.keys():
            if unicode(event.path).startswith(k):
                w = self.watchlist[k]
                break
        if not w:
            if self.verbose:
                print 'Event', event.maskname, 'on', event.path, ':', event
            raise RuntimeError(u'Unknown watch: ' + unicode(event.path))
        
        # Check for ignore
        if w.ignore and w.ignore.match(event.name):
            return
        
        # Print event
        if self.verbose:
            print 'Event', event.maskname, 'on', event.path, ':', event
        
        # Send eMail
        msg = MIMEText(w.body.substitute(event.__dict__), w.btype)
        msg.set_charset('utf-8')
        msg['Subject'] = w.subject.substitute(event.__dict__)
        msg['From'] = w.mailfrom
        msg['To'] = w.mailto
        
        s = smtplib.SMTP('localhost')
        s.sendmail(
            w.mailfrom,
            (w.mailto,),
            msg.as_string()
        )
        s.quit()
    
class WatchItem():
    ''' A item bein' watched '''

    def __init__(self, name, path, events, recurse, ignore, mailto, mailfrom,
            subject, body, btype):
        self.name = name
        self.path = path
        self.events = events
        self.recurse = recurse
        self.ignore = ignore
        self.mailto = mailto
        self.mailfrom = mailfrom
        self.subject = subject
        self.body = body
        self.btype=btype

class Main():
    ''' Main class '''

    def __init__(self):
        ''' Read config and command line '''

        # Read the command line
        parser = argparse.ArgumentParser(
            description = NAME + ' ' + VERSION + ': ' + __doc__,
            prog = NAME,
        )
        parser.add_argument('configfile',
            help='the file to read config from')
        parser.add_argument('-v', '--verbose', dest='verbose',
            action='store_true',
            help='also notify on stdout')
        
        args = parser.parse_args()
        self.verbose = args.verbose

        # Read the config file
        config = ConfigParser.ConfigParser()
        config.read(args.configfile)

        # Build WatchItem objects
        self.watch = {}
        for s in config.sections():
            events = map(lambda i: i.strip(), config.get(s,'events').split(','))
            events = sum(map(lambda i: getattr(pyinotify,i), events))
            try:
                ignore = re.compile(config.get(s, 'ignore'))
            except ConfigParser.NoOptionError:
                ignore = None
            self.watch[config.get(s, 'path')] = WatchItem(
                s,
                config.get(s, 'path'),
                events,
                config.getboolean(s, 'recurse'),
                ignore,
                config.get(s, 'mailto'),
                config.get(s, 'mailfrom'),
                Template(config.get(s, 'subject')),
                Template(config.get(s, 'body')),
                config.get(s, 'type'),
            )
    
    def run(self):
        ''' Starts the daemon '''
        
        # watch manager
        wm = pyinotify.WatchManager()
        for k in self.watch.keys():
            w = self.watch[k]
            wm.add_watch(w.path, w.events, rec=w.recurse, quiet=False)

        # event handler
        eh = EventHandler(self.watch, self.verbose)

        # Start notifier loop
        notifier = pyinotify.Notifier(wm, eh)
        notifier.loop()

if __name__ == '__main__':
    Main().run()
