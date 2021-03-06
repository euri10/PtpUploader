﻿from InformationSource.Imdb import Imdb
from Job.JobRunningState import JobRunningState
from Source.SourceBase import SourceBase

from Helper import DecodeHtmlEntities, GetSizeFromText, RemoveDisallowedCharactersFromPath, ValidateTorrentFile
from MyGlobals import MyGlobals
from NfoParser import NfoParser
from PtpUploaderException import *
from ReleaseExtractor import ReleaseExtractor
from ReleaseInfo import ReleaseInfo

import os
import re
import urllib
import urllib2


class Karagarga(SourceBase):
    def __init__(self):
        SourceBase.__init__(self)

        self.Name = "kg"
        self.NameInSettings = "Karagarga"

    def LoadSettings(self, settings):
        SourceBase.LoadSettings(self, settings)

        self.AutoUploadSd = int(settings.GetDefault(self.NameInSettings, "AutoUploadSd", "1")) != 0
        self.AutoUpload720p = int(settings.GetDefault(self.NameInSettings, "AutoUpload720p", "0")) != 0
        self.AutoUpload1080p = int(settings.GetDefault(self.NameInSettings, "AutoUpload1080p", "0")) != 0

    def IsEnabled(self):
        return len(self.Username) > 0 and len(self.Password) > 0

    def Login(self):
        if len(self.Username) <= 0:
            raise PtpUploaderInvalidLoginException("Couldn't log in to Karagarga. Your username is not specified..")

        if len(self.Password) <= 0:
            raise PtpUploaderInvalidLoginException("Couldn't log in to Karagarga. Your password is not specified..")

        MyGlobals.Logger.info("Logging in to Karagarga.")
        opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(MyGlobals.CookieJar))
        postData = urllib.urlencode({"username": self.Username, "password": self.Password})
        request = urllib2.Request("http://karagarga.net/takelogin.php", postData)
        result = opener.open(request)
        response = result.read()
        self.__CheckIfLoggedInFromResponse(response)

    def __CheckIfLoggedInFromResponse(self, response):
        if response.find('action="takelogin.php"') != -1 or response.find("""<h2>Login failed!</h2>""") != -1:
            raise PtpUploaderException("Looks like you are not logged in to Karagarga. Probably due to the bad user name or password in settings.")

    def __DownloadNfoParseSourceType(self, releaseInfo, description):
        if releaseInfo.IsSourceSet():
            releaseInfo.Logger.info(
                "Source '%s' is already set, not getting from the torrent page." % releaseInfo.Source)
            return

        # <tr><td class="heading" align="right" valign="top">Source</td><td colspan="2" align="left" valign="top">dvdrip</td></tr>
        matches = re.search("""<tr><td class="heading".*?>Source</td><td.*?>(.+?)</td></tr>""", description)
        if matches is None:
            raise PtpUploaderException(JobRunningState.Ignored_MissingInfo,
                                       "Source type can't be found. Probably the layout of the site has changed.")

        sourceType = matches.group(1).lower()

        if sourceType == "blu-ray":
            releaseInfo.Source = "Blu-ray"
        elif sourceType == "dvd":
            releaseInfo.Source = "DVD"
        elif sourceType == "web":
            releaseInfo.Source = "WEB"
        elif sourceType == "vhs":
            releaseInfo.Source = "VHS"
        elif sourceType == "tv":
            releaseInfo.Source = "TV"
        else:
            raise PtpUploaderException(JobRunningState.Ignored_NotSupported,
                                       "Unsupported source type '%s'." % sourceType)

    def __DownloadNfoParseFormatType(self, releaseInfo, description):
        if releaseInfo.IsCodecSet():
            releaseInfo.Logger.info("Codec '%s' is already set, not getting from the torrent page." % releaseInfo.Codec)
            return

        # <tr><td class="heading" align="right" valign="top">Rip Specs</td><td colspan="2" align="left" valign="top">[General] Format: AVI
        # ...
        # </td></tr>
        ripSpecs = re.search(r"<tr><td.*?>Rip Specs</td><td.*?>(.+?)</td></tr>", description, re.DOTALL)
        if ripSpecs is None:
            raise PtpUploaderException(JobRunningState.Ignored_MissingInfo,
                                       "Rip specifications can't be found on the page.")

        ripSpecs = ripSpecs.group(1).upper()

        if ripSpecs.find("XVID") >= 0:
            releaseInfo.Codec = "XviD"
        elif ripSpecs.find("DIVX") >= 0:
            releaseInfo.Codec = "DivX"
        elif ripSpecs.find("X264") >= 0 or ripSpecs.find("V_MPEG4/ISO/AVC") >= 0:
            releaseInfo.Codec = "x264"
        else:
            raise PtpUploaderException(JobRunningState.Ignored_NotSupported,
                                       "Can't figure out codec from the rip specifications.")

    def __DownloadNfoParseResolution(self, releaseInfo, description):
        if releaseInfo.IsResolutionTypeSet():
            releaseInfo.Logger.info(
                "Resolution type '%s' is already set, not getting from the torrent page." % releaseInfo.ResolutionType)
            return

        if description.find('"genreimages/hdrip720.png"') != -1:
            releaseInfo.ResolutionType = "720"
        elif description.find('"genreimages/hdrip1080.png"') != -1:
            releaseInfo.ResolutionType = "1080"
        elif description.find('"genreimages/dvdr.png"') != -1:
            raise PtpUploaderException(JobRunningState.Ignored_NotSupported, "Untouched DVDs aren't supported.")
        elif description.find('"genreimages/bluray.png"') != -1:
            raise PtpUploaderException(JobRunningState.Ignored_NotSupported, "Untouched Blu-ray aren't supported.")
        else:
            # DVDR and other HD in the genre list. They're not supported.
            # <td style="border:none;"><img src="genreimages/dvdr.png" width="40" height="40" border="0" title="DVDR"></td>
            matches = re.search("""<td.*?><img src="genreimages/.+?" .*?title="(.+?)".*?></td>""", description)
            if matches is not None:
                notSupportedType = matches.group(1).lower()
                if notSupportedType == "dvdr" or notSupportedType == "hd":
                    raise PtpUploaderException(JobRunningState.Ignored_NotSupported,
                                               "Unsupported source or resolution type '%s'." % notSupportedType)

            releaseInfo.ResolutionType = "Other"

    def __DownloadNfoParseSubtitles(self, releaseInfo, description):
        # Only detect subtitles if they are not specified.
        if len(releaseInfo.GetSubtitles()) > 0:
            return

        # <td class="heading" align="right" valign="top">Subtitles</td><td colspan="2" align="left" valign="top">included: English<hr>
        match = re.search(r"<td.+?>Subtitles</td><td.+?>included: (.+?)<hr>", description)
        if match is None:
            return

        subtitlesText = match.group(1).lower()

        # Handle specially for subtitle comments like this: "None yet, started working on it.", "No, sorry."
        if subtitlesText.find("none") != -1 or subtitlesText.find("sorry") != -1:
            return

        if subtitlesText == "no" or subtitlesText == "no subtitles" or subtitlesText == "unknown if subtitles included":
            return

        # We don't want to add hardcoded subtitles.
        if subtitlesText.find("hard") != -1:
            return

        # On some torrents the subtitle type is indicated too. If it is IDX then we will
        # detect later in a more precise way.
        if subtitlesText.find("idx") != -1 or subtitlesText.find("vobsub") != -1:
            return

        # Remove comments.
        subtitlesText = subtitlesText.replace("subs added separately", "")
        subtitlesText = subtitlesText.replace("(custom)", "")
        subtitlesText = subtitlesText.replace("custom", "")
        subtitlesText = subtitlesText.replace("(optional/softcoded)", "")
        subtitlesText = subtitlesText.replace("(optional)", "")
        subtitlesText = subtitlesText.replace(".srt", "")
        subtitlesText = subtitlesText.replace("srt", "")

        # Go through the list of languages and try to get their PTP IDs.
        subtitleIds = []
        subtitleTexts = subtitlesText.split(",")
        for language in subtitleTexts:
            language = language.strip()
            id = MyGlobals.PtpSubtitle.GetId(language)
            if id is None:
                continue

            # IDs are stored strings. And we only add them only once to the list.
            id = str(id)
            if id not in subtitleIds:
                subtitleIds.append(id)

        if len(subtitleIds) > 0:
            releaseInfo.SetSubtitles(subtitleIds)

    def __ParsePage(self, logger, releaseInfo, html, parseForExternalCreateJob=False):
        # Make sure we only get information from the description and not from the comments.
        descriptionEndIndex = html.find('<p><a name="startcomments"></a></p>')
        if descriptionEndIndex == -1:
            raise PtpUploaderException(JobRunningState.Ignored_MissingInfo, "Description can't found on torrent page. Probably the layout of the site has changed.")

        description = html[:descriptionEndIndex]

        # We will use the torrent's name as release name.
        if not parseForExternalCreateJob:
            matches = re.search(r'href="/down.php/(\d+)/.+?">(.+?)\.torrent</a>', description)
            if matches is None:
                raise PtpUploaderException(JobRunningState.Ignored_MissingInfo,
                                           "Can't get release name from torrent page.")

            releaseName = DecodeHtmlEntities(matches.group(2))

            # Remove the extension of the container from the release name. (It is there on single file releases.)
            # Optional flags parameter for sub function was only introduced in
            # Python v2.7 so we use compile.sub instead.
            releaseName = re.compile(r"\.avi$", re.IGNORECASE).sub("", releaseName)
            releaseName = re.compile(r"\.mkv$", re.IGNORECASE).sub("", releaseName)
            releaseName = re.compile(r"\.mp4$", re.IGNORECASE).sub("", releaseName)
            # "none" can come from FlexGet from the announcement directory.
            if (not releaseInfo.IsReleaseNameSet()) or releaseInfo.ReleaseName == "none":
                releaseInfo.ReleaseName = releaseName

        # Make sure it is under the movie category.
        # <tr><td class="heading" align="right" valign="top">Type</td><td colspan="2" align="left" valign="top"><a href="browse.php?cat=1">Movie</a></td></tr>
        matches = re.search(r"""<tr><td.*?>Type</td><td.*?><a href="browse.php\?cat=1">Movie</a></td></tr>""",
                            description)
        if matches is None:
            raise PtpUploaderException(JobRunningState.Ignored_NotSupported, "Type is not movie.")

        # Get IMDb id.
        if (not releaseInfo.HasImdbId()) and (not releaseInfo.HasPtpId()):
            matches = re.search(r'imdb\.com/title/tt(\d+)', description)
            if matches is None:
                raise PtpUploaderException(JobRunningState.Ignored_MissingInfo,
                                           "IMDb id can't be found on torrent page.")

            releaseInfo.ImdbId = matches.group(1)

        # Get size.
        # <tr><td class="heading" align="right" valign="top">Size</td><td colspan="2" align="left" valign="top">1.37GB (1,476,374,914 bytes)</td></tr>
        matches = re.search(r"""<tr><td.*?>Size</td><td.*?>.+ \((.+ bytes)\)</td></tr>""", description)
        if matches is None:
            logger.warning("Size not found on torrent page.")
        else:
            size = matches.group(1)
            releaseInfo.Size = GetSizeFromText(size)

        self.__DownloadNfoParseSourceType(releaseInfo, description)
        self.__DownloadNfoParseFormatType(releaseInfo, description)
        self.__DownloadNfoParseResolution(releaseInfo, description)
        self.__DownloadNfoParseSubtitles(releaseInfo, description)

        # Make sure that this is not a wrongly categorized DVDR.
        if (not releaseInfo.IsDvdImage()) and (re.search(r"<td>.+?\.vob</td>", description, re.IGNORECASE) or re.search(r"<td>.+?\.iso</td>", description, re.IGNORECASE)):
            raise PtpUploaderException(JobRunningState.Ignored_NotSupported, "Wrongly categorized DVDR.")

    def __DownloadNfo(self, logger, releaseInfo):
        url = "http://karagarga.net/details.php?id=%s&filelist=1" % releaseInfo.AnnouncementId
        logger.info("Collecting info from torrent page '%s'." % url)

        opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(MyGlobals.CookieJar))
        request = urllib2.Request(url)
        result = opener.open(request)
        response = result.read()
        response = response.decode("ISO-8859-1", "ignore")
        self.__CheckIfLoggedInFromResponse(response)

        self.__ParsePage(logger, releaseInfo, response)

    def __HandleAutoCreatedJob(self, releaseInfo):
        if releaseInfo.ResolutionType == "720":
            if not self.AutoUpload720p:
                raise PtpUploaderException(JobRunningState.Ignored, "720p is on your ignore list.")
        elif releaseInfo.ResolutionType == "1080":
            if not self.AutoUpload1080p:
                raise PtpUploaderException(JobRunningState.Ignored, "1080p is on your ignore list.")
        elif releaseInfo.ResolutionType == "Other":
            if not self.AutoUploadSd:
                raise PtpUploaderException(JobRunningState.Ignored, "SD is on your ignore list.")

            # TODO: add filtering support for Karagarga
            # In case of automatic announcement we have to check the release name if it is valid.
            # We know the release name from the announcement, so we can filter it without downloading
            # anything (yet) from the source.
            # if not ReleaseFilter.IsValidReleaseName( releaseInfo.ReleaseName ):
            # logger.info( "Ignoring release '%s' because of its name." % releaseInfo.ReleaseName )
            # return None

    def PrepareDownload(self, logger, releaseInfo):
        if releaseInfo.IsUserCreatedJob():
            self.__DownloadNfo(logger, releaseInfo)
        else:
            self.__DownloadNfo(logger, releaseInfo)
            self.__HandleAutoCreatedJob(releaseInfo)

    def ParsePageForExternalCreateJob(self, logger, releaseInfo, html):
        self.__ParsePage(logger, releaseInfo, html, parseForExternalCreateJob=True)

    def DownloadTorrent(self, logger, releaseInfo, path):
        # Any non empty filename can be specified.
        url = "http://karagarga.net/down.php/%s/filename.torrent" % releaseInfo.AnnouncementId
        logger.info("Downloading torrent file from '%s' to '%s'." % (url, path))

        opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(MyGlobals.CookieJar))
        request = urllib2.Request(url)
        result = opener.open(request)
        response = result.read()
        self.__CheckIfLoggedInFromResponse(response)

        file = open(path, "wb")
        file.write(response)
        file.close()

        ValidateTorrentFile(path)

    def IncludeReleaseNameInReleaseDescription(self):
        return False

    def GetIdFromUrl(self, url):
        result = re.match(r".*karagarga\.net/details.php\?id=(\d+).*", url)
        if result is None:
            return ""
        else:
            return result.group(1)

    def GetUrlFromId(self, id):
        return "http://karagarga.net/details.php?id=" + id

    def GetIdFromAutodlIrssiUrl(self, url):
        # https://karagarga.net/down.php/10287/Zhuangzhuang%20Tian%20-%20Lan%20feng%20zheng%20AKA%20The%20Blue%20Kite.torrent
        matches = re.match(r"https?://karagarga.net/down.php/(\d+)/.+?\.torrent", url)
        if matches is None:
            return ""
        else:
            return matches.group(1)