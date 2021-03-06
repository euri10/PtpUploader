from PtpSubtitle import PtpSubtitle

import cookielib
import datetime
import logging
import os
import sys
import requests


class MyGlobalsClass:
    def __init__(self):
        self.CookieJar = None
        self.Logger = None
        self.PtpUploader = None
        self.SourceFactory = None
        self.PtpSubtitle = None
        self.TorrentClient = None
        self.session = requests.session()

    def InitializeGlobals(self, workingPath):
        self.InitializeLogger(workingPath)
        self.CookieJar = cookielib.CookieJar()
        self.PtpSubtitle = PtpSubtitle()

    # workingPath from Settings.WorkingPath.
    def InitializeLogger(self, workingPath):
        # This will create the log directory too.
        announcementLogDirPath = os.path.join(workingPath, "log/announcement")
        if not os.path.isdir(announcementLogDirPath):
            os.makedirs(announcementLogDirPath)

        logDirPath = os.path.join(workingPath, "log")

        logDate = datetime.datetime.now().strftime("%Y.%m.%d. - %H_%M_%S")
        logPath = os.path.join(logDirPath, logDate + ".txt")

        self.Logger = logging.getLogger('PtpUploader')

        # file
        handler = logging.FileHandler(logPath)
        formatter = logging.Formatter("[%(asctime)s] %(levelname)-8s %(message)s", "%Y-%m-%d %H:%M:%S")
        handler.setFormatter(formatter)
        self.Logger.addHandler(handler)

        # stdout
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(formatter)
        self.Logger.addHandler(console)

        self.Logger.setLevel(logging.INFO)

    # Inline imports are used here to avoid unnecessary dependencies.
    def GetTorrentClient(self):
        if self.TorrentClient is None:
            from Settings import Settings

            if Settings.TorrentClientName.lower() == "transmission":
                from Tool.Transmission import Transmission

                self.TorrentClient = Transmission(Settings.TorrentClientAddress, Settings.TorrentClientPort)
            else:
                from Tool.Rtorrent import Rtorrent

                self.TorrentClient = Rtorrent()

        return self.TorrentClient


MyGlobals = MyGlobalsClass()