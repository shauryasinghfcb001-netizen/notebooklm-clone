# -*- mode: python ; coding: utf-8 -*-
# NotebookLM Clone - Windows .exe build (run ON a Windows PC):
#   pip install pyinstaller && pyinstaller notebooklm.spec
# Output: dist\NotebookLM-Clone\NotebookLM-Clone.exe  (double-click to run)
# Notes: exe runs in TF-IDF mode (torch excluded for size); install
# `winget install ffmpeg` for audio/video; set OPENAI_API_KEY for real LLM.
block_cipher = None
a = Analysis(
    ['backend/run.py'],
    pathex=['backend'],
    binaries=[],
    datas=[('backend/app/static', 'static')],
    hiddenimports=['app.main', 'app.media', 'app.vectors', 'app.auth', 'app.integrations'],
    excludes=['torch', 'sentence_transformers', 'transformers', 'matplotlib'],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name='NotebookLM-Clone', debug=False, console=True,
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    name='NotebookLM-Clone',
)
