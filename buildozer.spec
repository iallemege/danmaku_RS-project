[app]
title = BiliDanmaku
package.name = bilidm
package.domain = org.bilidm
source.dir = .
source.include_exts = py,png,jpg,kv,ini
version = 1.0.0
requirements = python3,kivy,requests,chardet,idna
orientation = portrait
fullscreen = 0
android.permissions = INTERNET,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE
android.api = 30
android.ndk = 23b
android.arch = arm64-v8a

[buildozer]
log_level = 2
warn_on_root = 1
