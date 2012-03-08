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

import sys, os, time, atexit
from signal import SIGTERM
import pyinotify
import argparse, ConfigParser
import smtplib
from email.mime.text import MIMEText
from string import Template
import re

NAME = 'iNotifier'
VERSION = '1.1'

class Daemon(object):
    """
    A generic daemon class.
    
    Usage: subclass the Daemon class and override the run() method
    
    @author Sander Marechal
    @url http://www.jejik.com/articles/2007/02/a_simple_unix_linux_daemon_in_python/
    """
    def __init__(self, pidfile, stdin='/dev/null', stdout='/dev/null', stderr='/dev/null'):
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr
        self.pidfile = pidfile
    
    def daemonize(self):
        """
        do the UNIX double-fork magic, see Stevens' "Advanced 
        Programming in the UNIX Environment" for details (ISBN 0201563177)
        http://www.erlenstar.demon.co.uk/unix/faq_2.html#SEC16
        """
        try:
            pid = os.fork()
            if pid > 0:
                # exit first parent
                sys.exit(0)
        except OSError, e:
            sys.stderr.write("fork #1 failed: %d (%s)\n" % (e.errno, e.strerror))
            sys.exit(1)
    
        # decouple from parent environment
        os.chdir("/")
        os.setsid()
        os.umask(0)
    
        # do second fork
        try: 
            pid = os.fork()
            if pid > 0:
                # exit from second parent
                sys.exit(0)
        except OSError, e:
            sys.stderr.write("fork #2 failed: %d (%s)\n" % (e.errno, e.strerror))
            sys.exit(1)
    
        # write pidfile
        atexit.register(self.delpid)
        pid = str(os.getpid())
        try:
            file(self.pidfile,'w+').write("%s\n" % pid)
        except IOError, e:
            sys.stderr.write("write pid file %s failed: %d (%s)\n" % (self.pidfile, e.errno, e.strerror))
            sys.exit(1)
    
        # redirect standard file descriptors
        sys.stdout.flush()
        sys.stderr.flush()
        si = file(self.stdin, 'r')
        so = file(self.stdout, 'a+')
        se = file(self.stderr, 'a+', 0)
        os.dup2(si.fileno(), sys.stdin.fileno())
        os.dup2(so.fileno(), sys.stdout.fileno())
        os.dup2(se.fileno(), sys.stderr.fileno())
    
    def delpid(self):
        try:
            os.remove(self.pidfile)
        except OSError:
            pass

    def start(self):
        """
        Start the daemon
        """
        # Check for a pidfile to see if the daemon already runs
        try:
            pf = file(self.pidfile,'r')
            pid = int(pf.read().strip())
            pf.close()
        except IOError:
            pid = None
    
        if pid:
            message = "pidfile %s already exist. Daemon already running?\n"
            sys.stderr.write(message % self.pidfile)
            sys.exit(1)
        
        # Start the daemon
        self.daemonize()
        self.run()

    def stop(self):
        """
        Stop the daemon
        """
        # Get the pid from the pidfile
        try:
            pf = file(self.pidfile,'r')
            pid = int(pf.read().strip())
            pf.close()
        except IOError:
            pid = None
    
        if not pid:
            message = "pidfile %s does not exist. Daemon not running?\n"
            sys.stderr.write(message % self.pidfile)
            return # not an error in a restart

        # Try killing the daemon process    
        try:
            while 1:
                os.kill(pid, SIGTERM)
                time.sleep(0.1)
        except OSError, err:
            err = str(err)
            if err.find("No such process") > 0:
                if os.path.exists(self.pidfile):
                    os.remove(self.pidfile)
            else:
                print str(err)
                sys.exit(1)

    def restart(self):
        """
        Restart the daemon
        """
        self.stop()
        self.start()

    def run(self):
        """
        You should override this method when you subclass Daemon. It will be called after the process has been
        daemonized by start() or restart().
        """

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

class Main(Daemon):
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
        parser.add_argument('-f', '--foreground', dest='foreground',
            action='store_true',
            help='run in foreground, don\'t daemonize')
        parser.add_argument('-p', '--pid', dest='pid',
            default='/var/run/' + NAME.lower() + '.pid',
            help='name of the PID file (used when daemonizing, default: %(default)s)')
        
        args = parser.parse_args()
        self.verbose = args.verbose
        self.foreground = args.foreground
        self.pidfile = args.pid

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
        
        # Calls super init method
        super(Main, self).__init__(self.pidfile)

        # Start myself
        if self.foreground:
            self.run()
        else:
            self.start()
    
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
    Main()
    sys.exit(0)
