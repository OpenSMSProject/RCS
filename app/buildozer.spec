[app]
title = OpenSMS
package.name = opensms
package.domain = in.daslearning
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json,java,ttf
source.exclude_dirs = tests, logs, bin, venv, build, dist, patches, .venv, env, .env, p4a_local_recipes, hookers, __pycache__, config
version.regex = __version__ = ['"](.*)['"]
version.filename = %(source.dir)s/main.py

# Python packages bundled into the Android application.
requirements = python3, 
    kivy, 
    https://github.com/kivymd/KivyMD/archive/master.zip, 
    materialyoucolor==3.0.3, 
    materialshapes, 
    pycairo, 
    pillow, 
    exceptiongroup, 
    asyncgui, 
    asynckivy, 
    pyjnius, 
    android, 
    docutils, 
    filetype, 
    plyer==2.1.0, 
    Pygments, 
    requests,
    annotated-doc, 
    annotated-types, 
    pydantic-core,
    pydantic==2.12.3,
    idna,
    anyio,
    starlette==0.50.0,
    typing-extensions,
    typing-inspection,
    opentelemetry-api,
    fastapi==0.128.2,
    click,
    h11,
    uvicorn==0.48.0,
    websocket-client==1.8.0

icon.filename = %(source.dir)s/data/images/favicont512.png
icon.adaptive_foreground.filename = %(source.dir)s/data/images/icon_fg.png
icon.adaptive_background.filename = %(source.dir)s/data/images/icon_bg.png
orientation = all
services = opensmssvc:services/appSvc.py:foreground:foregroundServiceType=dataSync
fullscreen = 0

android.permissions = android.permission.INTERNET, android.permission.SEND_SMS, android.permission.WAKE_LOCK, android.permission.FOREGROUND_SERVICE, android.permission.FOREGROUND_SERVICE_DATA_SYNC, android.permission.POST_NOTIFICATIONS
android.api = 36
android.minapi = 28
android.ndk = 28c
android.accept_sdk_license = True
android.enable_androidx = True
android.manifest.orientation = fullSensor
android.archs = arm64-v8a
android.allow_backup = True
android.release_artifact = aab
android.display_cutout = shortEdges

# Keep the upstream project's Android toolchain fork.
p4a.url = https://github.com/daslearning-org/p4a-unofficial.git
p4a.branch = develop

# Existing cross-platform defaults retained.
osx.kivy_version = 2.2.0
ios.kivy_ios_url = https://github.com/kivy/kivy-ios
ios.kivy_ios_branch = master
ios.ios_deploy_url = https://github.com/phonegap/ios-deploy
ios.ios_deploy_branch = 1.12.2
ios.codesign.allowed = false

[buildozer]
log_level = 2
warn_on_root = 1
