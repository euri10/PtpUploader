from Job.JobRunningState import JobRunningState
from Source.SourceBase import SourceBase

from Helper import DecodeHtmlEntities, GetSizeFromText, MakeRetryingHttpRequest, RemoveDisallowedCharactersFromPath
from MyGlobals import MyGlobals
from NfoParser import NfoParser
from PtpUploaderException import PtpUploaderException
from ReleaseExtractor import ReleaseExtractor
from ReleaseInfo import ReleaseInfo
from ReleaseNameParser import ReleaseNameParser

import re
import time
import urllib
import urllib2


class HDAccess(SourceBase):
    RequiredHttpHeader = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.11 (KHTML, like Gecko) Chrome/23.0.1271.64 Safari/537.11', 'Referer': 'https://hdaccess.net', 'Origin': 'https://hdaccess.net'}

    def __init__(self):
        SourceBase.__init__(self)

        self.Name = "hda"
        self.NameInSettings = "HDAccess"

    def LoadSettings(self, settings):
        SourceBase.LoadSettings(self, settings)

    def IsEnabled(self):
        return len(self.Username) > 0 and len(self.Password) > 0

    def Login(self):
        MyGlobals.Logger.info("Logging in to HD-Access.")
        opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(MyGlobals.CookieJar))
        postData = urllib.urlencode({"username": self.Username, "password": self.Password, "perm_ssl": 1, "returnto": "/", "submitme": "X"})
        request = urllib2.Request("https://hdaccess.net/takelogin.php", postData, headers=HDAccess.RequiredHttpHeader)
        result = opener.open(request)
        response = result.read()
        self.CheckIfLoggedInFromResponse(response)

    def CheckIfLoggedInFromResponse(self, response):
        if response.find('form action="login.php""') != -1:
            raise PtpUploaderException("Looks like you are not logged in to HDAccess. Probably due to the bad user name or password in settings.")

        # Sets IMDb if presents in the torrent description.
        # Returns with the release name.

    def __ReadTorrentPage(self, logger, releaseInfo):
        url = "https://hdaccess.net/details.php?id=%s" % releaseInfo.AnnouncementId
        logger.info("Downloading NFO from page '%s'." % url)
        opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(MyGlobals.CookieJar))
        request = urllib2.Request(url, headers=HDAccess.RequiredHttpHeader)
        result = opener.open(request)
        response = result.read()
        response = response.decode("utf-8", "ignore")
        self.CheckIfLoggedInFromResponse(response)

        # Make sure we only get information from the description and not from the comments.
        descriptionEndIndex = response.find("""<a name="startcomments">""")
        if descriptionEndIndex == -1:
            raise PtpUploaderException(JobRunningState.Ignored_MissingInfo, "Description can't be found. Probably the layout of the site has changed.")

        description = response[:descriptionEndIndex]

        # Get release name.
        matches = re.search(r"""<h1>(.*)</h1>""", description)
        if matches is None:
            raise PtpUploaderException(JobRunningState.Ignored_MissingInfo, "Release name can't be found on torrent page.")

        releaseName = DecodeHtmlEntities(matches.group(1))

        # Get IMDb id.
        if (not releaseInfo.HasImdbId()) and (not releaseInfo.HasPtpId()):
            releaseInfo.ImdbId = NfoParser.GetImdbId(description)

        # Get size.
        #                   <tr><td class='heading' valign='top' align='right'>Size</td><td valign='top' align='left'>13.21 GB</td></tr>
        matches = re.search(r"""<td class='heading' valign='top' align='right'>Size</td><td valign='top' align='left'>(.*)</td>""", description)
        if matches is None:
            logger.warning("Size not found on torrent page.")
        else:
            size = matches.group(1)
            releaseInfo.Size = GetSizeFromText(size)

        # Store the download URL.
        matches = re.search(r"""href="download.php\?torrent=(.+?)">""", description)
        if matches is None:
            raise PtpUploaderException(JobRunningState.Ignored_MissingInfo, "Download link can't be found on torrent page.")
        releaseInfo.SceneAccessDownloadUrl = "https://hdaccess.net/download.php?torrent=" + matches.group(1)
        return releaseName

    def __HandleUserCreatedJob(self, logger, releaseInfo):
        releaseName = self.__ReadTorrentPage(logger, releaseInfo)
        releaseInfo.ReleaseName = releaseName

        releaseNameParser = ReleaseNameParser(releaseInfo.ReleaseName)
        isAllowedMessage = releaseNameParser.IsAllowed()
        if isAllowedMessage is not None:
            raise PtpUploaderException(JobRunningState.Ignored, isAllowedMessage)

        releaseInfo.ReleaseName = RemoveDisallowedCharactersFromPath(releaseInfo.ReleaseName)

        releaseNameParser.GetSourceAndFormat(releaseInfo)
        if releaseNameParser.Scene:
            releaseInfo.SetSceneRelease()

    def __HandleAutoCreatedJob(self, logger, releaseInfo):
        # In case of automatic announcement we have to check the release name if it is valid.
        # We know the release name from the announcement, so we can filter it without downloading anything
        # (yet) from the source.

        releaseInfo.ReleaseName = self.__ReadTorrentPage(logger, releaseInfo)
        releaseNameParser = ReleaseNameParser(releaseInfo.ReleaseName)
        isAllowedMessage = releaseNameParser.IsAllowed()
        if isAllowedMessage is not None:
            raise PtpUploaderException(JobRunningState.Ignored, isAllowedMessage)

        releaseInfo.ReleaseName = RemoveDisallowedCharactersFromPath(releaseInfo.ReleaseName)

        releaseNameParser.GetSourceAndFormat(releaseInfo)

        if releaseNameParser.Scene:
            releaseInfo.SetSceneRelease()

        if (not releaseInfo.IsSceneRelease()) and self.AutomaticJobFilter == "SceneOnly":
            raise PtpUploaderException(JobRunningState.Ignored, "Non-scene release.")

    def PrepareDownload(self, logger, releaseInfo):
        if releaseInfo.IsUserCreatedJob():
            self.__HandleUserCreatedJob(logger, releaseInfo)
        else:
            self.__HandleAutoCreatedJob(logger, releaseInfo)

    def DownloadTorrent(self, logger, releaseInfo, path):
        # This can't happen.
        if len(releaseInfo.SceneAccessDownloadUrl) <= 0:
            raise PtpUploaderException("Download URL is not set.")

        # We don't log the download URL because it is sensitive information.
        logger.info("Downloading torrent file from HDAcecss to '%s'." % path)

        opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(MyGlobals.CookieJar))
        request = urllib2.Request(releaseInfo.SceneAccessDownloadUrl, headers=HDAccess.RequiredHttpHeader)
        result = opener.open(request)
        response = result.read()
        self.CheckIfLoggedInFromResponse(response)

        file = open(path, "wb")
        file.write(response)
        file.close()

        # Calling Helper.ValidateTorrentFile is not needed because NfoParser.IsTorrentContainsMultipleNfos will throw
        # an exception if it is not a valid torrent file.

        # If a torrent contains multiple NFO files then it is likely that the site also showed the wrong NFO and we
        # have checked the existence of another movie on PTP.
        # So we abort here. These errors happen rarely anyway.
        # (We could also try read the NFO with the same name as the release or with the same name as the first RAR
        # and reschedule for checking with the correct IMDb id.)
        if NfoParser.IsTorrentContainsMultipleNfos(path):
            raise PtpUploaderException("Torrent '%s' contains multiple NFO files." % path)

    def GetIdFromUrl(self, url):
        result = re.match(r".*hdaccess\.org/download\.php\?torrent=(\s+).*", url)
        if result is None:
            return ""
        else:
            return result.group(1)

    def GetUrlFromId(self, id):
        return "https://hdaccess.net/details.php?id=" + id

    def GetIdFromAutodlIrssiUrl(self, url):
        # https://hd-torrents.org//download.php?id=808b75cd4c5517d5a3001becb3b7c6ce5274ca62&f=Brief%20Encounter%201945%20720p%20BluRay%20FLAC%20x264-HDB.torrent
        result = re.match(r".*hdaccess\.net\/\/details\.php\?id=(\w+)&f", url)
        if result is None:
            return ""
        else:
            return DecodeHtmlEntities(result.group(1))
