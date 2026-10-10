# Windows (planned)

Beacon is Mac-first. Windows support is parked here until the Mac version is finished.

What's already done:
- `Beacon.bat`: a launcher that starts a portable Python and Ollama from the drive on port 11435.
- Every Python dependency (Flask, numpy, pypdf, libzim, psutil) has Windows wheels.
- Ollama ships `ollama-windows-amd64.zip` (about 1.4 GB with GPU libraries).

What's left:
- Add the Windows runtime and engine back into the builder (`python-build-standalone` x86_64-pc-windows-msvc, `pip --platform win_amd64`).
- Format the drive as exFAT (Windows can't read APFS) and copy runtimes with symlinks dereferenced.
- Test on real Windows 10/11 machines, including SmartScreen prompts and NVIDIA acceleration.
