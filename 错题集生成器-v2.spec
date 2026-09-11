# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = [('web/dist', 'web/dist'), ('docs', 'docs')]
binaries = [('C:\\Windows\\System32\\vcruntime140.dll', '.'),
            ('C:\\Windows\\System32\\vcruntime140_1.dll', '.'),
            ('C:\\Windows\\System32\\msvcp140.dll', '.'),
            ('C:\\Windows\\System32\\vcomp140.dll', '.'),
            ('C:\\Windows\\System32\\concrt140.dll', '.')]
hiddenimports = ['app', 'app.main', 'app.launcher', 'app.jobs', 'app.models',
                 'app.core.engine', 'app.core.recognize', 'app.core.digital', 'app.core.scanned',
                 'app.core.docx_build', 'app.core.archive', 'app.core.merge_docx', 'app.core.excel']
for pkg in ('rapidocr_onnxruntime', 'onnxruntime', 'pypdfium2', 'pdfplumber', 'pdfminer',
            'uvicorn', 'fastapi', 'starlette', 'pydantic', 'charset_normalizer', 'cryptography'):
    try:
        tmp_ret = collect_all(pkg)
        datas += tmp_ret[0]
        binaries += tmp_ret[1]
        hiddenimports += tmp_ret[2]
    except Exception:
        pass

a = Analysis(['app\\launcher.py'], pathex=[], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports, hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=['pandas', 'matplotlib', 'scipy', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
                       'notebook', 'IPython', 'tkinter.test', 'test', 'unittest',
                       # Anaconda 基础环境里的大包会被误收集，显式排除可让 exe 从 484MB 降到约 250MB
                       'sklearn', 'altair', 'nbconvert', 'nbformat', 'jupyter', 'jupyterlab',
                       'sphinx', 'pydub', 'librosa', 'sympy', 'sqlalchemy', 'bokeh', 'plotly',
                       'holoviews', 'xarray', 'dask', 'distributed', 'numba', 'llvmlite', 'tables',
                       'h5py', 'zarr', 'botocore', 'boto3', 's3fs', 'fsspec', 'cloudpickle',
                       'pytest', 'setuptools._distutils', 'IPython.display'],
             noarchive=False, optimize=0)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='错题集生成器',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=True,
          runtime_tmpdir=None, console=True, disable_windowed_traceback=False,
          argv_emulation=False, target_arch=None, codesign_identity=None, entitlements_file=None)
