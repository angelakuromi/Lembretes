[app]
title = Lembretes
package.name = lembretes
package.domain = org.meu
source.dir = .
source.include_exts = py
version = 1.0
requirements = python3,kivy==2.3.0
orientation = portrait
fullscreen = 0
services = reminders:service.py:foreground:sticky
android.permissions = POST_NOTIFICATIONS,FOREGROUND_SERVICE,WAKE_LOCK
android.api = 33
android.minapi = 24
p4a.branch = v2024.01.21
android.ndk = 25b
android.archs = arm64-v8a
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 1
