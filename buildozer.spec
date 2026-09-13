[app]
title = Trading Advisor
package.name = tradingadvisor
package.domain = org.test

source.dir = .
source.include_exts = py,png,jpg,kv,atlas
source.include_patterns = assets/*,images/*

version = 0.1

requirements = python3,kivy,requests,charset-normalizer==2.1.1

orientation = portrait
fullscreen = 0

android.permissions = INTERNET,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE,FOREGROUND_SERVICE,FOREGROUND_SERVICE_DATA_SYNC,POST_NOTIFICATIONS,WAKE_LOCK

android.api = 34
android.minapi = 24
android.archs = arm64-v8a
android.accept_sdk_license = True

android.wakelock = True
android.presplash_color = #000000

[buildozer]
log_level = 1
warn_on_root = 1

[p4a]
branch = develop
