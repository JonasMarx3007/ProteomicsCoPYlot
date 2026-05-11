PROTEOMICS COPYLOT - INSTALL, RUN, BUILD GUIDE

This guide contains platform-specific setup, run commands, AI mode notes, build commands,
and remote Ollama hosting via Tailscale.


========================================================================
1) GLOBAL NOTES
========================================================================

- Repository:
  git clone https://github.com/JonasMarx3007/ProteomicsCoPYlot.git
  cd ProteomicsCoPYlot

- AI mode prerequisite:
  Install Ollama from https://ollama.com
  (external system dependency, not a pip requirement)

- AI run scripts support:
  - normal run
  - optional on-the-fly model pull argument, e.g. --deepseek-r1:1.5b


========================================================================
2) WINDOWS
========================================================================

2.1 Install

git clone https://github.com/JonasMarx3007/ProteomicsCoPYlot.git
cd ProteomicsCoPYlot
cd backend
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd ..\frontend
npm install
cd ..


2.2 Run (analysis/viewer)

- Analysis:
  run_app.bat

- Viewer:
  run_viewer.bat

- Analysis (AI):
  run_app_ai.bat
  run_app_ai.bat --deepseek-r1:1.5b
  run_app_ai.bat --dev
  run_app_ai.bat --dev0
  run_app_ai.bat --dev2
  run_app_ai.bat --dev20

- Viewer (AI):
  run_viewer_ai.bat
  run_viewer_ai.bat --deepseek-r1:1.5b
  run_viewer_ai.bat --dev
  run_viewer_ai.bat --dev0
  run_viewer_ai.bat --dev2
  run_viewer_ai.bat --dev20


2.3 Production run

- Analysis:
  cd frontend
  npm run build
  cd ..
  .\backend\.venv\Scripts\python.exe launch.py

- Viewer:
  cd frontend
  npm run build
  cd ..
  .\backend\.venv\Scripts\python.exe launch.py --viewer --port 8001


2.4 Onefile EXE build

PowerShell (inside project folder):
.\build_exe_windows.ps1 -Target Tool
.\build_exe_windows.ps1 -Target Viewer

CMD (inside project folder):
powershell -ExecutionPolicy Bypass -File ".\build_exe_windows.ps1" -Target Tool
powershell -ExecutionPolicy Bypass -File ".\build_exe_windows.ps1" -Target Viewer

Output:
- .\dist\ProteomicsCoPYlot.exe
- .\dist\DataViewer.exe

Build note:
- Tool and Viewer builds use different frontend modes.
- Switching target requires a rebuild without -SkipFrontendBuild.


2.5 Onefile EXE build (AI and AI dev20)

Important:
- AI-enabled EXEs require frontend AI flags during build.
- Runtime still requires COPYLOT_AI_MODE=1.

Tool (AI):
  cd frontend
  cmd /c "set VITE_APP_MODE=analysis&& set VITE_AI_ENABLED=1&& npm run build"
  powershell -NoProfile -Command "Set-Content -Path .\dist\.copylot_mode.txt -Value analysis -NoNewline"
  cd ..
  powershell -ExecutionPolicy Bypass -File ".\build_exe_windows.ps1" -Target Tool -SkipFrontendBuild

Tool (AI dev20 default endpoint):
  cd frontend
  powershell -NoProfile -Command "$env:DEV20_ENDPOINT=(Get-Content ..\local\dev_ai.local.env | Where-Object { $_ -like 'COPYLOT_DEV2_OLLAMA_ENDPOINT=*' } | Select-Object -First 1).Split('=',2)[1]; cmd /c \"set VITE_APP_MODE=analysis&& set VITE_AI_ENABLED=1&& set VITE_AI_DEFAULT_OLLAMA_ENDPOINT=%DEV20_ENDPOINT%&& set VITE_AI_DEFAULT_OLLAMA_MODEL=llama3.1:8b&& npm run build\""
  powershell -NoProfile -Command "Set-Content -Path .\dist\.copylot_mode.txt -Value analysis -NoNewline"
  cd ..
  powershell -ExecutionPolicy Bypass -File ".\build_exe_windows.ps1" -Target Tool -SkipFrontendBuild

Viewer (AI):
  cd frontend
  cmd /c "set VITE_APP_MODE=viewer&& set VITE_AI_ENABLED=1&& npm run build"
  powershell -NoProfile -Command "Set-Content -Path .\dist\.copylot_mode.txt -Value viewer -NoNewline"
  cd ..
  powershell -ExecutionPolicy Bypass -File ".\build_exe_windows.ps1" -Target Viewer -SkipFrontendBuild

Viewer (AI dev20 default endpoint):
  cd frontend
  powershell -NoProfile -Command "$env:DEV20_ENDPOINT=(Get-Content ..\local\dev_ai.local.env | Where-Object { $_ -like 'COPYLOT_DEV2_OLLAMA_ENDPOINT=*' } | Select-Object -First 1).Split('=',2)[1]; cmd /c \"set VITE_APP_MODE=viewer&& set VITE_AI_ENABLED=1&& set VITE_AI_DEFAULT_OLLAMA_ENDPOINT=%DEV20_ENDPOINT%&& set VITE_AI_DEFAULT_OLLAMA_MODEL=llama3.1:8b&& npm run build\""
  powershell -NoProfile -Command "Set-Content -Path .\dist\.copylot_mode.txt -Value viewer -NoNewline"
  cd ..
  powershell -ExecutionPolicy Bypass -File ".\build_exe_windows.ps1" -Target Viewer -SkipFrontendBuild

Run AI EXEs:
  set COPYLOT_AI_MODE=1
  .\dist\ProteomicsCoPYlot.exe
  .\dist\DataViewer.exe


========================================================================
3) MACOS
========================================================================

3.1 Install

git clone https://github.com/JonasMarx3007/ProteomicsCoPYlot.git
cd ProteomicsCoPYlot
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd ../frontend
npm install
cd ..
chmod +x run_app_macos.sh run_viewer_macos.sh


3.2 Run (analysis/viewer)

- Analysis:
  ./run_app_macos.sh

- Viewer:
  ./run_viewer_macos.sh

- Analysis (AI):
  ./run_app_ai_macos.sh
  ./run_app_ai_macos.sh --deepseek-r1:1.5b
  ./run_app_ai_macos.sh --dev

- Viewer (AI):
  ./run_viewer_ai_macos.sh
  ./run_viewer_ai_macos.sh --deepseek-r1:1.5b
  ./run_viewer_ai_macos.sh --dev


3.3 Production run

- Analysis:
  cd frontend
  npm run build
  cd ..
  ./backend/.venv/bin/python3 launch.py

- Viewer:
  cd frontend
  npm run build
  cd ..
  ./backend/.venv/bin/python3 launch.py --viewer --port 8001


3.4 Onefile app build

- Tool:
  cd frontend
  VITE_APP_MODE=analysis npm run build
  cd ..
  ./backend/.venv/bin/python3 -m pip install --upgrade pip pyinstaller
  ./backend/.venv/bin/python3 -m PyInstaller --noconfirm --clean --onefile --name ProteomicsCoPYlot --paths backend --hidden-import uvicorn.logging --hidden-import uvicorn.loops.auto --hidden-import uvicorn.protocols.http.auto --hidden-import uvicorn.protocols.websockets.auto --hidden-import uvicorn.lifespan.on --collect-all fastapi --collect-all starlette --collect-all uvicorn --collect-all pandas --collect-all numpy --collect-all scipy --collect-all matplotlib --collect-all seaborn --collect-all plotly --collect-all pyarrow --collect-all openpyxl --add-data "frontend/dist:frontend_dist" --add-data "viewer_config.json:." --add-data "viewer_data:viewer_data" launch_tool.py
  output: ./dist/ProteomicsCoPYlot

- Viewer:
  cd frontend
  VITE_APP_MODE=viewer npm run build
  cd ..
  ./backend/.venv/bin/python3 -m pip install --upgrade pip pyinstaller
  ./backend/.venv/bin/python3 -m PyInstaller --noconfirm --clean --onefile --name DataViewer --paths backend --hidden-import uvicorn.logging --hidden-import uvicorn.loops.auto --hidden-import uvicorn.protocols.http.auto --hidden-import uvicorn.protocols.websockets.auto --hidden-import uvicorn.lifespan.on --collect-all fastapi --collect-all starlette --collect-all uvicorn --collect-all pandas --collect-all numpy --collect-all scipy --collect-all matplotlib --collect-all seaborn --collect-all plotly --collect-all pyarrow --collect-all openpyxl --add-data "frontend/dist:frontend_dist" --add-data "viewer_config.json:." --add-data "viewer_data:viewer_data" launch_viewer.py
  output: ./dist/DataViewer


========================================================================
4) LINUX
========================================================================

4.1 Install

git clone https://github.com/JonasMarx3007/ProteomicsCoPYlot.git
cd ProteomicsCoPYlot
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd ../frontend
npm install
cd ..
chmod +x run_app_linux.sh run_viewer_linux.sh


4.2 Run (analysis/viewer)

- Analysis:
  ./run_app_linux.sh

- Viewer:
  ./run_viewer_linux.sh

- Analysis (AI):
  ./run_app_ai_linux.sh
  ./run_app_ai_linux.sh --deepseek-r1:1.5b
  ./run_app_ai_linux.sh --dev

- Viewer (AI):
  ./run_viewer_ai_linux.sh
  ./run_viewer_ai_linux.sh --deepseek-r1:1.5b
  ./run_viewer_ai_linux.sh --dev


4.3 Production run

- Analysis:
  cd frontend
  npm run build
  cd ..
  ./backend/.venv/bin/python3 launch.py

- Viewer:
  cd frontend
  npm run build
  cd ..
  ./backend/.venv/bin/python3 launch.py --viewer --port 8001


4.4 Onefile app build

- Tool:
  cd frontend
  VITE_APP_MODE=analysis npm run build
  cd ..
  ./backend/.venv/bin/python3 -m pip install --upgrade pip pyinstaller
  ./backend/.venv/bin/python3 -m PyInstaller --noconfirm --clean --onefile --name ProteomicsCoPYlot --paths backend --hidden-import uvicorn.logging --hidden-import uvicorn.loops.auto --hidden-import uvicorn.protocols.http.auto --hidden-import uvicorn.protocols.websockets.auto --hidden-import uvicorn.lifespan.on --collect-all fastapi --collect-all starlette --collect-all uvicorn --collect-all pandas --collect-all numpy --collect-all scipy --collect-all matplotlib --collect-all seaborn --collect-all plotly --collect-all pyarrow --collect-all openpyxl --add-data "frontend/dist:frontend_dist" --add-data "viewer_config.json:." --add-data "viewer_data:viewer_data" launch_tool.py
  output: ./dist/ProteomicsCoPYlot

- Viewer:
  cd frontend
  VITE_APP_MODE=viewer npm run build
  cd ..
  ./backend/.venv/bin/python3 -m pip install --upgrade pip pyinstaller
  ./backend/.venv/bin/python3 -m PyInstaller --noconfirm --clean --onefile --name DataViewer --paths backend --hidden-import uvicorn.logging --hidden-import uvicorn.loops.auto --hidden-import uvicorn.protocols.http.auto --hidden-import uvicorn.protocols.websockets.auto --hidden-import uvicorn.lifespan.on --collect-all fastapi --collect-all starlette --collect-all uvicorn --collect-all pandas --collect-all numpy --collect-all scipy --collect-all matplotlib --collect-all seaborn --collect-all plotly --collect-all pyarrow --collect-all openpyxl --add-data "frontend/dist:frontend_dist" --add-data "viewer_config.json:." --add-data "viewer_data:viewer_data" launch_viewer.py
  output: ./dist/DataViewer


========================================================================
5) REMOTE OLLAMA HOSTING + TAILSCALE MANUAL
========================================================================

Goal:
Run Ollama on host PC (PC-A) and use it from ProteomicsCoPYlot on client PC (PC-B)
through your tailnet.

5.1 Host PC (PC-A): install requirements

- Install and sign in to Tailscale.
- Install Ollama from https://ollama.com


5.2 Host PC (PC-A): expose Ollama on tailnet

Windows (PowerShell):
setx OLLAMA_HOST "0.0.0.0:11434"
Then fully restart Ollama (or reboot once).

Linux/macOS (terminal):
export OLLAMA_HOST=0.0.0.0:11434
ollama serve


5.3 Host PC (PC-A): pull a model

Example:
ollama pull phi3:mini

Check:
ollama list


5.4 Host PC (PC-A): firewall check (if needed)

Windows (PowerShell, admin):
New-NetFirewallRule -DisplayName "Ollama 11434" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 11434


5.5 Host PC (PC-A): find Tailscale address

Use either:
- Tailscale IP (example: 100.x.y.z)
- MagicDNS hostname (if enabled)


5.6 Client PC (PC-B): test connectivity

PowerShell example:
Invoke-RestMethod -Method Get "http://<TAILSCALE_IP_OR_HOSTNAME>:11434/api/tags"

If you get JSON with models, connection works.


5.7 Client PC (PC-B): connect inside ProteomicsCoPYlot

- Start AI app:
  run_app_ai.bat
  or
  run_viewer_ai.bat

- Open Chatbot -> AI Settings.
- Provider: Local (Ollama)
- Ollama endpoint:
  http://<TAILSCALE_IP_OR_HOSTNAME>:11434
- Press Enter (or leave the field) to apply endpoint.
- Select model and chat.
