"""Minimal Kodi addon host: browse + resolve, JSON on stdout.

Run as:  python minihost.py "plugin://plugin.video.fosdem/"
Emits:   {"items":[{label,url,is_folder,art,info}...]} or {"resolved":{url,headers,props}}
"""
import json, os, sys, types, xml.etree.ElementTree as ET
from urllib.parse import urlsplit, parse_qsl

ADDONS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "addons")
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "addon_data")
OUT = {"items": [], "resolved": None, "content": None, "category": None}


def _mod(name):
    m = types.ModuleType(name)
    sys.modules[name] = m
    return m


# ---------------- xbmcgui ----------------
xbmcgui = _mod("xbmcgui")


class ListItem:
    def __init__(self, label="", label2="", path="", offscreen=False):
        self._label, self._path = label, path
        self._art, self._info, self._props = {}, {}, {}

    def setLabel(self, l): self._label = l
    def getLabel(self): return self._label
    def setLabel2(self, l): pass
    def setPath(self, p): self._path = p
    def getPath(self): return self._path
    def setArt(self, d): self._art.update(d or {})
    def getArt(self, k): return self._art.get(k, "")
    def setInfo(self, type, infoLabels): self._info.update(infoLabels or {})
    def setProperty(self, k, v): self._props[k.lower()] = v
    def getProperty(self, k): return self._props.get(k.lower(), "")
    def setProperties(self, d): self._props.update({k.lower(): v for k, v in (d or {}).items()})
    def setContentLookup(self, b): pass
    def setMimeType(self, m): pass
    def setSubtitles(self, s): pass
    def addStreamInfo(self, t, d): pass
    def addContextMenuItems(self, items, replaceItems=False): pass
    def setIsFolder(self, b): pass
    def setIconImage(self, i): self._art["icon"] = i        # removed in v20
    def setThumbnailImage(self, i): self._art["thumb"] = i  # removed in v20
    def setCast(self, c): self._info["cast"] = c
    def setUniqueIDs(self, d, t=""): pass
    def setRating(self, *a, **k): pass
    def select(self, b): pass
    def getVideoInfoTag(self): return _InfoTag()


class _InfoTag:
    def __getattr__(self, n): return lambda *a, **k: None


class Dialog:
    """Non-interactive: answers come from $KODI_ANSWERS (a JSON list)."""
    _answers = json.loads(os.environ.get("KODI_ANSWERS", "[]"))

    def _next(self, default):
        return Dialog._answers.pop(0) if Dialog._answers else default

    def input(self, heading, defaultt="", type=0, option=0, autoclose=0):
        return self._next(defaultt)
    def yesno(self, *a, **k): return bool(self._next(False))
    def ok(self, *a, **k): return True
    def select(self, heading, list, **k): return int(self._next(-1))
    def notification(self, *a, **k): pass
    def textviewer(self, *a, **k): pass
    def browseSingle(self, *a, **k): return ""


class DialogProgress:
    def create(self, *a): pass
    def update(self, *a, **k): pass
    def close(self): pass
    def iscanceled(self): return False


DialogProgressBG = DialogProgress
xbmcgui.ListItem, xbmcgui.Dialog = ListItem, Dialog
xbmcgui.DialogProgress, xbmcgui.DialogProgressBG = DialogProgress, DialogProgressBG
xbmcgui.INPUT_ALPHANUM = 0
xbmcgui.Window = xbmcgui.WindowXML = xbmcgui.WindowDialog = object
xbmcgui.WindowXMLDialog = xbmcgui.WindowXMLDialog = object
xbmcgui.ControlLabel = xbmcgui.ControlButton = xbmcgui.ControlList = object
for _n, _v in {"INPUT_ALPHANUM": 0, "INPUT_NUMERIC": 1, "INPUT_DATE": 2, "INPUT_TIME": 3,
               "INPUT_IPADDRESS": 4, "INPUT_PASSWORD": 5, "ALPHANUM_HIDE_INPUT": 32,
               "PASSWORD_VERIFY": 1, "NOTIFICATION_INFO": "info",
               "NOTIFICATION_WARNING": "warning", "NOTIFICATION_ERROR": "error"}.items():
    setattr(xbmcgui, _n, _v)

# ---------------- xbmc ----------------
xbmc = _mod("xbmc")
for i, n in enumerate(["LOGDEBUG", "LOGINFO", "LOGWARNING", "LOGERROR", "LOGFATAL", "LOGNONE"]):
    setattr(xbmc, n, i)
xbmc.log = lambda msg, level=0: print(f"[addon] {msg}", file=sys.stderr)
xbmc.executebuiltin = lambda f, wait=False: None
xbmc.getInfoLabel = lambda k: ""
xbmc.getCondVisibility = lambda c: False
xbmc.getLanguage = lambda *a, **k: "English"
xbmc.getRegion = lambda k: ""
xbmc.sleep = lambda ms: None
_RPC = {
    "Application.GetProperties": {"version": {"major": 21, "minor": 0, "revision": "",
                                              "tag": "stable"}, "name": "Kodi", "muted": False,
                                  "volume": 100},
    "Settings.GetSettingValue": {"value": False},
    "Addons.GetAddons": {"addons": [], "limits": {"start": 0, "end": 0, "total": 0}},
    "JSONRPC.Version": {"version": {"major": 13, "minor": 3, "patch": 0}},
    "Profiles.GetCurrentProfile": {"label": "Master user"},
}


def executeJSONRPC(request):
    try:
        req = json.loads(request)
    except Exception:
        return '{"jsonrpc":"2.0","id":1,"result":"OK"}'
    res = _RPC.get(req.get("method"), "OK")
    return json.dumps({"jsonrpc": "2.0", "id": req.get("id", 1), "result": res})


xbmc.executeJSONRPC = executeJSONRPC
xbmc.translatePath = lambda p: translatePath(p)


class Keyboard:
    def __init__(self, default="", heading="", hidden=False):
        self._t = Dialog()._next(default)
    def doModal(self, autoclose=0): pass
    def isConfirmed(self): return True
    def getText(self): return self._t
    def setDefault(self, t): self._t = t


class Monitor:
    def abortRequested(self): return False
    def waitForAbort(self, timeout=0): return False
    def onSettingsChanged(self): pass


class Player:
    """Some addons bypass setResolvedUrl and drive the player directly."""
    def __init__(self, *a, **k): self._subs = None
    def play(self, item="", listitem=None, windowed=False, startpos=-1):
        path = item if isinstance(item, str) else getattr(item, "getPath", lambda: "")()
        url, _, hdr = str(path).partition("|")
        OUT["resolved"] = {"ok": True, "url": url, "headers": dict(parse_qsl(hdr)),
                           "props": getattr(listitem, "_props", {}), "subtitles": self._subs,
                           "via": "Player.play"}
    def setSubtitles(self, s): self._subs = s
    def showSubtitles(self, b): pass
    def stop(self): pass
    def pause(self): pass
    def isPlaying(self): return False
    def isPlayingVideo(self): return False
    def getPlayingFile(self): return (OUT.get("resolved") or {}).get("url", "")
    def getTotalTime(self): return 0.0
    def getTime(self): return 0.0
    def seekTime(self, t): pass
    def onPlayBackStarted(self): pass
    def onPlayBackStopped(self): pass
    def onPlayBackEnded(self): pass


xbmc.Keyboard, xbmc.Monitor, xbmc.Player = Keyboard, Monitor, Player
xbmc.PlayList = lambda *a: types.SimpleNamespace(clear=lambda: None, add=lambda *a, **k: None,
                                                 size=lambda: 0, getposition=lambda: 0)
for _n, _v in {"PLAYLIST_MUSIC": 0, "PLAYLIST_VIDEO": 1, "ISO_639_1": "ISO_639_1",
               "ISO_639_2": "ISO_639_2", "ENGLISH_NAME": "ENGLISH_NAME",
               "PLAYER_CORE_AUTO": 0, "PLAYER_CORE_PAPLAYER": 1, "PLAYER_CORE_DVDPLAYER": 2,
               "TRAY_OPEN": 16, "DRIVE_NOT_READY": 1, "abortRequested": False}.items():
    setattr(xbmc, _n, _v)
xbmc.convertLanguage = lambda lang, fmt: lang
xbmc.makeLegalFilename = lambda p, *a, **k: p
xbmc.validatePath = lambda p, *a, **k: p
xbmc.getSkinDir = lambda: "skin.estuary"
xbmc.getGlobalIdleTime = lambda: 0
xbmc.getSupportedMedia = lambda t: ""
xbmc.startServer = lambda *a, **k: True
xbmc.audioSuspend = xbmc.audioResume = lambda: None
xbmc.getCacheThumbName = lambda p: ""
xbmc.getCleanMovieTitle = lambda p, *a: (p, "")

# ---------------- xbmcvfs ----------------
xbmcvfs = _mod("xbmcvfs")
SPECIAL = {"special://home/": os.path.dirname(ADDONS) + "/",
           "special://temp/": os.path.join(os.path.dirname(ADDONS), "tmp") + "/",
           "special://profile/": DATA + "/",
           "special://userdata/": DATA + "/",
           "special://masterprofile/": DATA + "/"}


def translatePath(path):
    for k, v in SPECIAL.items():
        if path.startswith(k):
            return os.path.realpath(os.path.join(v, path[len(k):]))
    return path


xbmcvfs.translatePath = translatePath
xbmcvfs.exists = os.path.exists
xbmcvfs.mkdirs = lambda p: os.makedirs(translatePath(p), exist_ok=True)
xbmcvfs.mkdir = xbmcvfs.mkdirs
xbmcvfs.delete = lambda p: os.remove(translatePath(p))
xbmcvfs.listdir = lambda p: ([], os.listdir(translatePath(p)))


class File:
    def __init__(self, path, mode="r"):
        self._f = open(translatePath(path), mode if "b" in mode else mode + "b")
    def read(self): return self._f.read().decode("utf8")
    def readBytes(self): return self._f.read()
    def write(self, d): self._f.write(d.encode("utf8") if isinstance(d, str) else d)
    def close(self): self._f.close()
    def __enter__(self): return self
    def __exit__(self, *a): self.close()


xbmcvfs.File = File

# ---------------- xbmcaddon ----------------
xbmcaddon = _mod("xbmcaddon")


class Addon:
    def __init__(self, id=None):
        self.id = id or urlsplit(sys.argv[0]).netloc
        self.path = os.path.join(ADDONS, self.id)
        self.profile = os.path.join(DATA, self.id)
        os.makedirs(self.profile, exist_ok=True)
        self._x = {}
        f = os.path.join(self.path, "addon.xml")
        if os.path.exists(f):
            self._x = ET.parse(f).getroot().attrib
        self._s = {}
        sx = os.path.join(self.path, "resources", "settings.xml")
        if os.path.exists(sx):
            for e in ET.parse(sx).getroot().iter("setting"):
                if e.get("id"):
                    self._s[e.get("id")] = e.get("default") or (e.findtext("default") or "")
        self._store = os.path.join(self.profile, "settings.json")
        if os.path.exists(self._store):
            self._s.update(json.load(open(self._store)))
        self._strings = _load_po(self.path)

    def getAddonInfo(self, k):
        return {"id": self.id, "path": self.path, "profile": self.profile,
                "name": self._x.get("name", self.id), "version": self._x.get("version", "0.0.0"),
                "icon": os.path.join(self.path, "icon.png"),
                "fanart": os.path.join(self.path, "fanart.jpg")}.get(k, self._x.get(k, ""))

    def getSetting(self, id): return str(self._s.get(id, ""))
    def getSettingString(self, id): return self.getSetting(id)
    def getSettingBool(self, id): return self.getSetting(id).lower() == "true"
    def getSettingInt(self, id): return int(self.getSetting(id) or 0)
    def getSettingNumber(self, id): return float(self.getSetting(id) or 0)

    def setSetting(self, id, value):
        self._s[id] = str(value)
        json.dump(self._s, open(self._store, "w"))

    setSettingString = setSettingBool = setSettingInt = setSettingNumber = setSetting
    def getLocalizedString(self, id): return self._strings.get(int(id), "")
    getString = getLocalizedString                 # pre-v14 alias, still used
    def openSettings(self): pass
    def getSettings(self): return self


def _load_po(path):
    out, cur = {}, None
    for lang in ("resource.language.en_gb", "resource.language.en_us"):
        p = os.path.join(path, "resources", "language", lang, "strings.po")
        if not os.path.exists(p):
            continue
        for line in open(p, encoding="utf8"):
            line = line.strip()
            if line.startswith("msgctxt"):
                tok = line.split('"')[1].lstrip("#") if '"' in line else ""
                cur = int(tok) if tok.isdigit() else None
            elif line.startswith("msgid") and cur:
                out[cur] = line.split('"', 1)[1].rsplit('"', 1)[0]
                cur = None
        break
    return out


xbmcaddon.Addon = Addon

# ---------------- xbmcplugin ----------------
xbmcplugin = _mod("xbmcplugin")
_SORT = ("NONE LABEL LABEL_IGNORE_THE DATE SIZE FILE DRIVE_TYPE TRACKNUM DURATION TITLE "
         "TITLE_IGNORE_THE ARTIST ARTIST_IGNORE_THE ALBUM ALBUM_IGNORE_THE GENRE COUNTRY "
         "VIDEO_YEAR VIDEO_RATING VIDEO_USER_RATING DATEADDED PROGRAM_COUNT PLAYLIST_ORDER "
         "EPISODE VIDEO_TITLE VIDEO_SORT_TITLE VIDEO_SORT_TITLE_IGNORE_THE PRODUCTIONCODE "
         "SONG_RATING SONG_USER_RATING MPAA_RATING VIDEO_RUNTIME STUDIO STUDIO_IGNORE_THE "
         "FULLPATH LABEL_IGNORE_FOLDERS LASTPLAYED PLAYCOUNT LISTENERS UNSORTED CHANNEL "
         "CHANNEL_NUMBER BITRATE DATE_TAKEN").split()
for i, n in enumerate(_SORT):
    setattr(xbmcplugin, "SORT_METHOD_" + n, i)


def addDirectoryItem(handle, url, listitem, isFolder=False, totalItems=0):
    OUT["items"].append({"label": listitem.getLabel(), "url": url, "is_folder": bool(isFolder),
                         "art": listitem._art, "info": listitem._info, "props": listitem._props})
    return True


def addDirectoryItems(handle, items, totalItems=0):
    for it in items:
        addDirectoryItem(handle, it[0], it[1], it[2] if len(it) > 2 else False)
    return True


def setResolvedUrl(handle, succeeded, listitem):
    if not succeeded:
        OUT["resolved"] = {"ok": False}
        return
    path = listitem.getPath()
    url, _, hdr = path.partition("|")
    OUT["resolved"] = {"ok": True, "url": url, "headers": dict(parse_qsl(hdr)),
                       "props": listitem._props, "label": listitem.getLabel()}


xbmcplugin.addDirectoryItem = addDirectoryItem
xbmcplugin.addDirectoryItems = addDirectoryItems
xbmcplugin.setResolvedUrl = setResolvedUrl
# NB: parameter *names* must match Kodi's exactly — addons call these by keyword.
xbmcplugin.endOfDirectory = lambda handle, succeeded=True, updateListing=False, cacheToDisc=True: None
xbmcplugin.setContent = lambda handle, content: OUT.update(content=content)
xbmcplugin.setPluginCategory = lambda handle, category: OUT.update(category=category)
xbmcplugin.addSortMethod = lambda handle, sortMethod, labelMask="", label2Mask="%D": None
xbmcplugin.setPluginFanart = lambda handle, image=None, color1=None, color2=None, color3=None: None
xbmcplugin.setProperty = lambda handle, key, value: None
xbmcplugin.getSetting = lambda handle, id: Addon().getSetting(id)
xbmcplugin.setSetting = lambda handle, id, value: Addon().setSetting(id, value)

xbmcplugin.__all__ = [n for n in dir(xbmcplugin) if not n.startswith("_")]
xbmc.__all__ = [n for n in dir(xbmc) if not n.startswith("_")]
xbmcgui.__all__ = [n for n in dir(xbmcgui) if not n.startswith("_")]
xbmcvfs.__all__ = [n for n in dir(xbmcvfs) if not n.startswith("_")]

# ---------------- loader ----------------
MAX_RESOLVE = 5


def _deps(addon_id, seen):
    """Recursively put every dependency's `library` dir on sys.path."""
    if addon_id in seen:
        return
    seen.add(addon_id)
    f = os.path.join(ADDONS, addon_id, "addon.xml")
    if not os.path.exists(f):
        return
    root = ET.parse(f).getroot()
    for e in root.findall("extension"):
        if e.get("point") == "xbmc.python.module":
            sys.path.insert(0, os.path.join(ADDONS, addon_id, e.get("library")))
    for i in root.findall("./requires/import"):
        if i.get("addon") != "xbmc.python":
            _deps(i.get("addon"), seen)


def invoke(plugin_url, handle=1):
    u = urlsplit(plugin_url)
    addon_id = u.netloc
    root = ET.parse(os.path.join(ADDONS, addon_id, "addon.xml")).getroot()
    lib = next(e.get("library") for e in root.findall("extension")
               if e.get("point") == "xbmc.python.pluginsource")
    entry = os.path.join(ADDONS, addon_id, lib)
    _deps(addon_id, set())
    sys.path.insert(0, os.path.join(ADDONS, addon_id))
    sys.path.insert(0, os.path.dirname(entry))   # Kodi puts the entry script's dir on the path
    os.chdir(os.path.join(ADDONS, addon_id))
    sys.argv = [f"plugin://{addon_id}{u.path or '/'}", str(handle),
                ("?" + u.query) if u.query else "", "resume:false"]
    g = {"__name__": "__main__", "__file__": entry, "sys": sys,
         "xbmc": xbmc, "xbmcgui": xbmcgui, "xbmcplugin": xbmcplugin,
         "xbmcaddon": xbmcaddon, "xbmcvfs": xbmcvfs}
    exec(compile(open(entry, encoding="utf8").read(), entry, "exec"), g)


if __name__ == "__main__":
    url = sys.argv[1]
    for _ in range(MAX_RESOLVE):          # plugin:// chaining, bounded like Kodi
        OUT["items"], OUT["resolved"] = [], None
        invoke(url)
        r = OUT["resolved"]
        if r and r.get("ok") and r["url"].startswith("plugin://"):
            url = r["url"]
            continue
        break
    print(json.dumps({k: v for k, v in OUT.items() if v not in (None, [])},
                     ensure_ascii=False, indent=2, default=str))
