# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = [('C:\\Windows\\System32\\vcruntime140.dll', '.'), ('C:\\Windows\\System32\\vcruntime140_1.dll', '.'), ('C:\\Windows\\System32\\msvcp140.dll', '.'), ('C:\\Windows\\System32\\vcomp140.dll', '.'), ('C:\\Windows\\System32\\concrt140.dll', '.')]
hiddenimports = ['生成错题集']
tmp_ret = collect_all('rapidocr_onnxruntime')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('onnxruntime')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pypdfium2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['错题集生成器.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pandas', 'PyQt5', 'PyQt6', 'qtpy', 'PySide2', 'PySide6', 'dask', 'distributed', 'numba', 'llvmlite', 'xarray', 'bokeh', 'holoviews', 'plotly', 'sqlalchemy', 'tables', 'botocore', 'boto3', 's3fs', 'fsspec', 'lz4', 'cloudpickle', 'matplotlib', 'scipy', 'seaborn', 'zarr', 'h5py'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='错题集生成器',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
