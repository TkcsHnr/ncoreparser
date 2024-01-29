# pylint: disable=duplicate-code

import os
import functools
import httpx
from ncoreparser.data import (
    URLs,
    SearchParamType,
    SearchParamWhere,
    ParamSort,
    ParamSeq
)
from ncoreparser.error import (
    NcoreConnectionError,
    NcoreCredentialError,
    NcoreDownloadError
)
from ncoreparser.parser import (
    TorrentsPageParser,
    TorrenDetailParser,
    RssParser,
    ActivityParser,
    RecommendedParser
)
from ncoreparser.util import Size
from ncoreparser.torrent import Torrent


def _check_login(func):
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        if not self._logged_in: # pylint: disable=protected-access
            raise NcoreConnectionError("Cannot login to tracker. "
                                       f"Please use {AsyncClient.login.__name__} function first.")
        return func(self, *args, **kwargs)
    return wrapper


class AsyncClient:
    def __init__(self, timeout=1):
        self._client = httpx.AsyncClient(headers={'User-Agent': 'python ncoreparser'},
                                         timeout=timeout,
                                         follow_redirects=True)
        self._logged_in = False
        self._page_parser = TorrentsPageParser()
        self._detailed_parser = TorrenDetailParser()
        self._rss_parser = RssParser()
        self._activity_parser = ActivityParser()
        self._recommended_parser = RecommendedParser()


    async def login(self, username, password):
        self._client.cookies.clear()
        try:
            r = await self._client.post(URLs.LOGIN.value,
                                        data={"nev": username, "pass": password})
        except Exception as e:
            raise NcoreConnectionError(f"Error while perform post "
                                       f"method to url '{URLs.LOGIN.value}'.") from e
        if r.url != URLs.INDEX.value:
            await self.logout()
            raise NcoreCredentialError(f"Error while login, check "
                                       f"credentials for user: '{username}'")
        self._logged_in = True

    @_check_login
    # pylint: disable=too-many-arguments
    async def search(self, pattern, type=SearchParamType.ALL_OWN, where=SearchParamWhere.NAME,
               sort_by=ParamSort.UPLOAD, sort_order=ParamSeq.DECREASING, pages=1) -> list[Torrent]:
        page_count = 1
        torrents = []
        while page_count <= pages:
            url = URLs.DOWNLOAD_PATTERN.value.format(page=page_count,
                                                     t_type=type.value,
                                                     sort=sort_by.value,
                                                     seq=sort_order.value,
                                                     pattern=pattern,
                                                     where=where.value)
            try:
                request = await self._client.get(url)
            except Exception as e:
                raise NcoreConnectionError(f"Error while searhing torrents. {e}") from e
            new_torrents = [Torrent(**params) for params in self._page_parser.get_items(request.text)]
            torrents.extend(new_torrents)
            page_count += 1
        return torrents

    @_check_login
    async def get_torrent(self, id, **ext_params):
        url = URLs.DETAIL_PATTERN.value.format(id=id)
        try:
            content = await self._client.get(url)
        except Exception as e:
            raise NcoreConnectionError(f"Error while get detailed page. Url: '{url}'. {e}") from e
        params = self._detailed_parser.get_item(content.text)
        params["id"] = id
        params.update(ext_params)
        return Torrent(**params)

    @_check_login
    async def get_by_rss(self, url):
        try:
            content = await self._client.get(url)
        except Exception as e:
            raise NcoreConnectionError(f"Error while get rss. Url: '{url}'. {e}") from e

        torrents = []
        for id in self._rss_parser.get_ids(content.text):
            torrents.append(await self.get_torrent(id))
        return torrents

    @_check_login
    async def get_by_activity(self):
        try:
            content = await self._client.get(URLs.ACTIVITY.value)
        except Exception as e:
            raise NcoreConnectionError(f"Error while get activity. Url: '{URLs.ACTIVITY.value}'. {e}") from e

        torrents = []
        for id, start_t, updated_t, status, uploaded, downloaded, remaining_t, rate in \
                self._activity_parser.get_params(content.text):
            torrents.append(await self.get_torrent(id,
                                                   start=start_t,
                                                   updated=updated_t,
                                                   status=status,
                                                   uploaded=Size(uploaded),
                                                   downloaded=Size(downloaded),
                                                   remaining=remaining_t,
                                                   rate=float(rate)))
        return torrents

    @_check_login
    async def get_recommended(self, type=None):
        try:
            content = await self._client.get(URLs.RECOMMENDED.value)
        except Exception as e:
            raise NcoreConnectionError(f"Error while get recommended. Url: '{URLs.RECOMMENDED.value}'. {e}") from e

        all_recommended = [await self.get_torrent(id) for id in self._recommended_parser.get_ids(content.text)]
        return [torrent for torrent in all_recommended if not type or torrent['type'] == type]

    @_check_login
    async def download(self, torrent, path, override=False):
        file_path, url = torrent.prepare_download(path)
        try:
            content = await self._client.get(url)
        except Exception as e:
            raise NcoreConnectionError(f"Error while downloading torrent. Url: '{url}'. {e}") from e
        if not override and os.path.exists(file_path):
            raise NcoreDownloadError(f"Error while downloading file: '{file_path}'. It is already exists.")
        with open(file_path, 'wb') as fh:
            fh.write(content.content)
        return file_path

    async def logout(self):
        self._client.cookies.clear()
        await self._client.aclose()
        self._logged_in = False