# Area: Rilis dan versioning

**Standar yang dijaga:** setiap rilis punya nomor semver, entri CHANGELOG, dan tag git beranotasi yang cocok.

## Aturan versi (SemVer, 0.x)
- **PATCH** (0.2.1): perbaikan bug, dokumentasi, tanpa perubahan perilaku.
- **MINOR** (0.3.0): fitur baru; selama 0.x juga boleh memuat perubahan tak kompatibel, tandai **BREAKING** di CHANGELOG.
- **MAJOR** (1.0.0): setelah antarmuka (perintah bot, variabel `.env`) dianggap stabil.
- Sumber versi tunggal: `src/clautele/__init__.py` (`__version__`). `tests/test_version.py` menjaga CHANGELOG tetap sinkron.

## Langkah rilis
1. Pindahkan isi `## [Belum dirilis]` ke `## [X.Y.Z] - TANGGAL` di `CHANGELOG.md`, perbarui tautan di dasar berkas.
2. Ubah `__version__` ke `X.Y.Z`.
3. `docker build --target test .` harus hijau.
4. `git commit -am "release: vX.Y.Z"` lalu `git tag -a vX.Y.Z -m "Clautele vX.Y.Z"`.
5. `git push origin main --follow-tags` (atau `git push origin vX.Y.Z`).
6. Opsional: buat GitHub Release dari tag, tempel bagian CHANGELOG-nya.

## Aturan tag
- Selalu `vMAJOR.MINOR.PATCH` dan **beranotasi** (`-a`), supaya `git describe` dan GitHub menampilkan pesan.
- Tag tidak dipindah atau dihapus setelah dipush. Salah rilis → terbitkan PATCH baru.

## Riwayat
| Tag | Commit | Isi |
|---|---|---|
| v0.1.0 | 53f75b5 | Bot Telegram + Docker + dokumentasi PARA |
| v0.2.0 | 64daa7c | Mode host + 2FA TOTP |
