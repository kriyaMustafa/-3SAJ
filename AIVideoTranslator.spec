# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['backend\\launcher.py'],
    pathex=[],
    binaries=[],
    datas=[('backend/dist', 'dist'), ('backend/.env', '.'), ('backend/voice_samples', 'voice_samples')],
    hiddenimports=['uvicorn.logging', 'uvicorn.loops', 'uvicorn.loops.auto', 'uvicorn.protocols', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto', 'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto', 'uvicorn.lifespan', 'uvicorn.lifespan.on', 'sqlalchemy.sql.default_comparator', 'faster_whisper', 'pyannote.audio', 'celery.fixups', 'celery.fixups.django', 'celery.backends', 'celery.backends.redis', 'celery.loaders', 'celery.loaders.app', 'celery.loaders.default', 'kombu.transport', 'kombu.transport.redis'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['datasets', 'pyarrow', 'modelscope.trainers', 'modelscope.msdatasets', 'modelscope.trainers.hooks.swift', 'modelscope.pipelines.cv'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AIVideoTranslator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['app_icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AIVideoTranslator',
)
