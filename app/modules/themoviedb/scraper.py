import time
from pathlib import Path
from xml.dom import minidom

from app.core.config import settings
from app.core.context import MediaInfo
from app.core.metainfo import MetaInfo
from app.log import logger
from app.schemas.types import MediaType
from app.utils.dom import DomUtils
from app.utils.http import RequestUtils


class TmdbScraper:

    tmdb = None

    def __init__(self, tmdb):
        self.tmdb = tmdb

    def gen_scraper_files(self, mediainfo: MediaInfo, file_path: Path):
        """
        生成刮削文件
        :param mediainfo: 媒体信息
        :param file_path: 文件路径
        """

        def __get_episode_detail(_seasoninfo: dict, _episode: int):
            """
            根据季信息获取集的信息
            """
            for _episode_info in _seasoninfo.get("episodes") or []:
                if _episode_info.get("episode_number") == _episode:
                    return _episode_info
            return {}

        try:
            # 电影
            if mediainfo.type == MediaType.MOVIE:
                # 强制或者不已存在时才处理
                if not file_path.with_name("movie.nfo").exists() \
                        and not file_path.with_suffix(".nfo").exists():
                    #  生成电影描述文件
                    self.__gen_movie_nfo_file(mediainfo=mediainfo,
                                              file_path=file_path)
                # 生成电影图片
                for attr_name, attr_value in vars(mediainfo).items():
                    if attr_value \
                            and attr_name.endswith("_path") \
                            and attr_value \
                            and isinstance(attr_value, str) \
                            and attr_value.startswith("http"):
                        image_name = attr_name.replace("_path", "") + Path(attr_value).suffix
                        self.__save_image(url=attr_value,
                                          file_path=file_path.with_name(image_name))
            # 电视剧
            else:
                # 识别
                meta = MetaInfo(file_path.stem)
                # 不存在时才处理
                if not file_path.parent.with_name("tvshow.nfo").exists():
                    # 根目录描述文件
                    self.__gen_tv_nfo_file(mediainfo=mediainfo,
                                           dir_path=file_path.parents[1])
                # 生成根目录图片
                for attr_name, attr_value in vars(mediainfo).items():
                    if attr_value \
                            and attr_name.endswith("_path") \
                            and not attr_name.startswith("season") \
                            and attr_value \
                            and isinstance(attr_value, str) \
                            and attr_value.startswith("http"):
                        image_name = attr_name.replace("_path", "") + Path(attr_value).suffix
                        self.__save_image(url=attr_value,
                                          file_path=file_path.parent.with_name(image_name))
                # 查询季信息
                seasoninfo = self.tmdb.get_tv_season_detail(mediainfo.tmdb_id, meta.begin_season)
                if seasoninfo:
                    # 季目录NFO
                    if not file_path.with_name("season.nfo").exists():
                        self.__gen_tv_season_nfo_file(seasoninfo=seasoninfo,
                                                      season=meta.begin_season,
                                                      season_path=file_path.parent)
                    # 季的图片
                    for attr_name, attr_value in vars(mediainfo).items():
                        if attr_value \
                                and attr_name.startswith("season") \
                                and attr_value \
                                and isinstance(attr_value, str) \
                                and attr_value.startswith("http"):
                            image_name = attr_name.replace("_path",
                                                           "").replace("season",
                                                                       f"{str(meta.begin_season).rjust(2, '0')}-") \
                                         + Path(attr_value).suffix
                            self.__save_image(url=attr_value,
                                              file_path=file_path.parent.with_name(f"season{image_name}"))
                # 查询集详情
                episodeinfo = __get_episode_detail(seasoninfo, meta.begin_episode)
                if episodeinfo:
                    # 集NFO
                    if not file_path.with_suffix(".nfo").exists():
                        self.__gen_tv_episode_nfo_file(episodeinfo=episodeinfo,
                                                       tmdbid=mediainfo.tmdb_id,
                                                       season=meta.begin_season,
                                                       episode=meta.begin_episode,
                                                       file_path=file_path)
                    # 集的图片
                    if episodeinfo.get('still_path'):
                        self.__save_image(
                            f"https://{settings.TMDB_IMAGE_DOMAIN}/t/p/original{episodeinfo.get('still_path')}",
                            file_path.with_suffix(Path(episodeinfo.get('still_path')).suffix))
        except Exception as e:
            logger.error(f"{file_path} 刮削失败：{e}")

    @staticmethod
    def __gen_common_nfo(mediainfo: MediaInfo, doc, root):
        """
        生成公共NFO
        """
        # 添加时间
        DomUtils.add_node(doc, root, "dateadded",
                          time.strftime('%Y-%m-%d %H:%M:%S',
                                        time.localtime(time.time())))
        # TMDB
        DomUtils.add_node(doc, root, "tmdbid", mediainfo.tmdb_id or "")
        uniqueid_tmdb = DomUtils.add_node(doc, root, "uniqueid", mediainfo.tmdb_id or "")
        uniqueid_tmdb.setAttribute("type", "tmdb")
        uniqueid_tmdb.setAttribute("default", "true")
        # TVDB
        if mediainfo.tvdb_id:
            DomUtils.add_node(doc, root, "tvdbid", str(mediainfo.tvdb_id))
            uniqueid_tvdb = DomUtils.add_node(doc, root, "uniqueid", str(mediainfo.tvdb_id))
            uniqueid_tvdb.setAttribute("type", "tvdb")
        # IMDB
        if mediainfo.imdb_id:
            DomUtils.add_node(doc, root, "imdbid", mediainfo.imdb_id)
            uniqueid_imdb = DomUtils.add_node(doc, root, "uniqueid", mediainfo.imdb_id)
            uniqueid_imdb.setAttribute("type", "imdb")
            uniqueid_imdb.setAttribute("default", "true")
            uniqueid_tmdb.setAttribute("default", "false")

        # 简介
        xplot = DomUtils.add_node(doc, root, "plot")
        xplot.appendChild(doc.createCDATASection(mediainfo.overview or ""))
        xoutline = DomUtils.add_node(doc, root, "outline")
        xoutline.appendChild(doc.createCDATASection(mediainfo.overview or ""))
        # 导演
        for director in mediainfo.directors:
            xdirector = DomUtils.add_node(doc, root, "director", director.get("name") or "")
            xdirector.setAttribute("tmdbid", str(director.get("id") or ""))
        # 演员
        for actor in mediainfo.actors:
            xactor = DomUtils.add_node(doc, root, "actor")
            DomUtils.add_node(doc, xactor, "name", actor.get("name") or "")
            DomUtils.add_node(doc, xactor, "type", "Actor")
            DomUtils.add_node(doc, xactor, "role", actor.get("character") or actor.get("role") or "")
            DomUtils.add_node(doc, xactor, "order", actor.get("order") if actor.get("order") is not None else "")
            DomUtils.add_node(doc, xactor, "tmdbid", actor.get("id") or "")
            DomUtils.add_node(doc, xactor, "thumb", actor.get('image'))
            DomUtils.add_node(doc, xactor, "profile", actor.get('profile'))
        # 风格
        genres = mediainfo.genres or []
        for genre in genres:
            DomUtils.add_node(doc, root, "genre", genre.get("name") or "")
        # 评分
        DomUtils.add_node(doc, root, "rating", mediainfo.vote_average or "0")

        return doc

    def __gen_movie_nfo_file(self,
                             mediainfo: MediaInfo,
                             file_path: Path):
        """
        生成电影的NFO描述文件
        :param mediainfo: 识别后的媒体信息
        :param file_path: 电影文件路径
        """
        # 开始生成XML
        logger.info(f"正在生成电影NFO文件：{file_path.name}")
        doc = minidom.Document()
        root = DomUtils.add_node(doc, doc, "movie")
        # 公共部分
        doc = self.__gen_common_nfo(mediainfo=mediainfo,
                                    doc=doc,
                                    root=root)
        # 标题
        DomUtils.add_node(doc, root, "title", mediainfo.title or "")
        DomUtils.add_node(doc, root, "originaltitle", mediainfo.original_title or "")
        # 发布日期
        DomUtils.add_node(doc, root, "premiered", mediainfo.release_date or "")
        # 年份
        DomUtils.add_node(doc, root, "year", mediainfo.year or "")
        # 保存
        self.__save_nfo(doc, file_path.with_suffix(".nfo"))

    def __gen_tv_nfo_file(self,
                          mediainfo: MediaInfo,
                          dir_path: Path):
        """
        生成电视剧的NFO描述文件
        :param mediainfo: 媒体信息
        :param dir_path: 电视剧根目录
        """
        # 开始生成XML
        logger.info(f"正在生成电视剧NFO文件：{dir_path.name}")
        doc = minidom.Document()
        root = DomUtils.add_node(doc, doc, "tvshow")
        # 公共部分
        doc = self.__gen_common_nfo(mediainfo=mediainfo,
                                    doc=doc,
                                    root=root)
        # 标题
        DomUtils.add_node(doc, root, "title", mediainfo.title or "")
        DomUtils.add_node(doc, root, "originaltitle", mediainfo.original_title or "")
        # 发布日期
        DomUtils.add_node(doc, root, "premiered", mediainfo.release_date or "")
        # 年份
        DomUtils.add_node(doc, root, "year", mediainfo.year or "")
        DomUtils.add_node(doc, root, "season", "-1")
        DomUtils.add_node(doc, root, "episode", "-1")
        # 保存
        self.__save_nfo(doc, dir_path.joinpath("tvshow.nfo"))

    def __gen_tv_season_nfo_file(self, seasoninfo: dict, season: int, season_path: Path):
        """
        生成电视剧季的NFO描述文件
        :param seasoninfo: TMDB季媒体信息
        :param season: 季号
        :param season_path: 电视剧季的目录
        """
        logger.info(f"正在生成季NFO文件：{season_path.name}")
        doc = minidom.Document()
        root = DomUtils.add_node(doc, doc, "season")
        # 添加时间
        DomUtils.add_node(doc, root, "dateadded", time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time())))
        # 简介
        xplot = DomUtils.add_node(doc, root, "plot")
        xplot.appendChild(doc.createCDATASection(seasoninfo.get("overview") or ""))
        xoutline = DomUtils.add_node(doc, root, "outline")
        xoutline.appendChild(doc.createCDATASection(seasoninfo.get("overview") or ""))
        # 标题
        DomUtils.add_node(doc, root, "title", "季 %s" % season)
        # 发行日期
        DomUtils.add_node(doc, root, "premiered", seasoninfo.get("air_date") or "")
        DomUtils.add_node(doc, root, "releasedate", seasoninfo.get("air_date") or "")
        # 发行年份
        DomUtils.add_node(doc, root, "year", seasoninfo.get("air_date")[:4] if seasoninfo.get("air_date") else "")
        # seasonnumber
        DomUtils.add_node(doc, root, "seasonnumber", str(season))
        # 保存
        self.__save_nfo(doc, season_path.joinpath("season.nfo"))

    def __gen_tv_episode_nfo_file(self,
                                  tmdbid: int,
                                  episodeinfo: dict,
                                  season: int,
                                  episode: int,
                                  file_path: Path):
        """
        生成电视剧集的NFO描述文件
        :param tmdbid: TMDBID
        :param episodeinfo: 集TMDB元数据
        :param season: 季号
        :param episode: 集号
        :param file_path: 集文件的路径
        """
        # 开始生成集的信息
        logger.info(f"正在生成剧集NFO文件：{file_path.name}")
        doc = minidom.Document()
        root = DomUtils.add_node(doc, doc, "episodedetails")
        # 添加时间
        DomUtils.add_node(doc, root, "dateadded", time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time())))
        # TMDBID
        uniqueid = DomUtils.add_node(doc, root, "uniqueid", str(tmdbid))
        uniqueid.setAttribute("type", "tmdb")
        uniqueid.setAttribute("default", "true")
        # tmdbid
        DomUtils.add_node(doc, root, "tmdbid", str(tmdbid))
        # 标题
        DomUtils.add_node(doc, root, "title", episodeinfo.get("name") or "第 %s 集" % episode)
        # 简介
        xplot = DomUtils.add_node(doc, root, "plot")
        xplot.appendChild(doc.createCDATASection(episodeinfo.get("overview") or ""))
        xoutline = DomUtils.add_node(doc, root, "outline")
        xoutline.appendChild(doc.createCDATASection(episodeinfo.get("overview") or ""))
        # 发布日期
        DomUtils.add_node(doc, root, "aired", episodeinfo.get("air_date") or "")
        # 年份
        DomUtils.add_node(doc, root, "year",
                          episodeinfo.get("air_date")[:4] if episodeinfo.get("air_date") else "")
        # 季
        DomUtils.add_node(doc, root, "season", str(season))
        # 集
        DomUtils.add_node(doc, root, "episode", str(episode))
        # 评分
        DomUtils.add_node(doc, root, "rating", episodeinfo.get("vote_average") or "0")
        # 导演
        directors = episodeinfo.get("crew") or []
        for director in directors:
            if director.get("known_for_department") == "Directing":
                xdirector = DomUtils.add_node(doc, root, "director", director.get("name") or "")
                xdirector.setAttribute("tmdbid", str(director.get("id") or ""))
        # 演员
        actors = episodeinfo.get("guest_stars") or []
        for actor in actors:
            if actor.get("known_for_department") == "Acting":
                xactor = DomUtils.add_node(doc, root, "actor")
                DomUtils.add_node(doc, xactor, "name", actor.get("name") or "")
                DomUtils.add_node(doc, xactor, "type", "Actor")
                DomUtils.add_node(doc, xactor, "tmdbid", actor.get("id") or "")
        # 保存文件
        self.__save_nfo(doc, file_path.with_suffix(".nfo"))

    @staticmethod
    def __save_image(url: str, file_path: Path):
        """
        下载图片并保存
        """
        if file_path.exists():
            return
        try:
            logger.info(f"正在下载{file_path.stem}图片：{url} ...")
            r = RequestUtils().get_res(url=url)
            if r:
                file_path.write_bytes(r.content)
                logger.info(f"图片已保存：{file_path}")
            else:
                logger.info(f"{file_path.stem}图片下载失败，请检查网络连通性")
        except Exception as err:
            logger.error(f"{file_path.stem}图片下载失败：{err}")

    @staticmethod
    def __save_nfo(doc, file_path: Path):
        """
        保存NFO
        """
        if file_path.exists():
            return
        xml_str = doc.toprettyxml(indent="  ", encoding="utf-8")
        file_path.write_bytes(xml_str)
        logger.info(f"NFO文件已保存：{file_path}")
